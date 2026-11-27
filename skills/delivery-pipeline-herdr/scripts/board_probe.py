"""按 registry 坐标批量读取 Herdr agent 现场。"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from board_snapshot import LiveProbe, LiveStatus, ProbeLane


def probe(lanes: list[ProbeLane]) -> dict[str, LiveStatus]:
    # 从桌面启动时 PATH 可能未包含用户安装的 Herdr。
    binary = shutil.which("herdr") or str(Path.home() / ".local/bin/herdr")
    try:
        reply = subprocess.run([binary, "agent", "list"], capture_output=True,
                               text=True, check=True, timeout=2)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("herdr agent list 超时（2 秒）") from error
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip() or f"退出码 {error.returncode}"
        raise RuntimeError(f"herdr agent list 失败：{detail}") from error

    try:
        agents = {(agent["pane_id"], agent["name"]): agent["agent_status"]
                  for agent in json.loads(reply.stdout)["result"]["agents"]}
    except (ValueError, KeyError, TypeError) as error:
        raise RuntimeError("herdr agent list 返回无法识别的结果") from error
    observed: dict[str, LiveStatus] = {}
    for lane in lanes:
        overlay = lane["overlay"]
        pane, name = overlay.get("pane_id"), overlay.get("agent_name")
        if pane and name and (pane, name) in agents:
            observed[lane["lane_id"]] = "working" if agents[pane, name] == "working" else "not_working"
    return observed


def register(probes: dict[str, LiveProbe]) -> None:
    probes["herdr"] = probe
