#!/usr/bin/env python3
"""Orca 项目侧 overlay 合同；持久化仍由共享 lane registry owner 负责。"""

from __future__ import annotations

import copy
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

OVERLAY_FIELDS = (
    "run_id",
    "task_id",
    "dispatch_id",
    "terminal_handle",
    "worktree_selector",
    "execution_host",
    "attempt_index",
    "coordinator_host_id",
    "coordinator_terminal_handle",
    "mutation",
    "observation",
)
MUTATION_FIELDS = ("operation", "request_id", "receipt_reference")
OBSERVATION_FIELDS = ("source", "observed_at", "evidence_reference")
ATTEMPT_FIELDS = (
    "dispatch_id",
    "terminal_handle",
    "worktree_selector",
    "execution_host",
    "attempt_index",
)


class OverlayError(ValueError):
    """Overlay 缺失、冲突或身份不明，不能安全写入。"""


class OverlayPersistError(OverlayError):
    """写入结果不能确认；observed 保存最后一次 registry readback。"""

    def __init__(self, message: str, *, observed: Any) -> None:
        super().__init__(message)
        self.observed = copy.deepcopy(observed)


class OverlayConflict(OverlayError):
    """新证据不能覆盖已有的不同身份或未结算 mutation。"""


def _known_text(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value.strip().lower() in {"none", "null", "unknown"}
    ):
        raise OverlayError(f"{field} 必须是已知非空文本")
    return value.strip()


def _optional_text(value: Any, field: str) -> None:
    if value is not None:
        _known_text(value, field)


def empty_overlay() -> dict[str, Any]:
    """返回字段完整、未绑定任何 Orca 身份的 overlay。"""
    return dict.fromkeys(OVERLAY_FIELDS)


def _validate_mutation(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, dict) or set(value) != set(MUTATION_FIELDS):
        raise OverlayError(
            "orca.mutation 必须精确包含 operation/request_id/receipt_reference"
        )
    _known_text(value["operation"], "orca.mutation.operation")
    _optional_text(value["request_id"], "orca.mutation.request_id")
    _optional_text(value["receipt_reference"], "orca.mutation.receipt_reference")


def _validate_observation(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, dict) or set(value) != set(OBSERVATION_FIELDS):
        raise OverlayError(
            "orca.observation 必须精确包含 source/observed_at/evidence_reference"
        )
    for field in OBSERVATION_FIELDS:
        _known_text(value[field], f"orca.observation.{field}")


def validate_overlay(value: Any) -> dict[str, Any]:
    """验证完整 overlay；不接受缺字段、猜测值或 Orca API 额外字段。"""
    if not isinstance(value, dict) or set(value) != set(OVERLAY_FIELDS):
        raise OverlayError("orca overlay 字段必须与共享合同完全一致")
    for field in OVERLAY_FIELDS[:6] + OVERLAY_FIELDS[7:9]:
        _optional_text(value[field], f"orca.{field}")
    attempt = value["attempt_index"]
    if attempt is not None and (type(attempt) is not int or attempt < 0):
        raise OverlayError("orca.attempt_index 必须是非负 native 整数或 null")
    _validate_mutation(value["mutation"])
    _validate_observation(value["observation"])
    return value


def _copy_row(row: Any) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise OverlayError("registry row 必须是 object")
    result = copy.deepcopy(row)
    if "orca" not in result or result["orca"] is None:
        result["orca"] = empty_overlay()
    validate_overlay(result["orca"])
    return result


def _blocked(resource: str, reason: str, **identities: Any) -> dict[str, Any]:
    return {
        "status": "blocked",
        "reason": reason,
        f"create_{resource}": False,
        **identities,
    }


def _writer_blocked(writer_active: Any, resource: str) -> dict[str, Any] | None:
    if type(writer_active) is not bool or writer_active:
        return _blocked(resource, "active writer 未明确为 false")
    return None


def _required_identity(
    value: Any, field: str, resource: str
) -> tuple[str | None, dict[str, Any] | None]:
    try:
        return _known_text(value, field), None
    except OverlayError as error:
        return None, _blocked(resource, str(error))


