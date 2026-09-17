#!/usr/bin/env python3
"""Orca Phase 2B provider mutation 薄层门禁（tracker/artifact/PR-MR）。

只核验 caller-declared capability/identity/readback 的结构与绑定，不执行
gh/Linear/provider 命令、不写 registry、不另建 request/receipt 数据库。
所有返回 `authority: false`、`mutations: []`、
`project_lane_transition: unchanged`；权限/网络失败、Unknown response 与
重复 request 均 fail-closed，只阻塞当前 Phase 2 operation，
不回改 Phase 1 本地交付证据。provider 状态变化永不替代 project-side gate。
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import registry_overlay as REGISTRY
import worker_lifecycle as WORKER

Error = WORKER.WorkerLifecycleError
text = WORKER._known_text
boolean = WORKER._known_bool
at = WORKER._at
readable = WORKER._readable_absolute
read_json = WORKER._read_json_object

OPERATIONS = frozenset(
    {
        "tracker-read",
        "tracker-mutate",
        "artifact-publish",
        "artifact-read",
        "artifact-archive",
        "artifact-delete",
        "pr-ready",
        "verify-result",
    }
)

PROVIDERS = frozenset({"github", "linear"})

# 每个 provider 的命令闭集：未声明的 provider operation 不得猜测。
READ_COMMANDS = {
    "github": frozenset({"gh issue view", "gh issue list", "gh pr view", "gh api"}),
    "linear": frozenset({"linear issue view", "linear issue list"}),
}
MUTATE_COMMANDS = {
    "github": frozenset(
        {"gh issue comment", "gh issue edit", "gh issue close", "gh api"}
    ),
    "linear": frozenset({"linear issue update", "linear comment create"}),
}
PR_READY_COMMANDS = {
    "github": frozenset({"gh pr ready"}),
    "linear": frozenset(),
}
PUBLISH_OUTPUT_MODES = frozenset({"artifact", "checks", "verdict"})


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise Error(reason)


def mapping(value: Any, field: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{field} 必须是 object")
    return value


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
    request: dict[str, Any], allowed: dict[str, frozenset[str]]
) -> dict[str, Any]:
    """provider-scoped capability/identity/authority 前置核验。

    每种 provider operation 执行前核对：版本匹配 CLI reference、登录身份、
    目标坐标所属 provider 与命令闭集。缺失时只阻塞当前 operation。
    """
    capability = mapping(request.get("capability"), "capability")
    provider = text(capability.get("provider"), "capability.provider")
    require(provider in PROVIDERS, f"未知 provider {provider!r}")
    require(provider in allowed, f"operation 不支持 provider {provider!r}")
    command = text(capability.get("command"), "capability.command")
    require(
        command in allowed[provider],
        f"provider {provider} 不允许命令 {command!r}（闭集外）",
    )
    text(capability.get("reference"), "capability.reference")
    version_path = readable(
        capability.get("cli_version_readback"), "capability.cli_version_readback"
    )
    require(
        bool(Path(version_path).read_text(encoding="utf-8").strip()),
        "capability.cli_version_readback 为空",
    )
    _, identity = read_json(
        capability.get("identity_readback"), "capability.identity_readback"
    )
    expected = text(capability.get("expected_identity"), "capability.expected_identity")
    login = identity.get("login") or identity.get("viewer", {})
    if isinstance(login, dict):
        login = login.get("login")
    require(
        login == expected,
        f"provider 登录身份 {login!r} 与声明 {expected!r} 不一致",
    )
    return capability


def check_authorization(request: dict[str, Any]) -> None:
    authorization = mapping(request.get("authorization"), "authorization")
    require(
        boolean(authorization.get("approved"), "authorization.approved"),
        "authorization.approved 必须为 true",
    )
    text(authorization.get("scope"), "authorization.scope")
    readable(authorization.get("evidence"), "authorization.evidence")


def check_target(request: dict[str, Any], capability: dict[str, Any]) -> None:
    target = mapping(request.get("target"), "target")
    text(target.get("repository"), "target.repository")
    if capability["command"] == "gh api":
        method = text(target.get("method"), "target.method").upper()
        require(
            method in {"GET", "POST", "PATCH", "DELETE"},
            f"gh api method {method!r} 未声明或不受支持",
        )
        text(target.get("endpoint"), "target.endpoint")


def idempotency_marker(key: str) -> str:
    return f"dp-idem:{key}"


def check_idempotency(request: dict[str, Any], lane: dict[str, Any]) -> str:
    """稳定 key 绑定 map/work item/lane；retry 只接受 readback-first。"""
    idempotency = mapping(request.get("idempotency"), "idempotency")
    key = text(idempotency.get("key"), "idempotency.key")
    require(
        lane["map"] in key or lane["work_item"] in key,
        "idempotency.key 必须可关联到 map/work item",
    )
    require(
        idempotency.get("retry_rule") == "readback-first",
        "幂等 retry 只接受 readback-first，response 丢失不盲重发",
    )
    return key


def resume_flag(request: dict[str, Any]) -> bool:
    value = request.get("resume")
    require(value is None or type(value) is bool, "resume 必须是 boolean")
    return bool(value)


def dedupe_marker(request: dict[str, Any], marker: str) -> list[str]:
    """在 provider readback 中查找幂等 marker；response-lost 恢复的唯一依据。"""
    dedupe = mapping(request.get("dedupe"), "dedupe")
    path = readable(dedupe.get("readback"), "dedupe.readback")
    content = Path(path).read_text(encoding="utf-8")
    return [line for line in content.splitlines() if marker in line] or (
        [content] if marker in content else []
    )


def tracker_read(request: dict[str, Any]) -> dict[str, Any]:
    capability = check_capability(request, READ_COMMANDS)
    if capability["command"] == "gh api":
        target = mapping(request.get("target"), "target")
        require(
            text(target.get("method"), "target.method").upper() == "GET",
            "tracker-read 的 gh api 只允许 GET",
        )
    check_target(request, capability)
    return result(request, "ready", action="execute-readonly")


def tracker_mutate(request: dict[str, Any], lane: dict[str, Any]) -> dict[str, Any]:
    capability = check_capability(request, MUTATE_COMMANDS)
    check_authorization(request)
    check_target(request, capability)
    key = check_idempotency(request, lane)
    marker = idempotency_marker(key)
    hits = dedupe_marker(request, marker)
    if hits:
        require(
            resume_flag(request) and len(hits) == 1,
            "readback 已存在相同幂等 marker 且非 response-lost 恢复，禁止盲重发",
        )
        return result(request, "ready", action="consume-existing-mutation")
    require(not resume_flag(request), "resume 恢复但 readback 中没有该幂等 marker")
    return result(request, "ready", action="execute-idempotent-mutation")


def check_artifact(request: dict[str, Any]) -> dict[str, Any]:
    artifact = mapping(request.get("artifact"), "artifact")
    path = readable(artifact.get("path"), "artifact.path")
    text(artifact.get("kind"), "artifact.kind")
    declared = text(artifact.get("sha256"), "artifact.sha256")
    actual = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    require(
        declared == actual,
        "artifact.sha256 与文件内容不一致（publish/read 边界不匹配）",
    )
    return artifact


def artifact_publish(request: dict[str, Any], lane: dict[str, Any]) -> dict[str, Any]:
    check_authorization(request)
    check_idempotency(request, lane)
    artifact = check_artifact(request)
    output_mode = text(request.get("output_mode"), "output_mode")
    require(
        output_mode in PUBLISH_OUTPUT_MODES,
        f"output_mode {output_mode!r} 不允许 artifact publish",
    )
    destination = mapping(request.get("destination"), "destination")
    require(
        Path(text(destination.get("dir"), "destination.dir")).is_absolute(),
        "destination.dir 必须是绝对路径",
    )
    dedupe = mapping(request.get("dedupe"), "dedupe")
    _, listing = read_json(dedupe.get("listing_readback"), "dedupe.listing_readback")
    entries = listing.get("artifacts")
    require(isinstance(entries, list), "listing readback 缺 artifacts list")
    name = Path(artifact["path"]).name
    same_name = [
        entry
        for entry in entries or []
        if isinstance(entry, dict) and entry.get("name") == name
    ]
    if same_name:
        identical = [
            entry
            for entry in same_name or []
            if entry.get("sha256") == artifact["sha256"]
        ]
        require(
            bool(identical) and len(same_name) == len(identical),
            "destination 存在同名不同内容的 artifact，禁止盲覆盖",
        )
        return result(request, "ready", action="deduplicated")
    return result(request, "ready", action="publish-artifact")


def artifact_read(request: dict[str, Any]) -> dict[str, Any]:
    check_artifact(request)
    return result(request, "ready", action="execute-readonly")


def artifact_retire(request: dict[str, Any], action: str) -> dict[str, Any]:
    check_authorization(request)
    artifact = mapping(request.get("artifact"), "artifact")
    require(
        Path(text(artifact.get("path"), "artifact.path")).is_absolute(),
        "artifact.path 必须是绝对路径",
    )
    cleanup = mapping(request.get("cleanup_gate"), "cleanup_gate")
    text(cleanup.get("verdict"), "cleanup_gate.verdict")
    readable(cleanup.get("evidence"), "cleanup_gate.evidence")
    review = mapping(request.get("review_evidence"), "review_evidence")
    readable(review.get("verdict"), "review_evidence.verdict")
    return result(request, "ready", action=action)


def pr_ready(request: dict[str, Any], lane: dict[str, Any]) -> dict[str, Any]:
    capability = check_capability(request, PR_READY_COMMANDS)
    check_authorization(request)
    check_target(request, capability)
    check_idempotency(request, lane)
    target = mapping(request.get("target"), "target")
    require(
        isinstance(target.get("pull_request"), int) and target["pull_request"] > 0,
        "target.pull_request 必须是正整数",
    )
    _, envelope = read_json(request.get("state_readback"), "state_readback")
    state = str(envelope.get("state", "")).upper()
    require(state == "OPEN", f"PR 当前状态 {state or 'Unknown'}，不盲操作")
    if not envelope.get("isDraft", True):
        return result(request, "ready", action="deduplicated")
    return result(request, "ready", action="mark-ready-for-review")


def verify_result(request: dict[str, Any]) -> dict[str, Any]:
    evidence = mapping(request.get("evidence"), "evidence")
    outcome = evidence.get("outcome")
    require(
        isinstance(outcome, str)
        and outcome.strip().lower()
        in {"success", "failed", "unknown", "timeout", "network-loss"},
        "evidence.outcome 必须是 success/failed/unknown/timeout/network-loss",
    )
    require(
        outcome == "success",
        f"operation 结果为 {outcome}：fail-closed，不修改 project completion state",
    )
    readable(evidence.get("mutation_receipt"), "evidence.mutation_receipt")
    _, readback = read_json(evidence.get("result_readback"), "evidence.result_readback")
    marker = evidence.get("idempotency_key")
    if marker is not None:
        require(
            idempotency_marker(text(marker, "evidence.idempotency_key"))
            in json.dumps(readback, ensure_ascii=False),
            "result readback 不含声明的幂等 marker（证据无法关联 request）",
        )
    artifacts = evidence.get("artifacts")
    require(isinstance(artifacts, list), "evidence.artifacts 必须是 list")
    for path in artifacts or []:
        readable(path, "evidence.artifacts[]")
    text(evidence.get("captured_at"), "evidence.captured_at")
    return result(request, "ready", action="evidence-bound")


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
        handlers = {
            "tracker-read": lambda: tracker_read(request),
            "tracker-mutate": lambda: tracker_mutate(request, lane),
            "artifact-publish": lambda: artifact_publish(request, lane),
            "artifact-read": lambda: artifact_read(request),
            "artifact-archive": lambda: artifact_retire(request, "archive-artifact"),
            "artifact-delete": lambda: artifact_retire(request, "delete-artifact"),
            "pr-ready": lambda: pr_ready(request, lane),
            "verify-result": lambda: verify_result(request),
        }
        return handlers[operation]()
    except (Error, KeyError, REGISTRY.OverlayError) as error:
        return result(request, "blocked", reason=str(error))


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] != "check":
        print(
            "usage: provider_mutation.py check <absolute-request.json>", file=sys.stderr
        )
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
