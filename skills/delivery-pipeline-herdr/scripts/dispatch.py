#!/usr/bin/env python3
"""Herdr lane 一次派发：解析计划 → 写 registry → 落 pane → 启动 agent → 投递 packet →
确认 working → 挂 watcher → 回写 running。成功只打印一行 JSON 坐标；失败写 setup_blocked。

用法：
  dispatch.py --config <model-roles.json> --evidence <capability.json> --task <task type>
              --output-mode <mode> --lane <lane_id> --work-item <url> --title <pane label>
              --worktree <abs> --branch <branch> --base <sha> --packet <abs> --registry <abs .md>
              --map-registry <abs map registry .md | none>
              [--ticket-mode NAME] [--map-mode NAME] [--tab-prefix X] [--off-chain-reason TEXT]

派发前（任何 herdr 调用前）拒绝：lane 名超过 Herdr agent 名上限、map registry 未通过
recovery_record.py check、packet owner 已移出交付链路且未给 --off-chain-reason。
registry 记录 contract_rev（派发时 skill 仓 HEAD）与 map（map registry 的 lane_id）。
"""
from __future__ import annotations

import argparse
import fcntl
import importlib.util
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODEL_CONFIG = HERE.parents[1] / "delivery-pipeline-setup" / "scripts" / "model_config.py"
RECOVERY_RECORD = HERE.parents[1] / "delivery-pipeline" / "scripts" / "recovery_record.py"
HERDR_NAME_MAX = 32
# 已移出交付链路、只作独立 skill 保留的 owner（5ecd9ce）；链路内派发须显式写理由。
OFF_CHAIN_OWNERS = {"ticket-sizing"}
OWNER_RE = re.compile(r"^Owner[：:]\s*([^；;\s]+)", re.M)
WATCHER = Path(os.environ.get("DP_LANE_WATCH", HERE / "lane-watch.sh"))
TAB_CAPACITY = 4
RUNTIME = {"pi": "herdr-pi-pane", "codex": "herdr-codex-pane", "claude": "herdr-claude-pane"}


class DispatchError(Exception):
    pass


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_model_config():
    return load_module("model_config", MODEL_CONFIG)