def validate_markers(row: Any, *, kind: str) -> dict[str, Any]:
    """验证 map/lane 的显式 transport markers，不从当前环境推断。"""
    if kind not in {"map", "lane"}:
        raise OverlayError("kind 必须是 map 或 lane")
    result = _copy_row(row)
    expected = {
        "runtime": "orchestrator" if kind == "map" else "orca",
        "dispatch_runtime": "orca",
        "coordinator_runtime": "orca-terminal",
    }
    for field, value in expected.items():
        if result.get(field) != value:
            raise OverlayError(f"{kind} 的 {field} 必须显式为 {value}")
    if kind == "map":
        worker_fields = (
            "task_id",
            *ATTEMPT_FIELDS,
        )
        if any(result["orca"][field] is not None for field in worker_fields):
            raise OverlayError("map.orca 不得写入 worker-specific 坐标")
    return result


def persist_overlay(
    previous: Any,
    row: Any,
    *,
    readback: Callable[[], Any],
    write: Callable[[dict[str, Any]], None],
) -> dict[str, Any]:
    """以 previous 做乐观并发核对，写入 row 后再次精确读回。"""
    expected_previous = _copy_row(previous)
    expected = _copy_row(row)
    current = _copy_row(readback())
    if current != expected_previous:
        raise OverlayConflict("registry readback 已变化；保留旧证据，不覆盖")
    try:
        write(copy.deepcopy(expected))
    except Exception as error:
        try:
            observed = _copy_row(readback())
        except Exception as readback_error:
            raise OverlayPersistError(
                f"overlay 写入与 readback 结果均 Unknown: {error}; {readback_error}",
                observed=current,
            ) from error
        if observed == expected:
            return observed
        state = "未生效" if observed == expected_previous else "不一致"
        raise OverlayPersistError(
            f"overlay 写入失败且 readback {state}；不重写: {error}",
            observed=observed,
        ) from error
    try:
        observed = _copy_row(readback())
    except Exception as error:
        raise OverlayPersistError(
            f"overlay 写入后 readback Unknown；不重写: {error}", observed=current
        ) from error
    if observed != expected:
        raise OverlayPersistError(
            "overlay 写入后 readback 不一致；保留当前 readback，不重写",
            observed=observed,
        )
    return observed


def record_native_coordinates(row: Any, **coordinates: Any) -> dict[str, Any]:
    """补 native readback 坐标；已知身份冲突时拒绝覆盖。"""
    result = _copy_row(row)
    supported = {
        "run_id",
        "task_id",
        "dispatch_id",
        "terminal_handle",
        "worktree_selector",
        "execution_host",
        "attempt_index",
    }
    unknown = set(coordinates) - supported
    if unknown:
        raise OverlayError(f"不支持的 Orca 坐标: {sorted(unknown)}")
    overlay = result["orca"]
    for field, value in coordinates.items():
        if value is None:
            continue
        if field == "attempt_index":
            if type(value) is not int or value < 0:
                raise OverlayError("orca.attempt_index 必须是非负 native 整数")
        else:
            _known_text(value, f"orca.{field}")
        previous = overlay[field]
        if previous is not None and previous != value:
            raise OverlayConflict(f"orca.{field} 身份冲突；保留旧证据，不覆盖")
        overlay[field] = value
    result["orca"] = validate_overlay(overlay)
    return result


def record_readback(
    row: Any,
    *,
    coordinates: dict[str, Any] | None = None,
    source: str,
    observed_at: str,
    evidence_reference: str,
    replace: bool = False,
) -> dict[str, Any]:
    """一次性写入 native 坐标与 observation，供 tracker owner 持久化后再读回。"""
    result = record_native_coordinates(row, **(coordinates or {}))
    return record_observation(
        result,
        source=source,
        observed_at=observed_at,
        evidence_reference=evidence_reference,
        replace=replace,
    )


def _set_stable_identity(overlay: dict[str, Any], field: str, value: str) -> None:
    value = _known_text(value, f"orca.{field}")
    previous = overlay[field]
    if previous is not None and previous != value:
        raise OverlayConflict(f"orca.{field} 身份冲突；保留旧证据，不覆盖")
    overlay[field] = value


