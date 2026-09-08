#!/usr/bin/env python3
"""canonical continuation：在既有 lane registry 上安全重入同一 session。"""

from __future__ import annotations

import copy
import hashlib
from typing import Any

import checkpoint as CHECKPOINT


UNKNOWN = CHECKPOINT.UNKNOWN
IDENTITY_FIELDS = CHECKPOINT.OBSERVATION_IDENTITY_FIELDS
EVENT_FIELDS = {
    "request": "request",
    "acceptance": "tool_acceptance",
    "new_turn": "new_turn",
    "actual_model": "actual_model",
}
TERMINAL_LANE_STATES = {"terminal", "consumed", "integrated", "closed", "close_pending"}
ACTIVE_LANE_STATES = {"running", "awaiting_human"}


class ContinuationError(ValueError):
    """恢复现场、持久 overlay 或阶段事件不能安全核验。"""


def _unknown(value: object) -> bool:
    return value is None or (isinstance(value, str) and value.strip().lower() == UNKNOWN.lower())


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or _unknown(value):
        raise ContinuationError(f"{field} 缺失或 Unknown")
    return value


def _blocked(reason: str, *, action: str = "blocked") -> dict[str, Any]:
    return {
        "action": action,
        "can_continue": False,
        "fan_in": False,
        "request": None,
        "overlay": None,
        "reason": reason,
    }


def _mark_blocked(lane: dict[str, Any], reason: str) -> tuple[dict[str, Any], str]:
    updated = copy.deepcopy(lane)
    continuation = updated.get("continuation")
    if isinstance(continuation, dict):
        continuation["state"] = "blocked"
        continuation["reason"] = reason
    return updated, "blocked: " + reason


def _identity_matches(document: dict[str, Any], observation: dict[str, Any]) -> bool:
    return all(
        isinstance(observation.get(field), str)
        and not _unknown(observation.get(field))
        and observation[field] == document[field]
        for field in IDENTITY_FIELDS
    )


def _runtime_preflight(document: dict[str, Any], observation: dict[str, Any], signal: str) -> dict[str, Any]:
    if not isinstance(observation, dict):
        return _blocked("runtime observation 不是 object")
    if not _identity_matches(document, observation):
        return _blocked("runtime/session/coordinator 身份缺失或不匹配")
    status = observation.get("status")
    if status == "active":
        return _blocked("原回合仍 active", action="wait-for-stop")
    if _unknown(status) or status not in {"idle", "stopped"}:
        return _blocked("停止状态 Unknown 或不支持")
    if observation.get("writer_active") is not False:
        return _blocked("worker writer 未明确停止")
    if observation.get("coordinator_active") is not False:
        return _blocked("旧 coordinator 活性 Unknown 或仍 active")
    if observation.get("session_resumable") is not True:
        return _blocked("原 session 不可恢复或证据 Unknown")
    if signal not in {"PREWALK_READY", "WORKER_STOPPED"}:
        return _blocked("不支持的阶段信号")
    return {"action": "runtime-verified", "can_continue": True, "fan_in": False,
            "request": None, "overlay": None}


def _gate_preflight(document: dict[str, Any], gate_evidence: object) -> str | None:
    if not isinstance(gate_evidence, dict):
        return "适用 gate evidence 缺失"
    if gate_evidence.get("status") != "passed":
        return "适用 gate 未通过或 Unknown"
    if gate_evidence.get("work_item") != document["work_item"]:
        return "gate work_item 与 checkpoint 不匹配"
    try:
        _text(gate_evidence.get("source"), "gate_evidence.source")
        checkpoint_sha = _text(gate_evidence.get("checkpoint_sha256"),
                               "gate_evidence.checkpoint_sha256")
    except ContinuationError as error:
        return str(error)
    if checkpoint_sha != document[CHECKPOINT.FINGERPRINT_FIELD]:
        return "gate evidence 未批准当前 checkpoint 版本"
    return None


