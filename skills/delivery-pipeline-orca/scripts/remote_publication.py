#!/usr/bin/env python3
"""Orca Phase 4 remote publication 薄层门禁（push/PR-MR/merge/closeout）。

只核验 caller-declared capability/identity/授权/幂等/readback 的结构与绑定，
不执行 git push、gh pr create/merge 或 cleanup 命令、不写 registry、不另建
request/receipt 数据库。所有返回 `authority: false`、`mutations: []`、
`project_lane_transition: unchanged`、`scope: phase4-publication-only`；
权限/网络失败、Unknown response 与重复 request 均 fail-closed，只阻塞当前
Phase 4 operation，不回改已完成的 Phase 1-3 证据。push、PR/MR 与 merge 状态
变化永不替代 project-side ticket、Integration、testing 或 review gate。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, cast

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
        "publication-read",
        "branch-push",
        "pr-create",
        "pr-update",
        "pr-merge",
        "remote-closeout",
        "verify-result",
    }
)

PROVIDERS = frozenset({"github", "linear"})

# 每种 provider 的命令闭集：未声明的 provider operation 不得猜测。
READ_COMMANDS = {
    "github": frozenset(
        {
            "git ls-remote",
            "git status",
            "git rev-parse",
            "git log",
            "gh pr view",
            "gh pr list",
            "gh api",
        }
    ),
    "linear": frozenset(),
}
PUSH_COMMANDS = {
    "github": frozenset({"git push"}),
    "linear": frozenset(),
}
PR_CREATE_COMMANDS = {
    "github": frozenset({"gh pr create"}),
    "linear": frozenset(),
}
PR_UPDATE_COMMANDS = {
    "github": frozenset({"gh pr edit", "gh api"}),
    "linear": frozenset(),
}
PR_MERGE_COMMANDS = {
    "github": frozenset({"gh pr merge"}),
    "linear": frozenset(),
}
CLOSEOUT_COMMANDS = {
    "github": frozenset({"git push", "gh api"}),
    "linear": frozenset(),
}
MERGE_METHODS = frozenset({"merge", "squash", "rebase"})


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
        "scope": "phase4-publication-only",
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

    每种 publication operation 执行前核对：版本匹配 CLI reference、登录身份、
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
    """push/PR-MR/merge/closeout 授权与 tracker/artifact 授权独立，不复用。

    `authorization.operation_authority` 必须唯一列出本 operation 的
    authority 来源（packet 范围、用户确认 artifact）；缺失即 blocked，
    不由 capability 或 spec 标签自动授予 push/merge 权限。
    """
    authorization = mapping(request.get("authorization"), "authorization")
    require(
        boolean(authorization.get("approved"), "authorization.approved"),
        "authorization.approved 必须为 true",
    )
    text(authorization.get("scope"), "authorization.scope")
    readable(authorization.get("evidence"), "authorization.evidence")
    text(
        authorization.get("operation_authority"),
        "authorization.operation_authority",
    )


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


def check_fan_in(request: dict[str, Any]) -> None:
    """merge/closeout 前置：Phase 1-3 的 project-side fan-in 证据可读且完整。

    只验证存在性与完整性，不回改、不判定既有 Phase 1-3 结果；任何缺失
    或 Unknown 只阻塞当前 Phase 4 operation。
    """
    fan_in = mapping(request.get("fan_in"), "fan_in")
    for field in (
        "integration",
        "testing",
        "review",
        "artifacts",
        "tracker",
        "cleanup",
    ):
        readable(fan_in.get(field), f"fan_in.{field}")


def check_local_state(request: dict[str, Any]) -> dict[str, Any]:
    local = mapping(request.get("local_state"), "local_state")
    text(local.get("branch"), "local_state.branch")
    head = text(local.get("head"), "local_state.head")
    readable(local.get("status_readback"), "local_state.status_readback")
    readable(local.get("rev_parse_readback"), "local_state.rev_parse_readback")
    return local


def remote_ref(readback: dict[str, Any], branch: str) -> str | None:
    refs = readback.get("refs")
    require(isinstance(refs, dict), "remote ref readback 缺 refs object")
    refs_dict = cast("dict[str, Any]", refs)
    value = refs_dict.get(branch)
    require(value is None or isinstance(value, str), f"refs.{branch} 必须是文本")
    return value


def publication_read(request: dict[str, Any]) -> dict[str, Any]:
    capability = check_capability(request, READ_COMMANDS)
    if capability["command"] == "gh api":
        target = mapping(request.get("target"), "target")
        require(
            text(target.get("method"), "target.method").upper() == "GET",
            "publication-read 的 gh api 只允许 GET",
        )
    check_target(request, capability)
    return result(request, "ready", action="execute-readonly")


def branch_push(request: dict[str, Any], lane: dict[str, Any]) -> dict[str, Any]:
    check_capability(request, PUSH_COMMANDS)
    check_authorization(request)
    check_target(request, mapping(request.get("capability"), "capability"))
    check_idempotency(request, lane)
    local = check_local_state(request)
    require(local["branch"] == lane["branch"], "push branch 与 lane branch 不一致")
    _, readback = read_json(request.get("remote_readback"), "remote_readback")
    remote = remote_ref(readback, local["branch"])
    if remote == local["head"]:
        return result(request, "ready", action="deduplicated")
    if remote is None:
        return result(request, "ready", action="push-new-branch")
    _, ancestry = read_json(request.get("ancestry_readback"), "ancestry_readback")
    require(
        ancestry.get("ancestor") == remote and ancestry.get("descendant") == local["head"],
        "remote ref 不是 local HEAD 祖先（non-fast-forward），禁止盲 force-push",
    )
    return result(request, "ready", action="push-fast-forward")


def pr_state(request: dict[str, Any], field: str = "pr_readback") -> dict[str, Any]:
    _, envelope = read_json(request.get(field), field)
    require(isinstance(envelope, dict), f"{field} 必须是 JSON object")
    return envelope


def branch_of(request: dict[str, Any], lane: dict[str, Any]) -> str:
    branch = mapping(request.get("branch"), "branch")
    head = text(branch.get("head"), "branch.head")
    text(branch.get("base"), "branch.base")
    require(head == lane["branch"], "PR head branch 与 lane branch 不一致")
    return head


def find_existing_pr(readback: dict[str, Any], head: str) -> list[dict[str, Any]]:
    prs = readback.get("prs")
    require(isinstance(prs, list), "existing_pr_readback 缺 prs list")
    prs_list = cast("list[Any]", prs)
    return [
        pr
        for pr in prs_list
        if isinstance(pr, dict)
        and pr.get("headRefName") == head
        and str(pr.get("state", "")).upper() == "OPEN"
    ]


def pr_create(request: dict[str, Any], lane: dict[str, Any]) -> dict[str, Any]:
    check_capability(request, PR_CREATE_COMMANDS)
    check_authorization(request)
    check_target(request, mapping(request.get("capability"), "capability"))
    key = check_idempotency(request, lane)
    marker = idempotency_marker(key)
    head = branch_of(request, lane)
    _, readback = read_json(
        request.get("existing_pr_readback"), "existing_pr_readback"
    )
    existing = find_existing_pr(readback, head)
    if existing:
        require(
            resume_flag(request) and len(existing) == 1,
            "同 head branch 已存在 OPEN PR 且非 response-lost 恢复，禁止重复创建",
        )
        number = existing[0].get("number")
        require(
            isinstance(number, int) and number > 0,
            "existing PR readback 缺有效 number，无法恢复",
        )
        require(
            marker in json.dumps(existing[0], ensure_ascii=False),
            "response-lost 恢复但 existing PR 不含声明的幂等 marker",
        )
        return result(request, "ready", action="consume-existing-pr")
    require(
        not resume_flag(request), "resume 恢复但 readback 中没有该 head 的 OPEN PR"
    )
    pushed = pr_state(request, "push_readback")
    require(
        pushed.get("refs", {}).get(head) is not None,
        "push readback 未包含 head branch 的 remote ref，先 push 再创建 PR",
    )
    return result(request, "ready", action="create-pr")


def pr_update(request: dict[str, Any], lane: dict[str, Any]) -> dict[str, Any]:
    capability = check_capability(request, PR_UPDATE_COMMANDS)
    check_authorization(request)
    check_target(request, capability)
    key = check_idempotency(request, lane)
    marker = idempotency_marker(key)
    branch_of(request, lane)
    target = mapping(request.get("target"), "target")
    require(
        isinstance(target.get("pull_request"), int) and target["pull_request"] > 0,
        "target.pull_request 必须是正整数",
    )
    current = pr_state(request)
    state = str(current.get("state", "")).upper()
    require(state == "OPEN", f"PR 当前状态 {state or 'Unknown'}，不盲更新")
    if marker in json.dumps(current, ensure_ascii=False):
        require(
            resume_flag(request),
            "readback 已存在相同幂等 marker 且非 response-lost 恢复，禁止盲重发",
        )
        return result(request, "ready", action="deduplicated")
    require(not resume_flag(request), "resume 恢复但 readback 中没有该幂等 marker")
    return result(request, "ready", action="update-pr")


def check_pr_evidence(request: dict[str, Any]) -> None:
    evidence = mapping(request.get("pr_evidence"), "pr_evidence")
    readable(evidence.get("ci"), "pr_evidence.ci")
    readable(evidence.get("review"), "pr_evidence.review")
    readable(evidence.get("conflict"), "pr_evidence.conflict")


def pr_merge(request: dict[str, Any], lane: dict[str, Any]) -> dict[str, Any]:
    capability = check_capability(request, PR_MERGE_COMMANDS)
    check_authorization(request)
    check_target(request, capability)
    check_idempotency(request, lane)
    branch_of(request, lane)
    target = mapping(request.get("target"), "target")
    require(
        isinstance(target.get("pull_request"), int) and target["pull_request"] > 0,
        "target.pull_request 必须是正整数",
    )
    method = text(request.get("merge_method"), "merge_method")
    require(method in MERGE_METHODS, f"merge_method {method!r} 不受支持")
    current = pr_state(request)
    state = str(current.get("state", "")).upper()
    if state in {"MERGED", "CLOSED"}:
        require(
            resume_flag(request) and state == "MERGED",
            f"PR 已 {state} 且非 response-lost 恢复，禁止重复 merge",
        )
        return result(request, "ready", action="deduplicated")
    require(state == "OPEN", f"PR 当前状态 {state or 'Unknown'}，不盲 merge")
    require(
        not resume_flag(request), "resume 恢复但 PR 仍 OPEN，先重新 readback 再判定"
    )
    require(
        boolean(current.get("mergeable"), "pr_readback.mergeable"),
        "PR mergeable 非 true（冲突或 Unknown），禁止 merge",
    )
    require(
        current.get("headRefOid") == lane.get("integrated_commit", current.get("headRefOid")),
        "PR head 与 lane 集成 commit 不一致，禁止 merge",
    )
    check_pr_evidence(request)
    check_fan_in(request)
    return result(request, "ready", action=f"merge-{method}")


def remote_closeout(request: dict[str, Any], lane: dict[str, Any]) -> dict[str, Any]:
    capability = check_capability(request, CLOSEOUT_COMMANDS)
    check_authorization(request)
    check_target(request, capability)
    check_idempotency(request, lane)
    head = branch_of(request, lane)
    _, parity = read_json(request.get("parity_readback"), "parity_readback")
    require(
        parity.get("local_head") == parity.get("remote_head"),
        "local/remote parity 未证实或 Unknown，不执行 remote closeout",
    )
    merged = pr_state(request, "merge_readback")
    require(
        str(merged.get("state", "")).upper() == "MERGED",
        "merge readback 未证实 MERGED，先完成 merge 再 closeout",
    )
    check_fan_in(request)
    cleanup = mapping(request.get("closeout_cleanup"), "closeout_cleanup")
    for field in ("worker_release", "archive_output", "worktree_cleanup", "registry"):
        readable(cleanup.get(field), f"closeout_cleanup.{field}")
    _, registry = read_json(cleanup["registry"], "closeout_cleanup.registry")
    state = text(registry.get("state"), "closeout_cleanup.registry.state")
    require(
        state in {"close_pending", "closed"},
        f"registry 状态 {state!r} 不允许 remote closeout（仅 close_pending/closed）",
    )
    _, readback = read_json(request.get("remote_readback"), "remote_readback")
    if remote_ref(readback, head) is None:
        return result(request, "ready", action="deduplicated")
    require(
        boolean(request.get("delete_branch"), "delete_branch"),
        "remote branch 仍存在且未声明 delete_branch，不盲删除",
    )
    return result(request, "ready", action="delete-remote-branch")


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
            "scope": "phase4-publication-only",
        }
    try:
        operation = text(request.get("operation"), "operation")
        require(operation in OPERATIONS, f"未知 operation {operation!r}")
        lane = lane_row(request)
        check_binding(request, lane)
        handlers = {
            "publication-read": lambda: publication_read(request),
            "branch-push": lambda: branch_push(request, lane),
            "pr-create": lambda: pr_create(request, lane),
            "pr-update": lambda: pr_update(request, lane),
            "pr-merge": lambda: pr_merge(request, lane),
            "remote-closeout": lambda: remote_closeout(request, lane),
            "verify-result": lambda: verify_result(request),
        }
        return handlers[operation]()
    except (Error, KeyError, REGISTRY.OverlayError) as error:
        return result(request, "blocked", reason=str(error))


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] != "check":
        print(
            "usage: remote_publication.py check <absolute-request.json>",
            file=sys.stderr,
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
            "scope": "phase4-publication-only",
        }
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0 if output["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