def bind_map_run(
    row: Any,
    *,
    run_id: str,
    coordinator_host_id: str,
    coordinator_terminal_handle: str,
) -> dict[str, Any]:
    """绑定一个 map 的唯一 Run；重复恢复只接受同一身份。"""
    result = validate_markers(row, kind="map")
    overlay = result["orca"]
    _set_stable_identity(overlay, "run_id", run_id)
    _set_stable_identity(overlay, "coordinator_host_id", coordinator_host_id)
    _set_stable_identity(
        overlay, "coordinator_terminal_handle", coordinator_terminal_handle
    )
    result["orca"] = validate_overlay(overlay)
    return result


def rebind_map_coordinator(
    row: Any,
    *,
    observed_run_id: str,
    coordinator_host_id: str,
    coordinator_terminal_handle: str,
    writer_active: bool,
) -> dict[str, Any]:
    """同一 Run takeover 后更新 coordinator；旧 writer 未排除时拒绝。"""
    result = validate_markers(row, kind="map")
    if blocked := _writer_blocked(writer_active, "run"):
        raise OverlayConflict(blocked["reason"])
    overlay = result["orca"]
    run_id = _known_text(overlay.get("run_id"), "map.orca.run_id")
    if run_id != _known_text(observed_run_id, "observed_run_id"):
        raise OverlayConflict("registry 与 native Run 不一致；不更新 coordinator")
    overlay["coordinator_host_id"] = _known_text(
        coordinator_host_id, "orca.coordinator_host_id"
    )
    overlay["coordinator_terminal_handle"] = _known_text(
        coordinator_terminal_handle, "orca.coordinator_terminal_handle"
    )
    result["orca"] = validate_overlay(overlay)
    return result


def bind_lane_task(row: Any, *, map_row: Any, task_id: str) -> dict[str, Any]:
    """把 lane 绑定到 map Run 与一个长期 Task，不创建第二个 Task。"""
    lane = validate_markers(row, kind="lane")
    parent = validate_markers(map_row, kind="map")
    map_run = _known_text(parent["orca"].get("run_id"), "map.orca.run_id")
    overlay = lane["orca"]
    _set_stable_identity(overlay, "run_id", map_run)
    _set_stable_identity(overlay, "task_id", task_id)
    lane["orca"] = validate_overlay(overlay)
    return lane


def bind_attempt(
    row: Any,
    *,
    dispatch_id: str,
    terminal_handle: str,
    worktree_selector: str,
    execution_host: str,
    attempt_index: int,
) -> dict[str, Any]:
    """仅用 native readback 补齐 Dispatch attempt 坐标，不从名称推导身份。"""
    result = validate_markers(row, kind="lane")
    _known_text(result["orca"].get("run_id"), "lane.orca.run_id")
    _known_text(result["orca"].get("task_id"), "lane.orca.task_id")
    return record_native_coordinates(
        result,
        dispatch_id=dispatch_id,
        terminal_handle=terminal_handle,
        worktree_selector=worktree_selector,
        execution_host=execution_host,
        attempt_index=attempt_index,
    )


def record_mutation(
    row: Any,
    *,
    operation: str,
    request_id: str | None = None,
    receipt_reference: str | None = None,
    replace: bool = False,
) -> dict[str, Any]:
    """先记录 intent，再补 native request/receipt；不明或冲突时 fail-closed。"""
    result = _copy_row(row)
    operation = _known_text(operation, "operation")
    _optional_text(request_id, "request_id")
    _optional_text(receipt_reference, "receipt_reference")
    incoming = {
        "operation": operation,
        "request_id": request_id,
        "receipt_reference": receipt_reference,
    }
    previous = result["orca"]["mutation"]
    if previous is None:
        result["orca"]["mutation"] = incoming
    elif previous == incoming:
        return result
    elif (
        previous["operation"] == operation
        and previous["receipt_reference"] is None
        and previous["request_id"] is None
        and request_id is not None
    ) or (
        previous["operation"] == operation
        and previous["request_id"] == request_id
        and previous["receipt_reference"] is None
        and receipt_reference is not None
    ):
        result["orca"]["mutation"] = incoming
    elif not replace or previous["receipt_reference"] is None:
        raise OverlayConflict("当前 mutation 未完成或身份冲突；保留旧证据，不重发")
    else:
        result["orca"]["mutation"] = incoming
    result["orca"] = validate_overlay(result["orca"])
    return result