def _target_request(document: dict[str, Any], user_override: object) -> tuple[dict[str, str], str, bool] | tuple[None, str, bool]:
    default = dict(document["phase_plan"]["execution"])
    if not isinstance(user_override, dict):
        return None, "用户覆盖 readback 缺失", False
    status = user_override.get("status")
    if status not in {"unchanged", "edited"}:
        return None, "user_override.status 不支持", False
    inherited = status == "unchanged" and user_override.get("authorization") == "inherited-dispatch"
    if user_override.get("approved") is not True and not inherited:
        return None, "用户未明确批准接续", False
    if user_override.get("checkpoint_sha256") != document[CHECKPOINT.FINGERPRINT_FIELD]:
        return None, "用户覆盖针对旧 checkpoint，接续意图已失效", False
    source = _text(user_override.get("source"), "user_override.source")
    target = user_override.get("target_request", default)
    if not isinstance(target, dict) or set(target) != {"model", "effort"}:
        return None, "用户目标请求必须明确 model/effort", False
    try:
        model = _text(target.get("model"), "target_request.model")
        effort = _text(target.get("effort"), "target_request.effort")
    except ContinuationError as error:
        return None, str(error), False
    if status == "unchanged" and target != default:
        return None, "unchanged 覆盖不能改变冻结目标", False
    return {"model": model, "effort": effort}, source, status == "edited"


def _lane_preflight(document: dict[str, Any], lane: object) -> str | None:
    if not isinstance(lane, dict):
        return "lane registry readback 不是 object"
    if lane.get("lane_id") != document["lane_id"]:
        return "lane_id 与 checkpoint 不匹配"
    if lane.get("work_item") != document["work_item"]:
        return "registry work_item 与 checkpoint 不匹配"
    if lane.get("checkpoint") != document["checkpoint_path"]:
        return "registry checkpoint 坐标不匹配"
    if lane.get("checkpoint_sha256") != document[CHECKPOINT.FINGERPRINT_FIELD]:
        return "registry checkpoint 指纹不匹配"
    if lane.get("coordinator_thread_id") != document["coordinator_thread_id"]:
        return "coordinator thread 坐标不匹配"
    if lane.get("coordinator_host_id") != document["coordinator_host_id"]:
        return "coordinator host 坐标不匹配"
    registry_identity = {
        "runtime": document["runtime"],
        "worktree": document["execution_worktree"],
        "branch": document["execution_branch"],
        "base_commit": document["base_commit"],
        "head_commit": document["head_commit"],
        "checkpoint_version": document["checkpoint_version"],
        "execution_mode": document["development_mode"],
        "execution_source": document["mode_source"],
        "starting_model": document["phase_plan"]["starting"]["model"],
        "starting_effort": document["phase_plan"]["starting"]["effort"],
        "execution_model": document["phase_plan"]["execution"]["model"],
        "execution_effort": document["phase_plan"]["execution"]["effort"],
        "direct_model": document["phase_plan"]["direct"]["model"],
        "direct_effort": document["phase_plan"]["direct"]["effort"],
    }
    for field, expected in registry_identity.items():
        if lane.get(field) != expected:
            return f"registry {field} 与 checkpoint 不匹配"
    execution_phase = lane.get("execution_phase")
    continuation = lane.get("continuation")
    if execution_phase not in {"starting", "switching", "executing"}:
        return "registry execution_phase 缺失、Unknown 或不支持"
    if execution_phase == "starting" and continuation is not None:
        return "registry execution_phase 与 continuation 不一致"
    if execution_phase == "switching" and not isinstance(continuation, dict):
        return "registry switching 缺少 continuation"
    if execution_phase == "executing" and (
            not isinstance(continuation, dict)
            or continuation.get("state") not in {"started", "executing"}):
        return "registry executing 缺少已启动的新轮证据"
    state = lane.get("state")
    if state not in ACTIVE_LANE_STATES and state not in TERMINAL_LANE_STATES:
        return "lane registry state 不允许接续"
    return None


def _intent_valid(lane: dict[str, Any], intent: object) -> bool:
    if not isinstance(intent, dict):
        return False
    expected = {"lane_id", "session_id", "source_phase", "checkpoint_sha256",
                "target_phase", "target_request", CHECKPOINT.INTENT_FINGERPRINT_FIELD}
    if (set(intent) != expected or intent.get("lane_id") != lane.get("lane_id")
            or intent.get("checkpoint_sha256") != lane.get("checkpoint_sha256")):
        return False
    target = intent.get("target_request")
    if not isinstance(target, dict) or set(target) != {"model", "effort"}:
        return False
    if (intent.get("source_phase") != "starting"
            or intent.get("target_phase") != "execution"):
        return False
    try:
        _text(intent.get("session_id"), "intent.session_id")
        _text(target.get("model"), "intent.target_request.model")
        _text(target.get("effort"), "intent.target_request.effort")
    except ContinuationError:
        return False
    unsigned = {key: value for key, value in intent.items()
                if key != CHECKPOINT.INTENT_FINGERPRINT_FIELD}
    return intent[CHECKPOINT.INTENT_FINGERPRINT_FIELD] == hashlib.sha256(
        CHECKPOINT.canonical_bytes(unsigned)).hexdigest()


