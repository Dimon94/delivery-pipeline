#!/usr/bin/env python3
"""App 分派边界：读取 JSON，输出可持久化 overlay 与工具参数；不发送请求。"""
import hashlib
import json
import os
from pathlib import Path
import runpy
import stat
import subprocess
import sys

MODES = {"sol-luna": ("gpt-5.6-luna", "max"),
         "sol-sol": ("gpt-5.6-sol", "high"),
         "sol-direct": ("gpt-5.6-sol", "high"),
         # 只用于恢复已持久化的旧 lane。
         "astra-luna": ("gpt-5.6-luna", "max"),
         "astra-sol": ("gpt-5.6-sol", "high")}
NEW_MODES = {"sol-luna", "sol-sol", "sol-direct"}
PREWALK_MODES = {"sol-luna", "sol-sol", "astra-luna", "astra-sol"}
check_implementation = runpy.run_path(str(Path(__file__).resolve().parents[2] /
    "delivery-pipeline/scripts/implementation_gate.py"))["check"]


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args])


def snapshot(root):
    root = Path(root).resolve(strict=True)
    if Path(os.fsdecode(git(root, "rev-parse", "--show-toplevel")).strip()).resolve() != root:
        raise ValueError("worktree 必须是 Git 顶层目录")
    paths = set(git(root, "diff", "--name-only", "-z", "HEAD").split(b"\0"))
    paths.update(git(root, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0"))
    files = {}
    for raw in sorted(paths - {b""}):
        name = os.fsdecode(raw)
        path = root / name
        # 目录型 gitlink/特殊文件不能冒充已完整校验的普通修改。
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            files[name] = {"deleted": True}
            continue
        if stat.S_ISLNK(mode):
            body = os.fsencode(os.readlink(path))
        elif stat.S_ISREG(mode):
            body = path.read_bytes()
        else:
            raise ValueError("不支持的 dirty 文件类型: " + name)
        files[name] = {"mode": mode, "sha256": hashlib.sha256(body).hexdigest()}
    return {"worktree": str(root), "head": git(root, "rev-parse", "HEAD").decode().strip(),
            "branch": git(root, "rev-parse", "--abbrev-ref", "HEAD").decode().strip(),
            "common_dir": os.fsdecode(git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")).strip(),
            "index_sha256": hashlib.sha256(git(root, "diff", "--cached", "--binary", "HEAD")).hexdigest(),
            "dirty": files}


def resolve(data):
    lane = data.get("existing_lane")
    if lane is not None:
        return {"action": "recover", "overlay": lane, "request": None}
    if data.get("output_mode") != "commit" or data.get("role") not in ("design", "frontend", "backend"):
        return {"action": "not-applicable", "request": None}
    check_implementation(data)
    mode, source = "sol-luna", "default"
    for key in ("ticket_mode", "map_mode"):
        if data.get(key) is not None:
            mode, source = data[key], key.removesuffix("_mode")
            break
    if mode not in NEW_MODES:
        raise ValueError("非法 development_mode")
    direct = mode == "sol-direct"
    model, effort = "gpt-5.6-sol", "high"
    return {"action": "create", "overlay": {"development_mode": mode, "mode_source": source,
            "execution_phase": "executing" if direct else "starting", "checkpoint": None,
            "requested_model": model, "requested_effort": effort,
            "model": "Unknown", "effort": "Unknown", "model_evidence": "Unknown"},
            "request": {"model": model, "thinking": effort}}


def coordinator(data):
    if not all(isinstance(data.get(k), str) and data[k].strip() and data[k] != "Unknown"
               for k in ("model", "effort", "source")):
        return {"action": "Unknown", "model": "Unknown", "effort": "Unknown", "source": "Unknown"}
    return {"action": "verified", "model": data["model"], "effort": data["effort"],
            "source": data["source"]}


def prepare(data):
    lane = data["lane"]
    if lane.get("execution_phase") in ("switching", "executing"):
        return {"action": "readback", "overlay": lane, "request": None}
    if lane.get("execution_phase") != "starting" or lane.get("development_mode") not in PREWALK_MODES:
        raise ValueError("当前 lane 不允许 Prewalk 接续")
    if lane.get("state") != "running":
        raise ValueError("当前 lane 非 running")
    observation, checkpoint = data["observation"], data["checkpoint"]
    for key in ("lane_id", "thread_id", "host_id"):
        if not lane.get(key) or lane[key] != checkpoint.get(key):
            raise ValueError("检查点坐标不匹配: " + key)
    for key in ("thread_id", "host_id"):
        if lane[key] != observation.get(key):
            raise ValueError("宿主观测坐标不匹配: " + key)
    if not observation.get("source"):
        raise ValueError("缺失起步轮宿主证据")
    if observation.get("status") == "active":
        return {"action": "wait-for-stop", "overlay": lane, "request": None,
                "target": {"threadId": lane["thread_id"], "hostId": lane["host_id"]}}
    if observation.get("status") != "idle":
        raise ValueError("缺失起步轮停止的宿主证据")
    check_implementation(data)
    path = Path(data["checkpoint_path"])
    if not path.is_absolute() or not path.is_file() or json.loads(path.read_text()) != checkpoint:
        raise ValueError("检查点持久 readback 不匹配")
    root = Path(lane["worktree"]).resolve()
    if path.resolve().is_relative_to(root):
        raise ValueError("检查点必须位于 repo 外")
    if not lane.get("base_commit") or checkpoint.get("base_commit") != lane["base_commit"]:
        raise ValueError("检查点 base 不匹配")
    git(root, "merge-base", "--is-ancestor", lane["base_commit"], "HEAD")
    current = snapshot(root)
    if current != checkpoint.get("snapshot"):
        raise ValueError("检查点已过期")
    first_edit = checkpoint.get("first_edit")
    if not isinstance(first_edit, list) or not first_edit or any(
            not isinstance(name, str) or name not in current["dirty"] for name in first_edit):
        raise ValueError("缺少可核对的首处实现路径")
    for key in ("todo", "checks", "evidence", "decision"):
        if not checkpoint.get(key):
            raise ValueError("检查点缺失: " + key)
    model, effort = MODES[lane["development_mode"]]
    overlay = {**lane, "execution_phase": "switching", "checkpoint": str(path),
               "previous_model_evidence": {k: lane.get(k, "Unknown") for k in
                   ("requested_model", "requested_effort", "model", "effort", "model_evidence")},
               "requested_model": model, "requested_effort": effort, "model": "Unknown",
               "effort": "Unknown", "model_evidence": "Unknown"}
    return {"action": "persist-before-send", "overlay": overlay,
            "request": {"threadId": lane["thread_id"], "hostId": lane["host_id"],
                        "model": model, "thinking": effort,
                        "prompt": "你是本任务 Execution Worktree 内的实现 worker；直接继续实现，不承担协调器监控。"
                                  "起步轮限制已结束。沿本任务历史及原 packet/owner/权限接续；读取检查点 "
                                  + str(path) + "，完成剩余实现、测试与原 owner 的交付步骤。"}}


def subagent(data):
    """父会话先读宿主活跃列表；这个入口不创建或锁定子代理。"""
    work, count = data["work"], data["active_count"]
    if work not in ("assistance", "second-opinion", "review", "ticket-sizing", "testing", "integration"):
        raise ValueError("非法内部工作类型")
    if type(count) is not int or count < 0 or not data.get("source") or type(data.get("read_only")) is not bool:
        raise ValueError("缺少有效的宿主并发/父权限观测")
    slots = 2 if work == "review" else 1
    if work in ("testing", "integration") and count != 0:
        raise ValueError(work + " 需要独占父会话的子代理容量")
    if work == "integration" and data["read_only"]:
        raise ValueError("integration 需要父任务写权限")
    result = {"request": None, "read_only": data["read_only"] or work not in ("assistance", "integration"),
              "required_slots": slots, "limit": 3}
    if count + slots > 3:
        return {**result, "action": "wait"}
    if work == "review":
        return {**result, "action": "invoke-owner"}
    model, effort = ("gpt-5.6-luna", "max") if work in ("assistance", "testing", "integration") else ("gpt-6-astra", "low")
    if work == "ticket-sizing":
        model, effort = "gpt-5.6-sol", "high"
    return {**result, "action": "spawn", "request": {
        "model": model, "reasoning_effort": effort, "fork_turns": "none"}}


def main():
    try:
        data = json.load(sys.stdin)
        command = sys.argv[1]
        if command == "snapshot":
            result = snapshot(data["worktree"])
        elif command == "coordinator":
            result = coordinator(data)
        elif command == "resolve":
            result = resolve(data)
        elif command == "subagent":
            result = subagent(data)
        elif command == "prepare":
            result = prepare(data)
        else:
            raise ValueError("未知命令")
        print(json.dumps(result, ensure_ascii=False))
    except (ValueError, KeyError, TypeError, OSError, subprocess.CalledProcessError, IndexError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
