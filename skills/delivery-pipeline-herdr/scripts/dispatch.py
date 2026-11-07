#!/usr/bin/env python3
"""Herdr lane 一次派发：解析计划 → 写 registry → 落 pane → 启动 agent → 投递 packet →
确认 working → 挂 watcher → 回写 running。成功只打印一行 JSON 坐标；失败写 setup_blocked。

用法：
  dispatch.py --config <model-roles.json> --evidence <capability.json> --task <task type>
              --output-mode <mode> --lane <lane_id> --work-item <url> --title <pane label>
              --worktree <abs> --branch <branch> --base <sha> --packet <abs> --registry <abs .md>
              [--ticket-mode NAME] [--map-mode NAME] [--tab-prefix X]
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
WATCHER = Path(os.environ.get("DP_LANE_WATCH", HERE / "lane-watch.sh"))
TAB_CAPACITY = 4
RUNTIME = {"pi": "herdr-pi-pane", "codex": "herdr-codex-pane", "claude": "herdr-claude-pane"}


class DispatchError(Exception):
    pass


def load_model_config():
    spec = importlib.util.spec_from_file_location("model_config", MODEL_CONFIG)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
    lines = ["<!-- wayfinder-lane-registry:v2 -->", "```yaml"]
    for key, value in row.items():
        if isinstance(value, dict):
            lines.append(f"{key}:")
            lines += [f"  {k}: {'none' if v is None else v}" for k, v in value.items()]
        else:
            lines.append(f"{key}: {'none' if value is None else value}")
    lines.append("```")
    text = "\n".join(lines) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    if path.read_text(encoding="utf-8") != text:
        raise DispatchError(f"registry readback mismatch: {path}")


def wait_working(name: str) -> bool:
    return subprocess.run(["herdr", "agent", "wait", name, "--until", "working", "--timeout", "15000"],
                          capture_output=True).returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser()
    for flag in ("config", "evidence", "task", "output-mode", "lane", "work-item", "title",
                 "worktree", "branch", "base", "packet", "registry"):
        parser.add_argument(f"--{flag}", required=True)
    parser.add_argument("--ticket-mode")
    parser.add_argument("--map-mode")
    parser.add_argument("--tab-prefix", default="X")
    args = parser.parse_args()

    registry = Path(args.registry)
    row: dict = {}
    try:
        for label, value in (("worktree", args.worktree), ("packet", args.packet)):
            if not Path(value).is_absolute() or not Path(value).exists():
                raise DispatchError(f"{label} must be an existing absolute path: {value}")
        if registry.exists() and re.search(r"^state: (running|awaiting_human|created)$",
                                           registry.read_text(encoding="utf-8"), re.M):
            raise DispatchError(f"registry already has an active writer: {registry}")
        mc = load_model_config()
        plan = mc.resolve_plan(mc.load_document(Path(args.config).expanduser()), args.task,
                               ticket_mode=args.ticket_mode, map_mode=args.map_mode,
                               evidence=json.loads(Path(args.evidence).expanduser().read_text()),
                               output_mode=args.output_mode)
        frozen = mc.freeze_overlay(plan)
        coord = coordinator()
        row = {
            "lane_id": args.lane, "work_item": args.work_item, "role": args.task,
            "output_mode": args.output_mode, "runtime": RUNTIME[plan["agent"]], "state": "created",
            "agent": frozen["agent"], "model": frozen["model"], "effort": frozen["effort"],
            "mode": frozen["mode"], "worktree": args.worktree, "branch": args.branch,
            "base_commit": args.base, "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        write_registry(registry, row)
        # 同批并发 dispatch 时串行化落位，避免同时 split 同一 tab 或重复开 X。
        lock_path = Path(os.environ.get("TMPDIR", "/tmp")) / f"dp-dispatch-{coord['workspace_id'].replace(':', '_')}.lock"
        with open(lock_path, "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            pane = place(coord, args.worktree, args.tab_prefix)
        name = re.sub(r"[^a-z0-9-]+", "-", args.lane.lower()).strip("-") or "lane"
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
