#!/usr/bin/env python3
"""Driver：程序驱动的 map / Epic 状态机（ADR-0026）。

core 只有三件事：
- `decide(state) -> Action`：纯函数，冻结输入、无副作用；Action 是一行 JSON {"action","id","args"}。
- `apply(state, action, receipt)`：纯函数，把回执变成 driver.json 新值与待写 lane 行。
- IO 层（load / record / run）：读 map 目录、写 driver.json 与 lane registry，执行 core 执行器
  （fan_in、closeout、consume、render_review）。壳的 run 循环传入额外执行器（如 Herdr dispatch）。

registry 只由 Driver 写；回执按 id 幂等。core 不引用任何壳文件。

命令：
  driver.py decide <map_dir>                      只输出下一条 Action
  driver.py run <map_dir>                         执行程序能执行的 Action，交回第一条需宿主/判断/等待/停下的 Action
  driver.py record <map_dir> <id> <receipt_json>  交回回执；id 为 halt 时 receipt 是用户决定原文
  driver.py signal <map_dir> "<LANE_DONE 行>"      交回 worker 终态行（watcher 或 coordinator 调用）
  driver.py init <map_dir> <map_id>               为新 map 写空 driver.json（进入 Plan Review 流程）
  driver.py epic <epic_json>                      Epic 级：输出下一条 open_map / wait / done
  driver.py self-test
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import subprocess
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from types import MappingProxyType

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import closeout  # noqa: E402

DRIVER_FILE = "driver.json"
VERSION = 1

# Halt 封闭清单（ADR-0026 决策 8）。清单外不得产生 halt。
HALT_CLASSES = {
    "plan_change": "1 计划的 T/R、范围或验收要改",
    "extra_ticket": "2 补票超出已批准波次或改动合同票",
    "review_exhausted": "3 REVIEW_EXHAUSTED",
    "resplit_failed": "4 重拆之后仍然失败",
    "authority": "5 需要远程权限、不可逆操作或授权外的决定",
    "ci_red": "CI 红",
    "review_blocking": "评审意见阻塞",
}
# 程序在 core 内直接执行的 Action；壳可追加（Herdr: dispatch）。
CORE_PROGRAM = frozenset({"fan_in", "closeout", "consume", "render_review"})
# 不唤醒 LLM 的结果。
QUIET = frozenset({"wait"})
ACTIVE = {"created", "running", "awaiting_human"}
FAILED = {"blocked", "integration_checks_failed"}
MAX_REPAIRS = 2  # ADR-0012：两轮修复后重拆
PLANNING_OWNERS = (("discovery", "wayfinder"), ("spec", "to-spec"), ("tickets", "to-tickets"))
REMOTE_STEPS = ("push", "open_pr", "wait_ci", "merge", "finalize")


def act(action: str, ident: str, **args) -> dict:
    return {"action": action, "id": ident, "args": args}


def freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({k: freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(freeze(v) for v in value)
    return value


def thaw(value):
    if isinstance(value, MappingProxyType | dict):
        return {k: thaw(v) for k, v in value.items()}
    if isinstance(value, tuple | list):
        return [thaw(v) for v in value]
    return value


def plan_sha(plan) -> str:
    return hashlib.sha256(json.dumps(thaw(plan), sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


# ---------- 纯决定面 ----------

def lanes_by_item(lanes) -> dict:
    out: dict = {}
    for row in lanes.values():
        if row.get("role") != "map" and row.get("work_item"):
            out.setdefault(row["work_item"], []).append(row)
    return out


def item_done(rows) -> bool:
    return any(r.get("state") in closeout.DONE for r in rows or ())


def map_row(lanes):
    return closeout.map_row(dict(lanes))


def deviations(state) -> list[str]:
    """清单外、自动处理过的偏差；Merge Review 报告用。纯函数，每次重算。"""
    d = state["driver"]
    planned = {t["id"] for t in d["plan"]["tickets"]}
    out = []
    for row in sorted(state["lanes"].values(), key=lambda r: r["lane_id"]):
        if row.get("role") in ("map", "testing", "review", "integration"):
            if row.get("role") == "integration" and row.get("merges"):
                out.append(f"merger {row['lane_id']} 处理 {row['merges']} 的收口失败")
            continue
        if row.get("work_item") not in planned:
            out.append(f"波次内补票 {row.get('work_item')}（{row['lane_id']}）")
        if int(row.get("repairs") or 0):
            out.append(f"{row['lane_id']} 验收修复 {row['repairs']} 轮")
        if row.get("resplit_of"):
            out.append(f"{row['lane_id']} 重拆自 {row['resplit_of']}")
    out.extend(f"轻判断 {k}: {v.get('answer')}" for k, v in sorted(d.get("judgements", {}).items()))
    return out


def detect_halt(state):
    """封闭 Halt 清单的检测；已由用户裁决的 id 不再触发。"""
    d, lanes = state["driver"], state["lanes"]
    resolved = set(d.get("resolved_halts", ()))
    planned = {t["id"]: t for t in d["plan"]["tickets"]}
    max_wave = max((t.get("wave", 1) for t in planned.values()), default=1)

    def halt(kind, key, reason, evidence, options):
        hid = f"halt:{kind}:{key}"
        if hid in resolved:
            return None
        return act("halt", hid, kind=kind, label=HALT_CLASSES[kind], reason=reason,
                   evidence=list(evidence), options=list(options))

    candidates = []
    for row in sorted(lanes.values(), key=lambda r: r["lane_id"]):
        lid, reason = row["lane_id"], row.get("blocked_reason") or ""
        if row.get("state") == "blocked" and "REVIEW_EXHAUSTED" in reason:
            candidates.append(halt("review_exhausted", lid, "三轮 review 后仍有阻断项", [row.get("_file", ""), lid],
                                   ["接受剩余 findings 继续", "重拆该票", "放弃本 MMF"]))
        if row.get("state") == "blocked" and "needs-decision" in reason:
            candidates.append(halt("plan_change", lid, reason, [row.get("artifact") or lid],
                                   ["补充 Spec/验收来源后重派", "改范围", "放弃该票"]))
        if row.get("resplit_of") and row.get("state") in FAILED and int(row.get("repairs") or 0) >= MAX_REPAIRS:
            candidates.append(halt("resplit_failed", lid, f"重拆自 {row['resplit_of']} 后仍失败",
                                   [lid, row["resplit_of"]], ["人工接手", "改计划", "放弃该票"]))
        item = row.get("work_item")
        if row.get("role") not in ("map", "testing", "review", "integration") and item not in planned:
            if int(row.get("wave") or 1) > max_wave or row.get("contract_change") == "true":
                candidates.append(halt("extra_ticket", lid, f"补票 {item} 超出已批准波次或改动合同票",
                                       [lid], ["批准补票", "拒绝补票"]))
    strategy = d.get("test_strategy") or {}
    current = d.get("scope") or {}
    if strategy and current and (current.get("sha") != strategy.get("scope_sha") or current.get("risk") != strategy.get("risk")):
        candidates.append(halt("plan_change", "test-decision", "范围或风险相对 Plan Review 已变化，测试策略需重定",
                               [DRIVER_FILE + "#scope"], ["沿用原策略", "改测试策略"]))
    remote = d.get("remote") or {}
    if remote.get("ci") == "red":
        candidates.append(halt("ci_red", remote.get("pr") or "pr", "CI 红", [remote.get("pr") or "Unknown"],
                               ["派修复后重跑", "放弃合入"]))
    if remote.get("review") == "blocking":
        candidates.append(halt("review_blocking", remote.get("pr") or "pr", "评审意见阻塞",
                               [remote.get("pr") or "Unknown"], ["派修复", "放弃合入"]))
    for wanted in remote.get("needs_authority", ()):
        candidates.append(halt("authority", wanted, f"需要授权外操作：{wanted}", [DRIVER_FILE + "#remote"],
                               ["授权", "拒绝"]))
    return next((c for c in candidates if c), None)


def decide_planning(state):
    """无 Autonomy Grant：走 owner 链到 Plan Review。"""
    d, lanes = state["driver"], state["lanes"]
    gates = d.get("gates", {})
    for gate, owner in PLANNING_OWNERS:
        if not gates.get(gate):
            if gate == "discovery" and d.get("skip_discovery"):
                continue
            nxt = d.get("owner_next") or {}
            if nxt.get("next") == "blocked-human":
                return act("ask_human", f"owner:{gate}:human", kind="owner-blocked", owner=owner,
                           reason=nxt.get("reason"))
            return act("invoke_owner", f"owner:{gate}", owner=owner, gate=gate,
                       feedback=d.get("plan_feedback"))
    if d.get("plan_check") != "pass":
        return act("invoke_owner", "owner:tickets:recheck", owner="to-tickets", gate="tickets",
                   feedback=d.get("plan_check"))
    review = (d.get("reviews") or {}).get("plan") or {}
    sha = plan_sha(d["plan"])
    if review.get("sha") != sha:
        return act("render_review", f"render:plan:{sha}", kind="plan")
    return act("ask_human", f"review:plan:{sha}", kind="plan-review", html=review.get("html"),
               reply="回复\"通过\"授予 Autonomy Grant；其他内容作为修改意见退回 to-tickets")


def decide(state) -> dict:
    """唯一推进逻辑。state = {"driver": driver.json | None, "lanes": {lane_id: row}}。"""
    state = freeze(state)
    d, lanes = state["driver"], state["lanes"]
    if d is None:
        if map_row(lanes):
            return act("legacy", "legacy", reason="无 driver.json 与 Autonomy Grant：沿旧流程逐 gate 推进，直到下一次 Plan Review")
        return act("halt", "halt:authority:no-map", kind="authority", label=HALT_CLASSES["authority"],
                   reason="map 目录没有 driver.json，也没有 map row", evidence=[], options=["driver.py init"])
    if d.get("status") in ("done", "aborted"):
        return act("done", f"done:{d['status']}")
    if d.get("halt"):
        return thaw(d["halt"])
    if not d.get("grant"):
        return thaw(decide_planning(state))
    if d["grant"].get("plan_sha") != plan_sha(d["plan"]):
        return act("halt", "halt:plan_change:grant", kind="plan_change", label=HALT_CLASSES["plan_change"],
                   reason="计划已变，原 Autonomy Grant 失效", evidence=[DRIVER_FILE + "#grant"],
                   options=["重新 Plan Review"])
    halt = detect_halt(state)
    if halt:
        return thaw(halt)
    if not d.get("published"):
        return act("invoke_owner", "owner:publish", owner="to-tickets", gate="publish",
                   note="Autonomy Grant 已授予；按已批准草稿发布")
    mrow = map_row(lanes)
    if not mrow:
        return act("prepare_map", "prepare_map", note="建 Map Integration Worktree 并交回 map row")

    # 1. 程序收口：terminal → fan_in / consume；完成 → closeout
    for row in sorted(lanes.values(), key=lambda r: r["lane_id"]):
        lid, st = row["lane_id"], row.get("state")
        if row.get("role") == "map":
            continue
        if st == "terminal":
            if row.get("output_mode") == "commit":
                return act("fan_in", f"fan_in:{lid}", lane_id=lid, commit=row.get("head_commit"),
                           integration=mrow.get("integration_worktree_path"))
            return act("consume", f"consume:{lid}", lane_id=lid, output_mode=row.get("output_mode"),
                       verdict=row.get("verdict"))
        if st in ("integrated", "consumed") and row.get("role") != "review":
            return act("closeout", f"closeout:{lid}", lane_id=lid)

    # 2. 失败处理
    merging = {r.get("merges") for r in lanes.values() if r.get("role") == "integration"}
    for row in sorted(lanes.values(), key=lambda r: r["lane_id"]):
        lid, st, reason = row["lane_id"], row.get("state"), row.get("blocked_reason") or ""
        if st in ("integration_conflict", "integration_checks_failed") and lid not in merging:
            return act("dispatch", f"dispatch:merger:{lid}", task="integration", output_mode="integration",
                       lane_id=f"{lid}-merger", merges=lid, work_item=row.get("work_item"))
        if st == "blocked" and not any(k in reason for k in ("REVIEW_EXHAUSTED", "needs-decision")):
            repairs = int(row.get("repairs") or 0)
            if not reason:
                key = f"judge:classify:{lid}"
                if key not in d.get("judgements", {}):
                    return act("judge", key, weight="light", lane_id=lid,
                               question="blocked 未给原因：判定是验收失败（修复）还是需重拆",
                               options=["repair", "resplit"], requires=["answer", "evidence"])
                if d["judgements"][key]["answer"] == "resplit":
                    repairs = MAX_REPAIRS
            if repairs < MAX_REPAIRS:
                return act("judge", f"judge:diagnose:{lid}:{repairs + 1}", weight="heavy", lane_id=lid,
                           kind="acceptance-diagnosis", note="ADR-0012：派诊断+修复 lane，按原判据复验")
            if not row.get("resplit_of"):
                return act("judge", f"judge:resplit:{lid}", weight="heavy", lane_id=lid, kind="resplit",
                           note="ADR-0013：两轮修复仍失败，波次内重拆")

    # 3. frontier
    by_item = lanes_by_item(lanes)
    pending_hitl = []
    for ticket in sorted(d["plan"]["tickets"], key=lambda t: (t.get("wave", 1), t["id"])):
        if by_item.get(ticket["id"]):
            continue
        if not all(item_done(by_item.get(dep)) for dep in ticket.get("deps", ())):
            continue
        if ticket.get("hitl") and ticket["id"] not in d.get("answers", {}):
            pending_hitl.append(ticket)
            continue
        return act("dispatch", f"dispatch:{ticket['id']}", task=ticket.get("task", "backend"),
                   output_mode=ticket.get("output_mode", "commit"), work_item=ticket["id"],
                   lane_id=ticket.get("lane_id", ticket["id"]), answer=d.get("answers", {}).get(ticket["id"]))
    if pending_hitl:
        ids = ",".join(t["id"] for t in pending_hitl)
        return act("ask_human", f"hitl:{ids}", kind="hitl",
                   questions=[{"ticket": t["id"], "question": t.get("question", "")} for t in pending_hitl])

    active = [r["lane_id"] for r in lanes.values()
              if r.get("role") != "map" and (r.get("state") in ACTIVE or r.get("state") in FAILED)]
    planned_done = all(item_done(by_item.get(t["id"])) for t in d["plan"]["tickets"])
    if active or not planned_done:
        return act("wait", "wait", lanes=sorted(active))

    # 4. whole-change testing → review
    for role, mode in (("testing", "checks"), ("review", "verdict")):
        rows = [r for r in lanes.values() if r.get("role") == role]
        if not rows:
            return act("dispatch", f"dispatch:{role}", task=role, output_mode=mode, lane_id=f"{d['map']}-{role}",
                       work_item=f"{d['map']}#{role}", strategy=thaw(d.get("test_strategy")))
        latest = max(rows, key=lambda r: r["lane_id"])
        if role == "review" and latest.get("verdict") == "FIX":
            rnd = int(latest.get("round") or 1)
            return act("judge", f"judge:review_fix:{rnd}", weight="heavy", kind="review-fix",
                       lane_id=latest["lane_id"], note="FIX findings 交同一 implementer lane 修复后开下一轮")
        if latest.get("state") not in closeout.DONE:
            return act("wait", "wait", lanes=[latest["lane_id"]])

    # 5. Merge Review → remote
    review = (d.get("reviews") or {}).get("merge") or {}
    if not review.get("approved"):
        devs = deviations(state)
        sha = hashlib.sha256(json.dumps(devs, ensure_ascii=False).encode()).hexdigest()[:16]
        if review.get("sha") != sha:
            return act("render_review", f"render:merge:{sha}", kind="merge")
        return act("ask_human", f"review:merge:{sha}", kind="merge-review", html=review.get("html"),
                   reply="回复\"通过\"授权 push、建 PR、等 CI 并按分支合同合入收尾")
    remote = d.get("remote") or {}
    for step in REMOTE_STEPS:
        if not remote.get(step):
            if step == "wait_ci" and remote.get("ci") == "pending":
                return act("wait", "wait", ci=remote.get("pr"))
            return act("remote", f"remote:{step}", step=step, pr=remote.get("pr"),
                       note="Merge Review 已授权；按仓库分支合同执行")
    return act("done", "done:delivered")


def decide_epic(epic) -> dict:
    """Epic 级：只读候选表与各 map 终态，为阻塞已解除的 MMF 开 map 并启动 to-spec。"""
    epic = freeze(epic)
    closed = {m for m, st in epic.get("maps", {}).items() if st == "closed"}
    by_mmf = {c["mmf"]: c for c in epic["candidates"]}
    for cand in epic["candidates"]:
        if cand.get("map"):
            continue
        if all(by_mmf.get(b, {}).get("map") in closed for b in cand.get("blocked_by", ())):
            return act("open_map", f"open_map:{cand['mmf']}", mmf=cand["mmf"], start="to-spec",
                       note="新 map 独立 worktree 与 lane，不与其他 map 共享")
    if all(c.get("map") in closed for c in epic["candidates"]):
        return act("done", "done:epic")
    return act("wait", "wait", maps=sorted(set(epic.get("maps", {})) - closed))


# ---------- 回执 ----------

REQUIRED = {
    "invoke_owner": {"artifact", "next"},
    "ask_human": {"reply"},
    "judge": set(),
    "dispatch": {"lane"},
    "prepare_map": {"map_row"},
    "remote": {"result"},
    "fan_in": {"state"},
    "consume": {"state"},
    "closeout": {"result"},
    "render_review": {"html", "sha"},
    "open_map": {"map"},
}


def apply(state, action, receipt) -> tuple[dict, list[dict]]:
    """纯函数：校验回执并返回 (新 driver.json, 待追加 lane 行)。"""
    d = thaw(state["driver"]) if state["driver"] is not None else None
    lanes = state["lanes"]
    kind, args, ident = action["action"], action["args"], action["id"]
    if kind in ("wait", "done", "legacy"):
        raise ValueError(f"{kind} 不接受回执")
    if kind == "halt":
        if not isinstance(receipt, str) or not receipt.strip():
            raise ValueError("halt 回执必须是用户决定原文")
        d["resolved_halts"] = [*d.get("resolved_halts", []), ident]
        d.setdefault("halt_log", []).append({"id": ident, "decision": receipt})
        d["halt"] = None
        if receipt.strip() in ("放弃", "放弃本 MMF", "abort"):
            d["status"] = "aborted"
        return d, []
    if not isinstance(receipt, dict):
        raise ValueError("回执必须是 JSON object")
    missing = REQUIRED[kind] - set(receipt)
    if kind == "judge":
        missing = ({"answer", "evidence"} if args["weight"] == "light" else {"lane_id"}) - set(receipt)
    if missing:
        raise ValueError(f"{kind} 回执缺字段: {sorted(missing)}")
    updates: list[dict] = []

    def lane_update(lid, **fields):
        row = {k: v for k, v in lanes[lid].items() if k != "_file"}
        row.update(fields)
        row["_file"] = lanes[lid].get("_file")
        updates.append(row)

    if kind == "invoke_owner":
        gate = args["gate"]
        if receipt["next"] == "blocked-human":
            d["owner_next"] = {"next": "blocked-human", "reason": receipt.get("reason")}
            return d, []
        d["owner_next"] = None
        if gate == "publish":
            d["published"] = receipt["artifact"]
            return d, []
        d.setdefault("gates", {})[gate] = receipt["artifact"]
        if gate == "tickets":
            if not isinstance(receipt.get("plan"), dict) or "tickets" not in receipt["plan"]:
                raise ValueError("to-tickets 回执必须带 plan.tickets")
            d["plan"] = receipt["plan"]
            d["plan_check"] = receipt.get("check")
            d["plan_feedback"] = None
    elif kind == "ask_human":
        reply = receipt["reply"]
        if args["kind"] == "plan-review":
            if str(reply).strip() == "通过":
                sha = plan_sha(d["plan"])
                d["grant"] = {"plan_sha": sha, "review": ident}
                d["test_strategy"] = {**(d["plan"].get("test_strategy") or {}),
                                      "scope_sha": sha, "risk": d["plan"].get("risk")}
                d["scope"] = {"sha": sha, "risk": d["plan"].get("risk")}
            else:
                d["plan_feedback"] = reply
                d["plan_check"] = None
                d.setdefault("gates", {})["tickets"] = None
        elif args["kind"] == "merge-review":
            if str(reply).strip() == "通过":
                d.setdefault("reviews", {}).setdefault("merge", {})["approved"] = True
            else:
                d.setdefault("halt_log", []).append({"id": ident, "decision": reply})
                d["status"] = "aborted" if str(reply).strip() == "放弃" else d.get("status")
        elif args["kind"] == "hitl":
            if not isinstance(reply, dict) or set(reply) != {q["ticket"] for q in args["questions"]}:
                raise ValueError("hitl 回执必须逐票回答当前 frontier 全部问题")
            d.setdefault("answers", {}).update(reply)
        elif args["kind"] == "owner-blocked":
            d["owner_next"] = None
            d["plan_feedback"] = reply
    elif kind == "judge":
        if args["weight"] == "light":
            if receipt["answer"] not in args["options"] or not receipt["evidence"]:
                raise ValueError("轻判断必须从 options 选一项并附证据坐标")
            d.setdefault("judgements", {})[ident] = {"answer": receipt["answer"], "evidence": receipt["evidence"]}
        else:
            lid = args["lane_id"]
            if args["kind"] == "acceptance-diagnosis":
                lane_update(lid, state="running", repairs=int(lanes[lid].get("repairs") or 0) + 1,
                            repair_lane=receipt["lane_id"])
            elif args["kind"] == "resplit":
                lane_update(lid, state="superseded", superseded_by=receipt["lane_id"])
            elif args["kind"] == "review-fix":
                lane_update(lid, state="superseded", fix_lane=receipt["lane_id"])
    elif kind == "dispatch":
        row = receipt["lane"]
        if not isinstance(row, dict) or row.get("lane_id") != args["lane_id"]:
            raise ValueError("dispatch 回执的 lane_id 与 Action 不符")
        if row.get("work_item") != args["work_item"]:
            raise ValueError("dispatch 回执的 work_item 与 Action 不符")
        if receipt.get("persisted"):  # 壳 helper（Herdr dispatch.py）已写 registry
            return d, []
        updates.append({**row, "_file": None})
    elif kind == "prepare_map":
        row = receipt["map_row"]
        if row.get("role") != "map" or not row.get("integration_worktree_path"):
            raise ValueError("map row 必须 role: map 且带 integration_worktree_path")
        updates.append({**row, "_file": None})
    elif kind in ("fan_in", "consume"):
        allowed = {"fan_in": {"integrated", "integration_conflict", "integration_checks_failed"},
                   "consume": {"consumed", "blocked"}}[kind]
        if receipt["state"] not in allowed:
            raise ValueError(f"{kind} 回执 state 非法")
        extra = {k: receipt[k] for k in ("integrated_commit", "blocked_reason", "verdict") if k in receipt}
        lane_update(args["lane_id"], state=receipt["state"], **extra)
    elif kind == "closeout":
        if receipt["result"] not in ("closed", "close_pending"):
            raise ValueError("closeout 回执 result 非法")
        lane_update(args["lane_id"], state=receipt["result"], close_reason=receipt.get("reason"))
    elif kind == "render_review":
        d.setdefault("reviews", {})[args["kind"]] = {**(d.get("reviews", {}).get(args["kind"]) or {}),
                                                    "html": receipt["html"], "sha": receipt["sha"]}
    elif kind == "remote":
        step, result = args["step"], receipt["result"]
        remote = d.setdefault("remote", {})
        if result == "needs_authority":
            remote.setdefault("needs_authority", []).append(step)
        else:
            remote.update({k: receipt[k] for k in ("pr", "ci", "review") if k in receipt})
            if step != "wait_ci" or remote.get("ci") == "green":
                remote[step] = result
    return d, updates


# ---------- HTML 审核页（同一模板，确定性） ----------

def render(state, kind: str) -> str:
    d = state["driver"]
    plan = d["plan"]
    esc = lambda v: html.escape(str(v if v is not None else "Unknown"))  # noqa: E731
    title = "Plan Review" if kind == "plan" else "Merge Review"
    rows = []
    by_item = lanes_by_item(state["lanes"]) if kind == "merge" else {}
    for t in sorted(plan["tickets"], key=lambda t: (t.get("wave", 1), t["id"])):
        actual = ""
        if kind == "merge":
            states = ", ".join(f"{r['lane_id']}={r.get('state')}" for r in by_item.get(t["id"], []))
            actual = f"<td>{esc(states or '未派发')}</td>"
        rows.append(f"<tr><td>{esc(t['id'])}</td><td>{esc(t.get('wave', 1))}</td><td>{esc(t.get('task'))}</td>"
                    f"<td>{esc(', '.join(t.get('deps', [])) or '-')}</td><td>{'HITL' if t.get('hitl') else 'AFK'}</td>{actual}</tr>")
    head = "<tr><th>票</th><th>波次</th><th>类型</th><th>依赖</th><th>HITL/AFK</th>" + ("<th>实际</th>" if kind == "merge" else "") + "</tr>"
    parts = [
        "<!doctype html><html lang=\"zh-CN\"><meta charset=\"utf-8\">",
        f"<title>{title} · {esc(d.get('map'))}</title>",
        "<style>body{font:15px/1.6 system-ui;max-width:960px;margin:2rem auto;padding:0 1rem}"
        "table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:.3rem .5rem;text-align:left}</style>",
        f"<h1>{title} · {esc(d.get('map'))}</h1>",
        f"<p>计划指纹 <code>{esc(plan_sha(plan))}</code></p>",
        f"<h2>Spec</h2><p>{esc(d.get('gates', {}).get('spec'))}</p>",
        f"<h2>切片</h2><table>{head}{''.join(rows)}</table>",
        f"<h2>关键路径</h2><p>{esc(' → '.join(plan.get('critical_path', [])) or 'Unknown')}</p>",
        f"<h2>测试策略</h2><p>{esc(json.dumps(plan.get('test_strategy'), ensure_ascii=False))}</p>",
    ]
    if kind == "merge":
        devs = deviations(state)
        parts.append("<h2>自动处理的偏差</h2><ul>" + "".join(f"<li>{esc(x)}</li>" for x in devs) + "</ul>" if devs
                     else "<h2>自动处理的偏差</h2><p>无</p>")
        parts.append("<p>回复“通过”授权 push、建 PR、等 CI 并按分支合同合入收尾。</p>")
    else:
        parts.append("<p>回复“通过”授予 Autonomy Grant；之后只在 Halt 清单命中时停下。</p>")
    return "\n".join(parts) + "\n</html>\n"


# ---------- IO ----------

def load(map_dir: Path) -> dict:
    path = map_dir / DRIVER_FILE
    driver = json.loads(path.read_text()) if path.exists() else None
    lanes = closeout.latest_rows(map_dir) if map_dir.exists() else {}
    return {"driver": driver, "lanes": lanes}


def write_json(path: Path, value: dict) -> None:
    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    with os.fdopen(fd, "w") as h:
        h.write(text)
    os.replace(name, path)
    if path.read_text() != text:
        raise ValueError("driver.json readback 不一致")


def persist_lanes(map_dir: Path, updates: list[dict]) -> None:
    if not updates:
        return
    import lane_registry  # 延迟导入：其依赖 replacement → model_config
    default = map_dir / "registry.md"
    for row in updates:
        target = Path(row.pop("_file") or default)
        with lane_registry.lock(target) as path:
            lane_registry.persist(path, [row])


def record(map_dir: Path, ident: str, receipt, action: dict | None = None) -> dict:
    """交回回执：id 必须等于当前 decide 输出；已记录的 id 幂等返回。

    run 内部执行器传入它执行的 action：执行器（如 Herdr dispatch.py）可能已改写 registry。"""
    state = load(map_dir)
    d = state["driver"]
    if d is not None and ident in d.get("receipts", {}):
        return {"recorded": ident, "duplicate": True}
    action = action or decide(state)
    if ident == "halt" and action["action"] == "halt":
        ident = action["id"]
    if action["id"] != ident:
        raise ValueError(f"回执 id {ident} 不是当前待办 {action['id']}")
    new, updates = apply(state, action, receipt)
    persist_lanes(map_dir, updates)
    if new is not None:
        new.setdefault("receipts", {})[ident] = receipt if isinstance(receipt, dict) else {"decision": receipt}
        write_json(map_dir / DRIVER_FILE, new)
    return {"recorded": ident, "duplicate": False}


# core 执行器：输入 (map_dir, state, action) → 回执
def run_git(cwd: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, env=closeout.ENV)


def exec_fan_in(map_dir: Path, state, action) -> dict:
    a = action["args"]
    wt, commit = a.get("integration"), a.get("commit")
    if not wt or not commit:
        return {"state": "integration_checks_failed", "blocked_reason": "缺 integration worktree 或 head_commit"}
    if run_git(wt, "cherry-pick", commit).returncode != 0:
        run_git(wt, "cherry-pick", "--abort")
        return {"state": "integration_conflict", "blocked_reason": "cherry-pick 冲突"}
    head = run_git(wt, "rev-parse", "HEAD").stdout.strip()
    same = run_git(wt, "rev-parse", "HEAD^{tree}").stdout.strip() == run_git(wt, "rev-parse", f"{commit}^{{tree}}").stdout.strip()
    if not same:
        checks = (state["driver"].get("plan") or {}).get("focused_checks")
        if not checks:
            return {"state": "integration_checks_failed", "integrated_commit": head, "blocked_reason": "focused checks 命令缺失"}
        if subprocess.run(checks, shell=True, cwd=wt, capture_output=True).returncode != 0:
            return {"state": "integration_checks_failed", "integrated_commit": head, "blocked_reason": "focused checks 失败"}
    return {"state": "integrated", "integrated_commit": head}


def exec_consume(map_dir: Path, state, action) -> dict:
    row = state["lanes"][action["args"]["lane_id"]]
    if row.get("output_mode") == "verdict" and row.get("verdict") == "REVIEW_EXHAUSTED":
        return {"state": "blocked", "blocked_reason": "REVIEW_EXHAUSTED"}
    if row.get("output_mode") == "checks" and row.get("checks") == "fail":
        return {"state": "blocked", "blocked_reason": row.get("checks_detail") or "checks 失败"}
    return {"state": "consumed", **({"verdict": row["verdict"]} if row.get("verdict") else {})}


def exec_closeout(map_dir: Path, state, action) -> dict:
    row = state["lanes"][action["args"]["lane_id"]]
    out = subprocess.run([sys.executable, str(SCRIPTS / "closeout.py"), "lane", row["_file"], "--lane-id", row["lane_id"]],
                         capture_output=True, text=True)
    first = (out.stdout.splitlines() or [""])[0]
    if " closed" in first and out.returncode == 0:
        return {"result": "closed"}
    return {"result": "close_pending", "reason": first.partition(":")[2].strip() or out.stderr.strip()}


def exec_render(map_dir: Path, state, action) -> dict:
    kind = action["args"]["kind"]
    page = render(state, kind)
    path = map_dir / f"{kind}-review.html"
    path.write_text(page)
    return {"html": str(path), "sha": action["id"].rsplit(":", 1)[1]}


VERDICTS = ("REVIEW_EXHAUSTED", "REVIEW_BLOCKED", "PASS", "FIX")


def parse_marker(row, line: str) -> dict | None:
    """纯函数：终态行 → lane 字段更新；不是本 lane 的活跃终态时返回 None（幂等）。"""
    parts = line.strip().split(None, 3)
    if len(parts) < 2 or parts[0] != "LANE_DONE" or row is None or parts[1] != row["lane_id"]:
        return None
    if row.get("state") not in ACTIVE:
        return None
    if len(parts) >= 3 and parts[2] == "BLOCKED":
        return {"state": "blocked", "blocked_reason": " ".join(parts[3:]) or "Unknown"}
    coord = " ".join(parts[2:])
    mode = row.get("output_mode")
    fields = {"state": "terminal"}
    if mode in ("commit", "integration"):
        fields["head_commit"] = coord or "Unknown"
    elif mode == "verdict":
        fields["verdict_path"] = coord
        text = Path(coord).read_text() if coord and Path(coord).is_file() else ""
        fields["verdict"] = next((v for v in VERDICTS if v in text), "Unknown")
    else:
        fields["delivery"] = coord or "Unknown"
    return fields


def signal(map_dir: Path, line: str) -> dict:
    """watcher / coordinator 交回 worker 终态行；Driver 写 lane 行。"""
    lanes = closeout.latest_rows(map_dir)
    parts = line.split()
    row = lanes.get(parts[1]) if len(parts) > 1 else None
    fields = parse_marker(row, line)
    if fields is None:
        return {"signal": "ignored"}
    persist_lanes(map_dir, [{**{k: v for k, v in row.items() if k != "_file"}, **fields, "_file": row.get("_file")}])
    return {"signal": "recorded", "lane_id": row["lane_id"], "state": fields["state"]}


def render_packet(state, action, transport_lines=()) -> str:
    """按 lane-registry §轻量交接派发模板确定性渲染 packet；缺字段写 Unknown。"""
    a = action["args"]
    ticket = next((t for t in state["driver"]["plan"]["tickets"] if t["id"] == a["work_item"]), {})
    owner = ticket.get("owner") or {}
    get = lambda k: ticket.get(k) or a.get(k) or "Unknown"  # noqa: E731
    lines = [
        f"Lane ID：{a['lane_id']}",
        f"Work item：{ticket.get('url') or a['work_item']}",
        f"执行：{a['task']}/{a['output_mode']}；phase: executing",
        f"Owner：{owner.get('name', 'Unknown')}; {owner.get('path', 'Unknown')}; {owner.get('label', 'Unknown')}",
        f"Registry：{a.get('registry', 'Unknown')}",
        f"现场：{a.get('worktree', 'Unknown')}；{a.get('branch', 'Unknown')}；{a.get('base', 'Unknown')}",
        f"范围：{get('scope')}",
        f"验收：{get('acceptance')}",
        f"输入：{get('inputs')}" + (f"；HITL 回答：{a['answer']}" if a.get("answer") else ""),
        *transport_lines,
    ]
    return "\n".join(lines) + "\n"


CORE_EXECUTORS = {"fan_in": exec_fan_in, "consume": exec_consume, "closeout": exec_closeout, "render_review": exec_render}


def run(map_dir: Path, executors: dict | None = None, limit: int = 200) -> dict:
    """反复 decide；程序可执行的直接执行并 record，交回第一条需宿主/判断/等待/停下的 Action。"""
    table = {**CORE_EXECUTORS, **(executors or {})}
    for _ in range(limit):
        state = load(map_dir)
        action = decide(state)
        if action["action"] == "halt" and state["driver"] and state["driver"].get("halt") != action:
            new = dict(state["driver"], halt=action)  # 原因、证据坐标与可选项写入 map registry
            write_json(map_dir / DRIVER_FILE, new)
        fn = table.get(action["action"])
        receipt = fn(map_dir, state, action) if fn else None
        if receipt is None:  # 无执行器或执行器声明交回宿主
            return action
        record(map_dir, action["id"], receipt, action)
    raise RuntimeError("run 超过步数上限，疑似回执未推进状态")


def wakes_llm(action: dict) -> bool:
    return action["action"] not in QUIET


# ---------- self-test ----------

def _plan():
    return {"tickets": [
        {"id": "T1", "wave": 1, "task": "backend", "deps": []},
        {"id": "T2", "wave": 1, "task": "frontend", "deps": ["T1"]},
        {"id": "T3", "wave": 2, "task": "design", "deps": ["T2"], "hitl": True, "question": "选 A 还是 B"},
        {"id": "T4", "wave": 2, "task": "design", "deps": ["T2"], "hitl": True, "question": "颜色"},
    ], "test_strategy": {"level": "focused"}, "risk": "low", "critical_path": ["T1", "T2"]}


def _granted(**extra):
    plan = _plan()
    sha = plan_sha(plan)
    d = {"version": VERSION, "map": "m1", "gates": {"discovery": "a", "spec": "s", "tickets": "t"},
         "plan": plan, "plan_check": "pass", "grant": {"plan_sha": sha}, "published": "p",
         "test_strategy": {"level": "focused", "scope_sha": sha, "risk": "low"},
         "scope": {"sha": sha, "risk": "low"}}
    d.update(extra)
    return d


MAP = {"lane_id": "m1", "role": "map", "state": "running", "integration_worktree_path": "/i"}


def _lane(lid, state, **kw):
    return {"lane_id": lid, "work_item": kw.pop("work_item", lid), "role": kw.pop("role", "backend"),
            "output_mode": kw.pop("output_mode", "commit"), "state": state, **kw}


def _state(driver, *rows):
    return {"driver": driver, "lanes": {r["lane_id"]: r for r in rows}}


def _cases():
    done = lambda *ids: [_lane(i, "closed") for i in ids]  # noqa: E731
    all_done = done("T1", "T2", "T3", "T4")
    ok = lambda r: {"lane_id": r, "state": "closed"}  # noqa: E731
    _ = ok
    cases = [
        # (名称, state, 期望 action, 期望 id 前缀 / kind)
        ("legacy", _state(None, MAP), "legacy", "legacy"),
        ("no-map", _state(None), "halt", "halt:authority:no-map"),
        ("discovery", _state({"version": 1, "map": "m1", "gates": {}, "plan": {"tickets": []}}), "invoke_owner", "owner:discovery"),
        ("owner-blocked", _state({"version": 1, "map": "m1", "gates": {}, "plan": {"tickets": []},
                                  "owner_next": {"next": "blocked-human", "reason": "r"}}), "ask_human", "owner:discovery:human"),
        ("recheck", _state({"version": 1, "map": "m1", "gates": {"discovery": 1, "spec": 1, "tickets": 1},
                            "plan": _plan(), "plan_check": "fail"}), "invoke_owner", "owner:tickets:recheck"),
        ("render-plan", _state({"version": 1, "map": "m1", "gates": {"discovery": 1, "spec": 1, "tickets": 1},
                                "plan": _plan(), "plan_check": "pass"}), "render_review", "render:plan:"),
        ("plan-review", _state({"version": 1, "map": "m1", "gates": {"discovery": 1, "spec": 1, "tickets": 1},
                                "plan": _plan(), "plan_check": "pass",
                                "reviews": {"plan": {"sha": plan_sha(_plan()), "html": "/p.html"}}}), "ask_human", "review:plan:"),
        ("grant-stale", _state(_granted(grant={"plan_sha": "x"})), "halt", "halt:plan_change:grant"),
        ("publish", _state(_granted(published=None)), "invoke_owner", "owner:publish"),
        ("prepare-map", _state(_granted()), "prepare_map", "prepare_map"),
        ("dispatch-frontier", _state(_granted(), MAP), "dispatch", "dispatch:T1"),
        ("dep-wait", _state(_granted(), MAP, _lane("T1", "running")), "wait", "wait"),
        ("fan-in", _state(_granted(), MAP, _lane("T1", "terminal", head_commit="c")), "fan_in", "fan_in:T1"),
        ("consume", _state(_granted(), MAP, _lane("T1", "terminal", output_mode="artifact")), "consume", "consume:T1"),
        ("closeout", _state(_granted(), MAP, _lane("T1", "integrated")), "closeout", "closeout:T1"),
        ("merger", _state(_granted(), MAP, _lane("T1", "integration_conflict")), "dispatch", "dispatch:merger:T1"),
        ("judge-light", _state(_granted(), MAP, _lane("T1", "blocked")), "judge", "judge:classify:T1"),
        ("judge-heavy", _state(_granted(), MAP, _lane("T1", "blocked", blocked_reason="acceptance failed")), "judge", "judge:diagnose:T1:1"),
        ("resplit", _state(_granted(), MAP, _lane("T1", "blocked", blocked_reason="x", repairs="2")), "judge", "judge:resplit:T1"),
        ("hitl-merged", _state(_granted(), MAP, *done("T1", "T2")), "ask_human", "hitl:T3,T4"),
        ("testing", _state(_granted(), MAP, *all_done), "dispatch", "dispatch:testing"),
        ("review", _state(_granted(), MAP, *all_done, _lane("t", "closed", role="testing", work_item="m1#testing")), "dispatch", "dispatch:review"),
        ("review-fix", _state(_granted(), MAP, *all_done, _lane("t", "closed", role="testing", work_item="m1#testing"),
                              _lane("r", "consumed", role="review", work_item="m1#review", verdict="FIX")), "judge", "judge:review_fix:1"),
        ("render-merge", _state(_granted(), MAP, *all_done, _lane("t", "closed", role="testing", work_item="m1#testing"),
                                _lane("r", "consumed", role="review", work_item="m1#review", verdict="PASS")), "render_review", "render:merge:"),
        ("remote", _state(_granted(reviews={"merge": {"approved": True}}), MAP, *all_done,
                          _lane("t", "closed", role="testing", work_item="m1#testing"),
                          _lane("r", "consumed", role="review", work_item="m1#review", verdict="PASS")), "remote", "remote:push"),
        ("ci-wait", _state(_granted(reviews={"merge": {"approved": True}}, remote={"push": 1, "open_pr": 1, "ci": "pending", "pr": "u"}), MAP, *all_done,
                           _lane("t", "closed", role="testing", work_item="m1#testing"),
                           _lane("r", "consumed", role="review", work_item="m1#review", verdict="PASS")), "wait", "wait"),
        ("delivered", _state(_granted(reviews={"merge": {"approved": True}}, remote={s: 1 for s in REMOTE_STEPS}), MAP, *all_done,
                             _lane("t", "closed", role="testing", work_item="m1#testing"),
                             _lane("r", "consumed", role="review", work_item="m1#review", verdict="PASS")), "done", "done:delivered"),
        ("aborted", _state(_granted(status="aborted")), "done", "done:aborted"),
        # Halt 封闭清单：每一类
        ("halt-1-needs-decision", _state(_granted(), MAP, _lane("T1", "blocked", blocked_reason="needs-decision:spec-gap; a")), "halt", "halt:plan_change:T1"),
        ("halt-1-test-decision", _state(_granted(scope={"sha": "changed", "risk": "low"}), MAP), "halt", "halt:plan_change:test-decision"),
        ("halt-2-extra-ticket", _state(_granted(), MAP, _lane("X9", "running", wave="3")), "halt", "halt:extra_ticket:X9"),
        ("halt-3-review-exhausted", _state(_granted(), MAP, _lane("T1", "blocked", blocked_reason="REVIEW_EXHAUSTED")), "halt", "halt:review_exhausted:T1"),
        ("halt-4-resplit-failed", _state(_granted(), MAP, _lane("T1b", "blocked", work_item="T1", resplit_of="T1", repairs="2", blocked_reason="x")), "halt", "halt:resplit_failed:T1b"),
        ("halt-5-authority", _state(_granted(remote={"needs_authority": ["force-push"]}), MAP), "halt", "halt:authority:force-push"),
        ("halt-ci-red", _state(_granted(remote={"ci": "red", "pr": "u"}), MAP), "halt", "halt:ci_red:u"),
        ("halt-review-blocking", _state(_granted(remote={"review": "blocking", "pr": "u"}), MAP), "halt", "halt:review_blocking:u"),
        ("halt-resolved", _state(_granted(resolved_halts=["halt:extra_ticket:X9"]), MAP, _lane("X9", "running", wave="3")), "dispatch", "dispatch:T1"),
        ("extra-in-wave-auto", _state(_granted(), MAP, _lane("X1", "running", wave="1")), "dispatch", "dispatch:T1"),
    ]
    return cases


def self_test() -> int:
    failures = []
    for name, state, want, prefix in _cases():
        before = json.dumps(state, sort_keys=True, default=str)
        try:
            got = decide(state)
        except Exception as e:  # noqa: BLE001
            failures.append(f"{name}: {e!r}")
            continue
        if json.dumps(state, sort_keys=True, default=str) != before:
            failures.append(f"{name}: decide 改了输入")
        if got["action"] != want or not got["id"].startswith(prefix) or set(got) != {"action", "id", "args"}:
            failures.append(f"{name}: want {want}/{prefix} got {got['action']}/{got['id']}")
        json.loads(json.dumps(got, ensure_ascii=False))
    halts = {c[3].split(":")[1] for c in _cases() if c[2] == "halt"}
    if not set(HALT_CLASSES) <= halts:
        failures.append(f"Halt 类覆盖缺 {sorted(set(HALT_CLASSES) - halts)}")
    kinds = {c[2] for c in _cases()}
    need = {"legacy", "halt", "invoke_owner", "ask_human", "render_review", "prepare_map", "dispatch", "wait",
            "fan_in", "consume", "closeout", "judge", "remote", "done"}
    if not need <= kinds:
        failures.append(f"Action 覆盖缺 {sorted(need - kinds)}")
    # Epic
    epic = {"candidates": [{"mmf": "A", "map": "mA"}, {"mmf": "B", "blocked_by": ["A"]}], "maps": {"mA": "running"}}
    if decide_epic(epic)["action"] != "wait":
        failures.append("epic: 阻塞未解除不应开 map")
    epic["maps"]["mA"] = "closed"
    got = decide_epic(epic)
    if got["action"] != "open_map" or got["args"]["start"] != "to-spec" or got["id"] != "open_map:B":
        failures.append(f"epic: 应为 B 开 map 并启动 to-spec，got {got}")
    if decide_epic({"candidates": [{"mmf": "A", "map": "mA"}], "maps": {"mA": "closed"}})["action"] != "done":
        failures.append("epic: 全部 closed 应 done")
    failures += _io_self_test()
    for f in failures:
        print("FAIL", f)
    print("driver self-test:", "fail" if failures else "pass", f"({len(_cases())} cases)")
    return 1 if failures else 0


def _io_self_test() -> list[str]:
    """record 幂等、回执校验、halt 写入 registry、Plan Review 授权与 run 的程序执行。"""
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        md = Path(tmp)
        write_json(md / DRIVER_FILE, {"version": 1, "map": "m1", "gates": {"discovery": "a", "spec": "s", "tickets": "t"},
                                      "plan": _plan(), "plan_check": "pass"})
        a = run(md)
        if a["action"] != "ask_human" or a["args"]["kind"] != "plan-review" or not (md / "plan-review.html").exists():
            failures.append(f"run 应渲染 Plan Review 后交回 ask_human，got {a}")
        if render(load(md), "plan") != (md / "plan-review.html").read_text():
            failures.append("Plan Review HTML 不确定")
        try:
            record(md, "review:plan:wrong", {"reply": "通过"})
            failures.append("错误 id 应拒绝")
        except ValueError:
            pass
        record(md, a["id"], {"reply": "通过"})
        if record(md, a["id"], {"reply": "通过"}).get("duplicate") is not True:
            failures.append("重复回执应幂等")
        d = load(md)["driver"]
        if not d.get("grant") or d["test_strategy"].get("scope_sha") != plan_sha(d["plan"]):
            failures.append("Plan Review 通过应写 Autonomy Grant 与测试策略")
        record(md, "owner:publish", {"artifact": "tracker#1", "next": "to-tickets"})
        record(md, "prepare_map", {"map_row": dict(MAP, work_item="m1")})
        nxt = decide(load(md))
        if nxt["id"] != "dispatch:T1":
            failures.append(f"建 map 后应派 T1，got {nxt['id']}")
        try:
            record(md, "dispatch:T1", {"lane": {"lane_id": "T1", "work_item": "T9"}})
            failures.append("dispatch 回执 work_item 不符应拒绝")
        except ValueError:
            pass
        record(md, "dispatch:T1", {"lane": _lane("T1", "running")})
        if decide(load(md))["action"] != "wait":
            failures.append("T1 运行中应 wait")
        if signal(md, "LANE_DONE T1 abc123")["signal"] != "recorded" or load(md)["lanes"]["T1"].get("head_commit") != "abc123":
            failures.append("终态行应写 terminal 与 head_commit")
        if signal(md, "LANE_DONE T1 abc123")["signal"] != "ignored":
            failures.append("重复终态行应幂等忽略")
        if decide(load(md))["id"] != "fan_in:T1":
            failures.append("terminal commit lane 应 fan_in")
        if "Owner：Unknown" not in render_packet(load(md), act("dispatch", "x", work_item="T2", lane_id="T2", task="frontend", output_mode="commit")):
            failures.append("packet 缺 owner 应写 Unknown")
        # halt：写入 map registry，用户决定交回
        persist_lanes(md, [{**_lane("T1", "blocked", blocked_reason="REVIEW_EXHAUSTED"), "_file": str(md / "registry.md")}])
        h = run(md)
        if h["action"] != "halt" or (load(md)["driver"].get("halt") or {}).get("id") != h["id"]:
            failures.append("halt 应写入 driver.json")
        if not h["args"]["options"] or not h["args"]["evidence"]:
            failures.append("halt 必须带可选项与证据坐标")
        record(md, "halt", "接受剩余 findings 继续")
        if decide(load(md))["id"] == h["id"]:
            failures.append("已裁决的 halt 不应再触发")
    return failures


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd = argv[0]
    if cmd == "self-test":
        return self_test()
    if cmd == "epic":
        print(json.dumps(decide_epic(json.loads(Path(argv[1]).read_text())), ensure_ascii=False))
        return 0
    map_dir = Path(argv[1]).resolve()
    if cmd == "decide":
        print(json.dumps(decide(load(map_dir)), ensure_ascii=False))
    elif cmd == "run":
        print(json.dumps(run(map_dir), ensure_ascii=False))
    elif cmd == "record":
        raw = argv[3]
        try:
            receipt = json.loads(raw)
        except json.JSONDecodeError:
            receipt = raw  # halt 决定原文
        print(json.dumps(record(map_dir, argv[2], receipt), ensure_ascii=False))
    elif cmd == "signal":
        print(json.dumps(signal(map_dir, argv[2]), ensure_ascii=False))
    elif cmd == "init":
        path = map_dir / DRIVER_FILE
        if path.exists():
            raise SystemExit("driver.json 已存在")
        map_dir.mkdir(parents=True, exist_ok=True)
        write_json(path, {"version": VERSION, "map": argv[2], "gates": {}, "plan": {"tickets": []}})
        print(json.dumps(decide(load(map_dir)), ensure_ascii=False))
    else:
        raise SystemExit(f"未知命令 {cmd}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except ValueError as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
