#!/usr/bin/env python3
"""Driver：程序驱动的 map / Epic 状态机（ADR-0026）。

core 只有三件事：
- `decide(state) -> Action`：纯函数，冻结输入、无副作用；Action 是一行 JSON {"action","id","args"}。
- `apply(state, action, receipt)`：纯函数，把回执变成 driver.json 新值与待写 lane 行。
- IO 层（load / record / run）：读 map 目录、写 driver.json 与 lane registry，执行 core 执行器
  （fan_in、closeout、consume、render_review、scenario、dispatch_briefs）。壳的 run 循环传入额外执行器（如 Herdr dispatch）。

registry 只由 Driver 写；回执按 id 幂等。core 不引用任何壳文件。

命令：
  driver.py decide <map_dir>                      只输出下一条 Action
  driver.py run <map_dir>                         执行程序能执行的 Action，交回第一条需宿主/判断/等待/停下的 Action
  driver.py record <map_dir> <id> <receipt_json>  交回回执；id 为 halt 时 receipt 是用户决定原文
  driver.py signal <map_dir> "<LANE_DONE 行>"      交回 worker 终态行（watcher 或 coordinator 调用）
  driver.py init <map_dir> <map_id>               为新 map 初始化自动规划
  driver.py epic <epic_json>                      Epic 级：输出下一条 open_map / wait / done
  driver.py self-test

run / record / signal 之后按状态同步 map 内 issue 的 tracker 阶段（issue_status.py）。
"""

from __future__ import annotations

import fcntl
import hashlib
import re
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
import issue_status  # noqa: E402
import brief_delivery  # noqa: E402
import review_html  # noqa: E402

DRIVER_FILE = "driver.json"
VERSION = 1

# Halt 封闭清单（ADR-0026 决策 8）。清单外不得产生 halt。
HALT_CLASSES = {
    "plan_change": "1 计划的 T/R、范围或验收要改",
    "extra_ticket": "2 补票超出已批准波次或改动合同票",
    "review_exhausted": "3 Review 反例修不绿（旧账本 REVIEW_EXHAUSTED）",
    "resplit_failed": "4 重拆之后仍然失败",
    "authority": "5 需要远程权限、不可逆操作或授权外的决定",
    "ci_red": "CI 红",
    "review_blocking": "评审意见阻塞",
}
# 程序在 core 内直接执行的 Action；壳可追加（Herdr: dispatch）。
CORE_PROGRAM = frozenset({"fan_in", "closeout", "consume", "render_review", "freeze_plan", "scenario"})
# 不唤醒 LLM 的结果。
QUIET = frozenset({"wait"})
ACTIVE = {"created", "running", "awaiting_human"}
FAILED = {"blocked", "integration_checks_failed"}
MAX_REPAIRS = 2  # ADR-0012：两轮修复后重拆
PLANNING_OWNERS = (("discovery", "wayfinder"), ("spec", "to-spec"), ("tickets", "to-tickets"))
REMOTE_STEPS = ("push", "open_pr", "wait_ci", "merge", "finalize")
PURPOSE_OUTPUT_MODE = {
    "planning": "artifact",
    "code": "commit",
    "artifact": "artifact",
    "checks": "checks",
    "advisory": "artifact",
}


def resolve_ticket_output_mode(ticket, work_types) -> tuple[str | None, str | None]:
    """按配置任务类型的用途推导未显式填写的 output_mode；配置中已删除该类型时返回 (None, error)。"""
    task = ticket.get("task", "backend")
    if work_types is not None:
        if task not in work_types:
            return None, f"task type not defined in config: {task}"
        explicit = ticket.get("output_mode")
        if explicit:
            return explicit, None
        return PURPOSE_OUTPUT_MODE[work_types[task]], None
    return ticket.get("output_mode", "commit"), None


def resolve_checks_task(work_types) -> str | None:
    """解析 whole-change testing 使用的任务类型：优先同名 testing（checks），否则取首个 checks 类型。"""
    if work_types is None:
        return "testing"
    if work_types.get("testing") == "checks":
        return "testing"
    return next((task for task, purpose in work_types.items() if purpose == "checks"), None)


def is_whole_change_testing(row, map_id: str) -> bool:
    return row.get("role") == "testing" or row.get("work_item") == f"{map_id}#testing"


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


def brief_tasks(state):
    return sorted({t.get("task", "backend") for t in state["driver"]["plan"]["tickets"]
                   if brief_delivery.has_briefs(t)})


def scenario_id(item, head):
    return f"scenario:{item}:{head}"


def merge_brief_evidence(state):
    """当前 Integration HEAD 的场景证据和该票实际执行片。"""
    d = state["driver"]
    lanes = lanes_by_item(state["lanes"])
    head = state.get("integration_head")
    receipts = d.get("receipts", {})
    reports = {(row["lane_id"], row["head_commit"]): row.get("worker_reports", [])
               for key, receipt in receipts.items() if key.startswith("briefs:")
               for row in receipt["lanes"]}
    fields = ("slice_id", "model", "effort", "head_commit")
    return {
        ticket["id"]: {
            "slices": [{**{k: row.get(k) for k in fields},
                        "worker_reports": reports.get((row["lane_id"], row.get("head_commit")), [])}
                       for row in sorted(lanes.get(ticket["id"], ()), key=lambda r: r.get("slice_id") or "")
                       if row.get("slice_id")],
            "scenario": receipts.get(scenario_id(ticket["id"], head)),
        }
        for ticket in d["plan"]["tickets"] if brief_delivery.has_briefs(ticket)
    }


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
    repair_lanes = {r.get("repair_lane") for r in state["lanes"].values() if r.get("repair_lane")}
    fix_lanes = {r.get("fix_lane") for r in state["lanes"].values() if r.get("fix_lane")}
    out = []
    for row in sorted(state["lanes"].values(), key=lambda r: r["lane_id"]):
        role = row.get("role")
        if role in ("map", "planning", "review", "integration"):
            if role == "integration" and row.get("merges"):
                out.append(f"merger {row['lane_id']} 处理 {row['merges']} 的收口失败")
            continue
        if is_whole_change_testing(row, d["map"]):
            if int(row.get("repairs") or 0):
                suffix = f"（{row['repair_lane']}）" if row.get("repair_lane") else ""
                out.append(f"整体检查 {row['lane_id']} 修复 {row['repairs']} 轮{suffix}")
            continue
        if (row.get("work_item") not in planned
                and row["lane_id"] not in repair_lanes
                and row["lane_id"] not in fix_lanes):
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
    head, seen = state.get("integration_head"), d.get("integration_seen")
    if seen and head and head != seen and driver_owns_head(lanes):
        candidates.append(halt("authority", f"integration-head:{head}",
                               "集成分支上有不是 Driver 留下的提交。coordinator 不在集成树手工 cherry-pick、合并或改码；"
                               "冲突和检查失败交回 Driver，由它派 merger 或修复 lane",
                               [f"Driver 留下 {seen[:12]}，当前 {head[:12]}", *state.get("integration_foreign", ())],
                               ["认可这些提交并继续", f"回退到 {seen[:12]} 后继续", "放弃本 MMF"]))
    for row in sorted(lanes.values(), key=lambda r: r["lane_id"]):
        lid, reason = row["lane_id"], row.get("blocked_reason") or ""
        if row.get("state") == "blocked" and "REVIEW_EXHAUSTED" in reason:
            candidates.append(halt("review_exhausted", lid, "Review 阻断项反例修不绿", [row.get("_file", ""), lid],
                                   ["接受剩余 findings 继续", "重拆该票", "放弃本 MMF"]))
        if row.get("state") == "blocked" and "needs-decision" in reason:
            candidates.append(halt("plan_change", lid, reason, [row.get("artifact") or lid],
                                   ["补充 Spec/验收来源后重派", "改范围", "放弃该票"]))
        if row.get("resplit_of") and row.get("state") in FAILED and int(row.get("repairs") or 0) >= MAX_REPAIRS:
            candidates.append(halt("resplit_failed", lid, f"重拆自 {row['resplit_of']} 后仍失败",
                                   [lid, row["resplit_of"]], ["人工接手", "改计划", "放弃该票"]))
        item = row.get("work_item")
        if (row.get("role") not in ("map", "testing", "review", "integration")
                and not is_whole_change_testing(row, d["map"]) and item not in planned):
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


def driver_owns_head(lanes) -> bool:
    """票实施阶段集成 HEAD 只由 Driver 移动；merger 在途或进入整体测试、评审后，别的 lane 也会合法地动它。"""
    return not any(r.get("role") in ("testing", "review")
                   or str(r.get("work_item") or "").endswith("#testing")
                   or (r.get("role") == "integration" and r.get("state") in ACTIVE | {"terminal"})
                   for r in lanes.values())


def owner_action_id(d, gate, prefix):
    attempt = d.get("owner_attempts", {}).get(gate, 0)
    return f"{prefix}:{attempt}" if attempt else prefix