def record_observation(
    row: Any,
    *,
    source: str,
    observed_at: str,
    evidence_reference: str,
    replace: bool = False,
) -> dict[str, Any]:
    """保存 readback 来源、时间和证据引用；同一 readback 幂等。"""
    result = _copy_row(row)
    incoming = {
        "source": _known_text(source, "source"),
        "observed_at": _known_text(observed_at, "observed_at"),
        "evidence_reference": _known_text(evidence_reference, "evidence_reference"),
    }
    previous = result["orca"]["observation"]
    if previous is None or previous == incoming or replace:
        result["orca"]["observation"] = incoming
    else:
        raise OverlayConflict("readback 证据冲突；保留旧证据，不覆盖")
    result["orca"] = validate_overlay(result["orca"])
    return result


def recover_map(
    row: Any,
    *,
    observed_run_id: str,
    observed_coordinator_host_id: str,
    observed_coordinator_terminal_handle: str,
    writer_active: bool,
) -> dict[str, Any]:
    """重启时只沿已持久 Run 恢复；active/Unknown/不一致均不创建副本。"""
    result = validate_markers(row, kind="map")
    blocked = _writer_blocked(writer_active, "run")
    if blocked is not None:
        return blocked
    identities = (
        (result["orca"].get("run_id"), "map.orca.run_id"),
        (
            result["orca"].get("coordinator_host_id"),
            "map.orca.coordinator_host_id",
        ),
        (
            result["orca"].get("coordinator_terminal_handle"),
            "map.orca.coordinator_terminal_handle",
        ),
        (observed_run_id, "observed_run_id"),
        (observed_coordinator_host_id, "observed_coordinator_host_id"),
        (
            observed_coordinator_terminal_handle,
            "observed_coordinator_terminal_handle",
        ),
    )
    resolved: list[str] = []
    for value, field in identities:
        identity, blocked = _required_identity(value, field, "run")
        if blocked is not None:
            return blocked
        if identity is None:
            return _blocked("run", f"{field} 身份 Unknown")
        resolved.append(identity)
    run_id, host_id, terminal_handle, observed_run, observed_host, observed_terminal = (
        resolved
    )
    if run_id != observed_run:
        return _blocked("run", "registry 与 native Run 不一致", run_id=run_id)
    if host_id != observed_host or terminal_handle != observed_terminal:
        return _blocked(
            "run", "registry 与 native coordinator origin 不一致", run_id=run_id
        )
    return {"status": "ready", "run_id": run_id, "create_run": False}


def recover_lane(
    row: Any,
    *,
    map_row: Any,
    observed_run_id: str,
    observed_task_id: str,
    writer_active: bool,
) -> dict[str, Any]:
    """重启时只沿既有 Run/Task 恢复；不确定时零新 writer。"""
    lane = validate_markers(row, kind="lane")
    parent = validate_markers(map_row, kind="map")
    blocked = _writer_blocked(writer_active, "task")
    if blocked is not None:
        return blocked
    identities = (
        (lane["orca"].get("run_id"), "lane.orca.run_id"),
        (lane["orca"].get("task_id"), "lane.orca.task_id"),
        (parent["orca"].get("run_id"), "map.orca.run_id"),
        (observed_run_id, "observed_run_id"),
        (observed_task_id, "observed_task_id"),
    )
    resolved: list[str] = []
    for value, field in identities:
        identity, blocked = _required_identity(value, field, "task")
        if blocked is not None:
            return blocked
        if identity is None:
            return _blocked("task", f"{field} 身份 Unknown")
        resolved.append(identity)
    run_id, task_id, map_run, observed_run, observed_task = resolved
    if run_id != map_run or run_id != observed_run:
        return _blocked("task", "lane/map/native Run 不一致", run_id=run_id)
    if task_id != observed_task:
        return _blocked("task", "registry 与 native Task 不一致", task_id=task_id)
    return {
        "status": "ready",
        "run_id": run_id,
        "task_id": task_id,
        "create_task": False,
    }


