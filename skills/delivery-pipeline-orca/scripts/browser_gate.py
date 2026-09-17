#!/usr/bin/env python3
"""Orca Phase 2A browser/automation operation 薄层门禁。

只核验 caller-declared capability/readback 的结构与绑定，不执行 Orca 命令、
不写 registry、不另建 receipt/job 数据库。所有返回 `authority: false`、
`mutations: []`、`project_lane_transition: unchanged`；Unknown/timeout/host-loss
均 fail-closed，只阻塞当前 Phase 2 operation，不回改 Phase 1 本地证据。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import registry_overlay as REGISTRY
import worker_lifecycle as WORKER

Error = WORKER.WorkerLifecycleError
text = WORKER._known_text
at = WORKER._at
readable = WORKER._readable_absolute
read_json = WORKER._read_json_object

# 只读命令闭集：不修改页面/浏览器外部状态，不新增用户确认。
READ_COMMANDS = frozenset(
    {
        "snapshot",
        "screenshot",
        "get",
        "is",
        "find",
        "tab list",
        "tab show",
        "tab current",
        "tab profile list",
        "tab profile show",
        "automations list",
        "automations runs",
        "automations show",
    }
)
# 导航/本地视图状态：可重试，但 retry 必须先 readback（readback-first）。
NAVIGATE_COMMANDS = frozenset(
    {
        "tab create",
        "goto",
        "reload",
        "back",
        "forward",
        "wait",
        "tab switch",
        "tab close",
        "scroll",
        "scrollintoview",
        "hover",
        "focus",
        "set device",
        "set offline",
        "set headers",
    }
)
# 可能修改外部数据或发出外部消息的命令：必须核对既有明确授权。
WRITE_COMMANDS = frozenset(
    {
        "click",
        "dblclick",
        "fill",
        "type",
        "inserttext",
        "select",
        "check",
        "uncheck",
        "clear",
        "upload",
        "eval",
        "keypress",
        "drag",
        "mouse move",
        "mouse down",
        "mouse up",
        "mouse wheel",
    }
)
ARTIFACT_COMMANDS = frozenset({"screenshot"})

OPERATIONS = frozenset(
    {
        "browser-read",
        "browser-navigate",
        "browser-write",
        "automation-create",
        "automation-run",
        "automation-pause",
        "verify-result",
    }
)

IN_FLIGHT = frozenset(
    {"running", "pending", "queued", "in_progress", "dispatching", "dispatched"}
)


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise Error(reason)


boolean = WORKER._known_bool


def mapping(value: Any, field: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{field} 必须是 object")
    return value


def ok_envelope(envelope: dict[str, Any], field: str) -> None:
    require(boolean(envelope.get("ok"), f"{field}.ok"), f"{field} 不是 ok envelope")


def host_capability(envelope: dict[str, Any], required: Any, field: str) -> None:
    """声明 require 时，目标 host readback 必须含对应版本 capability。"""
    if required is None:
        return
    name = text(required, f"{field}.require")
    capabilities = at(envelope, ("result", "runtime", "capabilities"), field)
    require(
        isinstance(capabilities, list) and name in capabilities,
        f"目标 host 缺 capability {name}（不能以本地 capability 宣布代替）",
    )


def result(
    request: dict[str, Any],
    status: str,
    action: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    output = {
        "status": status,
        "operation": request.get("operation"),
        "authority": False,
        "mutations": [],
        "project_lane_transition": "unchanged",
        "scope": "phase2-operation-only",
    }
    if action:
        output["action"] = action
    if reason:
        output["reason"] = reason
    return output


def lane_row(request: dict[str, Any]) -> dict[str, Any]:
    lane = REGISTRY.validate_markers(request["lane"], kind="lane")
    for field in ("lane_id", "work_item", "worktree", "branch", "agent"):
        text(lane.get(field), field)
    orca = lane["orca"]
    for field in ("run_id", "task_id"):
        text(orca.get(field), f"lane.orca.{field}")
    for field in REGISTRY.ATTEMPT_FIELDS:
        if field == "attempt_index":
            require(
                isinstance(orca.get(field), int) and orca[field] >= 0,
                "lane.orca.attempt_index 必须是非负整数",
            )
        else:
            text(orca.get(field), f"lane.orca.{field}")
    return lane


def check_binding(request: dict[str, Any], lane: dict[str, Any]) -> None:
    binding = mapping(request.get("binding"), "binding")
    require(
        text(binding.get("lane_id"), "binding.lane_id") == lane["lane_id"]
        and text(binding.get("work_item"), "binding.work_item") == lane["work_item"],
        "binding 与 lane 的 lane_id/work_item 不一致",
    )
    orca = lane["orca"]
    for field in (
        "run_id",
        "task_id",
        "dispatch_id",
        "terminal_handle",
        "execution_host",
    ):
        require(
            text(binding.get(field), f"binding.{field}") == orca[field],
            f"binding.{field} 与 lane attempt 不一致",
        )


def check_capability(
    request: dict[str, Any], allowed: frozenset[str]
) -> dict[str, Any]:
    capability = mapping(request.get("capability"), "capability")
    command = text(capability.get("command"), "capability.command")
    require(command in allowed, f"operation 不允许命令 {command!r}（闭集外）")
    text(capability.get("reference"), "capability.reference")
    runtime = text(capability.get("runtime_id"), "capability.runtime_id")
    _, schema = read_json(capability.get("schema"), "capability.schema")
    require(
        isinstance(schema.get("schemaVersion"), int) and schema["schemaVersion"] >= 1,
        "capability.schema 缺 schemaVersion",
    )
    commands = schema.get("commands")
    require(
        isinstance(commands, list)
        and any(
            isinstance(entry, dict) and entry.get("command") == command
            for entry in commands
        ),
        f"目标 host 版本匹配 schema 不含命令 {command!r}（capability 缺失）",
    )
    _, envelope = read_json(capability.get("host_readback"), "capability.host_readback")
    ok_envelope(envelope, "capability.host_readback")
    require(
        at(envelope, ("_meta", "runtimeId"), "capability.host_readback") == runtime,
        "host readback runtime 与声明不一致：不能用本地 capability 宣布代替目标证据",
    )
    host_capability(envelope, capability.get("require"), "capability.host_readback")
    return capability


def check_authorization(request: dict[str, Any]) -> None:
    authorization = mapping(request.get("authorization"), "authorization")
    require(
        boolean(authorization.get("approved"), "authorization.approved"),
        "authorization.approved 必须为 true",
    )
    text(authorization.get("scope"), "authorization.scope")
    readable(authorization.get("evidence"), "authorization.evidence")


def check_idempotency(request: dict[str, Any]) -> None:
    idempotency = mapping(request.get("idempotency"), "idempotency")
    text(idempotency.get("key"), "idempotency.key")
    require(
        idempotency.get("retry_rule") == "readback-first",
        "幂等 retry 只接受 readback-first，不允许盲重发",
    )
    prior = idempotency.get("prior_readback")
    if prior is not None:
        _, envelope = read_json(prior, "idempotency.prior_readback")
        ok_envelope(envelope, "idempotency.prior_readback")


def check_target_url(request: dict[str, Any], *, required: bool) -> None:
    target = request.get("target")
    if target is None:
        require(not required, "target.url 缺失")
        return
    target = mapping(target, "target")
    text(target.get("url"), "target.url")


def browser_read(request: dict[str, Any]) -> dict[str, Any]:
    capability = check_capability(request, READ_COMMANDS)
    if capability["command"] in ARTIFACT_COMMANDS:
        artifact = request.get("artifact")
        require(artifact is not None, f"{capability['command']} 必须声明 artifact")
        artifact = mapping(artifact, "artifact")
        require(
            Path(text(artifact.get("path"), "artifact.path")).is_absolute(),
            "artifact.path 必须是绝对路径",
        )
        text(artifact.get("kind"), "artifact.kind")
    return result(request, "ready", action="execute-readonly")


def browser_navigate(request: dict[str, Any]) -> dict[str, Any]:
    capability = check_capability(request, NAVIGATE_COMMANDS)
    check_idempotency(request)
    check_target_url(request, required=capability["command"] in {"tab create", "goto"})
    return result(request, "ready", action="execute-navigate")


def browser_write(request: dict[str, Any]) -> dict[str, Any]:
    check_capability(request, WRITE_COMMANDS)
    check_authorization(request)
    check_idempotency(request)
    check_target_url(request, required=False)
    return result(request, "ready", action="execute-authorized-write")


def _automation_entries(envelope: dict[str, Any]) -> list[dict[str, Any]]:
    items = at(envelope, ("result",), "automations readback")
    entries = items.get("automations") or items.get("items") or []
    require(isinstance(entries, list), "automations readback 缺 list 字段")
    return [entry for entry in entries if isinstance(entry, dict)]


def resume_flag(request: dict[str, Any]) -> bool:
    value = request.get("resume")
    require(value is None or type(value) is bool, "resume 必须是 boolean")
    return bool(value)


def automation_create(request: dict[str, Any]) -> dict[str, Any]:
    check_capability(request, frozenset({"automations create"}))
    check_authorization(request)
    automation = mapping(request.get("automation"), "automation")
    name = text(automation.get("name"), "automation.name")
    schedule = mapping(automation.get("schedule"), "automation.schedule")
    kind = text(schedule.get("kind"), "automation.schedule.kind")
    require(kind in {"one-shot", "interval"}, "schedule.kind 只接受 one-shot/interval")
    if kind == "interval":
        require(
            schedule.get("ends_at") or isinstance(schedule.get("max_runs"), int),
            "interval automation 必须有 ends_at/max_runs，禁止无界 recurring scheduler",
        )
    dedupe = mapping(request.get("dedupe"), "dedupe")
    _, envelope = read_json(dedupe.get("list_readback"), "dedupe.list_readback")
    ok_envelope(envelope, "dedupe.list_readback")
    existing = [
        entry for entry in _automation_entries(envelope) if entry.get("name") == name
    ]
    if existing:
        require(
            resume_flag(request) and len(existing) == 1,
            "同名 automation 已存在且非 response-lost 恢复，禁止重复创建",
        )
        return result(request, "ready", action="consume-existing-automation")
    require(not resume_flag(request), "resume 恢复但读回中没有同名 automation")
    return result(request, "ready", action="create-bounded-automation")


def automation_run(request: dict[str, Any]) -> dict[str, Any]:
    check_capability(request, frozenset({"automations run"}))
    check_authorization(request)
    automation_id = text(request.get("automation_id"), "automation_id")
    dedupe = mapping(request.get("dedupe"), "dedupe")
    _, envelope = read_json(dedupe.get("runs_readback"), "dedupe.runs_readback")
    ok_envelope(envelope, "dedupe.runs_readback")
    runs = at(envelope, ("result", "runs"), "dedupe.runs_readback")
    require(isinstance(runs, list), "runs readback 缺 runs list")
    active = [
        run
        for run in runs
        if isinstance(run, dict)
        and run.get("automationId") == automation_id
        and run.get("status") in IN_FLIGHT
    ]
    if active:
        require(
            resume_flag(request) and len(active) == 1,
            "同一 automation 已有在途 job，重复触发必须先读回",
        )
        return result(request, "ready", action="consume-existing-job")
    require(not resume_flag(request), "resume 恢复但读回中没有在途 job")
    return result(request, "ready", action="trigger-automation")


def automation_pause(request: dict[str, Any]) -> dict[str, Any]:
    check_capability(request, frozenset({"automations edit"}))
    check_authorization(request)
    automation_id = text(request.get("automation_id"), "automation_id")
    _, envelope = read_json(request.get("state_readback"), "state_readback")
    ok_envelope(envelope, "state_readback")
    current = at(envelope, ("result", "automation"), "state_readback")
    require(
        current.get("id") == automation_id, "state readback 的 automation id 不一致"
    )
    require(
        boolean(current.get("enabled"), "state_readback.enabled"),
        "automation 当前不在 active 状态，不盲暂停",
    )
    return result(request, "ready", action="pause-automation")


def verify_result(request: dict[str, Any]) -> dict[str, Any]:
    capability = check_capability(
        request, READ_COMMANDS | NAVIGATE_COMMANDS | WRITE_COMMANDS
    )
    evidence = mapping(request.get("evidence"), "evidence")
    outcome = evidence.get("outcome")
    require(
        isinstance(outcome, str)
        and outcome.strip().lower()
        in {"success", "failed", "unknown", "timeout", "host-loss"},
        "evidence.outcome 必须是 success/failed/unknown/timeout/host-loss",
    )
    require(
        outcome == "success",
        f"operation 结果为 {outcome}：fail-closed，不修改 project completion state",
    )
    _, receipt = read_json(evidence.get("input_receipt"), "evidence.input_receipt")
    ok_envelope(receipt, "evidence.input_receipt")
    _, readback = read_json(evidence.get("result_readback"), "evidence.result_readback")
    ok_envelope(readback, "evidence.result_readback")
    runtime = capability["runtime_id"]
    for field, envelope in (
        ("evidence.input_receipt", receipt),
        ("evidence.result_readback", readback),
    ):
        require(
            at(envelope, ("_meta", "runtimeId"), field) == runtime,
            f"{field} 的 runtime 与 capability 目标不一致",
        )
    artifacts = evidence.get("artifacts")
    require(isinstance(artifacts, list), "evidence.artifacts 必须是 list")
    for path in artifacts or []:
        readable(path, "evidence.artifacts[]")
    text(evidence.get("captured_at"), "evidence.captured_at")
    return result(request, "ready", action="evidence-bound")


HANDLERS = {
    "browser-read": browser_read,
    "browser-navigate": browser_navigate,
    "browser-write": browser_write,
    "automation-create": automation_create,
    "automation-run": automation_run,
    "automation-pause": automation_pause,
    "verify-result": verify_result,
}


def validate(request: Any) -> dict[str, Any]:
    if not isinstance(request, dict):
        return {
            "status": "blocked",
            "operation": None,
            "reason": "request 必须是 object",
            "authority": False,
            "mutations": [],
            "project_lane_transition": "unchanged",
            "scope": "phase2-operation-only",
        }
    try:
        operation = text(request.get("operation"), "operation")
        require(operation in OPERATIONS, f"未知 operation {operation!r}")
        lane = lane_row(request)
        check_binding(request, lane)
        return HANDLERS[operation](request)
    except (Error, KeyError, REGISTRY.OverlayError) as error:
        return result(request, "blocked", reason=str(error))


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] != "check":
        print("usage: browser_gate.py check <absolute-request.json>", file=sys.stderr)
        return 2
    try:
        _, request = read_json(sys.argv[2], "request")
        output = validate(request)
    except Error as error:
        output = {
            "status": "blocked",
            "operation": None,
            "reason": str(error),
            "authority": False,
            "mutations": [],
            "project_lane_transition": "unchanged",
            "scope": "phase2-operation-only",
        }
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0 if output["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