def agent_name(lane: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", lane.lower()).strip("-") or "lane"


def contract_rev() -> str:
    result = subprocess.run(["git", "-C", str(HERE), "rev-parse", "HEAD"], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else "Unknown"


def preflight(args) -> str | None:
    """herdr 调用前的确定性拒绝；返回 map lane_id（--map-registry none 时为 None）。"""
    name = agent_name(args.lane)
    if len(name) > HERDR_NAME_MAX:
        raise DispatchError(f"lane name {name!r} is {len(name)} chars; Herdr agent names allow "
                            f"{HERDR_NAME_MAX}: shorten to {name[:HERDR_NAME_MAX].rstrip('-')!r} or similar")
    owner = OWNER_RE.search(Path(args.packet).read_text(encoding="utf-8"))
    if owner and owner.group(1) in OFF_CHAIN_OWNERS and not args.off_chain_reason:
        raise DispatchError(f"packet owner {owner.group(1)} is off the delivery chain; "
                            "pass --off-chain-reason with the user decision or gate that requires it")
    if args.map_registry == "none":
        return None
    map_path = Path(args.map_registry)
    if not map_path.is_absolute() or not map_path.exists():
        raise DispatchError(f"map-registry must be an existing absolute path or none: {map_path}")
    problems = load_module("recovery_record", RECOVERY_RECORD).check(map_path)
    if problems:
        raise DispatchError("map registry fails recovery_record.py check: " + " ; ".join(problems))
    lane_id = re.search(r"^lane_id: (.+)$", map_path.read_text(encoding="utf-8"), re.M)
    return lane_id.group(1).strip() if lane_id else "Unknown"


def herdr(*args: str) -> dict:
    result = subprocess.run(["herdr", *args], text=True, capture_output=True)
    if result.returncode != 0:
        raise DispatchError(f"herdr {' '.join(args[:2])} failed: {result.stderr.strip() or result.stdout.strip()}")
    try:
        return json.loads(result.stdout) if result.stdout.strip() else {}
    except json.JSONDecodeError:
        return {}


def find_pane(value: object) -> dict | None:
    """在任意 herdr 响应里找第一个带 pane_id 的对象。"""
    if isinstance(value, dict):
        if "pane_id" in value:
            return value
        for child in value.values():
            found = find_pane(child)
            if found:
                return found
    if isinstance(value, list):
        for child in value:
            found = find_pane(child)
            if found:
                return found
    return None


def coordinator() -> dict:
    env = {k: os.environ.get(k, "") for k in ("HERDR_ENV", "HERDR_WORKSPACE_ID", "HERDR_TAB_ID", "HERDR_PANE_ID")}
    if env["HERDR_ENV"] != "1" or not all(env.values()):
        raise DispatchError("dispatch unavailable: not inside a Herdr pane")
    pane = find_pane(herdr("pane", "current", "--current")) or {}
    actual = (pane.get("workspace_id"), pane.get("tab_id"), pane.get("pane_id"))
    expected = (env["HERDR_WORKSPACE_ID"], env["HERDR_TAB_ID"], env["HERDR_PANE_ID"])
    if actual != expected:
        raise DispatchError(f"coordinator pane readback mismatch: {actual} != {expected}")
    return {"workspace_id": actual[0], "tab_id": actual[1], "pane_id": actual[2]}


def place(coord: dict, worktree: str, prefix: str) -> dict:
    """容量管理的 worker tab：同前缀 tab 未满则在其中 split，否则新开 tab。"""
    workspace = coord["workspace_id"]
    tabs = herdr("tab", "list", "--workspace", workspace).get("result", {}).get("tabs", [])
    label_re = re.compile(rf"^{re.escape(prefix)}(-\d+)?$")
    workers = [t for t in tabs if t.get("tab_id") != coord["tab_id"] and label_re.match(str(t.get("label", "")))]
    target = next((t for t in workers if int(t.get("pane_count", 0)) < TAB_CAPACITY), None)
    if target:
        panes = [p for p in herdr("pane", "list", "--workspace", workspace).get("result", {}).get("panes", [])
                 if p.get("tab_id") == target["tab_id"]]
        if not panes:
            raise DispatchError(f"worker tab {target['tab_id']} has no panes")
        # 四角：1→右，2→左下，3→右下
        anchor = panes[0] if len(panes) < 3 else panes[1]
        direction = "right" if len(panes) == 1 else "down"
        created = herdr("pane", "split", "--pane", anchor["pane_id"], "--direction", direction,
                        "--cwd", worktree, "--no-focus")
    else:
        label = prefix if not workers else f"{prefix}-{len(workers) + 1}"
        created = herdr("tab", "create", "--workspace", workspace, "--cwd", worktree, "--label", label, "--no-focus")
    pane = find_pane(created)
    if not pane:
        raise DispatchError("placement response carries no pane_id")
    readback = find_pane(herdr("pane", "get", pane["pane_id"])) or {}
    if readback.get("workspace_id") != workspace or readback.get("pane_id") == coord["pane_id"] \
            or readback.get("tab_id") == coord["tab_id"]:
        raise DispatchError(f"placement readback mismatch: {readback}")
    return {"workspace_id": workspace, "tab_id": readback.get("tab_id"), "pane_id": readback["pane_id"]}


def write_registry(path: Path, row: dict) -> None:
    core = HERE.parents[1] / "delivery-pipeline" / "scripts"
    if str(core) not in sys.path:
        sys.path.insert(0, str(core))
    import lane_registry
    lane_registry.write(path, row)


def wait_working(name: str) -> bool:
    return subprocess.run(["herdr", "agent", "wait", name, "--until", "working", "--timeout", "15000"],
                          capture_output=True).returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser()
    for flag in ("config", "evidence", "task", "output-mode", "lane", "work-item", "title",
                 "worktree", "branch", "base", "packet", "registry", "map-registry"):
        parser.add_argument(f"--{flag}", required=True)
    parser.add_argument("--off-chain-reason")
    parser.add_argument("--ticket-mode")
    parser.add_argument("--map-mode")
    parser.add_argument("--tab-prefix", default="X")
    parser.add_argument("--review-scope")
    parser.add_argument("--required-axes", nargs="+", choices=["standards", "spec"])
    parser.add_argument("--request-id")
    parser.add_argument("--implementation-registry", nargs="+")
    args = parser.parse_args()

    registry = Path(args.registry)
    row: dict = {}
    try:
        for label, value in (("worktree", args.worktree), ("packet", args.packet)):
            if not Path(value).is_absolute() or not Path(value).exists():
                raise DispatchError(f"{label} must be an existing absolute path: {value}")
        map_lane = preflight(args)
        sys.path.insert(0,str(HERE.parents[1]/"delivery-pipeline/scripts"))
        import lane_registry
        existing = lane_registry.rows(registry)
        if args.task == "review" and args.lane in existing:
            raise DispatchError("review lane already frozen: recover original plan/receipt; do not redispatch")
        if any(row.get("state") in {"running","awaiting_human","created"} for row in existing.values()):
            raise DispatchError(f"registry already has an active writer: {registry}")
        mc = load_model_config()
        evidence = json.loads(Path(args.evidence).expanduser().read_text())
        review = None
        if args.task == "review":
            if (args.review_scope != "whole-change" or args.output_mode != "verdict"
                    or args.map_registry == "none" or not args.required_axes or not args.request_id
                    or args.ticket_mode or args.map_mode):
                raise DispatchError("review requires Map Integration whole-change verdict, axes and request_id")
            packet_path = Path(args.packet)
            packet_text = packet_path.read_text()
            owner = re.search(r"^Owner[：:]\s*code-review[；;]\s*([^；;\n]+)[；;]\s*(.+)$", packet_text, re.M)
            if not owner or not Path(owner[1].strip()).is_absolute():
                raise DispatchError("review requires resolved code-review owner name/path/invocation label")
            owner_path = Path(owner[1].strip()).resolve()
            if not re.search(r"^name: code-review\s*$", owner_path.read_text(), re.M):
                raise DispatchError("resolved code-review owner mismatch")
            map_rows = lane_registry.rows(Path(args.map_registry))
            fixed_point = map_rows[map_lane].get("base_commit")
            if not fixed_point:
                raise DispatchError("Map Integration fixed point required")
            contribution_rows = dict(map_rows)
            for path in args.implementation_registry or []:
                contribution_rows.update(lane_registry.rows(Path(path)))
            implementations = lane_registry.collect_implementation_identities(contribution_rows, fixed_point)
            review = mc.resolve_review_plan(mc.load_document(Path(args.config).expanduser()),
                required_axes=args.required_axes, implementations=implementations,
                evidence=evidence, native_capabilities={}, request_id=args.request_id)
            calls = lane_registry.build_owner_calls(review)
            payload = {"review_plan": review, "owner_calls": calls}
            marker = "<!-- DP_REVIEW_PLAN -->"
            if marker in packet_text:
                stored = json.loads(packet_text.split(marker, 1)[1].split("```json", 1)[1].split("```", 1)[0])
                lane_registry.verify_review_packet(review, stored)
            else:
                packet_path.write_text(packet_text + "\n" + marker + "\n```json\n" +
                    json.dumps(payload, ensure_ascii=False) + "\n```\n" +
                    "resolved code-review owner：逐轴按 owner_calls 的 requested 调用 required axes；"
                    "不得重新读取配置选模型。每轴保留独立 findings/verdict 和原生 readback，"
                    "无 readback 写 Unknown；pane 启动身份不得复制为双轴 executed。"
                    "沿用原 Review Evidence Bundle、Review Budget 和 review_gate。"
                    f"fan-in 必须运行 python3 {HERE / 'review_execution.py'} --ledger <原轮次账本>，"
                    "stdin 传 round、axes 完整结果、原 review_packet 与逐轴 native_readbacks；"
                    "REVIEW_BLOCKED 保留 findings、阻断本轮放行，禁止自动重跑或换候选。\n")
            actual = json.loads(packet_path.read_text().split(marker, 1)[1].split("```json", 1)[1].split("```", 1)[0])
            lane_registry.verify_review_packet(review, actual)
            plan = mc.review_start_plan(review, evidence)
        else:
            plan = mc.resolve_plan(mc.load_document(Path(args.config).expanduser()), args.task,
                                   ticket_mode=args.ticket_mode, map_mode=args.map_mode,
                                   evidence=evidence, output_mode=args.output_mode)
        frozen = mc.freeze_overlay(plan)
        coord = coordinator()
        row = {
            "lane_id": args.lane, "work_item": args.work_item, "role": args.task,
            "output_mode": args.output_mode, "runtime": RUNTIME[plan["agent"]], "state": "created",
            **frozen, "worktree": args.worktree, "branch": args.branch,
            "base_commit": args.base, "map": map_lane, "contract_rev": contract_rev(),
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        if args.off_chain_reason:
            row["off_chain_reason"] = args.off_chain_reason.replace("\n", " ")
        write_registry(registry, row)
        if review is not None:
            lane_registry.freeze_review_plan(registry, args.lane, review, args.request_id)
            persisted = lane_registry.load_review_plan(registry, args.lane, args.request_id)
            lane_registry.verify_review_packet(persisted, actual)
        # 同批并发 dispatch 时串行化落位，避免同时 split 同一 tab 或重复开 X。
        lock_path = Path(os.environ.get("TMPDIR", "/tmp")) / f"dp-dispatch-{coord['workspace_id'].replace(':', '_')}.lock"
        with open(lock_path, "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            pane = place(coord, args.worktree, args.tab_prefix)
        name = agent_name(args.lane)
        row["herdr"] = {**pane, "agent_name": name, "coordinator_pane_id": coord["pane_id"]}
        write_registry(registry, row)
        herdr(*mc.startup_request(plan, worker_name=name, pane_id=pane["pane_id"])[1:])
        herdr("pane", "rename", pane["pane_id"], args.title)
        prompt = f"完整读取 {args.packet} 并严格按其中全部指令执行。"
        herdr("agent", "prompt", name, prompt)
        if not wait_working(name):
            herdr("agent", "prompt", name, prompt)
            if not wait_working(name):
                subprocess.run(["herdr", "pane", "close", pane["pane_id"]], capture_output=True)
                raise DispatchError("agent did not reach working after one re-prompt")
        log = open(f"/tmp/lane-watch-{name}.log", "ab")
        subprocess.Popen([str(WATCHER), pane["pane_id"], coord["pane_id"], args.lane, args.title],
                         stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True)
        row["state"] = "running"
        row["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        write_registry(registry, row)
    except (DispatchError, ValueError, OSError, KeyError, json.JSONDecodeError) as error:
        if row:
            row["state"] = "setup_blocked"
            row["blocker"] = str(error).replace("\n", " ")
            try:
                write_registry(registry, row)
            except (DispatchError, OSError):
                pass
        print(json.dumps({"lane_id": args.lane, "state": "setup_blocked", "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps({"lane_id": args.lane, "state": "running", **row["herdr"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