def lane_attempt_id(prefix: str, row) -> str:
    repairs = int(row.get("repairs") or 0)
    return f"{prefix}:{row['lane_id']}:{repairs}" if repairs else f"{prefix}:{row['lane_id']}"


def decide_planning(state):
    """无 Autonomy Grant：沿 owner 链完成计划检查或转 Epic。"""
    d = state["driver"]
    gates = d.get("gates", {})
    if d.get("epic"):
        return act("handoff_epic", "epic:handoff", epic=d["epic"])
    if split := d.get("epic_split"):
        return act("invoke_owner", owner_action_id(d, "epic", "owner:epic"), owner="to-epic", gate="epic", input=split["artifact"],
                   decision=thaw(split["decision"]), feedback=d.get("plan_feedback"), planning_mode=d.get("planning_mode"))
    for gate, owner in PLANNING_OWNERS:
        if not gates.get(gate):
            if gate == "discovery" and d.get("skip_discovery"):
                continue
            return act("invoke_owner", owner_action_id(d, gate, f"owner:{gate}"), owner=owner, gate=gate,
                       feedback=d.get("plan_feedback"), planning_mode=d.get("planning_mode"))
    if d.get("plan_check") != "pass":
        revision = d.get("ticket_revision", 0)
        return act("invoke_owner", owner_action_id(d, "tickets", f"owner:tickets:recheck:{revision}"), owner="to-tickets", gate="tickets",
                   feedback=d.get("plan_feedback") or d.get("plan_check"), planning_mode=d.get("planning_mode"))
    review = (d.get("reviews") or {}).get("plan") or {}
    sha = plan_sha(d["plan"])
    if d.get("planning_mode") == "auto":
        return act("freeze_plan", f"freeze:plan:{sha}", kind="plan")
    if review.get("sha") != sha:
        return act("render_review", f"render:plan:{sha}", kind="plan")
    review_key = plan_sha([sha, review["preflight"]]) if review.get("preflight") else sha
    return act("ask_human", f"review:plan:{review_key}", kind="plan-review", html=review.get("html"),
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
    if d.get("status") in ("done", "aborted", "handed_off"):
        return act("done", f"done:{d['status']}")
    if d.get("halt"):
        return thaw(d["halt"])
    nxt = d.get("owner_next") or {}
    if nxt.get("next") == "blocked-human":
        gate = nxt.get("gate") or next((g for g, _ in PLANNING_OWNERS if not d.get("gates", {}).get(g)), "tickets")
        return act("ask_human", owner_action_id(d, gate, f"owner:{gate}:human"), kind="owner-blocked",
                   gate=gate, reason=nxt.get("reason"))
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
        return act("invoke_owner", owner_action_id(d, "publish", "owner:publish"), owner="to-tickets", gate="publish",
                   planning_mode=d.get("planning_mode"), feedback=d.get("plan_feedback"),
                   note="Autonomy Grant 已授予；按已批准草稿发布")
    mrow = map_row(lanes)
    if not mrow:
        return act("prepare_map", "prepare_map", note="建 Map Integration Worktree 并交回 map row")

    tickets = sorted(d['plan']['tickets'], key=lambda t: (t.get('wave', 1), t['id']))
    by_item = lanes_by_item(lanes)
    receipts = d.get('receipts', {})
    managed = {t['id']: t for t in tickets if brief_delivery.has_briefs(t) or 'scenario_check' in t}

    def current_scenario(item):
        return scenario_id(item, state.get('integration_head', ''))

    def done(item):
        if item in managed:
            return (brief_delivery.complete(managed[item], by_item.get(item, ()))
                    and receipts.get(current_scenario(item), {}).get('ok') is True)
        return item_done(by_item.get(item))

    for item, ticket in managed.items():
        rows = by_item.get(item, ())
        if brief_delivery.complete(ticket, rows) and current_scenario(item) not in receipts:
            return act('scenario', current_scenario(item), work_item=item, head=state.get('integration_head'))
        if receipts.get(current_scenario(item), {}).get('ok') is False:
            return act('halt', f'halt:plan_change:scenario:{item}', kind='plan_change', label=HALT_CLASSES['plan_change'],
                       reason=f'{item} 整票场景未通过', evidence=[f'{DRIVER_FILE}#{current_scenario(item)}'], options=['修订计划后重审'])

    # 1. 程序收口：terminal → fan_in / consume；完成 → closeout
    for row in sorted(lanes.values(), key=lambda r: r["lane_id"]):
        lid, st = row["lane_id"], row.get("state")
        if row.get("role") == "map":
            continue
        if st == "terminal":
            if row.get("output_mode") == "commit":
                return act("fan_in", lane_attempt_id("fan_in", row), lane_id=lid, commit=row.get("head_commit"),
                           integration=mrow.get("integration_worktree_path"))
            return act("consume", lane_attempt_id("consume", row), lane_id=lid, output_mode=row.get("output_mode"),
                       verdict=row.get("verdict"))
        if row.get('work_item') in managed and not done(row['work_item']):
            continue
        if st in ("integrated", "consumed"):
            return act("closeout", f"closeout:{lid}", lane_id=lid)
        if st == "close_pending":  # 释放失败不重试、不跳过：停下报原因
            return act("halt", f"halt:authority:close_pending:{lid}", kind="authority", label=HALT_CLASSES["authority"],
                       reason=f"{lid} 未释放：{row.get('close_reason') or 'Unknown'}", evidence=[row.get("_file") or lid],
                       options=["按原因处理 pane 或树后把 lane 改回 consumed/integrated 再 run"])

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
    work_types = state.get("work_types")
    task, jobs = brief_delivery.batch(tickets, by_item, done, d.get('answers', {}))
    if jobs and work_types is not None and task not in work_types:
        hid = f"halt:plan_change:missing-task:{task}"
        if hid not in set(d.get("resolved_halts", ())):
            return act("halt", hid, kind="plan_change", label=HALT_CLASSES["plan_change"],
                       reason=f"task type not defined in config: {task}",
                       evidence=[f"{DRIVER_FILE}#plan"],
                       options=["在配置中补回该任务类型后重新 run", "修订票面任务类型后重审计划"])
    if jobs and any(row.get('role') != 'map' and row.get('state') in ACTIVE for row in lanes.values()):
        return act('wait', 'wait', lanes=sorted(row['lane_id'] for row in lanes.values()
                   if row.get('state') in ACTIVE and row.get('role') != 'map'))
    if jobs:
        return act('dispatch_briefs', 'briefs:' + plan_sha(jobs), task=task, briefs=thaw(jobs))
    pending_hitl = []
    for ticket in tickets:
        if by_item.get(ticket["id"]):
            continue
        if not all(done(dep) for dep in ticket.get("deps", ())):
            continue
        if ticket.get("hitl") and ticket["id"] not in d.get("answers", {}):
            pending_hitl.append(ticket)
            continue
        if ticket['id'] in managed:
            continue
        task_name = ticket.get("task", "backend")
        mode, task_err = resolve_ticket_output_mode(ticket, work_types)
        if task_err:
            hid = f"halt:plan_change:missing-task:{ticket['id']}:{task_name}"
            if hid not in set(d.get("resolved_halts", ())):
                return act("halt", hid, kind="plan_change", label=HALT_CLASSES["plan_change"],
                           reason=task_err, evidence=[f"{DRIVER_FILE}#plan", f"ticket:{ticket['id']}"],
                           options=["在配置中补回该任务类型后重新 run", "修订票面任务类型后重审计划"])
            mode = ticket.get("output_mode", "commit")
        brief = thaw(d.get("contracts", {}).get(ticket["id"]))
        if mode == "commit" and not brief:  # ADR-0028：没有合同不派发
            return act("prepare_contract", f"contract:{ticket['id']}", owner="delegate-ticket",
                       work_item=ticket["id"], base=state.get("integration_head"))
        extra = {}
        if ticket.get("ticket_mode"):
            extra["ticket_mode"] = ticket["ticket_mode"]
        if d["plan"].get("map_mode"):
            extra["map_mode"] = d["plan"]["map_mode"]
        if brief:
            extra.update(contract=brief, **brief_delivery.packet(brief))
        return act("dispatch", f"dispatch:{ticket['id']}", task=task_name,
                   output_mode=mode, work_item=ticket["id"],
                   lane_id=ticket.get("lane_id", ticket["id"]), answer=d.get("answers", {}).get(ticket["id"]),
                   **extra)
    if pending_hitl:
        ids = ",".join(t["id"] for t in pending_hitl)
        return act("ask_human", f"hitl:{ids}", kind="hitl",
                   questions=[{"ticket": t["id"], "question": t.get("question", "")} for t in pending_hitl])

    active = [r["lane_id"] for r in lanes.values()
              if r.get("role") != "map" and (r.get("state") in ACTIVE or r.get("state") in FAILED)]
    planned_done = all(done(t['id']) for t in tickets)
    if active or not planned_done:
        return act("wait", "wait", lanes=sorted(active))

    # 4. whole-change testing → review
    testing_rows = [r for r in lanes.values() if is_whole_change_testing(r, d["map"])]
    if not testing_rows:
        checks_task = resolve_checks_task(work_types)
        if checks_task is None:
            return act("halt", "halt:plan_change:missing-task:testing", kind="plan_change",
                       label=HALT_CLASSES["plan_change"],
                       reason="task type not defined in config: testing",
                       evidence=[f"{DRIVER_FILE}#plan"],
                       options=["在配置中补回 checks 用途任务类型后重新 run"])
        return act("dispatch", "dispatch:testing", task=checks_task, output_mode="checks",
                   lane_id=f"{d['map']}-testing", work_item=f"{d['map']}#testing",
                   strategy=thaw(d.get("test_strategy")))
    latest_testing = max(testing_rows, key=lambda r: r["lane_id"])
    if latest_testing.get("state") not in closeout.DONE:
        return act("wait", "wait", lanes=[latest_testing["lane_id"]])

    review_rows = [r for r in lanes.values() if r.get("role") == "review"]
    if not review_rows:
        return act("dispatch", "dispatch:review", task="review", output_mode="verdict",
                   lane_id=f"{d['map']}-review", work_item=f"{d['map']}#review",
                   strategy=thaw(d.get("test_strategy")))
    latest_review = max(review_rows, key=lambda r: r["lane_id"])
    if latest_review.get("verdict") == "FIX":
        rnd = int(latest_review.get("round") or 1)
        fix_id = f"judge:review_fix:{rnd}"
        if latest_review.get("state") != "superseded" and fix_id not in receipts:
            return act("judge", fix_id, weight="heavy", kind="review-fix",
                       lane_id=latest_review["lane_id"], note="FIX findings 交同一 implementer lane 修复；反例变绿加完整测试即关闭，不开下一轮（ADR-0027）")
    elif latest_review.get("state") not in closeout.DONE:
        return act("wait", "wait", lanes=[latest_review["lane_id"]])

    # 5. Merge Review → remote
    review = (d.get("reviews") or {}).get("merge") or {}
    if not review.get("approved"):
        observations = [{k: row.get(k) for k in ("lane_id", "state", "verdict", "checks", "verdict_path", "delivery")}
                        for row in sorted(lanes.values(), key=lambda r: r["lane_id"])]
        sha = plan_sha([d["plan"], d.get("planning_decisions", []), observations, deviations(state),
                        merge_brief_evidence(state), state.get("integration_head")])
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
    "prepare_contract": {"briefs"},
    "dispatch_briefs": {"lanes"},
    "scenario": {"base", "check", "observed", "ok"},
    "prepare_map": {"map_row"},
    "remote": {"result"},
    "fan_in": {"state"},
    "consume": {"state"},
    "closeout": {"result"},
    "render_review": {"html", "sha"},
    "freeze_plan": {"html", "sha", "preflight"},
    "handoff_epic": {"artifact"},
    "open_map": {"map"},
}