def recover_attempt(
    row: Any, *, observed_coordinates: Any, writer_active: bool
) -> dict[str, Any]:
    """只沿完整且一致的 Dispatch attempt 坐标恢复，不创建新 Dispatch。"""
    lane = validate_markers(row, kind="lane")
    blocked = _writer_blocked(writer_active, "dispatch")
    if blocked is not None:
        return blocked
    if not isinstance(observed_coordinates, dict) or set(observed_coordinates) != set(
        ATTEMPT_FIELDS
    ):
        return _blocked("dispatch", "native Dispatch readback 字段不完整")
    stored = {field: lane["orca"][field] for field in ATTEMPT_FIELDS}
    try:
        for field in ATTEMPT_FIELDS:
            if field == "attempt_index":
                if type(stored[field]) is not int or stored[field] < 0:
                    raise OverlayError("registry attempt_index 身份 Unknown")
                if (
                    type(observed_coordinates[field]) is not int
                    or observed_coordinates[field] < 0
                ):
                    raise OverlayError("native attempt_index 身份 Unknown")
            else:
                _known_text(stored[field], f"lane.orca.{field}")
                _known_text(observed_coordinates[field], f"observed.{field}")
    except OverlayError as error:
        return _blocked("dispatch", str(error))
    if stored != observed_coordinates:
        return _blocked(
            "dispatch",
            "registry 与 native Dispatch attempt 不一致",
            dispatch_id=stored["dispatch_id"],
        )
    return {
        "status": "ready",
        **stored,
        "create_dispatch": False,
    }


ACTIONS: dict[str, Callable[..., dict[str, Any]]] = {
    "record_mutation": record_mutation,
    "record_native_coordinates": record_native_coordinates,
    "record_readback": record_readback,
    "bind_map_run": bind_map_run,
    "rebind_map_coordinator": rebind_map_coordinator,
    "bind_lane_task": bind_lane_task,
    "bind_attempt": bind_attempt,
    "recover_map": recover_map,
    "recover_lane": recover_lane,
    "recover_attempt": recover_attempt,
}
ACTION_KINDS = {
    "bind_map_run": "map",
    "rebind_map_coordinator": "map",
    "recover_map": "map",
    "bind_lane_task": "lane",
    "bind_attempt": "lane",
    "recover_lane": "lane",
    "recover_attempt": "lane",
}


def apply_request(request: Any) -> dict[str, Any]:
    """执行一个纯 overlay 操作；caller 负责写回并读回共享 registry。"""
    if not isinstance(request, dict) or set(request) != {
        "action",
        "kind",
        "row",
        "arguments",
    }:
        raise OverlayError("request 必须精确包含 action/kind/row/arguments")
    action = _known_text(request["action"], "action")
    kind = _known_text(request["kind"], "kind")
    arguments = request["arguments"]
    if action not in ACTIONS or not isinstance(arguments, dict):
        raise OverlayError("未知 action 或 arguments 不是 object")
    if expected_kind := ACTION_KINDS.get(action):
        if kind != expected_kind:
            raise OverlayError(f"{action} 只接受 {expected_kind} row")
    row = validate_markers(request["row"], kind=kind)
    result = ACTIONS[action](row, **arguments)
    if action.startswith("recover_"):
        return result
    return validate_markers(result, kind=kind)