def _continuation_record(intent: dict[str, Any], *, source: str, edited: bool) -> dict[str, Any]:
    return {
        "intent": intent,
        "state": "prepared",
        "target_request_source": source,
        "configuration_unchanged": True,
        "user_edited": edited,
        "request": None,
        "tool_acceptance": None,
        "new_turn": None,
        "actual_model": None,
        "terminal": None,
        "fan_in": None,
    }


def _not_seen_after_marker(marker: object, observation: dict[str, Any]) -> bool:
    if not isinstance(marker, dict) or observation.get("request_seen") is not False:
        return False
    probe = observation.get("request_probe")
    if (not isinstance(probe, dict)
            or probe.get("request_id") != marker.get("request_id")
            or probe.get("status") != "not_seen"
            or probe.get("after_marker") is not True
            or probe.get("settled") is not True):
        return False
    try:
        _text(probe.get("source"), "request_probe.source")
        _text(probe.get("read_at"), "request_probe.read_at")
    except ContinuationError:
        return False
    return True


def _replacement_allowed(lane: dict[str, Any], observation: dict[str, Any]) -> bool:
    """仅允许尚未产生 runtime 请求的旧 intent 被新 checkpoint 替换。"""
    continuation = lane.get("continuation")
    if not isinstance(continuation, dict):
        return False
    state = continuation.get("state")
    if state == "prepared":
        return continuation.get("request") is None
    if state == "dispatching":
        marker = continuation.get("request")
        return (isinstance(marker, dict) and marker.get("status") == "dispatching"
                and _not_seen_after_marker(marker, observation))
    return False


def _same_event(kind: str, previous: object, event: dict[str, Any]) -> bool:
    if kind != "actual_model" or not isinstance(previous, dict):
        return previous == event
    computed = {key: value for key, value in previous.items() if key != "verification"}
    incoming = {key: value for key, value in event.items() if key != "verification"}
    return computed == incoming


def _actual_model_compatible(previous: object, event: dict[str, Any]) -> bool:
    if not isinstance(previous, dict):
        return False
    return previous.get("turn_id") == event.get("turn_id")


def _checkpoint_signal(document: dict[str, Any], observation: dict[str, Any], signal: str) -> dict[str, Any]:
    line = f"{signal} {document['lane_id']} {document['checkpoint_path']}"
    try:
        result = CHECKPOINT.evaluate_signal(document, line, observation)
    except CHECKPOINT.CheckpointError as error:
        return _blocked(f"checkpoint signal readback 失败: {error}")
    if result["action"] == "await-stop":
        return _blocked("READY 仅触发停止核验", action="await-stop")
    if result["action"] == "wait-for-stop":
        return _blocked("原回合仍 active", action="wait-for-stop")
    if result["action"] != "ready-for-coordinator":
        return _blocked(result.get("reason", "checkpoint 未达到可接续状态"))
    return {"action": "checkpoint-verified", "can_continue": True, "fan_in": False,
            "request": None, "overlay": None}