def grant_plan(d, ident):
    sha = plan_sha(d["plan"])
    d["grant"] = {"plan_sha": sha, "review": ident}
    d["test_strategy"] = {**(d["plan"].get("test_strategy") or {}), "scope_sha": sha, "risk": d["plan"].get("risk")}
    d["scope"] = {"sha": sha, "risk": d["plan"].get("risk")}


def record_decision(d, receipt, phase, artifact, required=False):
    decision = receipt.get("decision")
    if decision is None and not required:
        return
    if (not isinstance(decision, dict) or not decision.get("reason") or not decision.get("change")
            or not isinstance(decision.get("evidence"), list) or not decision["evidence"]):
        raise ValueError("自动调整需要 decision.reason、decision.change 与 decision.evidence 坐标")
    d.setdefault("planning_decisions", []).append({"phase": phase, "artifact": artifact, **decision})


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
            d["owner_next"] = {"next": "blocked-human", "gate": gate, "reason": receipt.get("reason")}
            return d, []
        d["owner_next"] = None
        split = receipt["next"] == "to-epic" and gate in ("spec", "tickets")
        record_decision(d, receipt, gate, receipt["artifact"], required=split or
                        (d.get("planning_mode") == "auto" and gate == "tickets" and receipt.get("check") != "pass"))
        if split:
            d["epic_split"] = {"artifact": receipt["artifact"], "decision": receipt["decision"]}
            return d, []
        if gate == "epic":
            if receipt["next"] != "to-spec" or not receipt["artifact"]:
                raise ValueError("Epic owner 必须返回已发布 Epic 坐标与 NEXT: to-spec")
            d["epic"] = receipt["artifact"]
            return d, []
        if gate == "publish":
            d["published"] = receipt["artifact"]
            return d, []
        d.setdefault("gates", {})[gate] = receipt["artifact"]
        if gate == "tickets":
            if not isinstance(receipt.get("plan"), dict) or "tickets" not in receipt["plan"]:
                raise ValueError("to-tickets 回执必须带 plan.tickets")
            d["plan"] = receipt["plan"]
            d["plan_check"] = receipt.get("check")
            d["ticket_revision"] = d.get("ticket_revision", 0) + 1
            d["plan_feedback"] = receipt.get("decision") if d["plan_check"] != "pass" else None
    elif kind == "ask_human":
        reply = receipt["reply"]
        if args["kind"] == "plan-review":
            if str(reply).strip() == "通过":
                preflight = d["reviews"]["plan"].get("preflight", [])
                if [r["task"] for r in preflight if r["ok"] is True] != brief_tasks(state):
                    raise ValueError("蜂巢执行预检未通过，请先修正配置")
                grant_plan(d, ident)
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
            gate = args["gate"]
            attempts = d.setdefault("owner_attempts", {})
            attempts[gate] = attempts.get(gate, 0) + 1
    elif kind == "judge":
        if args["weight"] == "light":
            if receipt["answer"] not in args["options"] or not receipt["evidence"]:
                raise ValueError("轻判断必须从 options 选一项并附证据坐标")
            d.setdefault("judgements", {})[ident] = {"answer": receipt["answer"], "evidence": receipt["evidence"]}
        else:
            lid = args["lane_id"]
            if args["kind"] == "acceptance-diagnosis":
                if "briefs" in receipt:  # 诊断结论是合同划错：换合同，原提交按新合同重核
                    item = lanes[lid]["work_item"]
                    d.setdefault("contracts", {})[item] = brief_delivery.contract(item, receipt["briefs"])
                lane_update(lid, state="running", repairs=int(lanes[lid].get("repairs") or 0) + 1,
                            repair_lane=receipt["lane_id"])
            elif args["kind"] == "resplit":
                record_decision(d, receipt, "resplit", receipt["lane_id"], required=d.get("planning_mode") == "auto")
                lane_update(lid, state="superseded", superseded_by=receipt["lane_id"])
            elif args["kind"] == "review-fix":
                lane_update(lid, state="superseded", fix_lane=receipt["lane_id"])
    elif kind == 'dispatch_briefs':
        updates.extend({**{k: v for k, v in row.items() if k != 'worker_reports'}, '_file': None} for row in receipt['lanes'])
    elif kind == "prepare_contract":
        d.setdefault("contracts", {})[args["work_item"]] = brief_delivery.contract(args["work_item"], receipt["briefs"])
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
        allowed = {"fan_in": {"integrated", "integration_conflict", "integration_checks_failed", "blocked"},
                   "consume": {"consumed", "blocked"}}[kind]
        if receipt["state"] not in allowed:
            raise ValueError(f"{kind} 回执 state 非法")
        extra = {k: receipt[k] for k in ("integrated_commit", "blocked_reason", "verdict", "scope_drift") if k in receipt}
        lane_update(args["lane_id"], state=receipt["state"], **extra)
    elif kind == "closeout":
        if receipt["result"] not in ("closed", "close_pending"):
            raise ValueError("closeout 回执 result 非法")
        lane_update(args["lane_id"], state=receipt["result"], close_reason=receipt.get("reason"))
    elif kind in ("render_review", "freeze_plan"):
        d.setdefault("reviews", {})[args["kind"]] = {**(d.get("reviews", {}).get(args["kind"]) or {}),
                                                    "html": receipt["html"], "sha": receipt["sha"]}
        if args["kind"] == "plan":
            d["reviews"]["plan"]["preflight"] = receipt["preflight"]
        if kind == "freeze_plan":
            if [r["task"] for r in receipt["preflight"] if r["ok"] is True] != brief_tasks(state):
                raise ValueError(f"蜂巢执行预检未通过，修正配置后重新 run。{receipt['html']}")
            grant_plan(d, ident)
    elif kind == "handoff_epic":
        if not receipt["artifact"]:
            raise ValueError("Epic 交接需要恢复坐标")
        d["status"] = "handed_off"
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


