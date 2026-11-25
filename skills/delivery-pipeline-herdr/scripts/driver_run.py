#!/usr/bin/env python3
"""Herdr 壳的 Driver run 循环（ADR-0026 决策 1、4）。

在 core `driver.run` 上追加 Herdr dispatch 执行器：建 Execution Worktree、按派发模板渲染
packet、调 `dispatch.py`。缺 `dispatch.evidence`、`transport.herdr.worktrees_root` 或执行失败时交回 coordinator。

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


def exec_dispatch(map_dir: Path, state, action):
    cfg = state["driver"].get("dispatch") or {}
    root = ((state["driver"].get("transport") or {}).get("herdr") or {}).get("worktrees_root")
    mrow = driver.map_row(state["lanes"]) or {}
    integration = mrow.get("integration_worktree_path")
    if not (cfg.get("evidence") and root and integration):
        return None  # 缺配置：交回 coordinator 按壳合同派发
    a = dict(action["args"])
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
    herdr_cfg = (state["driver"].get("transport") or {}).get("herdr") or {}
    cmd = [sys.executable, str(DISPATCH), "--evidence", cfg["evidence"],
           "--task", a["task"], "--output-mode", a["output_mode"], "--lane", lane,
           "--work-item", a["work_item"], "--title", a.get("title") or lane, "--worktree", str(worktree),
           "--branch", branch, "--base", base, "--packet", str(packet),
           "--registry", str(registry), "--map-registry", mrow.get("_file") or "none"]
    if herdr_cfg.get("tab_prefix"):
        cmd.extend(["--tab-prefix", str(herdr_cfg["tab_prefix"])])
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
            action = driver.run(map_dir, {'dispatch': exec_dispatch})
    except (ValueError, RuntimeError, OSError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(action, ensure_ascii=False))
    return 10 if driver.wakes_llm(action) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