def _verified_inputs(
    document: dict[str, Any],
    lane: dict[str, Any],
    observation: dict[str, Any],
    *,
    signal: str,
    gate_evidence: dict[str, Any],
    user_override: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, str] | None, str | None, bool, dict[str, Any] | None, dict[str, Any] | None]:
    """固定顺序核验 registry → session/writer → Git/checkpoint → user → gate → intent。"""
    lane_reason = _lane_preflight(document, lane)
    if lane_reason:
        return None, None, None, False, None, _blocked(lane_reason)
    runtime = _runtime_preflight(document, observation, signal)
    if not runtime["can_continue"]:
        return None, None, None, False, None, runtime
    try:
        persisted = CHECKPOINT.read_checkpoint(
            document["checkpoint_path"],
            worktree=document["execution_worktree"],
            expected_lane=document["lane_id"],
            expected_base=document["base_commit"],
        )
    except CHECKPOINT.CheckpointError as error:
        return None, None, None, False, None, _blocked(f"Git/checkpoint readback 失败: {error}")
    if persisted != document:
        return None, None, None, False, None, _blocked("传入 checkpoint 与持久 readback 不一致")
    signal_result = _checkpoint_signal(persisted, observation, signal)
    if not signal_result["can_continue"]:
        return None, None, None, False, None, signal_result
    try:
        target, source, edited = _target_request(persisted, user_override)
    except ContinuationError as error:
        return None, None, None, False, None, _blocked(str(error))
    if target is None:
        return None, None, None, False, None, _blocked(source)
    gate_reason = _gate_preflight(persisted, gate_evidence)
    if gate_reason:
        return None, None, None, False, None, _blocked(gate_reason)
    try:
        intent = CHECKPOINT.build_continuation_intent(persisted, target_request=target)
    except CHECKPOINT.CheckpointError as error:
        return None, None, None, False, None, _blocked(f"continuation intent 无效: {error}")
    return persisted, target, source, edited, intent, None


def ready_to_send(
    lane: dict[str, Any],
    *,
    document: dict[str, Any],
    observation: dict[str, Any],
    signal: str,
    gate_evidence: dict[str, Any],
    user_override: dict[str, Any],
) -> dict[str, Any]:
    """重新核验现场，只消费已持久 readback 的 lane；不写 registry，也不调用 runtime。"""
    if lane.get("state") in TERMINAL_LANE_STATES:
        return _blocked("terminal/consumed/integrated/closed lane 不重新发送", action="terminal-deduped")
    persisted, _target, source, edited, expected_intent, failure = _verified_inputs(
        document, lane, observation, signal=signal,
        gate_evidence=gate_evidence, user_override=user_override)
    if failure is not None:
        return failure
    if persisted is None or expected_intent is None:
        return _blocked("接续现场核验不完整")
    continuation = lane.get("continuation")
    if not isinstance(continuation, dict):
        return _blocked("缺少已持久化 continuation intent")
    if not _intent_valid(lane, continuation.get("intent")) or continuation["intent"] != expected_intent:
        return _blocked("已持久化 intent 与最新 checkpoint/目标不匹配")
    state = continuation.get("state")
    if state == "prepared":
        request = {
            "request_id": "request-" + continuation["intent"][CHECKPOINT.INTENT_FINGERPRINT_FIELD],
            "intent_sha256": continuation["intent"][CHECKPOINT.INTENT_FINGERPRINT_FIELD],
            "target_request": dict(continuation["intent"]["target_request"]),
            "status": "dispatching",
            "source": source,
        }
        next_continuation = copy.deepcopy(continuation)
        next_continuation["state"] = "dispatching"
        next_continuation["request"] = request
        next_continuation["target_request_source"] = source
        next_continuation["user_edited"] = edited
        return {"action": "persist-request-before-send", "can_continue": False, "fan_in": False,
                "request": None, "overlay": {"continuation": next_continuation},
                "intent_sha256": continuation["intent"][CHECKPOINT.INTENT_FINGERPRINT_FIELD],
                "reason": "发送前先持久化 dispatching request marker"}
    if state in {"dispatching", "send-authorized"}:
        marker = continuation.get("request")
        if state == "send-authorized" and (
                not _not_seen_after_marker(marker, observation)
                or observation["request_probe"].get("after_lease") is not True
                or observation["request_probe"] == continuation.get("send_probe")):
            return _blocked("send lease 缺少新的 lease 后 settled not_seen 回读；禁止再次授权",
                            action="readback-after-lease")
        if observation.get("request_seen") is not False:
            return _blocked("dispatching request 的 runtime readback 为 Unknown/已见，禁止盲重发",
                            action="readback-after-unknown")
        if not isinstance(marker, dict):
            return _blocked("dispatching request marker 缺失，禁止发送")
        expected_intent_sha = continuation["intent"][CHECKPOINT.INTENT_FINGERPRINT_FIELD]
        if (set(marker) != {"request_id", "intent_sha256", "target_request", "status", "source"}
                or marker.get("request_id") != "request-" + expected_intent_sha
                or marker.get("intent_sha256") != expected_intent_sha
                or marker.get("target_request") != continuation["intent"]["target_request"]
                or marker.get("status") != state):
            return _blocked("dispatching request marker 与 intent 不匹配，禁止发送")
        try:
            _text(marker.get("source"), "request_marker.source")
        except ContinuationError as error:
            return _blocked(str(error))
        if state == "send-authorized":
            recovered = copy.deepcopy(continuation)
            recovered["state"] = "dispatching"
            recovered["request"]["status"] = "dispatching"
            recovered["send_probe"] = copy.deepcopy(observation["request_probe"])
            return {"action": "persist-request-before-send", "can_continue": False, "fan_in": False,
                    "request": None, "overlay": {"continuation": recovered},
                    "intent_sha256": expected_intent_sha,
                    "reason": "lease 后权威未见；先持久化恢复 overlay 并读回，再生成新 send lease"}
        if not _not_seen_after_marker(marker, observation):
            return _blocked("缺少当前 dispatching request 的发送后 readback，禁止重发",
                            action="readback-after-unknown")
        request = {
            "request_id": marker["request_id"],
            "intent_sha256": marker["intent_sha256"],
            "target_request": dict(marker["target_request"]),
        }
        lease = copy.deepcopy(continuation)
        lease["state"] = "send-authorized"
        lease["request"]["status"] = "send-authorized"
        lease["send_probe"] = copy.deepcopy(observation["request_probe"])
        return {"action": "persist-send-lease", "can_continue": False, "fan_in": False,
                "request": request, "overlay": {"continuation": lease},
                "intent_sha256": continuation["intent"][CHECKPOINT.INTENT_FINGERPRINT_FIELD],
                "reason": "发送授权只消费一次；先持久化 send lease + readback，再使用 request"}
    if state == "send-unknown":
        return _blocked("send result Unknown，必须先回读原 session", action="readback-after-unknown")
    if state in {"sent", "accepted", "started", "executing"}:
        return _blocked("接续请求已留证，禁止重复发送", action="readback")
    return _blocked("continuation intent 已阻断或终态")