# ---------- HTML 审核页（同一模板，确定性；实现在 review_html.py） ----------

def render(state, kind: str, preflight: str = '') -> str:
    return review_html.render(
        state,
        kind,
        preflight,
        deviations_fn=deviations,
        evidence_fn=merge_brief_evidence,
        plan_sha_fn=plan_sha,
        has_briefs_fn=brief_delivery.has_briefs,
    )


# ---------- IO ----------

def load_work_types() -> dict[str, str] | None:
    """只读 CLI 配置的 task_id -> purpose 映射；配置缺失时返回 None（兼容无配置单测）。"""
    setup_scripts = str(SCRIPTS.parents[1] / "delivery-pipeline-setup" / "scripts")
    if setup_scripts not in sys.path:
        sys.path.insert(0, setup_scripts)
    import model_config
    path = model_config.cli_config_path()
    if not path.exists():
        return None
    doc = model_config.load_document(path)
    work = model_config.normalize_work_entries(doc)
    return {task: entry["purpose"] for task, entry in work.items()}


def load(map_dir: Path) -> dict:
    path = map_dir / DRIVER_FILE
    driver = json.loads(path.read_text()) if path.exists() else None
    lanes = closeout.latest_rows(map_dir) if map_dir.exists() else {}
    state = {'driver': driver, 'lanes': lanes}
    work_types = load_work_types()
    if work_types is not None:
        state['work_types'] = work_types
    mrow = map_row(lanes)
    if driver and mrow:
        wt = mrow.get('integration_worktree_path')
        if any(brief_delivery.has_briefs(t) for t in driver.get('plan', {}).get('tickets', ())):
            state['integration_head'] = brief_delivery.git(wt, 'rev-parse', 'HEAD')
        elif wt and Path(wt).is_dir():
            proc = run_git(wt, 'rev-parse', 'HEAD')
            if proc.returncode == 0 and proc.stdout.strip():
                state['integration_head'] = proc.stdout.strip()
        seen, head = driver.get('integration_seen'), state.get('integration_head')
        if seen and head and seen != head:
            log = run_git(wt, 'log', '--format=%h %s', '-20', f'{seen}..{head}')
            state['integration_foreign'] = log.stdout.splitlines() if log.returncode == 0 else []
    return state


def sync_issues(map_dir: Path, call=None) -> None:
    """按当前状态把 map 内 issue 推到应处阶段；已确认的阶段写回 driver.json#issue_status。"""
    state = load(map_dir)
    d = state['driver']
    if not d:
        return
    cache, error = issue_status.sync(d, lanes_by_item(state['lanes']), call)
    if cache != (d.get('issue_status') or {}):
        write_json(map_dir / DRIVER_FILE, dict(d, issue_status=cache))
    if error:
        raise ValueError(error)


def mark_seen(map_dir: Path) -> None:
    """记下 Driver 自己留下的集成 HEAD；之后出现的别的 HEAD 由 detect_halt 当外来提交处理。"""
    state = load(map_dir)
    d, head = state['driver'], state.get('integration_head')
    if d and head and d.get('integration_seen') != head:
        write_json(map_dir / DRIVER_FILE, dict(d, integration_seen=head))


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
    grouped = {}
    for row in updates:
        target = Path(row.pop('_file') or default)
        grouped.setdefault(target, []).append(row)
    for target, rows in grouped.items():
        with lane_registry.lock(target) as path:
            lane_registry.persist(path, rows)


def record(map_dir: Path, ident: str, receipt, action: dict | None = None) -> dict:
    """交回回执：id 必须等于当前 decide 输出；已记录的 id 幂等返回。

    run 内部执行器传入它执行的 action：执行器（如 Herdr dispatch.py）可能已改写 registry。"""
    state = load(map_dir)
    d = state["driver"]
    if d is not None and ident in d.get("receipts", {}):
        return {"recorded": ident, "duplicate": True}
    internal = action is not None
    action = action or decide(state)
    row = state['lanes'].get(action['args'].get('lane_id'), {})
    if not internal and (action['action'] in ('dispatch_briefs', 'scenario', 'render_review', 'freeze_plan') or row.get('slice_id')):
        raise ValueError('此 Action 只接受 Driver 执行回执')
    if ident == "halt" and action["action"] == "halt":
        ident = action["id"]
    if action["id"] != ident:
        raise ValueError(f"回执 id {ident} 不是当前待办 {action['id']}")
    if (action['args'].get('kind') == 'plan-review' and isinstance(receipt, dict)
            and str(receipt.get('reply')).strip() == '通过' and brief_tasks(state)):
        preflight = brief_preflight(state)
        if preflight != d['reviews']['plan'].get('preflight'):
            render_action = act("render_review", f"render:plan:{plan_sha(d['plan'])}", kind="plan")
            updated = exec_render(map_dir, state, render_action, preflight)
            new, _ = apply(state, render_action, updated)
            new.setdefault("receipts", {})[render_action["id"]] = updated
            write_json(map_dir / DRIVER_FILE, new)
            raise ValueError(f"蜂巢执行预检已变化，请重新查看 {updated['html']}")
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
    row = state['lanes'][a['lane_id']]
    if row.get('slice_id'):
        target = map_row(state['lanes']).get('integration_branch')
        return brief_delivery.integrate(wt, row, target)
    if not wt or not commit:
        return {"state": "integration_checks_failed", "blocked_reason": "缺 integration worktree 或 head_commit"}
    brief = (state["driver"].get("contracts") or {}).get(row.get("work_item"))
    why, outside = brief_delivery.audit(wt, row, brief, commit) if brief else (None, [])
    if why:  # 走既有诊断修复链（ADR-0012）
        return {"state": "blocked", "blocked_reason": why}
    drift = {"scope_drift": "、".join(outside)} if outside else {}  # 越界只记偏差，合并评审页显示
    if run_git(wt, "cherry-pick", commit).returncode != 0:
        empty = (run_git(wt, "rev-parse", "-q", "--verify", "CHERRY_PICK_HEAD").returncode == 0
                 and not run_git(wt, "diff", "--name-only", "--diff-filter=U").stdout.strip()
                 and run_git(wt, "diff", "--cached", "--quiet").returncode == 0)
        run_git(wt, "cherry-pick", "--abort")
        if empty:
            head = run_git(wt, "rev-parse", "HEAD").stdout.strip()
            return {"state": "integrated", "integrated_commit": head, **drift}
        return {"state": "integration_conflict", "blocked_reason": "cherry-pick 冲突"}
    head = run_git(wt, "rev-parse", "HEAD").stdout.strip()
    same = run_git(wt, "rev-parse", "HEAD^{tree}").stdout.strip() == run_git(wt, "rev-parse", f"{commit}^{{tree}}").stdout.strip()
    if not same:
        checks = (state["driver"].get("plan") or {}).get("focused_checks")
        if not checks:
            return {"state": "integration_checks_failed", "integrated_commit": head, "blocked_reason": "focused checks 命令缺失"}
        if subprocess.run(checks, shell=True, cwd=wt, capture_output=True).returncode != 0:
            return {"state": "integration_checks_failed", "integrated_commit": head, "blocked_reason": "focused checks 失败"}
    return {"state": "integrated", "integrated_commit": head, **drift}


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


def exec_render(map_dir: Path, state, action, preflight=None) -> dict:
    kind = action["args"]["kind"]
    result = {"sha": action["id"].rsplit(":", 1)[1]}
    if kind == 'plan':
        result["preflight"] = brief_preflight(state) if preflight is None else preflight
    page = render(state, kind, preflight_html(result.get("preflight", [])))
    path = map_dir / f"{kind}-review.html"
    path.write_text(page)
    return {"html": str(path), **result}


VERDICTS = ("REVIEW_EXHAUSTED", "REVIEW_BLOCKED", "PASS", "FIX")


def parse_marker(row, line: str) -> dict | None:
    """纯函数：终态行 → lane 字段更新；不是本 lane 的活跃终态时返回 None（幂等）。"""
    parts = line.strip().split(None, 3)
    if len(parts) < 2 or parts[0] != "LANE_DONE" or row is None or parts[1] != row["lane_id"]:
        return None
    if row.get("state") not in ACTIVE or (row["state"] == "created" and not row.get("worktree")):
        return None
    if len(parts) >= 3 and parts[2] == "BLOCKED":
        return {"state": "blocked", "blocked_reason": " ".join(parts[3:]) or "Unknown"}
    coord = " ".join(parts[2:])
    mode = row.get("output_mode")
    fields = {"state": "terminal"}
    if mode in ("commit", "integration"):
        if not re.fullmatch(r'[a-f0-9]{4,64}', coord):
            return None
        fields['head_commit'] = coord
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
    if row and row.get('slice_id'):
        return {'signal': 'ignored'}  # 已由 CLI 的真实提交与局部验收产生终态。
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
    get = lambda k: a.get(k) or ticket.get(k) or "Unknown"  # noqa: E731
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