def _self_test() -> None:
    def expect(condition: bool, message: str) -> None:
        if not condition:
            raise AssertionError(message)

    base = {
        "runtime": "orchestrator",
        "dispatch_runtime": "orca",
        "coordinator_runtime": "orca-terminal",
        "orca": empty_overlay(),
    }
    bound_map = bind_map_run(
        base,
        run_id="run-map-1",
        coordinator_host_id="host-1",
        coordinator_terminal_handle="term-1",
    )
    expect(
        recover_map(
            bound_map,
            observed_run_id="run-map-1",
            observed_coordinator_host_id="host-1",
            observed_coordinator_terminal_handle="term-1",
            writer_active=False,
        )
        == {"status": "ready", "run_id": "run-map-1", "create_run": False},
        "same map Run recovery must be idempotent",
    )
    lane = {
        "runtime": "orca",
        "dispatch_runtime": "orca",
        "coordinator_runtime": "orca-terminal",
        "orca": empty_overlay(),
    }
    bound_lane = bind_lane_task(lane, map_row=bound_map, task_id="task-1")
    bound_lane = bind_attempt(
        bound_lane,
        dispatch_id="dispatch-1",
        terminal_handle="term-1",
        worktree_selector="selector-1",
        execution_host="host-1",
        attempt_index=0,
    )
    bound_lane = record_mutation(bound_lane, operation="task-create")
    bound_lane = record_mutation(
        bound_lane, operation="task-create", request_id="req-1"
    )
    bound_lane = record_mutation(
        bound_lane,
        operation="task-create",
        request_id="req-1",
        receipt_reference="receipt-1",
    )
    lost_response = record_mutation(lane, operation="run-create")
    try:
        record_mutation(
            lost_response,
            operation="task-create",
            request_id="req-2",
            replace=True,
        )
    except OverlayConflict:
        pass
    else:
        raise AssertionError("unknown mutation outcome must not be replaced")
    bound_lane = record_observation(
        bound_lane,
        source="native",
        observed_at="2026-09-15T00:00:00Z",
        evidence_reference="evidence-1",
    )
    store = {"row": lane}
    persisted = persist_overlay(
        lane,
        bound_lane,
        readback=lambda: store["row"],
        write=lambda value: store.__setitem__("row", value),
    )
    if persisted != bound_lane or store["row"] != bound_lane:
        raise AssertionError("overlay must be read back exactly after write")
    try:
        persist_overlay(
            lane,
            bound_lane,
            readback=lambda: {
                **store["row"],
                "orca": {**store["row"]["orca"], "run_id": "run-map-2"},
            },
            write=lambda value: None,
        )
    except OverlayConflict:
        pass
    else:
        raise AssertionError("changed registry readback must fail closed")
    expect(
        recover_lane(
            bound_lane,
            map_row=bound_map,
            observed_run_id="run-map-1",
            observed_task_id="task-1",
            writer_active=False,
        )["status"]
        == "ready",
        "same Run/Task recovery must be ready",
    )
    blocked = recover_lane(
        bound_lane,
        map_row=bound_map,
        observed_run_id="Unknown",
        observed_task_id="task-1",
        writer_active=False,
    )
    expect(
        blocked["status"] == "blocked" and not blocked["create_task"],
        "unknown native identity must not create a writer",
    )
    active_map = recover_map(
        bound_map,
        observed_run_id="run-map-1",
        observed_coordinator_host_id="host-1",
        observed_coordinator_terminal_handle="term-1",
        writer_active=True,
    )
    expect(
        active_map["status"] == "blocked" and not active_map["create_run"],
        "active writer must not create a Run",
    )
    try:
        bind_map_run(
            bound_map,
            run_id="run-map-2",
            coordinator_host_id="host-1",
            coordinator_terminal_handle="term-1",
        )
    except OverlayConflict:
        pass
    else:
        raise AssertionError("different Run must fail closed")
    expect(
        recover_lane(
            bound_lane,
            map_row=bound_map,
            observed_run_id="run-map-1",
            observed_task_id="task-1",
            writer_active=True,
        )["status"]
        == "blocked",
        "active writer must remain blocked",
    )

    wrong_markers = dict(base, runtime="herdr-pi-pane")
    try:
        validate_markers(wrong_markers, kind="map")
    except OverlayError:
        pass
    else:
        raise AssertionError("wrong transport markers must fail closed")
    bad_map = copy.deepcopy(bound_map)
    bad_map["orca"]["task_id"] = "task-leaked-to-map"
    try:
        validate_markers(bad_map, kind="map")
    except OverlayError:
        pass
    else:
        raise AssertionError("map must not carry worker coordinates")

    cli_recovery = apply_request(
        {
            "action": "recover_map",
            "kind": "map",
            "row": bound_map,
            "arguments": {
                "observed_run_id": "run-map-1",
                "observed_coordinator_host_id": "host-1",
                "observed_coordinator_terminal_handle": "term-1",
                "writer_active": False,
            },
        }
    )
    expect(
        cli_recovery == {"status": "ready", "run_id": "run-map-1", "create_run": False},
        "production apply request must consume the persisted map identity",
    )
    attempt_recovery = recover_attempt(
        bound_lane,
        observed_coordinates={
            "dispatch_id": "dispatch-1",
            "terminal_handle": "term-1",
            "worktree_selector": "selector-1",
            "execution_host": "host-1",
            "attempt_index": 0,
        },
        writer_active=False,
    )
    expect(
        attempt_recovery["status"] == "ready"
        and not attempt_recovery["create_dispatch"],
        "same Dispatch attempt recovery must not create another Dispatch",
    )
    attempt_conflict = recover_attempt(
        bound_lane,
        observed_coordinates={
            "dispatch_id": "dispatch-2",
            "terminal_handle": "term-1",
            "worktree_selector": "selector-1",
            "execution_host": "host-1",
            "attempt_index": 0,
        },
        writer_active=False,
    )
    expect(
        attempt_conflict["status"] == "blocked"
        and not attempt_conflict["create_dispatch"],
        "different Dispatch attempt must fail closed",
    )
    rebound_map = rebind_map_coordinator(
        bound_map,
        observed_run_id="run-map-1",
        coordinator_host_id="host-2",
        coordinator_terminal_handle="term-2",
        writer_active=False,
    )
    expect(
        recover_map(
            rebound_map,
            observed_run_id="run-map-1",
            observed_coordinator_host_id="host-2",
            observed_coordinator_terminal_handle="term-2",
            writer_active=False,
        )["status"]
        == "ready",
        "coordinator takeover must preserve the Run identity",
    )
    try:
        rebind_map_coordinator(
            bound_map,
            observed_run_id="run-map-1",
            coordinator_host_id="host-2",
            coordinator_terminal_handle="term-2",
            writer_active=True,
        )
    except OverlayConflict:
        pass
    else:
        raise AssertionError("active old coordinator must block takeover")

    applied_then_lost = {"row": lane}

    def write_then_raise(value: dict[str, Any]) -> None:
        applied_then_lost["row"] = value
        raise RuntimeError("response lost")

    expect(
        persist_overlay(
            lane,
            bound_lane,
            readback=lambda: applied_then_lost["row"],
            write=write_then_raise,
        )
        == bound_lane,
        "lost write response must recover from exact readback",
    )
    write_calls = 0

    def reject_write(value: dict[str, Any]) -> None:
        nonlocal write_calls
        write_calls += 1
        raise RuntimeError("write rejected")

    try:
        persist_overlay(
            lane,
            bound_lane,
            readback=lambda: lane,
            write=reject_write,
        )
    except OverlayPersistError as error:
        expect(error.observed == lane, "failed write must preserve last readback")
    else:
        raise AssertionError("failed write must remain blocked")
    expect(write_calls == 1, "unknown write outcome must not be retried")

    divergent = copy.deepcopy(bound_lane)
    divergent["orca"]["observation"] = None
    readbacks = iter((lane, divergent))
    write_calls = 0

    def accepted_write(value: dict[str, Any]) -> None:
        nonlocal write_calls
        write_calls += 1

    try:
        persist_overlay(
            lane,
            bound_lane,
            readback=lambda: next(readbacks),
            write=accepted_write,
        )
    except OverlayPersistError as error:
        expect(
            error.observed == divergent,
            "post-write mismatch must preserve the divergent readback",
        )
    else:
        raise AssertionError("post-write mismatch must remain blocked")
    expect(write_calls == 1, "post-write mismatch must not rewrite")


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "self-test":
        _self_test()
        print("orca overlay: pass")
        return 0
    if len(sys.argv) == 3 and sys.argv[1] == "apply":
        try:
            request = json.loads(Path(sys.argv[2]).read_text())
            result = apply_request(request)
        except (OSError, json.JSONDecodeError, OverlayError, TypeError) as error:
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
        f"Usage: {sys.argv[0]} self-test | apply <absolute-request.json>",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
