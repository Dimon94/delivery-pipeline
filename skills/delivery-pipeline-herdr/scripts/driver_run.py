#!/usr/bin/env python3
"""Herdr 壳的 Driver run 循环（ADR-0026 决策 1、4）。

在 core `driver.run` 上追加 Herdr 执行器。dispatch：建 Execution Worktree、按派发模板渲染
packet、调 `dispatch.py`。closeout：core 收口成功后关闭本 lane 的 pane。缺 `dispatch.evidence`、`transport.herdr.worktrees_root` 或执行失败时交回 coordinator。

命令：
  driver_run.py run <map_dir>                 coordinator 每次唤醒调一次
  driver_run.py watch <map_dir> "<LANE_DONE 行>"  lane-watch.sh 调用：先交回终态行再 run
退出码：0 = 无需唤醒 LLM（wait 或已由程序执行完）；10 = 需要 coordinator 执行打印的 Action；1 = 错误。
"""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "delivery-pipeline" / "scripts"))
import driver  # noqa: E402

DISPATCH = Path(os.environ.get("DP_DISPATCH", HERE / "dispatch.py"))
PACKET = HERE.parent / "assets" / "HERDR_ROLE_DISPATCH_PACKET.md"
# 角色 lane 的中文短名固定；票 lane 的短名由 coordinator 写进 transport.herdr.labels。
ROLE_LABELS = {"integration": "合并", "testing": "测试", "review": "评审"}


def exec_dispatch(map_dir: Path, state, action):
    cfg = state["driver"].get("dispatch") or {}
    herdr_cfg = (state["driver"].get("transport") or {}).get("herdr") or {}
    root = herdr_cfg.get("worktrees_root")
    mrow = driver.map_row(state["lanes"]) or {}
    integration = mrow.get("integration_worktree_path")
    a = dict(action["args"])
    title = (ROLE_LABELS.get(a["task"])
             or ("测试" if str(a.get("work_item") or "").endswith("#testing") else None)
             or (herdr_cfg.get("labels") or {}).get(a["work_item"]))
    if not (cfg.get("evidence") and root and integration and title and herdr_cfg.get("tab_prefix")):
        return None  # 缺配置或中文短名：交回 coordinator 按壳合同派发
    lane = a["lane_id"]
    worktree = Path(root) / lane
    branch = f"{mrow.get('integration_branch') or 'map'}--{lane}"
    base = driver.run_git(integration, "rev-parse", "HEAD").stdout.strip()
    if not worktree.exists():
        added = driver.run_git(integration, "worktree", "add", "-b", branch, str(worktree), base)
        if added.returncode != 0:
            return None
    registry = map_dir / f"registry-{lane}.md"
    a.update(worktree=str(worktree), branch=branch, base=base, registry=str(registry))
    packet = map_dir / "packets" / f"{lane}.md"
    packet.parent.mkdir(parents=True, exist_ok=True)
    packet.write_text(driver.render_packet(state, {**action, "args": a},
                                           [f"Worker 合同：{PACKET}，读取 Worker 执行节"]))
    cmd = [sys.executable, str(DISPATCH), "--evidence", cfg["evidence"],
           "--task", a["task"], "--output-mode", a["output_mode"], "--lane", lane,
           "--work-item", a["work_item"], "--title", title, "--worktree", str(worktree),
           "--branch", branch, "--base", base, "--packet", str(packet),
           "--registry", str(registry), "--map-registry", mrow.get("_file") or "none",
           "--tab-prefix", str(herdr_cfg["tab_prefix"])]
    if a.get("merges"):
        cmd.extend(["--merges", str(a["merges"])])
    if a.get("ticket_mode"):
        cmd.extend(["--ticket-mode", str(a["ticket_mode"])])
    if a.get("map_mode"):
        cmd.extend(["--map-mode", str(a["map_mode"])])
    if herdr_cfg.get("workspace_label"):
        cmd.extend(["--workspace-label", str(herdr_cfg["workspace_label"])])
    out = subprocess.run(cmd, capture_output=True, text=True)
    try:
        reply = json.loads((out.stdout.strip().splitlines() or ["{}"])[-1])
    except json.JSONDecodeError:
        reply = {}
    if out.returncode != 0 or reply.get("state") != "running":
        return None  # setup_blocked 已由 dispatch.py 写入；交回 coordinator 判断
    return {"lane": {"lane_id": lane, "work_item": a["work_item"]}, "persisted": True}


# ---------- closeout：core 删树删分支，壳释放本 lane pane ----------
# 合同：lane 收口后它的 pane 由本执行器关闭，不靠 merger 或 coordinator 自觉。
# 只关 registry `herdr.pane_id`；pane 上跑的不是 `herdr.agent_name` 时不关，回 close_pending。
# pane 已不在算已释放（幂等）。检查：driver_run_check.py 的 closeout 段。

def herdr_json(*args: str) -> dict:
    out = subprocess.run(["herdr", *args], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"herdr {' '.join(args)} 失败：{(out.stderr or out.stdout).strip()}")
    return json.loads(out.stdout)["result"]


def release_pane(row) -> str | None:
    """关闭 lane 自己的 pane。返回 None 表示已释放，否则返回不能关的原因。"""
    owner = json.loads(row.get("herdr") or "null")
    if not owner:
        return None  # 没经 Herdr 派发（HITL、旧 map）：没有 pane
    pane, name = owner.get("pane_id"), owner.get("agent_name")
    if pane not in {p["pane_id"] for p in herdr_json("pane", "list")["panes"]}:
        return None
    holders = {a["name"] for a in herdr_json("agent", "list")["agents"] if a["pane_id"] == pane}
    if holders - {name}:
        return f"pane {pane} 已换成 {sorted(holders)}，不是 {name}，保留现场"
    herdr_json("pane", "close", pane)
    return None


def exec_closeout(map_dir: Path, state, action):
    receipt = driver.exec_closeout(map_dir, state, action)
    if receipt["result"] != "closed":
        return receipt
    try:
        reason = release_pane(state["lanes"][action["args"]["lane_id"]])
    except (RuntimeError, json.JSONDecodeError, KeyError) as error:
        reason = str(error)
    return {"result": "close_pending", "reason": reason} if reason else receipt


EXECUTORS = {"dispatch": exec_dispatch, "closeout": exec_closeout}


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[0] not in ("run", "watch"):
        print(__doc__)
        return 1
    map_dir = Path(argv[1]).resolve()
    try:
        with (map_dir / '.driver.lock').open('a') as guard:
            fcntl.flock(guard, fcntl.LOCK_EX)
            if argv[0] == 'watch':
                if len(argv) != 3:
                    raise ValueError('watch 需要一行终态信号')
                driver.signal(map_dir, argv[2])
            action = driver.run(map_dir, EXECUTORS)
    except (ValueError, RuntimeError, OSError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(action, ensure_ascii=False))
    return 10 if driver.wakes_llm(action) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