def exec_scenario(map_dir, state, action):
    item = action['args']['work_item']
    ticket = next(t for t in state['driver']['plan']['tickets'] if t['id'] == item)
    mrow = map_row(state['lanes'])
    proof = brief_delivery.scenario(mrow['integration_worktree_path'], ticket,
                                    lanes_by_item(state['lanes'])[item], mrow.get('integration_branch'))
    if proof['base'] != action['args']['head']:
        raise ValueError('集成 HEAD 已变化，请重读当前场景')
    return proof


def exec_briefs(map_dir, state, action):
    """蜂巢执行片与 transport 无关：本机 delivery-dispatch 按 model-roles 配置跑完整批。"""
    mrow = map_row(state['lanes'])
    tree = mrow['integration_worktree_path']
    if brief_delivery.git(tree, 'symbolic-ref', '--short', 'HEAD') != mrow.get('integration_branch'):
        raise ValueError('当前工作树不在 map 集成分支')
    jobs, role = action['args']['briefs'], action['args']['task']
    with tempfile.NamedTemporaryFile(mode='w', dir=map_dir) as source:
        json.dump(jobs, source)
        source.flush()
        cmd = [str(DISPATCH_CLI), 'batch', source.name, '--managed', str(map_dir), '--task', role]
        p = subprocess.run(cmd, cwd=tree, capture_output=True, text=True)
    if p.returncode:
        raise ValueError(p.stderr.strip() or '执行片未全部通过')
    records = [json.loads(line) for line in p.stdout.splitlines()]
    return {'lanes': brief_delivery.verify_rows(jobs, records, map_dir, tree, role, mrow['lane_id'])}


def brief_preflight(state):
    """Plan Review 与授权共用 Setup 解析结果。缺少任务回执行视作预检失败。"""
    tasks = brief_tasks(state)
    if not tasks:
        return []
    p = subprocess.run([str(DISPATCH_CLI), 'preflight', *tasks], capture_output=True, text=True)
    rows = {row["task"]: row for row in
            (json.loads(line) for line in p.stdout.splitlines() if line.startswith('{'))}
    return [rows.get(task, {'task': task, 'ok': False,
                            'error': p.stderr.strip() or '预检无输出'}) for task in tasks]


def preflight_html(rows):
    return review_html.preflight_html(rows)


DISPATCH_CLI = SCRIPTS.parents[2] / 'scripts' / 'delivery-dispatch'
CORE_EXECUTORS = {
    "scenario": exec_scenario, "dispatch_briefs": exec_briefs, "fan_in": exec_fan_in,
    "consume": exec_consume, "closeout": exec_closeout, "render_review": exec_render, "freeze_plan": exec_render,
}


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
            sync_issues(map_dir)
            return action
        record(map_dir, action["id"], receipt, action)
        mark_seen(map_dir)
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


def _brief(item, **kw):
    return {"ticket": item, "slice_id": "all", "writable": ["a.txt"], "read_first": ["README.md"],
            "check": ["git", "grep", "-q", "ok", "HEAD", "--", "a.txt"], "expected": "a.txt 含 ok", **kw}


