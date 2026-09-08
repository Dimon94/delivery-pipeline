#!/usr/bin/env python3
"""把 canonical continuation request 翻译为 Claude Code 原生接续计划。"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from uuid import UUID


_CHECKPOINT_SPEC = importlib.util.spec_from_file_location(
    "delivery_pipeline_checkpoint", Path(__file__).with_name("checkpoint.py"))
if _CHECKPOINT_SPEC is None or _CHECKPOINT_SPEC.loader is None:  # pragma: no cover - packaging error
    raise RuntimeError("checkpoint.py 不可加载")
CHECKPOINT = importlib.util.module_from_spec(_CHECKPOINT_SPEC)
_CHECKPOINT_SPEC.loader.exec_module(CHECKPOINT)


UNKNOWN = CHECKPOINT.UNKNOWN


class ClaudeAdapterError(ValueError):
    """Claude 原生 session 或接续请求不能安全确定。"""


def _text(value: object, field: str, *, allow_unknown: bool = False) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ClaudeAdapterError(f"{field} 缺失或不是文本")
    if not allow_unknown and value.strip().lower() == UNKNOWN.lower():
        raise ClaudeAdapterError(f"{field} 缺失或 Unknown")
    return value


def _uuid(value: object, field: str) -> str:
    text = _text(value, field)
    try:
        if str(UUID(text)) != text:
            raise ValueError
    except ValueError as error:
        raise ClaudeAdapterError(f"{field} 必须是精确原生 UUID，不能猜最近会话") from error
    return text


def _read_checkpoint(path: Path) -> dict[str, object]:
    try:
        # 先读 artifact 身份，再以 checkpoint 自带 Execution Worktree 做 live readback。
        document = CHECKPOINT.read_checkpoint(path)
        return CHECKPOINT.read_checkpoint(
            path,
            worktree=document["execution_worktree"],
            expected_lane=document["lane_id"],
            expected_base=document["base_commit"],
        )
    except CHECKPOINT.CheckpointError as error:
        raise ClaudeAdapterError(f"checkpoint/Git readback 失败: {error}") from error


def _verify_observation(document: dict[str, object], observation: object) -> None:
    if not isinstance(observation, dict):
        raise ClaudeAdapterError("runtime observation 必须是 object")
    for field in CHECKPOINT.OBSERVATION_IDENTITY_FIELDS:
        if observation.get(field) != document[field]:
            raise ClaudeAdapterError(f"runtime observation.{field} 与 checkpoint 不匹配")
    if observation.get("status") not in {"idle", "stopped"}:
        raise ClaudeAdapterError("runtime observation 必须明确 idle/stopped")
    if observation.get("writer_active") is not False:
        raise ClaudeAdapterError("旧 writer 未明确停止")
    if observation.get("coordinator_active") is not False:
        raise ClaudeAdapterError("旧 coordinator 未明确停止")
    if observation.get("session_resumable") is not True:
        raise ClaudeAdapterError("原 session 未明确可恢复")
    if observation.get("ready_seen") is not True or observation.get("stop_evidence") is not True:
        raise ClaudeAdapterError("缺少 PREWALK_READY/WORKER_STOPPED 停止证据")
    _text(observation.get("source"), "runtime observation.source")
    _text(observation.get("read_at"), "runtime observation.read_at")


def _verify_tui_probe(probe: object) -> None:
    if not isinstance(probe, dict):
        raise ClaudeAdapterError("tui_probe 必须是 object")
    if probe.get("status") not in {"unavailable", "unreliable"}:
        raise ClaudeAdapterError("TUI 可用时不能绕过 TUI 直接 resume")
    _text(probe.get("source"), "tui_probe.source")
    _text(probe.get("read_at"), "tui_probe.read_at")


def _verify_effort(evidence: object, effort: str) -> None:
    if not isinstance(evidence, dict):
        raise ClaudeAdapterError("effort_evidence 必须是 object")
    _text(evidence.get("source"), "effort_evidence.source")
    values = evidence.get("values")
    if (not isinstance(values, list) or not values
            or any(not isinstance(value, str) or not value.strip() for value in values)):
        raise ClaudeAdapterError("effort_evidence.values 必须是非空枚举列表")
    if effort not in values:
        raise ClaudeAdapterError("target effort 不在当前 Claude CLI evidence 中")


def resume_plan(payload: object) -> dict[str, object]:
    """核验持久现场后生成计划；实际值必须由原生新轮另行读回。"""
    expected = {
        "runtime", "session_id", "checkpoint_path", "request", "observation",
        "tui_probe", "effort_evidence",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ClaudeAdapterError("Claude adapter 输入字段不匹配")
    if payload["runtime"] != "herdr-claude-pane":
        raise ClaudeAdapterError("Claude adapter 只接受 herdr-claude-pane")

    session_id = _uuid(payload["session_id"], "session_id")
    checkpoint_path = Path(_text(payload["checkpoint_path"], "checkpoint_path"))
    if not checkpoint_path.is_absolute():
        raise ClaudeAdapterError("checkpoint_path 必须是绝对路径")
    document = _read_checkpoint(checkpoint_path)
    if document["runtime"] != payload["runtime"] or document["session_id"] != session_id:
        raise ClaudeAdapterError("checkpoint runtime/session 与请求不匹配")
    if document["phase"] != "starting" or document["development_mode"] != "staged":
        raise ClaudeAdapterError("只有 staged starting checkpoint 可以接续 execution")
    _verify_observation(document, payload["observation"])
    _verify_tui_probe(payload["tui_probe"])

    request = payload["request"]
    if not isinstance(request, dict) or set(request) != {"request_id", "intent_sha256", "target_request"}:
        raise ClaudeAdapterError("continuation request 字段不匹配")
    intent_sha = _text(request["intent_sha256"], "intent_sha256")
    if len(intent_sha) != 64 or any(character not in "0123456789abcdef" for character in intent_sha):
        raise ClaudeAdapterError("intent_sha256 无效")
    if request["request_id"] != "request-" + intent_sha:
        raise ClaudeAdapterError("request_id 与 continuation intent 不匹配")

    target = request["target_request"]
    if not isinstance(target, dict) or set(target) != {"model", "effort"}:
        raise ClaudeAdapterError("target_request 必须只有 model/effort")
    model = _text(target["model"], "target_request.model")
    effort = _text(target["effort"], "target_request.effort")
    _verify_effort(payload["effort_evidence"], effort)
    try:
        intent = CHECKPOINT.build_continuation_intent(
            document, target_request={"model": model, "effort": effort})
    except CHECKPOINT.CheckpointError as error:
        raise ClaudeAdapterError(f"continuation intent 无效: {error}") from error
    if intent[CHECKPOINT.INTENT_FINGERPRINT_FIELD] != intent_sha:
        raise ClaudeAdapterError("request intent_sha256 与 checkpoint/target 不匹配")

    return {
        "action": "resume-same-session",
        "agent_kind": "claude",
        "request_id": request["request_id"],
        "session_id": session_id,
        "argv": ["--resume", session_id, "--model", model, "--effort", effort,
                 "--dangerously-skip-permissions"],
        "prompt": ("沿原 session 与原 packet 接续；读取 checkpoint " + str(checkpoint_path)
                   + "；完成剩余实现、检查与 owner 交付。"),
        "requested_model": model,
        "requested_effort": effort,
        "checkpoint_sha256": document[CHECKPOINT.FINGERPRINT_FIELD],
        "execution_worktree": document["execution_worktree"],
        "execution_branch": document["execution_branch"],
        "head_commit": document["head_commit"],
        "tool_acceptance": UNKNOWN,
        "actual_model": UNKNOWN,
        "actual_effort": UNKNOWN,
    }


def main() -> int:
    try:
        print(json.dumps(resume_plan(json.load(sys.stdin)), ensure_ascii=False,
                         sort_keys=True, separators=(",", ":")))
        return 0
    except (ClaudeAdapterError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
