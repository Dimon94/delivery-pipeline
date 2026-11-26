#!/usr/bin/env python3
"""Issue Status：从 Driver 状态推导每张 issue 应处的阶段，同步到 Linear 并回读。

# ============================================================================
# L3-L6 Contract: map 内 issue 的 tracker 状态同步
# - COORD: skills/delivery-pipeline/scripts/issue_status.py
# - INPUT: driver.json 与按 work item 分组的 lane 行；Linear 调用函数 call(tool, args)。
# - OUTPUT: (cache, error)。cache = {issue key: 已确认的阶段}，由 Driver 写回 driver.json#issue_status。
# - INVARIANT: 阶段单调 backlog < todo < started < review < acceptance < done；
#   先读后写，只前进不回退，不碰 canceled/duplicate；每次写入必回读，不符即报错。
#   cache 已到目标阶段的 issue 不再调用 tracker。
# - CHAIN: driver.py 在 run 交回宿主前、record/signal 之后调用 sync_issues。
# - TEST: issue_status.py self-test
# ============================================================================

阶段来源（只读 Driver 状态，不读事件）：
  Spec gate：grant 后 started；testing/review lane 出现后 review；Merge Review 渲染后 acceptance；合入后 done。
  plan 票：发布后 todo；有 lane 后 started；lane 集成后 review；Merge Review 后 acceptance；合入后 done。

用法：issue_status.py self-test
"""
from __future__ import annotations

from collections.abc import Sequence
import json
import re
import subprocess
import sys

STAGES = ("backlog", "todo", "started", "review", "acceptance", "done")
RANK = {s: i for i, s in enumerate(STAGES)}
LANE_DONE = {"integrated", "consumed", "closed"}  # 与 closeout.DONE 同义
KEY_RE = re.compile(r"^([A-Z][A-Z0-9]*-\d+)\b")
URL_RE = re.compile(r"^https?://linear\.app/[^/]+/issue/([A-Z][A-Z0-9]*-\d+)", re.I)
ACCEPT_RE = re.compile(r"待验收|accept", re.I)
REVIEW_RE = re.compile(r"review", re.I)
TERMINAL = {"canceled", "duplicate"}
FIELDS = ["id", "status", "statusType", "teamId"]


def issue_key(ref) -> str | None:
    text = str(ref or "").strip()
    hit = URL_RE.match(text) or KEY_RE.match(text)
    return hit.group(1).upper() if hit else None


def _first(pairs, default):
    return next((stage for stage, hit in pairs if hit), default)


# ---------- 纯推导 ----------

def ticket_stage(d: dict, rows: Sequence[dict]) -> str | None:
    """单票阶段推导入口，接受 Driver 状态与该票的 lane 行。"""
    raise NotImplementedError("单票阶段推导由 DD-670 实现")


def targets(d: dict, by_item: dict) -> dict:
    """{issue key: 目标阶段}。非 Linear 坐标的票（如 T1）不参与。"""
    if not d or not d.get("grant"):
        return {}
    shipped = bool((d.get("remote") or {}).get("merge")) or d.get("status") == "done"
    accepting = bool((d.get("reviews") or {}).get("merge"))
    reviewing = any(r.get("role") in ("testing", "review") for rows in by_item.values() for r in rows)
    out = {}
    spec = issue_key((d.get("gates") or {}).get("spec"))
    if spec:
        out[spec] = _first([("done", shipped), ("acceptance", accepting), ("review", reviewing)], "started")
    if not d.get("published"):
        return out
    for ticket in d.get("plan", {}).get("tickets", ()):
        key = issue_key(ticket.get("url") or ticket["id"])
        rows = by_item.get(ticket["id"], ())
        if key:
            out[key] = _first([("done", shipped), ("acceptance", accepting),
                               ("review", any(r.get("state") in LANE_DONE for r in rows)),
                               ("started", bool(rows))], "todo")
    return out