def prepare_continuation(
    document: dict[str, Any],
    lane: dict[str, Any],
    observation: dict[str, Any],
    *,
    signal: str,
    gate_evidence: dict[str, Any],
    user_override: dict[str, Any],
) -> dict[str, Any]:
    """核验现场并返回 overlay；新 intent 必须由 coordinator 持久化后再发送。"""
    if lane.get("state") in TERMINAL_LANE_STATES:
        return _blocked("terminal/consumed/integrated/closed lane 不重新发送", action="terminal-deduped")
    persisted, _target, source, edited, intent, failure = _verified_inputs(
        document, lane, observation, signal=signal,
        gate_evidence=gate_evidence, user_override=user_override)
    if failure is not None:
        return failure
    assert persisted is not None and intent is not None

    existing = lane.get("continuation")
    if existing is not None:
        if not isinstance(existing, dict):
            return _blocked("已有 continuation intent 不可读")
        if existing.get("intent") != intent and _replacement_allowed(lane, observation):
            replacement = _continuation_record(intent, source=source, edited=edited)
            overlay = {
                "execution_phase": "switching",
                "checkpoint_sha256": document[CHECKPOINT.FINGERPRINT_FIELD],
                "continuation": replacement,
            }
            return {
                "action": "persist-before-send",
                "can_continue": False,
                "fan_in": False,
                "request": None,
                "overlay": overlay,
                "intent_sha256": intent[CHECKPOINT.INTENT_FINGERPRINT_FIELD],
                "reason": "旧 intent 未发送；用户确认新 checkpoint 后替换并重新持久化",
            }
        if existing.get("intent") != intent:
            return _blocked("已有 continuation intent 与当前 checkpoint/目标冲突")
        if existing.get("state") in {"terminal", "consumed", "integrated"}:
            return _blocked("已有终态 intent 不重复消费", action="terminal-deduped")
        replay = ready_to_send(
            lane, document=persisted, observation=observation, signal=signal,
            gate_evidence=gate_evidence, user_override=user_override)
        replay["reason"] = "重复 READY/恢复重入只读回既有 intent"
        return replay

    continuation = _continuation_record(intent, source=source, edited=edited)
    overlay = {
        "execution_phase": "switching",
        "checkpoint_sha256": document[CHECKPOINT.FINGERPRINT_FIELD],
        "continuation": continuation,
    }
    return {
        "action": "persist-before-send",
        "can_continue": False,
        "fan_in": False,
        "request": None,
        "overlay": overlay,
        "intent_sha256": intent[CHECKPOINT.INTENT_FINGERPRINT_FIELD],
        "reason": "已核验 stopped/Git/checkpoint/user override/gate；等待 registry persist + readback",
    }


