#!/usr/bin/env python3
"""把 canonical continuation request 翻译为 Pi 原生 TUI 命令。"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


THINKING_LEVELS = {"off", "minimal", "low", "medium", "high", "xhigh", "max"}
SHA256 = re.compile(r"[0-9a-f]{64}")


class PiAdapterError(ValueError):
    """接续请求不能安全映射到 Pi 原生 TUI。"""


def _nonempty(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PiAdapterError(f"{field} 缺失")
    return value


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value or value.lower() == "unknown":
        raise PiAdapterError(f"{field} 缺失、包含边界空白或为 Unknown")
    if any(character.isspace() or ord(character) < 32 for character in value):
        raise PiAdapterError(f"{field} 包含 TUI 命令不支持的字符")
    return value


def build_tui_switch(request: object) -> dict[str, Any]:
    """生成两条精确 TUI 命令；调用者负责在原 idle session 中发送并读回。"""
    if not isinstance(request, dict) or set(request) != {"request_id", "intent_sha256", "target_request"}:
        raise PiAdapterError("request 字段必须精确匹配 canonical continuation request")
    intent_sha256 = _text(request["intent_sha256"], "intent_sha256")
    request_id = _text(request["request_id"], "request_id")
    if not SHA256.fullmatch(intent_sha256) or request_id != f"request-{intent_sha256}":
        raise PiAdapterError("request_id 未绑定 canonical continuation intent")

    target = request["target_request"]
    if not isinstance(target, dict) or set(target) != {"model", "effort"}:
        raise PiAdapterError("target_request 必须精确包含 model/effort")
    model = _text(target["model"], "target_request.model")
    provider, separator, model_id = model.partition("/")
    if not separator or not provider or not model_id:
        raise PiAdapterError("Pi model 必须使用精确 provider/model id")
    effort = _text(target["effort"], "target_request.effort")
    if effort not in THINKING_LEVELS:
        raise PiAdapterError("Pi thinking level 不受支持")

    return {
        "commands": [
            {"expect": f"Model: {model_id}", "text": f"/model {model}"},
            {"expect": f"Thinking level: {effort}", "text": f"/thinking {effort}"},
        ],
        "intent_sha256": intent_sha256,
        "native_seam": "pi-tui",
        "request_id": request_id,
        "runtime": "herdr-pi-pane",
    }


def build_start_command(*, worker_name: str, pane_id: str, model: str, effort: str) -> list[str]:
    """构造 Pi staged 起步命令；执行器仍由 Herdr 负责。"""
    _text(model, "model")
    provider, separator, model_id = model.partition("/")
    if not separator or not provider or not model_id:
        raise PiAdapterError("Pi model 必须使用精确 provider/model id")
    effort = _text(effort, "effort")
    if effort not in THINKING_LEVELS:
        raise PiAdapterError("Pi thinking level 不受支持")
    worker_name = _text(worker_name, "worker_name")
    pane_id = _text(pane_id, "pane_id")
    return [
        "herdr", "agent", "start", worker_name, "--kind", "pi", "--pane", pane_id, "--",
        "--approve", "--model", model, "--thinking", effort,
    ]


def _herdr_json(herdr: str, *args: str) -> dict[str, Any]:
    result = subprocess.run([herdr, *args], text=True, capture_output=True, check=False)
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise PiAdapterError(f"Herdr 命令失败: {' '.join(args)}: {detail}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise PiAdapterError(f"Herdr 返回不是 JSON: {error}") from error
    if not isinstance(payload, dict):
        raise PiAdapterError("Herdr 返回不是 object")
    return payload


def _agent_info(herdr: str, target: str, worktree: str) -> dict[str, Any]:
    target = _text(target, "pane_id")
    payload = _herdr_json(herdr, "agent", "get", target)
    info = payload.get("result", {}).get("agent")
    if not isinstance(info, dict) or info.get("agent") != "pi":
        raise PiAdapterError("目标 pane 不是 Pi agent")
    if info.get("agent_status") not in {"idle", "done"}:
        raise PiAdapterError("Pi agent 未处于 idle/done，拒绝并发写入")
    actual_cwd = info.get("cwd")
    if not isinstance(actual_cwd, str) or Path(actual_cwd).resolve() != Path(worktree).resolve():
        raise PiAdapterError("Pi pane cwd 与 Execution Worktree 不匹配")
    session = info.get("agent_session")
    if not isinstance(session, dict) or session.get("kind") != "path":
        raise PiAdapterError("Pi 原生 session path 不可读")
    session_path = session.get("value")
    if not isinstance(session_path, str) or not Path(session_path).is_file():
        raise PiAdapterError("Pi 原生 session 文件不可读")
    return {**info, "session_path": str(Path(session_path).resolve())}


def read_session(session_path: str | Path) -> dict[str, Any]:
    """读取 Pi session header 与最近的 model/thinking 变更。"""
    path = Path(session_path).expanduser().resolve(strict=True)
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict):
            entries.append(entry)
    header = next((entry for entry in entries if entry.get("type") == "session"), None)
    if not isinstance(header, dict):
        raise PiAdapterError("Pi session 缺少原生 header")
    session_id = _text(header.get("id"), "session.id")
    cwd = _nonempty(header.get("cwd"), "session.cwd")
    model = None
    effort = None
    for entry in entries:
        if entry.get("type") == "model_change":
            provider = entry.get("provider")
            model_id = entry.get("modelId")
            if isinstance(provider, str) and isinstance(model_id, str):
                model = f"{provider}/{model_id}"
        elif entry.get("type") == "thinking_level_change":
            value = entry.get("thinkingLevel")
            if isinstance(value, str):
                effort = value
    return {"cwd": cwd, "effort": effort, "entries": entries,
            "model": model, "session_id": session_id, "session_path": str(path)}


def _wait_for_entry(session_path: str, before_count: int, kind: str, *, expected: dict[str, str],
                    timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = read_session(session_path)
        for entry in state["entries"][before_count:]:
            if entry.get("type") != kind:
                continue
            if all(entry.get(key) == value for key, value in expected.items()):
                return entry
        time.sleep(0.1)
    raise PiAdapterError(f"Pi TUI {kind} transcript readback 超时")


def apply_tui_switch(request: object, *, pane_id: str, worktree: str,
                     session_id: str, herdr: str = "herdr", timeout: float = 15.0) -> dict[str, Any]:
    """在已停止的原生 Pi TUI 中应用并读回 model/effort。"""
    plan = build_tui_switch(request)
    session_id = _text(session_id, "session_id")
    info = _agent_info(herdr, pane_id, worktree)
    state = read_session(info["session_path"])
    if state["session_id"] != session_id or Path(state["cwd"]).resolve() != Path(worktree).resolve():
        raise PiAdapterError("Pi session 身份或 cwd 与 checkpoint 不匹配")

    readbacks: list[dict[str, Any]] = []
    for command in plan["commands"]:
        before = read_session(info["session_path"])
        expected_model = plan["commands"][0]["text"][7:]
        expected_effort = plan["commands"][1]["text"][10:]
        if ((command["text"].startswith("/model ") and before["model"] == expected_model)
                or (command["text"].startswith("/thinking ") and before["effort"] == expected_effort)):
            readbacks.append({"command": command["text"], "entry": None,
                              "status": "already-target", "source": "pi-session-transcript"})
            continue
        before_count = len(before["entries"])
        text_result = subprocess.run(
            [herdr, "pane", "send-text", pane_id, command["text"]],
            text=True, capture_output=True, check=False,
        )
        if text_result.returncode:
            raise PiAdapterError(f"Pi TUI 命令发送失败: {command['text']}")
        time.sleep(0.15)
        for _ in range(2):
            enter_result = subprocess.run(
                [herdr, "pane", "send-keys", pane_id, "return"],
                text=True, capture_output=True, check=False,
            )
            if enter_result.returncode:
                raise PiAdapterError(f"Pi TUI Return 发送失败: {command['text']}")
            time.sleep(0.15)
        if command["text"].startswith("/model "):
            provider, _, expected_id = plan["commands"][0]["text"][7:].partition("/")
            entry = _wait_for_entry(
                info["session_path"], before_count, "model_change",
                expected={"provider": provider, "modelId": expected_id}, timeout=timeout,
            )
        else:
            entry = _wait_for_entry(
                info["session_path"], before_count, "thinking_level_change",
                expected={"thinkingLevel": command["text"][10:]}, timeout=timeout,
            )
        readbacks.append({"command": command["text"], "entry": entry,
                          "status": "accepted", "source": "herdr-pane"})

    final = read_session(info["session_path"])
    expected_model = plan["commands"][0]["text"][7:]
    expected_effort = plan["commands"][1]["text"][10:]
    if final["session_id"] != session_id or final["model"] != expected_model or final["effort"] != expected_effort:
        raise PiAdapterError("Pi TUI 实际 model/effort 与目标不匹配")
    after = _agent_info(herdr, pane_id, worktree)
    if after["session_path"] != info["session_path"]:
        raise PiAdapterError("Pi 原生 session path 在 TUI 接续期间改变")
    return {
        "actual_effort": final["effort"],
        "actual_model": final["model"],
        "actual_readback_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "actual_readback_source": "pi-session-transcript",
        "commands": readbacks,
        "intent_sha256": plan["intent_sha256"],
        "native_seam": plan["native_seam"],
        "request_id": plan["request_id"],
        "runtime": plan["runtime"],
        "session_id": final["session_id"],
        "session_path": final["session_path"],
        "tool_acceptance": {"accepted": True, "status": "accepted", "source": "herdr-pane"},
    }


def _self_test() -> None:
    intent = "a" * 64
    plan = build_tui_switch({
        "request_id": f"request-{intent}",
        "intent_sha256": intent,
        "target_request": {"model": "openai-codex/gpt-6-astra", "effort": "max"},
    })
    assert plan["commands"] == [
        {"expect": "Model: gpt-6-astra", "text": "/model openai-codex/gpt-6-astra"},
        {"expect": "Thinking level: max", "text": "/thinking max"},
    ]
    assert build_start_command(worker_name="worker", pane_id="w1:p1",
                               model="openai-codex/gpt-6-astra", effort="max")[-6:] == [
        "--", "--approve", "--model", "openai-codex/gpt-6-astra", "--thinking", "max",
    ]
    for invalid in (
        {"request_id": f"request-{intent}", "intent_sha256": intent,
         "target_request": {"model": "Unknown", "effort": "max"}},
        {"request_id": f"request-{intent}", "intent_sha256": intent,
         "target_request": {"model": "openai-codex/gpt-6-astra\n/exit", "effort": "max"}},
        {"request_id": f"request-{intent}", "intent_sha256": intent,
         "target_request": {"model": "openai-codex/gpt-6-astra", "effort": "turbo"}},
    ):
        try:
            build_tui_switch(invalid)
        except PiAdapterError:
            continue
        raise AssertionError("expected invalid Pi TUI request to fail closed")


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "self-test":
        _self_test()
        print("pi-adapter: pass")
        return 0
    if len(sys.argv) == 2 and sys.argv[1] == "commands":
        print(json.dumps(build_tui_switch(json.load(sys.stdin)), ensure_ascii=False,
                         sort_keys=True, separators=(",", ":")))
        return 0
    if len(sys.argv) >= 2 and sys.argv[1] == "apply":
        parser = argparse.ArgumentParser(prog="pi_adapter.py apply")
        parser.add_argument("--pane-id", required=True)
        parser.add_argument("--worktree", required=True)
        parser.add_argument("--session-id", required=True)
        parser.add_argument("--herdr", default="herdr")
        parser.add_argument("--timeout", type=float, default=15.0)
        options = parser.parse_args(sys.argv[2:])
        result = apply_tui_switch(
            json.load(sys.stdin), pane_id=options.pane_id, worktree=options.worktree,
            session_id=options.session_id, herdr=options.herdr, timeout=options.timeout,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 0
    print("usage: pi_adapter.py <apply|commands|self-test>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (PiAdapterError, json.JSONDecodeError) as error:
        print(f"pi-adapter: blocked: {error}", file=sys.stderr)
        raise SystemExit(1)