def stage_of(name: str, kind: str) -> str | None:
    """Linear 状态 → 阶段；canceled/duplicate 返回 None。"""
    if kind == "started":
        return _first([("acceptance", ACCEPT_RE.search(name)), ("review", REVIEW_RE.search(name))], "started")
    return {"triage": "backlog", "backlog": "backlog", "unstarted": "todo", "completed": "done"}.get(kind)


def pick(statuses: list, stage: str) -> dict | None:
    """在 Team 状态里找目标阶段；Team 没有待验收时退到 review。"""
    hits = [s for s in statuses if stage_of(s["name"], s["type"]) == stage]
    if not hits and stage == "acceptance":
        return pick(statuses, "review")
    preferred = {"todo": r"^todo$", "started": r"in\s*progress", "done": r"^done$"}.get(stage)
    return next((s for s in hits if preferred and re.search(preferred, s["name"], re.I)), hits[0] if hits else None)


# ---------- IO ----------

def linear_call(tool: str, args: dict):
    payload = json.dumps({"name": f"linear__{tool}", "arguments": args}, ensure_ascii=False)
    proc = subprocess.run(["mcporter", "call", "magpie.call_tool", "--args", payload, "--output", "json"],
                          capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise RuntimeError(f"Linear {tool} 调用失败（需可用 mcporter/magpie）：{proc.stderr.strip() or proc.stdout.strip()}")
    out = json.loads(proc.stdout)
    if isinstance(out, dict) and (out.get("isError") or isinstance(out.get("error"), str)):
        raise RuntimeError(f"Linear {tool} 拒绝执行：{out.get('error') or out.get('content')}")
    return out


def advance(call, teams: dict, key: str, stage: str) -> str:
    """把一张 issue 推进到 stage；已到或越过就不写。返回回读后的状态名。"""
    issue = call("get_issue", {"id": key, "fields": FIELDS})
    if issue.get("statusType") in TERMINAL:
        return issue["status"]
    if RANK[stage_of(issue["status"], issue["statusType"])] >= RANK[stage]:
        return issue["status"]
    team = issue["teamId"]
    statuses = teams[team] = teams.get(team) or call("list_issue_statuses", {"team": team})
    nxt = pick(statuses, stage)
    if not nxt:
        raise RuntimeError(f"{key} 所在 Team 没有 {stage} 阶段对应的状态")
    call("save_issue", {"id": key, "state": nxt["id"]})
    after = call("get_issue", {"id": key, "fields": FIELDS})
    if after.get("status") != nxt["name"]:
        raise RuntimeError(f"{key} 状态回读不符：期望 {nxt['name']}，实际 {after.get('status')}")
    return after["status"]


def sync(d: dict, by_item: dict, call=None) -> tuple[dict, str | None]:
    """按 targets 推进 cache 未到位的 issue。遇错停下，返回已确认部分与错误。"""
    call = call or linear_call
    cache, teams = dict(d.get("issue_status") or {}), {}
    for key, stage in sorted(targets(d, by_item).items()):
        if RANK[stage] <= RANK.get(cache.get(key), -1):
            continue
        try:
            advance(call, teams, key, stage)
        except (RuntimeError, KeyError, ValueError, subprocess.TimeoutExpired) as error:
            return cache, f"issue 状态同步失败 {key} → {stage}：{error}"
        cache[key] = stage
    return cache, None


# ---------- self-test ----------

DAWN = [{"id": i, "name": n, "type": t} for i, n, t in (
    ("s0", "Backlog", "backlog"), ("s1", "Todo", "unstarted"), ("s2", "In Progress", "started"),
    ("s3", "In Review", "started"), ("s4", "待验收", "started"), ("s5", "Done", "completed"),
    ("s6", "Canceled", "canceled"))]


class FakeLinear:
    def __init__(self, states: dict, statuses=DAWN, lie=False):
        self.states, self.statuses, self.lie, self.writes = dict(states), statuses, lie, []

    def __call__(self, tool, args):
        if tool == "list_issue_statuses":
            return self.statuses
        if tool == "save_issue":
            self.writes.append((args["id"], args["state"]))
            if not self.lie:
                self.states[args["id"]] = next(s["name"] for s in self.statuses if s["id"] == args["state"])
            return {}
        name = self.states[args["id"]]
        kind = next(s["type"] for s in self.statuses if s["name"] == name)
        return {"id": args["id"], "status": name, "statusType": kind, "teamId": "dawn"}


def _driver(**extra):
    d = {"grant": {"plan_sha": "x"}, "published": "p", "gates": {"spec": "https://linear.app/x/issue/DD-1/spec"},
         "plan": {"tickets": [{"id": "DD-2"}, {"id": "DD-3"}, {"id": "T9"}]}}
    return {**d, **extra}


def _cases():
    lane = lambda state, role="backend": {"state": state, "role": role}  # noqa: E731
    return [
        ("未授权不同步", {}, {"published": None, "grant": None}, {}),
        ("发布后票 todo、Spec started", {}, {}, {"DD-1": "started", "DD-2": "todo", "DD-3": "todo"}),
        ("派发 started、集成 review", {"DD-2": [lane("running")], "DD-3": [lane("integrated")]}, {},
         {"DD-1": "started", "DD-2": "started", "DD-3": "review"}),
        ("整体测试让 Spec 进 review", {"m#testing": [lane("running", "testing")]}, {},
         {"DD-1": "review", "DD-2": "todo", "DD-3": "todo"}),
        ("Merge Review 后全部待验收", {}, {"reviews": {"merge": {"sha": "s"}}},
         {"DD-1": "acceptance", "DD-2": "acceptance", "DD-3": "acceptance"}),
        ("合入后全部 done", {}, {"remote": {"merge": "ok"}}, {"DD-1": "done", "DD-2": "done", "DD-3": "done"}),
    ]


def self_test() -> int:
    failures = []
    for name, by_item, extra, want in _cases():
        got = targets(_driver(**extra), by_item)
        if got != want:
            failures.append(f"{name}: {got} != {want}")

    fake = FakeLinear({"DD-1": "Backlog", "DD-2": "Done", "DD-3": "Canceled"})
    cache, err = sync(_driver(reviews={"merge": {"sha": "s"}}), {}, fake)
    if err or fake.states != {"DD-1": "待验收", "DD-2": "Done", "DD-3": "Canceled"} or len(fake.writes) != 1:
        failures.append(f"只前进、不碰 Done/Canceled: {fake.states} {fake.writes} {err}")
    calls = FakeLinear(fake.states)
    sync(dict(_driver(reviews={"merge": {"sha": "s"}}), issue_status=cache), {}, calls)
    if calls.writes:
        failures.append(f"cache 到位后仍写 tracker: {calls.writes}")

    no_accept = FakeLinear({"DD-1": "In Progress", "DD-2": "Todo", "DD-3": "Todo"},
                           statuses=[s for s in DAWN if s["name"] != "待验收"])
    sync(_driver(reviews={"merge": {"sha": "s"}}), {}, no_accept)
    if set(no_accept.states.values()) != {"In Review"}:
        failures.append(f"Team 无待验收时应退到 In Review: {no_accept.states}")

    liar = FakeLinear({"DD-1": "Backlog", "DD-2": "Backlog", "DD-3": "Backlog"}, lie=True)
    cache, err = sync(_driver(), {}, liar)
    if not err or "回读不符" not in err or cache:
        failures.append(f"回读不符必须报错且不进 cache: {cache} {err}")

    for f in failures:
        print("FAIL", f)
    print("issue_status self-test", "FAILED" if failures else "ok")
    return 1 if failures else 0


if __name__ == "__main__":
    if sys.argv[1:] == ["self-test"]:
        raise SystemExit(self_test())
    print(__doc__)
    raise SystemExit(0 if sys.argv[1:] in ([], ["-h"], ["--help"]) else 2)