def _granted(**extra):
    plan = _plan()
    sha = plan_sha(plan)
    d = {"version": VERSION, "map": "m1", "gates": {"discovery": "a", "spec": "s", "tickets": "t"},
         "plan": plan, "plan_check": "pass", "grant": {"plan_sha": sha}, "published": "p",
         "contracts": {t["id"]: _brief(t["id"]) for t in plan["tickets"]},
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


def _moved(state):
    return dict(state, integration_head="b", integration_foreign=["b 手工修冲突"])


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
        ("contract-first", _state(_granted(contracts={}), MAP), "prepare_contract", "contract:T1"),
        ("dispatch-frontier", _state(_granted(), MAP), "dispatch", "dispatch:T1"),
        ("dep-wait", _state(_granted(), MAP, _lane("T1", "running")), "wait", "wait"),
        ("fan-in", _state(_granted(), MAP, _lane("T1", "terminal", head_commit="c")), "fan_in", "fan_in:T1"),
        ("fan-in-repaired", _state(_granted(), MAP, _lane("T1", "terminal", head_commit="c2", repairs="1")), "fan_in", "fan_in:T1:1"),
        ("consume", _state(_granted(), MAP, _lane("T1", "terminal", output_mode="artifact")), "consume", "consume:T1"),
        ("consume-repaired", _state(_granted(), MAP, _lane("T1", "terminal", output_mode="checks", repairs="1")), "consume", "consume:T1:1"),
        ("closeout", _state(_granted(), MAP, _lane("T1", "integrated")), "closeout", "closeout:T1"),
        ("merger", _state(_granted(), MAP, _lane("T1", "integration_conflict")), "dispatch", "dispatch:merger:T1"),
        ("foreign-head", _moved(_state(_granted(integration_seen="a"), MAP, _lane("T1", "integration_conflict"))),
         "halt", "halt:authority:integration-head:b"),
        ("foreign-head-resolved", _moved(_state(_granted(integration_seen="a", resolved_halts=["halt:authority:integration-head:b"]),
                                               MAP, _lane("T1", "integration_conflict"))), "dispatch", "dispatch:merger:T1"),
        ("merger-moves-head", _moved(_state(_granted(integration_seen="a"), MAP, _lane("T1", "integration_conflict"),
                                            _lane("T1-merger", "running", role="integration", merges="T1"))), "wait", "wait"),
        ("whole-change-moves-head", _moved(_state(_granted(integration_seen="a"), MAP, *all_done,
                                                  _lane("t", "closed", role="testing", work_item="m1#testing"))),
         "dispatch", "dispatch:review"),
        ("judge-light", _state(_granted(), MAP, _lane("T1", "blocked")), "judge", "judge:classify:T1"),
        ("judge-heavy", _state(_granted(), MAP, _lane("T1", "blocked", blocked_reason="acceptance failed")), "judge", "judge:diagnose:T1:1"),
        ("resplit", _state(_granted(), MAP, _lane("T1", "blocked", blocked_reason="x", repairs="2")), "judge", "judge:resplit:T1"),
        ("hitl-merged", _state(_granted(), MAP, *done("T1", "T2")), "ask_human", "hitl:T3,T4"),
        ("testing", _state(_granted(), MAP, *all_done), "dispatch", "dispatch:testing"),
        ("review", _state(_granted(), MAP, *all_done, _lane("t", "closed", role="testing", work_item="m1#testing")), "dispatch", "dispatch:review"),
        ("review-fix", _state(_granted(), MAP, *all_done, _lane("t", "closed", role="testing", work_item="m1#testing"),
                              _lane("r", "closed", role="review", work_item="m1#review", verdict="FIX")), "judge", "judge:review_fix:1"),
        ("review-fix-recorded", _state(_granted(receipts={"judge:review_fix:1": {"lane_id": "T1-fix"}}), MAP, *all_done,
                                       _lane("t", "closed", role="testing", work_item="m1#testing"),
                                       _lane("r", "superseded", role="review", work_item="m1#review", verdict="FIX", fix_lane="T1-fix"),
                                       _lane("T1-fix", "closed", work_item="T1")), "render_review", "render:merge:"),
        ("review-fix-running", _state(_granted(receipts={"judge:review_fix:1": {"lane_id": "T1-fix"}}), MAP, *all_done,
                                      _lane("t", "closed", role="testing", work_item="m1#testing"),
                                      _lane("r", "superseded", role="review", work_item="m1#review", verdict="FIX", fix_lane="T1-fix"),
                                      _lane("T1-fix", "running", work_item="T1")), "wait", "wait"),
        ("render-merge", _state(_granted(), MAP, *all_done, _lane("t", "closed", role="testing", work_item="m1#testing"),
                                _lane("r", "closed", role="review", work_item="m1#review", verdict="PASS")), "render_review", "render:merge:"),
        ("remote", _state(_granted(reviews={"merge": {"approved": True}}), MAP, *all_done,
                          _lane("t", "closed", role="testing", work_item="m1#testing"),
                          _lane("r", "closed", role="review", work_item="m1#review", verdict="PASS")), "remote", "remote:push"),
        ("ci-wait", _state(_granted(reviews={"merge": {"approved": True}}, remote={"push": 1, "open_pr": 1, "ci": "pending", "pr": "u"}), MAP, *all_done,
                           _lane("t", "closed", role="testing", work_item="m1#testing"),
                           _lane("r", "closed", role="review", work_item="m1#review", verdict="PASS")), "wait", "wait"),
        ("delivered", _state(_granted(reviews={"merge": {"approved": True}}, remote={s: 1 for s in REMOTE_STEPS}), MAP, *all_done,
                             _lane("t", "closed", role="testing", work_item="m1#testing"),
                             _lane("r", "closed", role="review", work_item="m1#review", verdict="PASS")), "done", "done:delivered"),
        ("review-closeout", _state(_granted(), MAP, *all_done, _lane("t", "closed", role="testing", work_item="m1#testing"),
                                   _lane("r", "consumed", role="review", work_item="m1#review", verdict="PASS")), "closeout", "closeout:r"),
        ("close-pending-halt", _state(_granted(reviews={"merge": {"approved": True}}, remote={s: 1 for s in REMOTE_STEPS}), MAP, *all_done,
                                   _lane("t", "closed", role="testing", work_item="m1#testing"),
                                   _lane("r", "close_pending", role="review", work_item="m1#review", verdict="PASS")), "halt", "halt:authority:close_pending:r"),
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
    need = {"legacy", "halt", "invoke_owner", "ask_human", "render_review", "prepare_map", "prepare_contract", "dispatch", "wait",
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
    failures += _issue_sync_self_test()
    failures += _contract_self_test()
    failures += _idempotent_fan_in_self_test()
    failures += _repair_fan_in_self_test()
    failures += _head_guard_self_test()
    failures += _planning_self_test()
    failures += _review_html_self_test()
    for f in failures:
        print("FAIL", f)
    print("driver self-test:", "fail" if failures else "pass", f"({len(_cases())} cases)")
    return 1 if failures else 0


def _io_self_test() -> list[str]:
    """record 幂等、回执校验、halt 写入 registry、Plan Review 授权与 run 的程序执行。"""
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        md = Path(tmp)
        plan = _plan()
        # JB-476 的普通票保留了空的 briefs 数组。
        plan["tickets"][0]["briefs"] = []
        write_json(md / DRIVER_FILE, {"version": 1, "map": "m1", "gates": {"discovery": "a", "spec": "s", "tickets": "t"},
                                      "plan": plan, "plan_check": "pass"})
        a = run(md)
        if a["action"] != "ask_human" or a["args"]["kind"] != "plan-review" or not (md / "plan-review.html").exists():
            failures.append(f"run 应渲染 Plan Review 后交回 ask_human，got {a}")
        if render(load(md), "plan") != (md / "plan-review.html").read_text():
            failures.append("Plan Review HTML 不确定")
        if "派发合同与整票场景" in (md / "plan-review.html").read_text():
            failures.append("空 briefs 的普通票不应展示蜂巢合同")
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
        if nxt["id"] != "contract:T1":
            failures.append(f"建 map 后应先要 T1 的派发合同，got {nxt['id']}")
        for bad in ([], [_brief("T1"), _brief("T1")], [_brief("T9")], [_brief("T1", writable=[])], [_brief("T1", check=[])]):
            try:
                record(md, "contract:T1", {"briefs": bad})
                failures.append(f"残缺合同应拒绝：{bad}")
            except ValueError:
                pass
        record(md, "contract:T1", {"briefs": [_brief("T1")]})
        nxt = decide(load(md))
        if nxt["id"] != "dispatch:T1" or nxt["args"].get("contract") != _brief("T1"):
            failures.append(f"合同齐备后应带合同派 T1，got {nxt}")
        if "范围：只改 a.txt" not in render_packet(load(md), nxt) or "输入：先读 README.md" not in render_packet(load(md), nxt):
            failures.append("派发包的范围与输入应由合同生成")
        try:
            record(md, "dispatch:T1", {"lane": {"lane_id": "T1", "work_item": "T9"}})
            failures.append("dispatch 回执 work_item 不符应拒绝")
        except ValueError:
            pass
        record(md, "dispatch:T1", {"lane": _lane("T1", "running")})
        if decide(load(md))["action"] != "wait":
            failures.append("T1 运行中应 wait")
        if signal(md, "LANE_DONE T1")["signal"] != "ignored":
            failures.append("缺少提交的 marker 不得写入 terminal")
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


def _issue_sync_self_test() -> list[str]:
    """Driver 读 map 现场推 issue 阶段：派发中的票 In Progress、Spec 进行中，已确认阶段落 cache；回读不符即报错。"""
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        md = Path(tmp)
        write_json(md / DRIVER_FILE, {"version": 1, "map": "m1", "grant": {"plan_sha": "x"}, "published": "p",
                                      "gates": {"spec": "https://linear.app/x/issue/DD-1"},
                                      "plan": {"tickets": [{"id": "DD-2"}, {"id": "DD-3"}]}})
        persist_lanes(md, [{**_lane("dd-2", "running", work_item="DD-2"), "_file": str(md / "registry.md")}])
        fake = issue_status.FakeLinear({"DD-1": "Backlog", "DD-2": "Backlog", "DD-3": "Backlog"})
        sync_issues(md, fake)
        if fake.states != {"DD-1": "In Progress", "DD-2": "In Progress", "DD-3": "Todo"}:
            failures.append(f"issue 同步应按 lane 现场推进阶段，got {fake.states}")
        if load(md)["driver"].get("issue_status") != {"DD-1": "started", "DD-2": "started", "DD-3": "todo"}:
            failures.append("已确认阶段应写回 driver.json#issue_status")
        liar = issue_status.FakeLinear({"DD-1": "In Progress", "DD-2": "In Progress", "DD-3": "Todo"}, lie=True)
        persist_lanes(md, [{**_lane("dd-3", "running", work_item="DD-3"), "_file": str(md / "registry.md")}])
        try:
            sync_issues(md, liar)
            failures.append("回读不符应让 Driver 报错")
        except ValueError:
            pass
    return failures


def _contract_self_test() -> list[str]:
    """ADR-0028：真实 Git 现场里，空变更、验收失败的提交进不了集成分支；越界照常集成但记成偏差。"""
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        repo, tree = str(Path(tmp, "repo")), str(Path(tmp, "lane"))
        git = brief_delivery.git
        subprocess.run(["git", "init", "-qb", "integration", repo], check=True)
        for kv in (("user.name", "Fixture"), ("user.email", "fixture@example.invalid")):
            git(repo, "config", *kv)
        Path(repo, "README.md").write_text("base\n")
        git(repo, "add", "--", "README.md")
        git(repo, "commit", "-qm", "base")
        base = git(repo, "rev-parse", "HEAD")
        git(repo, "worktree", "add", "-qb", "lane", tree)

        def deliver(files):
            git(tree, "reset", "-q", "--hard", base)
            for name, text in files.items():
                Path(tree, name).parent.mkdir(exist_ok=True)
                Path(tree, name).write_text(text)
            if files:
                git(tree, "add", "--", *files)
                git(tree, "commit", "-qm", "work")
            head = git(tree, "rev-parse", "HEAD")
            row = _lane("T1", "terminal", head_commit=head, worktree=tree)
            scoped = {"T1": _brief("T1", writable=["a.txt", "tests/"])}
            state = _state(_granted(contracts=scoped), dict(MAP, integration_worktree_path=repo), row)
            got = exec_fan_in(Path(tmp), state, decide(state))
            return got, git(repo, "rev-parse", "HEAD")

        for name, files, word in (("空变更", {}, "净变更为空"), ("验收失败", {"a.txt": "no\n"}, "验收命令退出")):
            got, head = deliver(files)
            if got.get("state") != "blocked" or word not in got.get("blocked_reason", "") or head != base:
                failures.append(f"合同违约（{name}）应 blocked 且不进集成分支，got {got}")
        got, head = deliver({"a.txt": "ok\n", "b.txt": "x\n", "tests/new.txt": "x\n"})
        if got.get("state") != "integrated" or got.get("scope_drift") != "b.txt":
            failures.append(f"越界应集成并只把范围外的文件记成偏差（目录项覆盖新文件），got {got}")
        git(repo, "reset", "-q", "--hard", base)
        got, head = deliver({"a.txt": "ok\n"})
        if got.get("state") != "integrated" or "scope_drift" in got or head == base or Path(repo, "a.txt").read_text() != "ok\n":
            failures.append(f"守约提交应集成且无偏差，got {got}")
        blocked = _state(_granted(), MAP, _lane("T1", "blocked", blocked_reason="合同违约：验收命令退出 1"))
        if decide(blocked)["id"] != "judge:diagnose:T1:1":
            failures.append("合同违约应进既有诊断修复链")
    return failures


def _idempotent_fan_in_self_test() -> list[str]:
    """DD-691：待集成提交的改动已完全在集成 HEAD 中（空 cherry-pick / 相同 tree）应幂等收口，真实冲突仍判 integration_conflict。"""
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        repo, tree = str(Path(tmp, "repo")), str(Path(tmp, "lane"))
        git = brief_delivery.git
        subprocess.run(["git", "init", "-qb", "integration", repo], check=True)
        for kv in (("user.name", "Fixture"), ("user.email", "fixture@example.invalid")):
            git(repo, "config", *kv)
        Path(repo, "README.md").write_text("base\n")
        git(repo, "add", "--", "README.md")
        git(repo, "commit", "-qm", "base")
        base = git(repo, "rev-parse", "HEAD")
        git(repo, "worktree", "add", "-qb", "lane", tree)
        Path(tree, "a.txt").write_text("ok\n")
        git(tree, "add", "--", "a.txt")
        git(tree, "commit", "-qm", "work")
        c1 = git(tree, "rev-parse", "HEAD")

        def fan_in(commit, contract):
            row = _lane("T1", "terminal", head_commit=commit, worktree=tree)
            state = _state(_granted(contracts={"T1": contract}), dict(MAP, integration_worktree_path=repo), row)
            return exec_fan_in(Path(tmp), state, decide(state))

        # 先在集成树落入相同改动（不同 commit SHA，相同 tree），模拟已集成后重复 fan-in。
        Path(repo, "a.txt").write_text("ok\n")
        git(repo, "add", "--", "a.txt")
        git(repo, "commit", "-qm", "integrated")
        head1 = git(repo, "rev-parse", "HEAD")

        # 1. 相同 tree 重复集成（空 cherry-pick）→ 幂等收口，不得误判 integration_conflict。
        dup = fan_in(c1, _brief("T1"))
        if (dup.get("state") != "integrated" or dup.get("integrated_commit") != head1
                or git(repo, "rev-parse", "HEAD") != head1 or git(repo, "status", "--porcelain")
                or run_git(repo, "rev-parse", "-q", "--verify", "CHERRY_PICK_HEAD").returncode == 0):
            failures.append(f"相同 tree 重复 fan-in 应幂等 integrated，got {dup}")

        # 2. 集成 HEAD 另有其他提交（tree 不同，但 c1 改动已全部在 HEAD 中）→ 同样按已集成幂等收口。
        Path(repo, "extra.txt").write_text("extra\n")
        git(repo, "add", "--", "extra.txt")
        git(repo, "commit", "-qm", "extra")
        head2 = git(repo, "rev-parse", "HEAD")
        subset = fan_in(c1, _brief("T1"))
        if (subset.get("state") != "integrated" or subset.get("integrated_commit") != head2
                or git(repo, "rev-parse", "HEAD") != head2 or git(repo, "status", "--porcelain")):
            failures.append(f"改动已在集成 HEAD 中的空 cherry-pick 应幂等 integrated，got {subset}")

        # 3. 真实冲突仍应返回 integration_conflict 并清理 CHERRY_PICK_HEAD。
        git(tree, "reset", "-q", "--hard", base)
        Path(tree, "a.txt").write_text("conflict\n")
        git(tree, "add", "--", "a.txt")
        git(tree, "commit", "-qm", "conflict")
        c2 = git(tree, "rev-parse", "HEAD")
        conflict = fan_in(c2, _brief("T1", check=["git", "grep", "-q", "conflict", "HEAD", "--", "a.txt"], expected="a.txt 含 conflict"))
        if (conflict.get("state") != "integration_conflict"
                or git(repo, "rev-parse", "HEAD") != head2 or git(repo, "status", "--porcelain")
                or run_git(repo, "rev-parse", "-q", "--verify", "CHERRY_PICK_HEAD").returncode == 0):
            failures.append(f"真实冲突应仍判 integration_conflict，got {conflict}")
    return failures


def _repair_fan_in_self_test() -> list[str]:
    """DD-690：blocked → repair → 再次 fan-in / consume 必须推进状态，不得当成重复回执死循环。"""
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        md, repo, tree = Path(tmp, "map"), str(Path(tmp, "repo")), str(Path(tmp, "lane"))
        md.mkdir()
        git = brief_delivery.git
        subprocess.run(["git", "init", "-qb", "integration", repo], check=True)
        for kv in (("user.name", "Fixture"), ("user.email", "fixture@example.invalid")):
            git(repo, "config", *kv)
        Path(repo, "README.md").write_text("base\n")
        git(repo, "add", "--", "README.md")
        git(repo, "commit", "-qm", "base")
        git(repo, "worktree", "add", "-qb", "lane", tree)
        Path(tree, "a.txt").write_text("no\n")
        git(tree, "add", "--", "a.txt")
        git(tree, "commit", "-qm", "bad")
        bad_commit = git(tree, "rev-parse", "HEAD")

        registry = str(md / "registry.md")
        write_json(md / DRIVER_FILE, _granted())
        persist_lanes(md, [
            dict(MAP, integration_worktree_path=repo, _file=registry),
            dict(_lane("T1", "terminal", head_commit=bad_commit, worktree=tree), _file=registry),
        ])
        first = run(md, limit=20)
        if first["id"] != "judge:diagnose:T1:1":
            return [f"首次合同违约应交回验收诊断，got {first}"]
        record(md, "judge:diagnose:T1:1", {"lane_id": "T1"})
        Path(tree, "a.txt").write_text("ok\n")
        git(tree, "add", "--", "a.txt")
        git(tree, "commit", "--amend", "-qm", "fix")
        good_commit = git(tree, "rev-parse", "HEAD")
        if signal(md, f"LANE_DONE T1 {good_commit}")["signal"] != "recorded":
            return ["修复后终态行应写入 terminal"]
        try:
            after = run(md, executors={"closeout": lambda *_: {"result": "closed"}}, limit=20)
        except RuntimeError as exc:
            return [f"修复后再次 fan-in 死循环：{exc}"]
        t1 = load(md)["lanes"]["T1"]
        if after["id"] != "dispatch:T2" or t1["state"] != "closed" or Path(repo, "a.txt").read_text() != "ok\n":
            failures.append(f"修复后再次 fan-in 应集成、收口并推进到 T2，got after={after} lane={t1}")
        if record(md, "fan_in:T1:1", {"state": "integrated"}).get("duplicate") is not True:
            failures.append("新轮次 fan_in:T1:1 的重复回执仍应幂等")

        # 同类路径：consume（checks 失败 → blocked → repair → 再次 consume）
        md2 = Path(tmp, "map2")
        md2.mkdir()
        reg2 = str(md2 / "registry.md")
        write_json(md2 / DRIVER_FILE, _granted())
        persist_lanes(md2, [
            dict(MAP, _file=reg2),
            *[dict(_lane(i, "closed"), _file=reg2) for i in ("T1", "T2", "T3", "T4")],
            dict(_lane("m1-testing", "terminal", role="testing", work_item="m1#testing",
                       output_mode="checks", checks="fail"), _file=reg2),
        ])
        if run(md2, limit=20)["id"] != "judge:diagnose:m1-testing:1":
            failures.append("testing checks 失败应进入诊断修复")
        else:
            record(md2, "judge:diagnose:m1-testing:1", {"lane_id": "m1-testing"})
            persist_lanes(md2, [{**load(md2)["lanes"]["m1-testing"], "state": "terminal", "checks": "pass"}])
            try:
                nxt = run(md2, executors={"closeout": lambda *_: {"result": "closed"}}, limit=20)
            except RuntimeError as exc:
                failures.append(f"修复后再次 consume 死循环：{exc}")
            else:
                if nxt["id"] != "dispatch:review" or load(md2)["lanes"]["m1-testing"]["state"] != "closed":
                    failures.append(f"修复后再次 consume 应推进到 review，got {nxt}")
    return failures


def _head_guard_self_test():
    """集成 HEAD 只认 Driver 留下的：旧错误是 coordinator 在集成树手工 cherry-pick 后 Driver 照单全收。"""
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        md, repo, tree = Path(tmp, "map"), str(Path(tmp, "repo")), str(Path(tmp, "tree"))
        md.mkdir()
        subprocess.run(["git", "init", "-qb", "integration", repo], check=True)
        git = brief_delivery.git
        git(repo, "config", "user.name", "t")
        git(repo, "config", "user.email", "t@example.invalid")
        Path(repo, "README.md").write_text("base\n")
        git(repo, "add", "README.md")
        git(repo, "commit", "-qm", "base")
        git(repo, "worktree", "add", "-qb", "lane", tree)
        Path(tree, "a.txt").write_text("ok\n")
        git(tree, "add", "a.txt")
        git(tree, "commit", "-qm", "work")
        registry = str(md / "registry.md")
        write_json(md / DRIVER_FILE, _granted())
        persist_lanes(md, [dict(MAP, integration_worktree_path=repo, _file=registry),
                           dict(_lane("T1", "terminal", head_commit=git(tree, "rev-parse", "HEAD"), worktree=tree), _file=registry)])
        first = run(md)
        head = git(repo, "rev-parse", "HEAD")
        if first["action"] == "halt" or load(md)["lanes"]["T1"]["state"] not in closeout.DONE or load(md)["driver"].get("integration_seen") != head:
            failures.append(f"Driver 自己 fan-in 后应记下集成 HEAD 且不停机，got {first}")
        Path(repo, "b.txt").write_text("x\n")
        git(repo, "add", "b.txt")
        git(repo, "commit", "-qm", "手工修冲突")
        foreign = git(repo, "rev-parse", "HEAD")
        got = run(md)
        if got["id"] != f"halt:authority:integration-head:{foreign}" or "手工修冲突" not in " ".join(got["args"]["evidence"]):
            failures.append(f"集成树出现外来提交应停机并列出提交，got {got}")
        elif record(md, "halt", "认可这些提交并继续") and run(md)["action"] == "halt":
            failures.append("用户认可外来提交后应继续")
    return failures


def _planning_self_test():
    failures = []
    decision = {"reason": "两条用户结果可以分别验收", "change": "按用户结果拆分", "evidence": ["spec.md#scenarios"]}
    with tempfile.TemporaryDirectory() as tmp:
        md = Path(tmp)
        write_json(md / DRIVER_FILE, {"map": "m1", "planning_mode": "auto", "gates": {"discovery": "d", "spec": "s"}})
        for check in ("fail", "fail", "pass"):
            action = run(md)
            record(md, action["id"], {"next": "to-tickets", "artifact": "draft", "plan": _plan(),
                                      "check": check, "decision": decision})
        action = run(md)
        d = load(md)["driver"]
        if action["id"] != "owner:publish" or d["grant"]["plan_sha"] != plan_sha(d["plan"]):
            failures.append("新普通 map 的计划过检后应自动冻结并交回发布 Action")
        if len(d["planning_decisions"]) != 3 or d.get("remote"):
            failures.append("自动重拆应保留每次决定且不授予合入权限")
        record(md, action["id"], {"next": "blocked-human", "artifact": "draft", "reason": "缺发布授权"})
        action = run(md)
        record(md, action["id"], {"reply": "授权发布计划票"})
        action = run(md)
        if action["id"] != "owner:publish:1":
            failures.append("授权答复应恢复等待中的发布 Action")
        record(md, action["id"], {"next": "to-tickets", "artifact": "published"})
        if run(md)["id"] != "prepare_map":
            failures.append("发布恢复后应继续建图")
    with tempfile.TemporaryDirectory() as tmp:
        md = Path(tmp)
        write_json(md / DRIVER_FILE, {"map": "m1", "planning_mode": "auto", "gates": {"discovery": "d"}})
        record(md, "owner:spec", {"artifact": "spec-draft", "next": "to-epic", "decision": decision})
        action = run(md)
        if action["id"] != "owner:epic" or action["args"]["input"] != "spec-draft":
            failures.append("多 MMF 应交 to-epic owner")
        record(md, action["id"], {"artifact": "epic:123", "next": "to-spec", "decision": decision})
        action = run(md)
        if action["action"] != "handoff_epic" or "grant" in load(md)["driver"]:
            failures.append("多 MMF 应交已有 Epic 调度且不冻结原 map")
        record(md, action["id"], {"artifact": "epic-registry"})
        if run(md)["id"] != "done:handed_off":
            failures.append("Epic 交接后原 map 应终止推进")
    return failures


def _review_html_self_test() -> list[str]:
    """Merge Review 渲染：check_result、偏差过滤、结构化证据解析、diff 树与主题变量。"""
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        md = Path(tmp)
        rev_json = md / "review.json"
        rev_json.write_text(json.dumps({
            "verdict": "PASS",
            "ocr": {"reviewable_count": 3, "excluded_count": 1},
            "axes": {
                "standards": {"verdict": "PASS", "counts": {"P0": 0, "P1": 0, "P2": 0, "P3": 1},
                              "findings": [{"severity": "P3", "title": "Stale note", "file": "README.md:10", "trigger_and_impact": "Docs drift"}],
                              "verification_gaps": ["Live CI check pending"]},
                "spec": {"verdict": "PASS", "counts": {"P0": 0, "P1": 0, "P2": 1, "P3": 0},
                         "findings": [{"severity": "P2", "title": "Missing main hook", "file": "test_x.py:1", "trigger_and_impact": "Skipped by runner"}],
                         "spec_gaps": []},
            },
        }, ensure_ascii=False))
        test_json = md / "testing.json"
        test_json.write_text(json.dumps({
            "check": ["pytest -q"],
            "observed": "pytest -q → 42 项通过（/tmp/run.log）",
            "gaps": [],
        }, ensure_ascii=False))
        plan = {
            "repo": "demo-repo",
            "mmf": "M1",
            "recommendation": "按两波完成静态门禁接入",
            "critical_path": ["01", "02"],
            "risk": ["需保持 fail-close"],
            "test_strategy": {"level": "focused", "unit": "单测覆盖全部规则", "e2e": "n/a"},
            "tickets": [
                {"id": "01", "wave": 1, "task": "backend", "kind": "contract", "deps": [],
                 "title": "冻结接口", "check_result": "导入与类型检查通过"},
                {"id": "02", "wave": 2, "task": "backend", "kind": "behavior", "deps": ["01"],
                 "title": "实现分类器", "check_result": "历史样本回归零崩溃", "scenarios": ["S1", "S2"]},
            ],
        }
        state = {
            "driver": {"version": 1, "map": "demo-m1", "gates": {"spec": "https://linear.app/x/issue/JB-99/spec-demo"},
                       "plan": plan},
            "integration_head": "83130172aec32e67969fde2f81dfc7c1a10b72ca",
            "diff_files": [{"path": "deploy/release/classifier.py", "added": 120, "deleted": 5}],
            "lanes": {
                "m": {"lane_id": "m", "role": "map", "state": "running", "branch": "feat/demo"},
                "spec-1": {"lane_id": "spec-1", "work_item": "https://linear.app/x#spec", "role": "planning", "state": "closed"},
                "01": {"lane_id": "01", "work_item": "01", "role": "backend", "output_mode": "commit", "state": "superseded",
                       "repairs": "1", "repair_lane": "01-repair-1"},
                "01-repair-1": {"lane_id": "01-repair-1", "work_item": "01", "role": "backend", "output_mode": "commit",
                                "state": "closed", "integrated_commit": "9ae1c9ffe60d10a8"},
                "02": {"lane_id": "02", "work_item": "02", "role": "backend", "output_mode": "commit",
                       "state": "closed", "integrated_commit": "20c8cdad2977691b", "scope_drift": "deploy/extra.py"},
                "t": {"lane_id": "t", "work_item": "demo-m1#testing", "role": "testing", "output_mode": "checks",
                      "state": "closed", "repairs": "1", "repair_lane": "t-fix-1", "delivery": str(test_json)},
                "t-fix-1": {"lane_id": "t-fix-1", "work_item": "t-fix-1", "role": "backend", "output_mode": "commit",
                            "state": "closed"},
                "r": {"lane_id": "r", "work_item": "demo-m1#review", "role": "review", "output_mode": "verdict",
                      "state": "consumed", "verdict": "PASS", "verdict_path": str(rev_json)},
            },
        }
        devs = deviations(state)
        if render(dict(state, lanes={k: {f: v for f, v in r.items() if f != "scope_drift"} for k, r in state["lanes"].items()}),
                  "merge").count("超出合同范围"):
            failures.append("没有越界的票不应显示超出合同范围")
        if any("波次内补票" in item for item in devs):
            failures.append(f"planning 或 repair lane 不应误判为波次内补票: {devs}")
        if not any("整体检查 t 修复 1 轮" in item for item in devs):
            failures.append(f"testing 修复应计入偏差: {devs}")
        page = render(state, "merge")
        for must in ("导入与类型检查通过", "历史样本回归零崩溃", "Stale note", "Missing main hook",
                     "Live CI check pending", "42 项通过", "classifier.py", "需保持 fail-close",
                     "单测覆盖全部规则", "var(--foreground", "超出合同范围", "deploy/extra.py"):
            if must not in page:
                failures.append(f"Merge Review 缺预期内容: {must}")
        for forbid in ("波次内补票", "01=superseded", "{&quot;e2e&quot;", "100vh"):
            if forbid in page:
                failures.append(f"Merge Review 不应含原始噪音: {forbid}")
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
    if cmd == 'init':
        map_dir.mkdir(parents=True, exist_ok=True)
    with (map_dir / '.driver.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        return execute(cmd, map_dir, argv)


def execute(cmd, map_dir, argv):
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
        sync_issues(map_dir)
    elif cmd == "signal":
        print(json.dumps(signal(map_dir, argv[2]), ensure_ascii=False))
        sync_issues(map_dir)
    elif cmd == "init":
        path = map_dir / DRIVER_FILE
        if path.exists():
            raise SystemExit("driver.json 已存在")
        map_dir.mkdir(parents=True, exist_ok=True)
        write_json(path, {"version": VERSION, "map": argv[2], "planning_mode": "auto", "gates": {}, "plan": {"tickets": []}})
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
