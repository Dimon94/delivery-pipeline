#!/usr/bin/env python3
"""Orca 本地 worker readback 与 FIFO settlement 的机械核验。"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

from registry_overlay import (
    OverlayError,
    bind_attempt,
    empty_overlay,
    record_mutation,
    record_observation,
    validate_markers,
)

STARTUP_OPERATION = "worker-start"
SETTLEMENT_OPERATION = "settlement"
MESSAGE_TYPES = {
    "status",
    "dispatch",
    "worker_done",
    "merge_ready",
    "escalation",
    "handoff",
    "decision_gate",
    "question",
    "heartbeat",
}
NEXT_ACTIONS = {"reuse", "retain", "release", "wait", "none"}


class WorkerLifecycleError(ValueError):
    """caller-declared native readback 缺失、冲突或不能安全交接。"""


def _known_text(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value.strip().lower() in {"none", "null", "unknown"}
    ):
        raise WorkerLifecycleError(f"{field} 必须是已知非空文本")
    return value.strip()


def _known_bool(value: Any, field: str) -> bool:
    if type(value) is not bool:
        raise WorkerLifecycleError(f"{field} 必须是 boolean")
    return value


def _mapping(value: Any, field: str, fields: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise WorkerLifecycleError(f"{field} 必须精确包含 {sorted(fields)}")
    return value


def _readable_absolute(value: Any, field: str) -> str:
    path = Path(_known_text(value, field)).expanduser()
    if not path.is_absolute():
        raise WorkerLifecycleError(f"{field} 必须是绝对路径")
    try:
        path = path.resolve(strict=True)
        if not path.is_file():
            raise WorkerLifecycleError(f"{field} 必须是文件")
        path.read_bytes()
    except (OSError, RuntimeError) as error:
        raise WorkerLifecycleError(f"{field} 不可读: {error}") from error
    return str(path)


def _read_json_object(value: Any, field: str) -> tuple[str, dict[str, Any]]:
    path = _readable_absolute(value, field)
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise WorkerLifecycleError(f"{field} 不是可读 JSON object: {error}") from error
    if not isinstance(document, dict):
        raise WorkerLifecycleError(f"{field} 必须包含 JSON object")
    return path, document


def _at(value: Any, keys: tuple[str, ...], field: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            raise WorkerLifecycleError(f"{field} 缺少 native 字段 {'.'.join(keys)}")
        current = current[key]
    return current


def _worktree(value: Any, field: str) -> dict[str, str]:
    result = _mapping(
        value,
        field,
        {"path", "branch", "head", "base", "selector", "host", "dirty_fingerprint"},
    )
    path = Path(_known_text(result["path"], f"{field}.path")).expanduser()
    if not path.is_absolute():
        raise WorkerLifecycleError(f"{field}.path 必须是绝对路径")
    try:
        path = path.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise WorkerLifecycleError(f"{field}.path 不可解析: {error}") from error
    if not path.is_dir():
        raise WorkerLifecycleError(f"{field}.path 必须是目录")
    return {
        "path": str(path),
        "branch": _known_text(result["branch"], f"{field}.branch"),
        "head": _known_text(result["head"], f"{field}.head"),
        "base": _known_text(result["base"], f"{field}.base"),
        "selector": _known_text(result["selector"], f"{field}.selector"),
        "host": _known_text(result["host"], f"{field}.host"),
        "dirty_fingerprint": _known_text(
            result["dirty_fingerprint"], f"{field}.dirty_fingerprint"
        ),
    }


def _launch_fields(value: Any, field: str) -> dict[str, str]:
    launch = _mapping(value, field, {"agent", "model", "effort"})
    return {
        name: _known_text(launch[name], f"{field}.{name}")
        for name in ("agent", "model", "effort")
    }


def _native_identity(
    value: Any,
    fields: dict[str, tuple[str, ...]],
    identity: dict[str, str],
    source: str,
) -> None:
    for native_name, keys in fields.items():
        if (
            _known_text(_at(value, keys, source), f"{source}.{native_name}")
            != identity[native_name]
        ):
            raise WorkerLifecycleError(
                f"{source} {native_name} 与 Dispatch identity 不匹配"
            )


def _previous_attempt(
    value: Any, identity: dict[str, Any], retry_of: Any
) -> dict[str, Any] | None:
    if identity["attempt_index"] == 0:
        if value is not None or retry_of is not None:
            raise WorkerLifecycleError(
                "首个 Dispatch attempt 必须没有 previous_attempt/retryOfDispatchId"
            )
        return None
    if not isinstance(value, dict):
        raise WorkerLifecycleError(
            "retry attempt 必须提供 previous_attempt native readback"
        )
    previous = _mapping(
        value,
        "previous_attempt",
        {"run_id", "task_id", "dispatch_id", "attempt_index", "source"},
    )
    previous_identity = {
        field: _known_text(previous[field], f"previous_attempt.{field}")
        for field in ("run_id", "task_id", "dispatch_id")
    }
    previous_index = previous["attempt_index"]
    if type(previous_index) is not int or previous_index < 0:
        raise WorkerLifecycleError("previous_attempt.attempt_index 必须是非负整数")
    if (
        previous_identity["run_id"] != identity["run_id"]
        or previous_identity["task_id"] != identity["task_id"]
    ):
        raise WorkerLifecycleError("previous_attempt 未绑定当前 Run/Task")
    if previous_index + 1 != identity["attempt_index"]:
        raise WorkerLifecycleError("retry attempt_index 必须连续继承上一 attempt")
    if (
        _known_text(retry_of, "launch.effective_source.retryOfDispatchId")
        != previous_identity["dispatch_id"]
    ):
        raise WorkerLifecycleError("retryOfDispatchId 与 previous_attempt 不一致")
    source, document = _read_json_object(previous["source"], "previous_attempt.source")
    _native_identity(
        document,
        {
            "run_id": ("result", "dispatch", "runId"),
            "task_id": ("result", "dispatch", "taskId"),
            "dispatch_id": ("result", "dispatch", "id"),
        },
        previous_identity,
        "previous_attempt.source",
    )
    return {
        **previous_identity,
        "attempt_index": previous_index,
        "source": source,
    }


def _null_launch_fields(value: Any, field: str) -> None:
    launch = _mapping(value, field, {"agent", "model", "effort"})
    if any(launch[name] is not None for name in ("agent", "model", "effort")):
        raise WorkerLifecycleError(
            f"{field} 必须全部为 null（agent-argv transport 不经 worker-start 传 model）"
        )


def _terminal_source(
    value: Any, identity: dict[str, Any], effective: dict[str, str]
) -> str:
    source, readback = _read_json_object(value, "launch.terminal_source")
    handle = _at(readback, ("result", "terminal", "handle"), "launch.terminal_source")
    if handle != identity["terminal_handle"]:
        raise WorkerLifecycleError("launch.terminal_source 与 Dispatch terminal 不匹配")
    text = json.dumps(readback, ensure_ascii=False)
    model_id = effective["model"].rsplit("/", 1)[-1]
    if model_id not in text:
        raise WorkerLifecycleError("launch.terminal_source 未包含 effective model")
    if f"[{effective['effort']}]" not in text and f"thinking {effective['effort']}" not in text:
        raise WorkerLifecycleError("launch.terminal_source 未包含 effective effort")
    return source


def _launch(
    value: Any, identity: dict[str, Any], previous_attempt: Any
) -> tuple[dict[str, Any], str]:
    if not isinstance(value, dict):
        raise WorkerLifecycleError("launch 必须是 object")
    transport = _known_text(value.get("transport"), "launch.transport")
    fields = {"transport", "requested", "effective", "requested_source", "effective_source"}
    if transport == "agent-argv":
        fields.add("terminal_source")
    elif transport != "launch-preferences":
        raise WorkerLifecycleError(f"launch.transport 未知: {transport}")
    result = _mapping(value, "launch", fields)
    requested = _launch_fields(result["requested"], "launch.requested")
    effective = _launch_fields(result["effective"], "launch.effective")
    requested_source, receipt = _read_json_object(
        result["requested_source"], "launch.requested_source"
    )
    effective_source, readback = _read_json_object(
        result["effective_source"], "launch.effective_source"
    )
    if requested_source == effective_source:
        raise WorkerLifecycleError(
            "requested/effective launch 必须来自独立 receipt/readback"
        )

    _native_identity(
        receipt,
        {
            "run_id": ("result", "runId"),
            "task_id": ("result", "taskId"),
            "dispatch_id": ("result", "dispatchId"),
        },
        identity,
        "launch.requested_source",
    )
    _native_identity(
        readback,
        {
            "run_id": ("result", "dispatch", "runId"),
            "task_id": ("result", "dispatch", "taskId"),
            "dispatch_id": ("result", "dispatch", "id"),
        },
        identity,
        "launch.effective_source",
    )
    retry_of = _at(
        readback,
        ("result", "dispatch", "retryOfDispatchId"),
        "launch.effective_source",
    )
    _previous_attempt(previous_attempt, identity, retry_of)
    _null_check = (
        _null_launch_fields if transport == "agent-argv" else _launch_fields
    )
    native_requested = _null_check(
        _at(receipt, ("result", "launch", "requested"), "launch.requested_source"),
        "native launch.requested",
    )
    native_effective = _null_check(
        _at(
            readback,
            ("result", "worker", "startOptions", "launch", "effective"),
            "launch.effective_source",
        ),
        "native launch.effective",
    )
    if transport == "launch-preferences":
        if requested != native_requested:
            raise WorkerLifecycleError("launch.requested 与 native receipt 不一致")
        if effective != native_effective:
            raise WorkerLifecycleError("launch.effective 与独立 native readback 不一致")
    if requested["agent"] != effective["agent"]:
        raise WorkerLifecycleError("requested/effective agent 不一致；禁止静默映射")
    for field in ("model", "effort"):
        if requested[field] != effective[field]:
            raise WorkerLifecycleError(
                f"requested/effective {field} 不一致；禁止静默 fallback"
            )
    mutation_request_id = _known_text(
        _at(
            receipt,
            ("result", "mutation", "requestId"),
            "launch.requested_source",
        ),
        "native worker-start mutation.requestId",
    )
    terminal_source = None
    if transport == "agent-argv":
        terminal_source = _terminal_source(
            result["terminal_source"], identity, effective
        )
    return {
        "transport": transport,
        "requested": requested,
        "effective": effective,
        "requested_source": requested_source,
        "effective_source": effective_source,
        "terminal_source": terminal_source,
    }, mutation_request_id


def _setup(value: Any) -> dict[str, str]:
    result = _mapping(
        value,
        "setup",
        {"requested", "effective", "requested_source", "effective_source"},
    )
    requested_source, receipt = _read_json_object(
        result["requested_source"], "setup.requested_source"
    )
    effective_source, readback = _read_json_object(
        result["effective_source"], "setup.effective_source"
    )
    if requested_source == effective_source:
        raise WorkerLifecycleError(
            "requested/effective setup 必须来自独立 receipt/readback"
        )
    requested = _known_text(result["requested"], "setup.requested")
    effective = _known_text(result["effective"], "setup.effective")
    native_requested = _known_text(
        _at(receipt, ("result", "setup", "requested"), "setup.requested_source"),
        "native setup.requested",
    )
    native_effective = _known_text(
        _at(
            readback,
            ("result", "worker", "startOptions", "setup"),
            "setup.effective_source",
        ),
        "native setup.effective",
    )
    if requested != native_requested:
        raise WorkerLifecycleError("setup.requested 与 native receipt 不一致")
    if effective != native_effective:
        raise WorkerLifecycleError("setup.effective 与独立 native readback 不一致")
    return {
        "requested": requested,
        "effective": effective,
        "requested_source": requested_source,
        "effective_source": effective_source,
    }


def _evidence(value: Any) -> dict[str, str]:
    result = _mapping(value, "evidence", {"source", "observed_at", "reference"})
    return {
        "source": _readable_absolute(result["source"], "evidence.source"),
        "observed_at": _known_text(result["observed_at"], "evidence.observed_at"),
        "reference": _readable_absolute(result["reference"], "evidence.reference"),
    }


def _identity(value: Any) -> dict[str, Any]:
    result = _mapping(
        value,
        "identity",
        {
            "run_id",
            "task_id",
            "dispatch_id",
            "terminal_handle",
            "worktree_selector",
            "execution_host",
            "attempt_index",
        },
    )
    identity: dict[str, Any] = {
        field: _known_text(result[field], f"identity.{field}")
        for field in (
            "run_id",
            "task_id",
            "dispatch_id",
            "terminal_handle",
            "worktree_selector",
            "execution_host",
        )
    }
    attempt_index = result["attempt_index"]
    if type(attempt_index) is not int or attempt_index < 0:
        raise WorkerLifecycleError("identity.attempt_index 必须是非负整数")
    identity["attempt_index"] = attempt_index
    return identity


def validate_startup(request: Any) -> dict[str, Any]:
    """核验 worker-start 之后的完整 native receipt/readback。"""
    if not isinstance(request, dict):
        raise WorkerLifecycleError("startup request 必须是 object")
    required = {
        "operation",
        "identity",
        "previous_attempt",
        "integration_base",
        "source_before",
        "source_after",
        "integration_worktree",
        "execution_worktree",
        "launch",
        "setup",
        "evidence",
    }
    if set(request) != required:
        raise WorkerLifecycleError(f"startup request 字段必须精确为 {sorted(required)}")
    if request["operation"] != STARTUP_OPERATION:
        raise WorkerLifecycleError("startup operation 必须为 worker-start")

    identity = _identity(request["identity"])
    launch, mutation_request_id = _launch(
        request["launch"], identity, request["previous_attempt"]
    )
    integration_base = _known_text(request["integration_base"], "integration_base")
    source_before = _worktree(request["source_before"], "source_before")
    source_after = _worktree(request["source_after"], "source_after")
    integration = _worktree(request["integration_worktree"], "integration_worktree")
    execution = _worktree(request["execution_worktree"], "execution_worktree")
    if source_before != source_after:
        raise WorkerLifecycleError("Source Worktree 前后 readback 不一致；禁止继续")
    if integration["path"] == source_before["path"]:
        raise WorkerLifecycleError("Map Integration Worktree 不得复用 Source Worktree")
    if integration["head"] != integration_base:
        raise WorkerLifecycleError("Map Integration Worktree HEAD 与冻结基线不一致")
    if execution["path"] in {source_before["path"], integration["path"]}:
        raise WorkerLifecycleError("Execution Worktree 必须与 Source/Integration 隔离")
    if execution["branch"] in {source_before["branch"], integration["branch"]}:
        raise WorkerLifecycleError("Execution Worktree 必须使用隔离 branch")
    if execution["base"] != integration_base:
        raise WorkerLifecycleError(
            "Execution Worktree base 不是冻结的 Integration HEAD"
        )
    if execution["head"] != integration_base:
        raise WorkerLifecycleError(
            "Execution Worktree 初始 HEAD 不是冻结的 Integration HEAD"
        )
    if execution["selector"] != identity["worktree_selector"]:
        raise WorkerLifecycleError("worktree selector 与 Dispatch identity 不一致")
    if execution["host"] != identity["execution_host"]:
        raise WorkerLifecycleError("execution host 与 Dispatch identity 不一致")
    setup = _setup(request["setup"])
    evidence = _evidence(request["evidence"])
    if identity["terminal_handle"] == "coordinator":
        raise WorkerLifecycleError("coordinator terminal 不能冒充 worker terminal")

    return {
        "status": "ready",
        "operation": STARTUP_OPERATION,
        "authority": False,
        "identity": identity,
        "integration_base": integration_base,
        "source_worktree": source_after,
        "integration_worktree": integration,
        "execution_worktree": execution,
        "launch": launch,
        "setup": setup,
        "mutation_request_id": mutation_request_id,
        "evidence": evidence,
        "project_lane_transition": "unchanged",
    }


def _bindings(value: Any, run_id: str) -> dict[str, dict[str, str | int]]:
    if not isinstance(value, list) or not value:
        raise WorkerLifecycleError("bindings 必须是非空列表")
    normalized: dict[str, dict[str, str | int]] = {}
    dispatches: set[tuple[str, str]] = set()
    for index, binding in enumerate(value):
        result = _mapping(
            binding,
            f"bindings[{index}]",
            {"run_id", "task_id", "dispatch_id", "terminal_handle"},
        )
        run_id_value = _known_text(result["run_id"], f"bindings[{index}].run_id")
        if run_id_value != run_id:
            raise WorkerLifecycleError(f"bindings[{index}] Run identity 不匹配")
        task_id = _known_text(result["task_id"], f"bindings[{index}].task_id")
        dispatch_id = _known_text(
            result["dispatch_id"], f"bindings[{index}].dispatch_id"
        )
        terminal_handle = _known_text(
            result["terminal_handle"], f"bindings[{index}].terminal_handle"
        )
        if terminal_handle in normalized:
            raise WorkerLifecycleError("bindings 含重复 terminal handle")
        dispatch_key = (task_id, dispatch_id)
        if dispatch_key in dispatches:
            raise WorkerLifecycleError("bindings 含重复 Task/Dispatch")
        dispatches.add(dispatch_key)
        normalized[terminal_handle] = {
            "run_id": run_id_value,
            "task_id": task_id,
            "dispatch_id": dispatch_id,
            "terminal_handle": terminal_handle,
        }
    return normalized


def _message(
    value: Any,
    index: int,
    run_id: str,
    bindings: dict[str, dict[str, str | int]],
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise WorkerLifecycleError(f"batch[{index}] 必须是 object")
    required = {
        "message_id",
        "run_id",
        "from_handle",
        "subject",
        "body",
        "type",
        "payload",
    }
    if set(value) != required:
        raise WorkerLifecycleError(f"batch[{index}] 字段必须精确为 {sorted(required)}")
    message_id = _known_text(value["message_id"], f"batch[{index}].message_id")
    if _known_text(value["run_id"], f"batch[{index}].run_id") != run_id:
        raise WorkerLifecycleError(f"batch[{index}] Run identity 不匹配")
    from_handle = _known_text(value["from_handle"], f"batch[{index}].from_handle")
    binding = bindings.get(from_handle)
    if binding is None:
        # 原生 ask 使用稳定 Dispatch sender；仍只接受当前 fleet 中唯一的 binding。
        matches = [value for value in bindings.values()
                   if from_handle == "dispatch:" + str(value["dispatch_id"])]
        if len(matches) == 1:
            binding = matches[0]
    if binding is None or binding["run_id"] != run_id:
        raise WorkerLifecycleError(f"batch[{index}] 未绑定已知 Dispatch terminal")
    message_type = _known_text(value["type"], f"batch[{index}].type")
    if message_type not in MESSAGE_TYPES:
        raise WorkerLifecycleError(f"batch[{index}].type 不支持: {message_type}")
    payload = value["payload"]
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise WorkerLifecycleError(f"batch[{index}].payload 必须是 object 或 null")
    if message_type == "worker_done":
        expected = {"task_id", "dispatch_id", "outcome"}
        if set(payload) == {"taskId", "dispatchId", "outcome"}:
            payload = {
                "task_id": payload["taskId"],
                "dispatch_id": payload["dispatchId"],
                "outcome": payload["outcome"],
            }
        if set(payload) != expected:
            raise WorkerLifecycleError(
                f"batch[{index}].worker_done payload 必须精确包含 {sorted(expected)}"
            )
        if (
            _known_text(payload["task_id"], f"batch[{index}].task_id")
            != binding["task_id"]
        ):
            raise WorkerLifecycleError("worker_done Task identity 不匹配")
        if (
            _known_text(payload["dispatch_id"], f"batch[{index}].dispatch_id")
            != binding["dispatch_id"]
        ):
            raise WorkerLifecycleError("worker_done Dispatch identity 不匹配")
        if _known_text(payload["outcome"], f"batch[{index}].outcome") not in {
            "succeeded",
            "failed",
        }:
            raise WorkerLifecycleError("worker_done outcome 必须为 succeeded/failed")
    body = value["body"]
    if body is None:
        body = ""
    if not isinstance(body, str):
        raise WorkerLifecycleError(f"batch[{index}].body 必须是 string 或 null")
    return {
        "message_id": message_id,
        "run_id": run_id,
        "from_handle": from_handle,
        "binding": copy.deepcopy(binding),
        "subject": _known_text(value["subject"], f"batch[{index}].subject"),
        "body": body,
        "type": message_type,
        "payload": copy.deepcopy(payload),
    }


def _native_delivery(
    reference: str,
    run_id: str,
    bindings: dict[str, dict[str, str | int]],
    delivery_id: str,
    batch: list[dict[str, Any]],
) -> str:
    _, document = _read_json_object(reference, "evidence.reference")
    result = _at(document, ("result",), "evidence.reference")
    if not isinstance(result, dict):
        raise WorkerLifecycleError("evidence.reference.result 必须是 object")
    if _known_text(result.get("runId"), "native Delivery.runId") != run_id:
        raise WorkerLifecycleError("native Delivery Run identity 不匹配")
    if (
        _known_text(result.get("deliveryId"), "native Delivery.deliveryId")
        != delivery_id
    ):
        raise WorkerLifecycleError("native Delivery identity 不匹配")
    native_messages = result.get("messages")
    if not isinstance(native_messages, list) or len(native_messages) != len(batch):
        raise WorkerLifecycleError("native Delivery 未包含声明的完整 FIFO batch")
    normalized_messages: list[dict[str, Any]] = []
    for index, message in enumerate(native_messages):
        if not isinstance(message, dict):
            raise WorkerLifecycleError(f"native messages[{index}] 必须是 object")
        payload = message.get("payload")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError as error:
                raise WorkerLifecycleError(
                    f"native messages[{index}].payload 不是 JSON object"
                ) from error
        normalized_messages.append(
            _message(
                {
                    "message_id": message.get("id"),
                    "run_id": message.get("run_id"),
                    "from_handle": message.get("from_handle"),
                    "subject": message.get("subject"),
                    "body": message.get("body"),
                    "type": message.get("type"),
                    "payload": payload,
                },
                index,
                run_id,
                bindings,
            )
        )
    if normalized_messages != batch:
        raise WorkerLifecycleError("声明 batch 与 native Delivery 的顺序或内容不一致")
    return _known_text(
        _at(document, ("result", "mutation", "requestId"), "evidence.reference"),
        "native check mutation.requestId",
    )


def _fleet_row(value: Any, index: int, run_id: str, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise WorkerLifecycleError(f"{field}.rows[{index}] 必须是 object")
    projection = value.get("projection")
    if not isinstance(projection, dict):
        projection = value

    def pick(snake: str, camel: str) -> Any:
        return projection.get(
            snake, projection.get(camel, value.get(snake, value.get(camel)))
        )

    row_run = pick("run_id", "runId")
    if _known_text(row_run, f"{field}.rows[{index}].run_id") != run_id:
        raise WorkerLifecycleError(f"{field} row Run identity 不匹配")
    worker_state = pick("worker_state", "workerState")
    dispatch_status = pick("dispatch_status", "dispatchStatus")
    terminal_state = pick("terminal_state", "terminalState")
    for name, field_value in (
        ("workerState", worker_state),
        ("dispatchStatus", dispatch_status),
        ("terminalState", terminal_state),
    ):
        _known_text(field_value, f"{field}.rows[{index}].{name}")
    next_action = projection.get("next_action", projection.get("nextAction"))
    if isinstance(next_action, dict):
        next_action = next_action.get("kind")
    if not isinstance(next_action, str) or not next_action.strip():
        raise WorkerLifecycleError(f"{field}.rows[{index}].nextAction 必须是非空文本")
    next_action = next_action.strip()
    if next_action not in NEXT_ACTIONS:
        raise WorkerLifecycleError(f"{field} nextAction 不支持: {next_action}")
    if next_action == "none":
        next_action = "retain" if terminal_state == "retained" else "wait"
    return {
        "run_id": row_run,
        "task_id": _known_text(
            pick("task_id", "taskId"), f"{field}.rows[{index}].taskId"
        ),
        "dispatch_id": _known_text(
            pick("dispatch_id", "dispatchId"), f"{field}.rows[{index}].dispatchId"
        ),
        "terminal_handle": _known_text(
            pick("terminal_handle", "agentTerminalHandle"),
            f"{field}.rows[{index}].agentTerminalHandle",
        ),
        "worker_state": worker_state,
        "dispatch_status": dispatch_status,
        "terminal_state": terminal_state,
        "next_action": next_action,
    }


def _worker_list(
    value: Any,
    field: str,
    identity: dict[str, Any],
    bindings: dict[str, dict[str, str | int]],
) -> dict[str, Any]:
    result = _mapping(
        value, field, {"source", "reference", "run_id", "fleet_verdict", "rows"}
    )
    if result["source"] != "worker-list":
        raise WorkerLifecycleError(
            f"{field} fleet verdict 必须来自 worker-list，不能来自 PTY observation"
        )
    if _known_text(result["run_id"], f"{field}.run_id") != identity["run_id"]:
        raise WorkerLifecycleError(f"{field} Run identity 不匹配")
    if not _known_bool(result["fleet_verdict"], f"{field}.fleet_verdict"):
        raise WorkerLifecycleError(f"{field} 未明确为 fleet verdict")
    rows = result["rows"]
    if not isinstance(rows, list) or not rows:
        raise WorkerLifecycleError(f"{field}.rows 必须是非空列表")
    normalized = [
        _fleet_row(row, index, identity["run_id"], field)
        for index, row in enumerate(rows)
    ]
    targets: list[dict[str, Any]] = []
    for binding in bindings.values():
        matched = [
            row
            for row in normalized
            if row["task_id"] == binding["task_id"]
            and row["dispatch_id"] == binding["dispatch_id"]
            and row["terminal_handle"] == binding["terminal_handle"]
        ]
        if len(matched) != 1:
            raise WorkerLifecycleError(
                f"{field} 未唯一绑定 Task/Dispatch/terminal: {binding['dispatch_id']}"
            )
        targets.append(matched[0])

    reference, document = _read_json_object(result["reference"], f"{field}.reference")
    native_rows = _at(document, ("result", "workers"), f"{field}.reference")
    if not isinstance(native_rows, list):
        raise WorkerLifecycleError(f"{field}.reference 缺少 native workers 列表")
    for index, row in enumerate(native_rows):
        projection = row.get("projection") if isinstance(row, dict) else None
        liveness = projection.get("liveness") if isinstance(projection, dict) else None
        verdict = liveness.get("verdict") if isinstance(liveness, dict) else None
        verdict = _known_text(
            verdict, f"{field}.reference.workers[{index}].projection.liveness.verdict"
        )
        if verdict not in {"live", "exited", "unverifiable"}:
            raise WorkerLifecycleError(
                f"{field}.reference worker liveness verdict 不支持: {verdict}"
            )
        if verdict == "unverifiable":
            raise WorkerLifecycleError(
                f"{field}.reference worker liveness 为 unverifiable；保留现场"
            )
    native_normalized = [
        _fleet_row(row, index, identity["run_id"], f"native {field}")
        for index, row in enumerate(native_rows)
    ]
    if normalized != native_normalized:
        raise WorkerLifecycleError(
            f"{field}.rows 与 native worker-list readback 不一致"
        )
    primary = [row for row in targets if row["dispatch_id"] == identity["dispatch_id"]]
    if len(primary) != 1:
        raise WorkerLifecycleError(f"{field} 未唯一绑定当前 lane identity")
    return {
        "reference": reference,
        "rows": normalized,
        "targets": targets,
        "target": primary[0],
    }


def _native_ack(
    value: Any, identity: dict[str, str], delivery_id: str
) -> tuple[str, str]:
    result = _mapping(value, "ack", {"delivery_id", "source"})
    if _known_text(result["delivery_id"], "ack.delivery_id") != delivery_id:
        raise WorkerLifecycleError("ack Delivery identity 不匹配")
    source, document = _read_json_object(result["source"], "ack.source")
    native = _at(document, ("result",), "ack.source")
    if not isinstance(native, dict):
        raise WorkerLifecycleError("ack.source.result 必须是 object")
    if _known_text(native.get("runId"), "native ack.runId") != identity["run_id"]:
        raise WorkerLifecycleError("native ack Run identity 不匹配")
    if (
        _known_text(native.get("acknowledged"), "native ack.acknowledged")
        != delivery_id
    ):
        raise WorkerLifecycleError("native ack 未确认当前 Delivery")
    request_id = _known_text(
        _at(document, ("result", "mutation", "requestId"), "ack.source"),
        "native ack mutation.requestId",
    )
    return source, request_id


def validate_settlement(request: Any) -> dict[str, Any]:
    """核验完整 FIFO batch 与 fleet settlement；不执行 native ack。"""
    if not isinstance(request, dict):
        raise WorkerLifecycleError("settlement request 必须是 object")
    required = {
        "operation",
        "identity",
        "bindings",
        "fifo",
        "batch",
        "persistence",
        "worker_list",
        "ack",
        "post_ack_worker_list",
        "history",
        "evidence",
    }
    if set(request) != required:
        raise WorkerLifecycleError(
            f"settlement request 字段必须精确为 {sorted(required)}"
        )
    if request["operation"] != SETTLEMENT_OPERATION:
        raise WorkerLifecycleError("settlement operation 必须为 settlement")
    identity = _identity(request["identity"])
    bindings = _bindings(request["bindings"], identity["run_id"])
    primary_binding = bindings.get(identity["terminal_handle"])
    if primary_binding is None or any(
        primary_binding[field] != identity[field]
        for field in ("run_id", "task_id", "dispatch_id", "terminal_handle")
    ):
        raise WorkerLifecycleError("identity 未精确绑定 bindings 中的当前 attempt")
    fifo = _mapping(
        request["fifo"],
        "fifo",
        {"complete", "ordered", "delivery_id", "ack_after_readback"},
    )
    if not all(
        _known_bool(fifo[field], f"fifo.{field}")
        for field in ("complete", "ordered", "ack_after_readback")
    ):
        raise WorkerLifecycleError("FIFO batch 未明确完整、有序且 ack-after-readback")
    delivery_id = _known_text(fifo["delivery_id"], "fifo.delivery_id")
    batch_value = request["batch"]
    if not isinstance(batch_value, list) or not batch_value:
        raise WorkerLifecycleError("batch 必须是非空列表")
    batch = [
        _message(value, index, identity["run_id"], bindings)
        for index, value in enumerate(batch_value)
    ]
    message_ids = [item["message_id"] for item in batch]
    if len(message_ids) != len(set(message_ids)):
        raise WorkerLifecycleError("同一 FIFO Delivery 含重复 message")

    persistence = _mapping(
        request["persistence"],
        "persistence",
        {
            "status",
            "delivery_id",
            "message_ids",
            "fan_in_keys",
            "pending_fan_in",
            "reference",
            "terminal_ownership",
            "registry_readback",
        },
    )
    if (
        persistence["status"] != "readback"
        or persistence["delivery_id"] != delivery_id
        or persistence["message_ids"] != message_ids
    ):
        raise WorkerLifecycleError(
            "ack 前 Delivery 与完整 message batch 持久化 readback 不完整"
        )

    worker_done_keys = [
        f"{item['binding']['task_id']}::{item['binding']['dispatch_id']}"
        for item in batch
        if item["type"] == "worker_done"
    ]
    if len(worker_done_keys) != len(set(worker_done_keys)):
        raise WorkerLifecycleError(
            "同一 FIFO Delivery 含重复 worker_done fan-in identity"
        )
    if persistence["fan_in_keys"] != worker_done_keys:
        raise WorkerLifecycleError("ack 前 worker_done fan-in identity 持久化不完整")

    history = _mapping(request["history"], "history", {"delivery_ids", "fan_in_keys"})
    if not isinstance(history["delivery_ids"], list) or not isinstance(
        history["fan_in_keys"], list
    ):
        raise WorkerLifecycleError("history 字段必须是列表")
    duplicate_delivery = delivery_id in history["delivery_ids"]
    history_keys = set(history["fan_in_keys"])
    pending_fan_in_keys = [key for key in worker_done_keys if key not in history_keys]
    if _known_bool(persistence["pending_fan_in"], "persistence.pending_fan_in") != bool(
        pending_fan_in_keys
    ):
        raise WorkerLifecycleError(
            "persistence.pending_fan_in 与既有 fan-in history 不一致"
        )
    if duplicate_delivery and pending_fan_in_keys:
        raise WorkerLifecycleError("重复 Delivery 缺少既有 fan-in 证据")
    terminal_ownership = _known_text(
        persistence["terminal_ownership"], "persistence.terminal_ownership"
    )
    if terminal_ownership not in {"reuse", "retain", "release"}:
        raise WorkerLifecycleError("terminal ownership 必须为 reuse/retain/release")
    if not _known_bool(
        persistence["registry_readback"], "persistence.registry_readback"
    ):
        raise WorkerLifecycleError("ack 前缺少 registry readback")

    persistence_reference, persisted = _read_json_object(
        persistence["reference"], "persistence.reference"
    )
    expected_persistence = {
        key: persistence[key]
        for key in (
            "status",
            "delivery_id",
            "message_ids",
            "fan_in_keys",
            "pending_fan_in",
            "terminal_ownership",
            "registry_readback",
        )
    }
    if persisted != expected_persistence:
        raise WorkerLifecycleError(
            "persistence.reference 与 ack 前 registry readback 不一致"
        )
    worker_list = _worker_list(
        request["worker_list"], "worker_list", identity, bindings
    )
    evidence = _evidence(request["evidence"])
    delivery_request_id = _native_delivery(
        evidence["reference"], identity["run_id"], bindings, delivery_id, batch
    )
    ack_source, mutation_request_id = _native_ack(request["ack"], identity, delivery_id)
    post_ack_worker_list = _worker_list(
        request["post_ack_worker_list"],
        "post_ack_worker_list",
        identity,
        bindings,
    )
    status = "deduplicated" if duplicate_delivery else "ready"
    return {
        "status": status,
        "operation": SETTLEMENT_OPERATION,
        "authority": False,
        "identity": identity,
        "bindings": list(bindings.values()),
        "delivery_id": delivery_id,
        "batch": batch,
        "worker_list": worker_list,
        "ack_id": delivery_id,
        "ack_source": ack_source,
        "post_ack_worker_list": post_ack_worker_list,
        "persistence_reference": persistence_reference,
        "fan_in": {
            "pending": pending_fan_in_keys,
            "already_recorded": [
                key for key in worker_done_keys if key in history_keys
            ],
        },
        "delivery_request_id": delivery_request_id,
        "mutation_request_id": mutation_request_id,
        "project_lane_transition": "unchanged",
        "evidence": evidence,
    }


def validate(request: Any) -> dict[str, Any]:
    operation = request.get("operation") if isinstance(request, dict) else None
    if operation == STARTUP_OPERATION:
        return validate_startup(request)
    if operation == SETTLEMENT_OPERATION:
        return validate_settlement(request)
    raise WorkerLifecycleError("operation 必须是 worker-start 或 settlement")


def _assert_lane_identity(
    lane: dict[str, Any], identity: dict[str, Any], *, attempt: bool
) -> None:
    fields = ["run_id", "task_id"]
    if attempt:
        fields.extend(
            (
                "dispatch_id",
                "terminal_handle",
                "worktree_selector",
                "execution_host",
                "attempt_index",
            )
        )
    overlay = lane["orca"]
    for field in fields:
        if overlay.get(field) != identity[field]:
            raise WorkerLifecycleError(
                f"lane.orca.{field} 与 native lifecycle identity 不匹配"
            )


def bind_startup(row: Any, request: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """验证启动 readback，并把已证明的 attempt 坐标写入同一 overlay row。"""
    receipt = validate_startup(request)
    lane = validate_markers(row, kind="lane")
    identity = receipt["identity"]
    _assert_lane_identity(lane, identity, attempt=False)
    lane = bind_attempt(
        lane,
        dispatch_id=identity["dispatch_id"],
        terminal_handle=identity["terminal_handle"],
        worktree_selector=identity["worktree_selector"],
        execution_host=identity["execution_host"],
        attempt_index=identity["attempt_index"],
    )
    lane = record_mutation(
        lane,
        operation=STARTUP_OPERATION,
        request_id=receipt["mutation_request_id"],
        receipt_reference=receipt["evidence"]["reference"],
        replace=True,
    )
    lane = record_observation(
        lane,
        source=receipt["evidence"]["source"],
        observed_at=receipt["evidence"]["observed_at"],
        evidence_reference=receipt["evidence"]["reference"],
        replace=True,
    )
    return lane, receipt


def record_settlement(row: Any, request: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """验证 settlement 后只更新共享 overlay 的 readback 指针，不执行 ack。"""
    settlement = validate_settlement(request)
    lane = validate_markers(row, kind="lane")
    _assert_lane_identity(lane, settlement["identity"], attempt=True)
    lane = record_mutation(
        lane,
        operation=SETTLEMENT_OPERATION,
        request_id=settlement["mutation_request_id"],
        receipt_reference=settlement["persistence_reference"],
        replace=True,
    )
    lane = record_observation(
        lane,
        source="orca orchestration worker-list",
        observed_at=settlement["evidence"]["observed_at"],
        evidence_reference=settlement["post_ack_worker_list"]["reference"],
        replace=True,
    )
    return lane, settlement


def _row() -> dict[str, Any]:
    return {
        "runtime": "orca",
        "dispatch_runtime": "orca",
        "coordinator_runtime": "orca-terminal",
        "orca": empty_overlay(),
    }


def _self_test() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        evidence = root / "native.json"
        evidence.write_text("{}", encoding="utf-8")
        requested_launch = {"agent": "pi", "model": "model-1", "effort": "xhigh"}
        worker_start = root / "worker-start.json"
        worker_start.write_text(
            json.dumps(
                {
                    "result": {
                        "runId": "run-1",
                        "taskId": "task-1",
                        "dispatchId": "dispatch-1",
                        "launch": {"requested": requested_launch},
                        "setup": {"requested": "skip"},
                        "mutation": {"requestId": "mutation-start-1"},
                    }
                }
            ),
            encoding="utf-8",
        )
        worker_show = root / "worker-show.json"
        worker_show.write_text(
            json.dumps(
                {
                    "result": {
                        "dispatch": {
                            "id": "dispatch-1",
                            "runId": "run-1",
                            "taskId": "task-1",
                            "retryOfDispatchId": None,
                        },
                        "worker": {
                            "startOptions": {
                                "launch": {"effective": requested_launch},
                                "setup": "skip",
                            }
                        },
                    }
                }
            ),
            encoding="utf-8",
        )
        (root / "source").mkdir()
        (root / "integration").mkdir()
        (root / "execution").mkdir()
        source = {
            "path": str(root / "source"),
            "branch": "main",
            "head": "a" * 40,
            "base": "a" * 40,
            "selector": "source-selector",
            "host": "host-1",
            "dirty_fingerprint": "clean",
        }
        integration = {
            "path": str(root / "integration"),
            "branch": "feature/map-114",
            "head": "a" * 40,
            "base": "a" * 40,
            "selector": "integration-selector",
            "host": "host-1",
            "dirty_fingerprint": "clean",
        }
        execution = {
            "path": str(root / "execution"),
            "branch": "worker/122",
            "head": "a" * 40,
            "base": "a" * 40,
            "selector": "execution-selector",
            "host": "host-1",
            "dirty_fingerprint": "clean",
        }
        startup_request = {
            "operation": STARTUP_OPERATION,
            "identity": {
                "run_id": "run-1",
                "task_id": "task-1",
                "dispatch_id": "dispatch-1",
                "terminal_handle": "term-1",
                "worktree_selector": "execution-selector",
                "execution_host": "host-1",
                "attempt_index": 0,
            },
            "previous_attempt": None,
            "integration_base": "a" * 40,
            "source_before": source,
            "source_after": source,
            "integration_worktree": integration,
            "execution_worktree": execution,
            "launch": {
                "transport": "launch-preferences",
                "requested": requested_launch,
                "effective": requested_launch,
                "requested_source": str(worker_start),
                "effective_source": str(worker_show),
            },
            "setup": {
                "requested": "skip",
                "effective": "skip",
                "requested_source": str(worker_start),
                "effective_source": str(worker_show),
            },
            "evidence": {
                "source": str(evidence),
                "observed_at": "now",
                "reference": str(worker_start),
            },
        }
        startup = validate_startup(startup_request)
        assert startup["status"] == "ready"
        bad = dict(startup["execution_worktree"])
        bad["base"] = "b" * 40
        try:
            validate_startup(
                {
                    "operation": STARTUP_OPERATION,
                    "identity": startup["identity"],
                    "previous_attempt": None,
                    "integration_base": "a" * 40,
                    "source_before": source,
                    "source_after": source,
                    "integration_worktree": integration,
                    "execution_worktree": bad,
                    "launch": startup["launch"],
                    "setup": startup["setup"],
                    "evidence": startup["evidence"],
                }
            )
        except WorkerLifecycleError:
            pass
        else:
            raise AssertionError("base mismatch was accepted")
        relative_path = copy.deepcopy(startup_request)
        relative_path["execution_worktree"]["path"] = "execution"
        try:
            validate_startup(relative_path)
        except WorkerLifecycleError:
            pass
        else:
            raise AssertionError("relative worktree path was accepted")

        previous_receipt = root / "previous-dispatch.json"
        previous_receipt.write_text(
            json.dumps(
                {
                    "result": {
                        "dispatch": {
                            "runId": "run-1",
                            "taskId": "task-1",
                            "id": "dispatch-0",
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        retry_identity = dict(startup["identity"])
        retry_identity["dispatch_id"] = "dispatch-1"
        retry_identity["attempt_index"] = 1
        previous = _previous_attempt(
            {
                "run_id": "run-1",
                "task_id": "task-1",
                "dispatch_id": "dispatch-0",
                "attempt_index": 0,
                "source": str(previous_receipt),
            },
            retry_identity,
            "dispatch-0",
        )
        assert previous is not None
        assert previous["dispatch_id"] == "dispatch-0"

        # agent-argv transport：worker-start 不为 pi 传 model，receipt/readback
        # 的 launch 字段全 null，model/effort 证据来自 worker 终端原生读回。
        null_launch = {"agent": None, "model": None, "effort": None}
        argv_start = root / "argv-worker-start.json"
        argv_start.write_text(
            json.dumps(
                {
                    "result": {
                        "runId": "run-1",
                        "taskId": "task-1",
                        "dispatchId": "dispatch-1",
                        "launch": {"requested": null_launch},
                        "setup": {"requested": "skip"},
                        "mutation": {"requestId": "mutation-start-2"},
                    }
                }
            ),
            encoding="utf-8",
        )
        argv_show = root / "argv-worker-show.json"
        argv_show.write_text(
            json.dumps(
                {
                    "result": {
                        "dispatch": {
                            "id": "dispatch-1",
                            "runId": "run-1",
                            "taskId": "task-1",
                            "retryOfDispatchId": None,
                        },
                        "worker": {
                            "startOptions": {
                                "launch": {"effective": null_launch},
                                "setup": "skip",
                            }
                        },
                    }
                }
            ),
            encoding="utf-8",
        )
        terminal_read = root / "terminal-read.json"
        terminal_read.write_text(
            json.dumps(
                {
                    "result": {
                        "terminal": {
                            "handle": "term-1",
                            "status": "running",
                            "tail": ["main | model-1[xhigh] | thinking xhigh"],
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        argv_request = copy.deepcopy(startup_request)
        argv_request["launch"] = {
            "transport": "agent-argv",
            "requested": requested_launch,
            "effective": requested_launch,
            "requested_source": str(argv_start),
            "effective_source": str(argv_show),
            "terminal_source": str(terminal_read),
        }
        argv_startup = validate_startup(argv_request)
        assert argv_startup["status"] == "ready"
        assert argv_startup["launch"]["transport"] == "agent-argv"

        # 反例：agent-argv 但 native receipt 携带非 null launch（未经 terminal 路径）
        bad_start = root / "argv-bad-start.json"
        bad_start.write_text(
            json.dumps(
                {
                    "result": {
                        "runId": "run-1",
                        "taskId": "task-1",
                        "dispatchId": "dispatch-1",
                        "launch": {"requested": requested_launch},
                        "mutation": {"requestId": "mutation-start-3"},
                    }
                }
            ),
            encoding="utf-8",
        )
        bad_request = copy.deepcopy(argv_request)
        bad_request["launch"] = {**argv_request["launch"], "requested_source": str(bad_start)}
        try:
            validate_startup(bad_request)
        except WorkerLifecycleError:
            pass
        else:
            raise AssertionError("agent-argv accepted non-null native launch")

        # 反例：terminal_source 读回不含 effective model
        bad_terminal = root / "terminal-read-bad.json"
        bad_terminal.write_text(
            json.dumps(
                {
                    "result": {
                        "terminal": {
                            "handle": "term-1",
                            "tail": ["main | other-2[low] | thinking low"],
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        bad_request = copy.deepcopy(argv_request)
        bad_request["launch"] = {**argv_request["launch"], "terminal_source": str(bad_terminal)}
        try:
            validate_startup(bad_request)
        except WorkerLifecycleError:
            pass
        else:
            raise AssertionError("agent-argv accepted terminal without effective model")
        try:
            _previous_attempt(
                {
                    "run_id": "run-1",
                    "task_id": "task-1",
                    "dispatch_id": "dispatch-other",
                    "attempt_index": 0,
                    "source": str(previous_receipt),
                },
                retry_identity,
                "dispatch-other",
            )
        except WorkerLifecycleError:
            pass
        else:
            raise AssertionError("unrelated retry predecessor was accepted")

        fifo_delivery = root / "fifo-delivery.json"
        message = {
            "message_id": "message-1",
            "run_id": "run-1",
            "from_handle": "term-1",
            "subject": "Worker complete",
            "body": "Readback complete.",
            "type": "worker_done",
            "payload": {
                "taskId": "task-1",
                "dispatchId": "dispatch-1",
                "outcome": "succeeded",
            },
        }
        question = {
            "message_id": "message-2",
            "run_id": "run-1",
            "from_handle": "term-2",
            "subject": "Need a decision",
            "body": "Choose the next step.",
            "type": "question",
            "payload": {},
        }
        fifo_delivery.write_text(
            json.dumps(
                {
                    "result": {
                        "runId": "run-1",
                        "deliveryId": "delivery-1",
                        "messages": [
                            {
                                "id": message["message_id"],
                                "run_id": message["run_id"],
                                "from_handle": message["from_handle"],
                                "subject": message["subject"],
                                "body": message["body"],
                                "type": message["type"],
                                "payload": json.dumps(message["payload"]),
                            },
                            {
                                "id": question["message_id"],
                                "run_id": question["run_id"],
                                "from_handle": question["from_handle"],
                                "subject": question["subject"],
                                "body": question["body"],
                                "type": question["type"],
                                "payload": json.dumps(question["payload"]),
                            },
                        ],
                        "mutation": {"requestId": "mutation-check-1"},
                    }
                }
            ),
            encoding="utf-8",
        )
        worker_row = {
            "runId": "run-1",
            "taskId": "task-1",
            "dispatchId": "dispatch-1",
            "agentTerminalHandle": "term-1",
            "workerState": "succeeded",
            "dispatchStatus": "completed",
            "terminalState": "reclaimable",
            "projection": {
                "liveness": {"verdict": "live"},
                "nextAction": {
                    "kind": "release",
                    "argv": ["orchestration", "worker-release"],
                }
            },
        }
        worker_row_2 = {
            "runId": "run-1",
            "taskId": "task-2",
            "dispatchId": "dispatch-2",
            "agentTerminalHandle": "term-2",
            "workerState": "running",
            "dispatchStatus": "active",
            "terminalState": "owned",
            "projection": {
                "liveness": {"verdict": "live"},
                "nextAction": {"kind": "none", "argv": []},
            },
        }
        worker_list_source = root / "worker-list.json"
        worker_list_source.write_text(
            json.dumps({"result": {"workers": [worker_row, worker_row_2]}}),
            encoding="utf-8",
        )
        ack_source = root / "fifo-ack.json"
        ack_source.write_text(
            json.dumps(
                {
                    "result": {
                        "runId": "run-1",
                        "acknowledged": "delivery-1",
                        "mutation": {"requestId": "mutation-ack-1"},
                    }
                }
            ),
            encoding="utf-8",
        )
        worker_list = {
            "source": "worker-list",
            "reference": str(worker_list_source),
            "run_id": "run-1",
            "fleet_verdict": True,
            "rows": [worker_row, worker_row_2],
        }
        persistence_readback = root / "settlement-persistence.json"
        persistence_readback.write_text(
            json.dumps(
                {
                    "status": "readback",
                    "delivery_id": "delivery-1",
                    "message_ids": ["message-1", "message-2"],
                    "fan_in_keys": ["task-1::dispatch-1"],
                    "pending_fan_in": True,
                    "terminal_ownership": "release",
                    "registry_readback": True,
                }
            ),
            encoding="utf-8",
        )
        settlement_request = {
            "operation": SETTLEMENT_OPERATION,
            "identity": startup["identity"],
            "bindings": [
                {
                    "run_id": "run-1",
                    "task_id": "task-1",
                    "dispatch_id": "dispatch-1",
                    "terminal_handle": "term-1",
                },
                {
                    "run_id": "run-1",
                    "task_id": "task-2",
                    "dispatch_id": "dispatch-2",
                    "terminal_handle": "term-2",
                },
            ],
            "fifo": {
                "complete": True,
                "ordered": True,
                "delivery_id": "delivery-1",
                "ack_after_readback": True,
            },
            "batch": [message, question],
            "persistence": {
                "status": "readback",
                "delivery_id": "delivery-1",
                "message_ids": ["message-1", "message-2"],
                "fan_in_keys": ["task-1::dispatch-1"],
                "pending_fan_in": True,
                "reference": str(persistence_readback),
                "terminal_ownership": "release",
                "registry_readback": True,
            },
            "worker_list": worker_list,
            "ack": {"delivery_id": "delivery-1", "source": str(ack_source)},
            "post_ack_worker_list": worker_list,
            "history": {"delivery_ids": [], "fan_in_keys": []},
            "evidence": {
                "source": str(evidence),
                "observed_at": "now",
                "reference": str(fifo_delivery),
            },
        }
        settlement = validate_settlement(settlement_request)
        assert settlement["ack_id"] == "delivery-1"
        assert len(settlement["bindings"]) == 2
        assert settlement["fan_in"]["pending"] == ["task-1::dispatch-1"]
        assert settlement["worker_list"]["rows"][1]["next_action"] == "wait"

        worker_row_2["projection"]["liveness"]["verdict"] = "unverifiable"
        worker_list_source.write_text(
            json.dumps({"result": {"workers": [worker_row, worker_row_2]}}),
            encoding="utf-8",
        )
        try:
            validate_settlement(settlement_request)
        except WorkerLifecycleError:
            pass
        else:
            raise AssertionError("unverifiable fleet liveness was accepted")
        worker_row_2["projection"]["liveness"]["verdict"] = "live"
        worker_list_source.write_text(
            json.dumps({"result": {"workers": [worker_row, worker_row_2]}}),
            encoding="utf-8",
        )

        blocked_launch = copy.deepcopy(startup_request)
        blocked_launch["launch"]["requested"]["model"] = None
        blocked_launch["launch"]["effective"]["model"] = None
        try:
            validate_startup(blocked_launch)
        except WorkerLifecycleError:
            pass
        else:
            raise AssertionError("Unknown launch model was accepted")
        persistence_readback.write_text(
            json.dumps(
                {
                    "status": "readback",
                    "delivery_id": "delivery-1",
                    "message_ids": ["message-1", "message-2"],
                    "fan_in_keys": ["task-1::dispatch-1"],
                    "pending_fan_in": False,
                    "terminal_ownership": "release",
                    "registry_readback": True,
                }
            ),
            encoding="utf-8",
        )
        duplicate = copy.deepcopy(settlement_request)
        duplicate["history"] = {
            "delivery_ids": ["delivery-1"],
            "fan_in_keys": ["task-1::dispatch-1"],
        }
        duplicate["persistence"]["pending_fan_in"] = False
        duplicate_result = validate_settlement(duplicate)
        assert duplicate_result["status"] == "deduplicated"
        assert duplicate_result["ack_id"] == "delivery-1"
        new_delivery_existing_fan_in = copy.deepcopy(settlement_request)
        new_delivery_existing_fan_in["history"]["fan_in_keys"] = ["task-1::dispatch-1"]
        new_delivery_existing_fan_in["persistence"]["pending_fan_in"] = False
        existing_result = validate_settlement(new_delivery_existing_fan_in)
        assert existing_result["status"] == "ready"
        assert existing_result["fan_in"]["pending"] == []
        assert existing_result["ack_id"] == "delivery-1"
        persistence_readback.write_text(
            json.dumps(
                {
                    "status": "readback",
                    "delivery_id": "delivery-1",
                    "message_ids": ["message-1", "message-2"],
                    "fan_in_keys": ["task-1::dispatch-1"],
                    "pending_fan_in": True,
                    "terminal_ownership": "release",
                    "registry_readback": True,
                }
            ),
            encoding="utf-8",
        )
        unbound_question = copy.deepcopy(settlement_request)
        unbound_question["batch"][0].update(
            {"type": "question", "payload": {}, "from_handle": "term-other"}
        )
        try:
            validate_settlement(unbound_question)
        except WorkerLifecycleError:
            pass
        else:
            raise AssertionError("unbound question was accepted")

        lane = _row()
        lane["orca"]["run_id"] = "run-1"
        lane["orca"]["task_id"] = "task-1"
        wrong_lane = copy.deepcopy(lane)
        wrong_lane["orca"]["task_id"] = "task-other"
        try:
            bind_startup(wrong_lane, startup_request)
        except WorkerLifecycleError:
            pass
        else:
            raise AssertionError("mismatched lane identity was accepted")
        lane, _ = bind_startup(lane, startup_request)
        assert lane["orca"]["dispatch_id"] == "dispatch-1"
        lane, _ = record_settlement(lane, settlement_request)
        assert lane["orca"]["mutation"]["operation"] == SETTLEMENT_OPERATION
        assert lane["orca"]["mutation"]["receipt_reference"] == str(
            persistence_readback.resolve()
        )
        assert lane["orca"]["observation"]["evidence_reference"] == str(
            worker_list_source.resolve()
        )


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "self-test":
        _self_test()
        print(json.dumps({"valid": True}, sort_keys=True))
        return 0
    if len(sys.argv) == 3 and sys.argv[1] == "validate":
        try:
            request_path = Path(sys.argv[2]).expanduser()
            if not request_path.is_absolute():
                raise WorkerLifecycleError("request path 必须是绝对路径")
            request = json.loads(request_path.read_text(encoding="utf-8"))
            result = validate(request)
        except (
            OSError,
            json.JSONDecodeError,
            WorkerLifecycleError,
            OverlayError,
        ) as error:
            print(
                json.dumps(
                    {"status": "blocked", "reason": str(error)},
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 1
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    print(
        f"Usage: {sys.argv[0]} self-test | validate <absolute-request.json>",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