def record_event(lane: dict[str, Any], kind: str, event: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """分别记录 request、tool acceptance、新轮和实际模型；重复相同事件幂等。"""
    if kind not in EVENT_FIELDS or not isinstance(event, dict):
        raise ContinuationError("unsupported continuation event")
    current = lane.get("continuation")
    if not isinstance(current, dict):
        raise ContinuationError("缺少 continuation intent")
    if not _intent_valid(lane, current.get("intent")):
        return _mark_blocked(lane, "continuation intent 不可核验")
    field = EVENT_FIELDS[kind]
    previous = current.get(field)
    recovery_update = False
    if previous is not None:
        if _same_event(kind, previous, event):
            return copy.deepcopy(lane), "deduplicated"
        if (kind == "request" and isinstance(previous, dict)
                and previous.get("status") in {"dispatching", "send-authorized"}
                and event.get("request_id") == previous.get("request_id")
                and event.get("intent_sha256") == previous.get("intent_sha256")
                and event.get("target_request") == previous.get("target_request")
                and event.get("status") in {"sent", UNKNOWN}):
            recovery_update = True
        elif (kind == "request" and isinstance(previous, dict)
              and previous.get("status") == UNKNOWN
              and event.get("request_id") == previous.get("request_id")
              and event.get("intent_sha256") == previous.get("intent_sha256")
              and event.get("target_request") == previous.get("target_request")
              and event.get("status") == "sent"):
            recovery_update = True
        elif (kind == "acceptance" and isinstance(previous, dict)
              and previous.get("status") == UNKNOWN
              and isinstance(current.get("request"), dict)
              and event.get("request_id") == current["request"].get("request_id")
              and event.get("status") in {"accepted", "rejected"}):
            recovery_update = True
        elif (kind == "new_turn" and isinstance(previous, dict)
              and previous.get("started") in {False, UNKNOWN, None}
              and event.get("started") is True
              and event.get("session_id") == current.get("intent", {}).get("session_id")):
            recovery_update = True
        elif kind == "actual_model" and _actual_model_compatible(previous, event):
            recovery_update = True
        else:
            return _mark_blocked(lane, "conflicting duplicate event")
    if current.get("state") in {"blocked", "terminal", "consumed", "integrated"}:
        return _mark_blocked(lane, "terminal or blocked continuation")

    updated = copy.deepcopy(lane)
    continuation = updated["continuation"]
    intent = continuation["intent"]
    try:
        _text(event.get("source"), f"{kind}.source")
    except ContinuationError as error:
        return _mark_blocked(updated, str(error))
    if kind == "request":
        previous_state = continuation.get("state")
        marker = continuation.get("request")
        if (not isinstance(marker, dict) or marker.get("status") not in {
                "dispatching", "send-authorized", UNKNOWN}
                or event.get("request_id") != marker.get("request_id")):
            return _mark_blocked(updated, "request 未匹配已持久化 dispatching marker")
        if previous_state not in {"dispatching", "send-authorized", "accepted", "started", "executing"} and not recovery_update:
            return _mark_blocked(updated, "request 不在 prepared 状态")
        if event.get("intent_sha256") != intent[CHECKPOINT.INTENT_FINGERPRINT_FIELD]:
            return _mark_blocked(updated, "request intent mismatch")
        if event.get("target_request") != intent["target_request"]:
            return _mark_blocked(updated, "request target mismatch")
        if event.get("status") not in {"sent", UNKNOWN}:
            return _mark_blocked(updated, "request status unsupported")
        continuation[field] = copy.deepcopy(event)
        if previous_state not in {"accepted", "started", "executing"}:
            continuation["state"] = "sent" if event["status"] == "sent" else "send-unknown"
    elif kind == "acceptance":
        if continuation.get("request") is None or continuation.get("state") not in {
                "sent", "send-unknown", "dispatching", "send-authorized",
                "started", "executing"}:
            return _mark_blocked(updated, "acceptance 早于 request")
        if (not isinstance(continuation["request"], dict)
                or event.get("request_id") != continuation["request"].get("request_id")):
            return _mark_blocked(updated, "acceptance request_id 不匹配")
        accepted = event.get("accepted")
        status = event.get("status")
        if status not in {"accepted", "rejected", UNKNOWN}:
            return _mark_blocked(updated, "acceptance status unsupported")
        if ((status == "accepted" and accepted is not True)
                or (status == "rejected" and accepted is not False)
                or (status == UNKNOWN and accepted is not None)):
            return _mark_blocked(updated, "acceptance accepted/status mismatch")
        previous_state = continuation.get("state")
        if status == "rejected" and previous_state in {"started", "executing"}:
            return _mark_blocked(updated, "新轮已启动后不接受 rejected 回读")
        continuation[field] = copy.deepcopy(event)
        if status == "rejected":
            continuation["state"] = "blocked"
            continuation["reason"] = "runtime rejected continuation request"
        elif status == UNKNOWN and previous_state not in {"started", "executing"}:
            continuation["state"] = "send-unknown"
        elif status == "accepted" and previous_state not in {"started", "executing"}:
            continuation["state"] = "accepted"
    elif kind == "new_turn":
        if not isinstance(continuation.get("request"), dict):
            return _mark_blocked(updated, "new turn 早于 request")
        try:
            request_id = _text(event.get("request_id"), "new_turn.request_id")
        except ContinuationError as error:
            return _mark_blocked(updated, str(error))
        if (event.get("session_id") != intent["session_id"]
                or request_id != continuation["request"].get("request_id")):
            return _mark_blocked(updated, "new turn 未证明原 session 启动")
        continuation[field] = copy.deepcopy(event)
        if event.get("started") is True:
            try:
                _text(event.get("turn_id"), "new_turn.turn_id")
            except ContinuationError as error:
                return _mark_blocked(updated, str(error))
            continuation["state"] = "started"
            updated["execution_phase"] = "executing"
        elif event.get("started") in {False, UNKNOWN, None}:
            acceptance = continuation.get("tool_acceptance")
            if isinstance(acceptance, dict) and acceptance.get("status") == "accepted":
                continuation["state"] = "accepted"
            elif (isinstance(acceptance, dict) and acceptance.get("status") == UNKNOWN
                  or continuation["request"].get("status") == UNKNOWN):
                continuation["state"] = "send-unknown"
            else:
                continuation["state"] = "sent"
        else:
            return _mark_blocked(updated, "new turn started 状态不支持")
    else:
        new_turn = continuation.get("new_turn")
        if not isinstance(new_turn, dict) or new_turn.get("started") is not True:
            return _mark_blocked(updated, "actual model 早于新轮证据")
        try:
            turn_id = _text(event.get("turn_id"), "actual_model.turn_id")
            _text(event.get("readback_at"), "actual_model.readback_at")
        except ContinuationError as error:
            return _mark_blocked(updated, str(error))
        if turn_id != new_turn.get("turn_id"):
            return _mark_blocked(updated, "actual model 不属于当前新轮")
        prior = continuation.get(field) if recovery_update and isinstance(continuation.get(field), dict) else {}
        values = {
            key: (prior.get(key) if _unknown(event.get(key)) and not _unknown(prior.get(key))
                  else event.get(key))
            for key in ("model", "effort", "source")
        }
        model = values["model"]
        effort = values["effort"]
        source = values["source"]
        if any(_unknown(value) for value in (model, effort, source)):
            verification = UNKNOWN
        elif {"model": model, "effort": effort} == intent["target_request"]:
            verification = "passed"
        else:
            verification = "mismatch"
        continuation[field] = {**copy.deepcopy(prior), **copy.deepcopy(event), **values,
                               "verification": verification}
        continuation["state"] = "executing"
        if verification == "mismatch":
            continuation["reason"] = "实际 model/effort 与目标请求不匹配；保留运行现场，不阻断既有交付 fan-in"
    return updated, "recorded"


def record_terminal(lane: dict[str, Any], event: dict[str, Any]) -> tuple[dict[str, Any], str]:
    if not isinstance(event, dict) or not _text(event.get("terminal_id"), "terminal_id"):
        raise ContinuationError("terminal event 缺少稳定 terminal_id")
    updated = copy.deepcopy(lane)
    continuation = updated.get("continuation")
    outcome = event.get("outcome")
    output_mode = lane.get("output_mode")
    if outcome not in {"completed", "blocked"}:
        return _mark_blocked(updated, "terminal outcome 不支持")
    if outcome == "completed" and output_mode not in {"commit", "artifact", "checks", "verdict"}:
        return _mark_blocked(updated, "completed terminal 缺少合法 output_mode")
    if outcome == "completed" and event.get("output_mode") != output_mode:
        return _mark_blocked(updated, "terminal output_mode 与 lane 不匹配")
    if outcome == "blocked":
        try:
            _text(event.get("reason"), "terminal.reason")
        except ContinuationError as error:
            return _mark_blocked(updated, str(error))
        previous = updated.get("terminal")
        if previous is not None:
            return (updated, "deduplicated") if previous == event else (updated, "blocked: conflicting terminal event")
        if updated.get("fan_in") is not None:
            return updated, "blocked: fan-in already recorded"
        updated["terminal"] = copy.deepcopy(event)
        if isinstance(continuation, dict):
            continuation["state"] = "blocked"
            continuation["reason"] = event["reason"]
        updated["state"] = "blocked"
        return updated, "recorded"
    actual_model = continuation.get("actual_model") if isinstance(continuation, dict) else None
    new_turn = continuation.get("new_turn") if isinstance(continuation, dict) else None
    if (not isinstance(continuation, dict) or continuation.get("state") != "executing"
            or not isinstance(new_turn, dict) or new_turn.get("started") is not True
            or not isinstance(actual_model, dict)):
        return _mark_blocked(updated, "terminal 缺少新轮与实际 model/effort 回读")
    request = continuation.get("request")
    if not isinstance(request, dict):
        return _mark_blocked(updated, "terminal 缺少接续 request 证据")
    try:
        terminal_session = _text(event.get("session_id"), "terminal.session_id")
        terminal_request = _text(event.get("request_id"), "terminal.request_id")
        terminal_turn = _text(event.get("turn_id"), "terminal.turn_id")
    except ContinuationError as error:
        return _mark_blocked(updated, str(error))
    if (terminal_session != continuation["intent"]["session_id"]
            or terminal_request != request.get("request_id")
            or terminal_turn != new_turn.get("turn_id")):
        return _mark_blocked(updated, "terminal 身份不匹配当前原 session/request/turn")
    previous = updated.get("terminal")
    if previous is not None:
        return (updated, "deduplicated") if previous == event else (updated, "blocked: conflicting terminal event")
    fan_in = updated.get("fan_in")
    if fan_in is not None:
        return updated, "blocked: fan-in already recorded"
    updated["terminal"] = copy.deepcopy(event)
    updated["state"] = "terminal"
    return updated, "recorded"


def record_fan_in(lane: dict[str, Any], *, terminal_id: str, outcome: str) -> tuple[dict[str, Any], str]:
    if outcome not in {"consumed", "integrated"}:
        raise ContinuationError("fan-in outcome unsupported")
    updated = copy.deepcopy(lane)
    continuation = updated.get("continuation")
    if (not isinstance(continuation, dict)
            or continuation.get("state") in {"blocked", "consumed", "integrated", "terminal"}):
        return updated, "blocked: continuation is not consumable"
    terminal = updated.get("terminal")
    if not isinstance(terminal, dict) or terminal.get("terminal_id") != terminal_id:
        return updated, "blocked: terminal evidence mismatch"
    if terminal.get("outcome") != "completed":
        return updated, "blocked: blocked terminal cannot fan-in"
    expected = {"commit": "integrated", "artifact": "consumed", "checks": "consumed", "verdict": "consumed"}
    output_mode = updated.get("output_mode")
    if output_mode not in expected or outcome != expected[output_mode]:
        return updated, "blocked: output_mode/fan-in outcome mismatch"
    if terminal.get("output_mode") != output_mode:
        return updated, "blocked: terminal output_mode mismatch"
    event = {"terminal_id": terminal_id, "outcome": outcome}
    previous = updated.get("fan_in")
    if previous is not None:
        return (updated, "deduplicated") if previous == event else (updated, "blocked: conflicting fan-in")
    updated["fan_in"] = event
    updated["state"] = outcome
    return updated, "recorded"
