#!/usr/bin/env python3
"""Orca project-side fan-in 与 cleanup 证据门禁。

该 helper 只核验 caller 提供的项目与 Orca readback，不执行 Git、Orca
worker-release、archive 或 worktree rm。真实 mutation 仍由既有 owner 执行。
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


PROJECT_FAN_IN_OPERATION = "project-fan-in"
CLEANUP_OPERATION = "cleanup"
OUTPUT_MODES = {
    "commit": "integrated",
    "artifact": "consumed",
    "checks": "consumed",
    "verdict": "consumed",
}
INTEGRATION_SEQUENCES = {
    "commit": ["review", "cherry-pick", "focused-checks"],
    "artifact": ["output-evidence"],
    "checks": ["output-evidence"],
    "verdict": ["output-evidence"],
}
CLEANUP_STEPS = (
    "project-cleanup-gate",
    "worker-release",
    "archive-readback",
    "worktree-rm",
    "git-branch-readback",
)
UNKNOWN = "Unknown"


class ProjectLifecycleError(ValueError):
    """项目证据缺失、冲突或不能安全推进。"""


def _known_text(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value.strip().lower() in {"none", "null", "unknown"}
    ):
        raise ProjectLifecycleError(f"{field} 必须是已知非空文本")
    return value.strip()


def _readback_text(value: Any, field: str) -> str:
    if value == UNKNOWN:
        return UNKNOWN
    return _known_text(value, field)


def _optional_text(value: Any, field: str) -> str | None:
    if value is None or value == "none":
        return None
    if value == UNKNOWN:
        raise ProjectLifecycleError(f"{field} 为 Unknown")
    return _known_text(value, field)


def _flag(value: Any, field: str) -> bool | str:
    if value == UNKNOWN:
        return UNKNOWN
    if type(value) is not bool:
        raise ProjectLifecycleError(f"{field} 必须是 boolean 或 Unknown")
    return value


def _mapping(value: Any, field: str, fields: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ProjectLifecycleError(f"{field} 必须精确包含 {sorted(fields)}")
    return value


def _absolute_path(value: Any, field: str, *, directory: bool | None = None) -> str:
    path = Path(_known_text(value, field)).expanduser()
    if not path.is_absolute():
        raise ProjectLifecycleError(f"{field} 必须是绝对路径")
    try:
        resolved = path.resolve(strict=directory is not False)
    except (OSError, RuntimeError) as error:
        raise ProjectLifecycleError(f"{field} 不可解析: {error}") from error
    if directory is True and not resolved.is_dir():
        raise ProjectLifecycleError(f"{field} 必须是目录")
    return str(resolved)


def _readable_file(value: Any, field: str) -> str:
    path = _absolute_path(value, field)
    try:
        Path(path).read_bytes()
    except OSError as error:
        raise ProjectLifecycleError(f"{field} 不可读: {error}") from error
    return path


def _readable_json(value: Any, field: str) -> tuple[str, dict[str, Any]]:
    path = _readable_file(value, field)
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ProjectLifecycleError(f"{field} 不是可读 JSON object: {error}") from error
    if not isinstance(document, dict):
        raise ProjectLifecycleError(f"{field} 必须包含 JSON object")
    return path, document


def _lane(value: Any, field: str, *, worktree_exists: bool) -> dict[str, Any]:
    result = _mapping(
        value,
        field,
        {
            "lane_id",
            "work_item",
            "output_mode",
            "state",
            "base_commit",
            "head_commit",
            "worktree",
            "branch",
            "dirty_state",
        },
    )
    lane = {
        "lane_id": _known_text(result["lane_id"], f"{field}.lane_id"),
        "work_item": _known_text(result["work_item"], f"{field}.work_item"),
        "output_mode": _known_text(result["output_mode"], f"{field}.output_mode"),
        "state": _readback_text(result["state"], f"{field}.state"),
        "base_commit": _optional_text(result["base_commit"], f"{field}.base_commit"),
        "head_commit": _optional_text(result["head_commit"], f"{field}.head_commit"),
        "worktree": _absolute_path(
            result["worktree"], f"{field}.worktree", directory=worktree_exists
        ),
        "branch": _known_text(result["branch"], f"{field}.branch"),
        "dirty_state": _readback_text(result["dirty_state"], f"{field}.dirty_state"),
    }
    if lane["output_mode"] not in OUTPUT_MODES:
        raise ProjectLifecycleError(f"{field}.output_mode 不支持: {lane['output_mode']}")
    if lane["output_mode"] in {"commit", "verdict"} and lane["base_commit"] is None:
        raise ProjectLifecycleError(f"{field}.base_commit 缺失")
    return lane


def _orca_evidence(value: Any, lane: dict[str, Any]) -> dict[str, Any]:
    result = _mapping(
        value,
        "orca",
        {
            "run_id",
            "task_id",
            "dispatch_id",
            "terminal_handle",
            "work_item",
            "settled",
            "worker_done",
            "fleet_verdict",
            "fifo_ack",
            "project_lane_transition",
            "reference",
        },
    )
    evidence = {
        field: _known_text(result[field], f"orca.{field}")
        for field in ("run_id", "task_id", "dispatch_id", "terminal_handle", "work_item")
    }
    for field in ("settled", "worker_done", "fleet_verdict", "fifo_ack"):
        if _flag(result[field], f"orca.{field}") is not True:
            raise ProjectLifecycleError(f"orca.{field} 未明确为 true")
    if result["project_lane_transition"] != "unchanged":
        raise ProjectLifecycleError(
            "Orca settlement 不得直接推进 project lane integrated/consumed/closed"
        )
    if evidence["work_item"] != lane["work_item"]:
        raise ProjectLifecycleError("orca.work_item 与 project lane 不一致")
    reference, document = _readable_json(result["reference"], "orca.reference")
    if document.get("authority") is not False:
        raise ProjectLifecycleError("orca.reference authority 必须为 false")
    if document.get("project_lane_transition") != "unchanged":
        raise ProjectLifecycleError("orca.reference 不能授权 project lane transition")
    identity = document.get("identity")
    if not isinstance(identity, dict):
        raise ProjectLifecycleError("orca.reference 缺少 identity readback")
    for field in ("run_id", "task_id", "dispatch_id", "terminal_handle"):
        if identity.get(field) != evidence[field]:
            raise ProjectLifecycleError(f"orca.reference identity.{field} 不匹配")
    return {
        **evidence,
        "settled": True,
        "worker_done": True,
        "fleet_verdict": True,
        "fifo_ack": True,
        "project_lane_transition": "unchanged",
        "reference": reference,
    }


def _project_gate(value: Any, lane: dict[str, Any]) -> dict[str, str]:
    result = _mapping(value, "project", {"status", "work_item", "fan_in_state", "source"})
    status = _readback_text(result["status"], "project.status")
    work_item = _known_text(result["work_item"], "project.work_item")
    fan_in_state = _readback_text(result["fan_in_state"], "project.fan_in_state")
    source = _readable_file(result["source"], "project.source")
    if work_item != lane["work_item"]:
        raise ProjectLifecycleError("project.work_item 与 lane 不一致")
    if status != "passed":
        raise ProjectLifecycleError(f"项目 gate 未通过: {status}")
    return {
        "status": status,
        "work_item": work_item,
        "fan_in_state": fan_in_state,
        "source": source,
    }


def _review(value: Any, lane: dict[str, Any]) -> dict[str, Any]:
    result = _mapping(value, "review", {"status", "fixed_point", "source"})
    status = _readback_text(result["status"], "review.status")
    fixed_point = _optional_text(result["fixed_point"], "review.fixed_point")
    source = _readable_file(result["source"], "review.source")
    if lane["output_mode"] in {"commit", "verdict"}:
        if status != "passed":
            raise ProjectLifecycleError(f"review gate 未通过: {status}")
        if fixed_point != lane["base_commit"]:
            raise ProjectLifecycleError("review fixed point 必须等于 Execution Base")
    elif status not in {"passed", "not_applicable"}:
        raise ProjectLifecycleError(f"review gate 状态不支持: {status}")
    return {"status": status, "fixed_point": fixed_point, "source": source}


def _git_evidence(value: Any, lane: dict[str, Any], *, worktree_exists: bool) -> dict[str, Any]:
    result = _mapping(
        value,
        "git",
        {
            "worktree_path",
            "branch",
            "base_commit",
            "head_commit",
            "terminal_commit",
            "dirty_state",
            "worktree_clean",
            "source",
        },
    )
    worktree_path = _absolute_path(
        result["worktree_path"], "git.worktree_path", directory=worktree_exists
    )
    evidence = {
        "worktree_path": worktree_path,
        "branch": _known_text(result["branch"], "git.branch"),
        "base_commit": _optional_text(result["base_commit"], "git.base_commit"),
        "head_commit": _optional_text(result["head_commit"], "git.head_commit"),
        "terminal_commit": _optional_text(result["terminal_commit"], "git.terminal_commit"),
        "dirty_state": _readback_text(result["dirty_state"], "git.dirty_state"),
        "worktree_clean": _flag(result["worktree_clean"], "git.worktree_clean"),
        "source": _readable_file(result["source"], "git.source"),
    }
    if evidence["worktree_path"] != lane["worktree"]:
        raise ProjectLifecycleError("git.worktree_path 与 lane.worktree 不一致")
    if evidence["branch"] != lane["branch"]:
        raise ProjectLifecycleError("git.branch 与 lane.branch 不一致")
    if evidence["base_commit"] != lane["base_commit"]:
        raise ProjectLifecycleError("git.base_commit 与 lane.base_commit 不一致")
    if evidence["worktree_clean"] is not True or evidence["dirty_state"] != "clean":
        raise ProjectLifecycleError("project fan-in 需要 clean Git worktree")
    if lane["output_mode"] == "commit":
        if not isinstance(evidence["terminal_commit"], str) or not evidence["terminal_commit"].strip():
            raise ProjectLifecycleError("commit mode 缺少 terminal commit")
        if evidence["terminal_commit"] != lane["head_commit"]:
            raise ProjectLifecycleError("terminal commit 与 lane head 不一致")
    elif evidence["terminal_commit"] is not None:
        raise ProjectLifecycleError("artifact/checks/verdict 不得携带 terminal commit")
    return evidence


def _integration(value: Any, lane: dict[str, Any]) -> dict[str, Any]:
    result = _mapping(
        value,
        "integration",
        {"status", "cherry_pick", "focused_checks", "conflict", "sequence", "source"},
    )
    integration = {
        "status": _readback_text(result["status"], "integration.status"),
        "cherry_pick": _readback_text(result["cherry_pick"], "integration.cherry_pick"),
        "focused_checks": _readback_text(
            result["focused_checks"], "integration.focused_checks"
        ),
        "conflict": _flag(result["conflict"], "integration.conflict"),
        "sequence": result["sequence"],
        "source": _readable_file(result["source"], "integration.source"),
    }
    if integration["sequence"] != INTEGRATION_SEQUENCES[lane["output_mode"]]:
        raise ProjectLifecycleError(
            "Integration sequence 必须先 review，再 cherry-pick/focused checks；非 commit 只做 output evidence"
        )
    if integration["conflict"] is not False:
        return integration
    if lane["output_mode"] == "commit":
        if integration["status"] != "passed":
            return integration
        if integration["cherry_pick"] != "completed":
            return integration
        if integration["focused_checks"] != "passed":
            return integration
    elif integration["cherry_pick"] != "not_applicable":
        raise ProjectLifecycleError(
            "artifact/checks/verdict mode 不得 cherry-pick"
        )
    return integration


def _fan_in_blocked(lane: dict[str, Any], reason: str, state: str) -> dict[str, Any]:
    return {
        "status": state,
        "operation": PROJECT_FAN_IN_OPERATION,
        "authority": False,
        "project_lane_transition": "unchanged",
        "project_state": state,
        "preserve": True,
        "reason": reason,
        "lane_id": lane["lane_id"],
        "output_mode": lane["output_mode"],
    }


def validate_project_fan_in(request: Any) -> dict[str, Any]:
    """验证 Orca settlement 可否进入既有项目 fan-in；不写 registry 或 Git。"""
    if not isinstance(request, dict):
        raise ProjectLifecycleError("project fan-in request 必须是 object")
    required = {"operation", "lane", "orca", "project", "review", "git", "integration", "evidence"}
    if set(request) != required:
        raise ProjectLifecycleError(f"project fan-in request 字段必须精确为 {sorted(required)}")
    if request["operation"] != PROJECT_FAN_IN_OPERATION:
        raise ProjectLifecycleError("project fan-in operation 不正确")
    lane = _lane(request["lane"], "lane", worktree_exists=True)
    expected = OUTPUT_MODES[lane["output_mode"]]
    if lane["state"] in {"integrated", "consumed", "closed"}:
        if lane["state"] != expected and lane["state"] != "closed":
            raise ProjectLifecycleError("已 fan-in lane 的 output mode/state 不一致")
        return {
            "status": "deduplicated",
            "operation": PROJECT_FAN_IN_OPERATION,
            "authority": False,
            "project_lane_transition": "unchanged",
            "project_state": lane["state"],
            "preserve": False,
            "lane_id": lane["lane_id"],
            "output_mode": lane["output_mode"],
        }
    if lane["state"] not in {"terminal", "close_pending"}:
        if lane["state"] == UNKNOWN:
            return _fan_in_blocked(lane, "project lane state Unknown；保留现场", "blocked")
        raise ProjectLifecycleError(f"lane state 不允许 project fan-in: {lane['state']}")
    try:
        orca = _orca_evidence(request["orca"], lane)
        project = _project_gate(request["project"], lane)
        review = _review(request["review"], lane)
        git = _git_evidence(request["git"], lane, worktree_exists=True)
        integration = _integration(request["integration"], lane)
        evidence = _readable_file(request["evidence"], "evidence")
    except ProjectLifecycleError as error:
        return _fan_in_blocked(lane, str(error), "blocked")
    if orca["settled"] is not True or orca["worker_done"] is not True:
        return _fan_in_blocked(lane, "worker_done/settlement 未完成", "blocked")
    if project["fan_in_state"] not in {"terminal", "close_pending"}:
        return _fan_in_blocked(lane, "project gate 已越过 fan-in 输入状态", "blocked")
    if integration["conflict"] == UNKNOWN:
        return _fan_in_blocked(lane, "Integration conflict 状态 Unknown；保留现场", "blocked")
    if integration["conflict"] is True or integration["status"] == "integration_conflict":
        return _fan_in_blocked(lane, "Integration conflict；保留 Execution Worktree", "integration_conflict")
    if lane["output_mode"] == "commit" and integration["cherry_pick"] != "completed":
        return _fan_in_blocked(
            lane,
            "commit fan-in cherry-pick 未完成；保留 Execution Worktree",
            "integration_checks_failed",
        )
    if lane["output_mode"] == "commit" and integration["status"] != "passed":
        return _fan_in_blocked(lane, "Integration 未通过", "integration_checks_failed")
    if lane["output_mode"] != "commit" and integration["status"] not in {"passed", "not_applicable"}:
        return _fan_in_blocked(lane, "Integration/readback 未通过", "integration_checks_failed")
    if lane["output_mode"] == "commit" and integration["focused_checks"] != "passed":
        return _fan_in_blocked(lane, "focused checks 未通过", "integration_checks_failed")
    if lane["output_mode"] != "commit" and integration["focused_checks"] not in {"passed", "not_applicable"}:
        return _fan_in_blocked(lane, "output-mode checks 未通过", "integration_checks_failed")
    return {
        "status": "ready",
        "operation": PROJECT_FAN_IN_OPERATION,
        "authority": False,
        "project_lane_transition": "unchanged",
        "project_state": "unchanged",
        "next_project_state": expected,
        "preserve": False,
        "lane_id": lane["lane_id"],
        "output_mode": lane["output_mode"],
        "fan_in": {
            "orca": orca,
            "project": project,
            "review": review,
            "git": git,
            "integration": integration,
            "evidence": evidence,
        },
        "cleanup_order": list(CLEANUP_STEPS),
    }


def _prior(value: Any) -> dict[str, Any]:
    result = _mapping(value, "prior", {"state", "completed_steps"})
    state = _readback_text(result["state"], "prior.state")
    if state not in {UNKNOWN, "integrated", "consumed", "cleanup_in_progress", "close_pending", "closed"}:
        raise ProjectLifecycleError(f"prior.state 不支持: {state}")
    completed = result["completed_steps"]
    if not isinstance(completed, list) or any(not isinstance(step, str) for step in completed):
        raise ProjectLifecycleError("prior.completed_steps 必须是字符串列表")
    if len(set(completed)) != len(completed):
        raise ProjectLifecycleError("prior.completed_steps 不得重复")
    if completed != list(CLEANUP_STEPS[: len(completed)]):
        raise ProjectLifecycleError("cleanup retry 必须沿固定顺序从已完成前缀继续")
    return {"state": state, "completed_steps": list(completed)}


def _release(value: Any) -> dict[str, Any]:
    result = _mapping(value, "release", {"status", "active_writer", "released", "source"})
    return {
        "status": _readback_text(result["status"], "release.status"),
        "active_writer": _flag(result["active_writer"], "release.active_writer"),
        "released": _flag(result["released"], "release.released"),
        "source": _readable_file(result["source"], "release.source"),
    }


def _archive(value: Any) -> dict[str, Any]:
    result = _mapping(value, "archive", {"status", "complete", "output_readback", "source"})
    return {
        "status": _readback_text(result["status"], "archive.status"),
        "complete": _flag(result["complete"], "archive.complete"),
        "output_readback": _flag(result["output_readback"], "archive.output_readback"),
        "source": _readable_file(result["source"], "archive.source"),
    }


def _worktree_cleanup(value: Any, lane: dict[str, Any]) -> dict[str, Any]:
    result = _mapping(
        value,
        "worktree",
        {"path", "branch", "removed", "worktree_present", "branch_present", "source"},
    )
    cleanup = {
        "path": _absolute_path(result["path"], "worktree.path", directory=False),
        "branch": _known_text(result["branch"], "worktree.branch"),
        "removed": _flag(result["removed"], "worktree.removed"),
        "worktree_present": _flag(result["worktree_present"], "worktree.worktree_present"),
        "branch_present": _flag(result["branch_present"], "worktree.branch_present"),
        "source": _readable_file(result["source"], "worktree.source"),
    }
    if cleanup["path"] != lane["worktree"]:
        raise ProjectLifecycleError("worktree.path 与 lane.worktree 不一致")
    if cleanup["branch"] != lane["branch"]:
        raise ProjectLifecycleError("worktree.branch 与 lane.branch 不一致")
    return cleanup


def _cleanup_blocked(lane: dict[str, Any], reason: str, retry_from: str) -> dict[str, Any]:
    return {
        "status": "close_pending",
        "operation": CLEANUP_OPERATION,
        "authority": False,
        "project_lane_transition": "unchanged",
        "project_state": "close_pending",
        "preserve": True,
        "reason": reason,
        "retry_from": retry_from,
        "lane_id": lane["lane_id"],
        "cleanup_order": list(CLEANUP_STEPS),
    }


def validate_cleanup(request: Any) -> dict[str, Any]:
    """验证 project cleanup gate → release → archive → worktree rm 顺序。"""
    if not isinstance(request, dict):
        raise ProjectLifecycleError("cleanup request 必须是 object")
    required = {"operation", "lane", "project", "release", "archive", "worktree", "prior", "sequence"}
    if set(request) != required:
        raise ProjectLifecycleError(f"cleanup request 字段必须精确为 {sorted(required)}")
    if request["operation"] != CLEANUP_OPERATION:
        raise ProjectLifecycleError("cleanup operation 不正确")
    if request["sequence"] != list(CLEANUP_STEPS):
        raise ProjectLifecycleError("cleanup 顺序必须是 project gate → release → archive → worktree rm → branch readback")
    lane = _lane(request["lane"], "lane", worktree_exists=False)
    expected = OUTPUT_MODES[lane["output_mode"]]
    prior = _prior(request["prior"])
    if lane["state"] == UNKNOWN or prior["state"] == UNKNOWN:
        return _cleanup_blocked(lane, "project lane cleanup identity/state Unknown，保留现场", "project-cleanup-gate")
    if lane["state"] == "closed" or prior["state"] == "closed":
        if prior["state"] != "closed" or prior["completed_steps"] != list(CLEANUP_STEPS):
            raise ProjectLifecycleError("closed lane 缺少完整 cleanup readback")
        return {
            "status": "deduplicated",
            "operation": CLEANUP_OPERATION,
            "authority": False,
            "project_lane_transition": "unchanged",
            "project_state": "closed",
            "preserve": False,
            "lane_id": lane["lane_id"],
            "cleanup_order": list(CLEANUP_STEPS),
        }
    if lane["state"] not in {expected, "close_pending", "cleanup_in_progress"}:
        return _cleanup_blocked(lane, "project lane 尚未 integrated/consumed", "project-cleanup-gate")
    try:
        project = _project_gate(request["project"], lane)
        release = _release(request["release"])
        archive = _archive(request["archive"])
        worktree = _worktree_cleanup(request["worktree"], lane)
    except ProjectLifecycleError as error:
        return _cleanup_blocked(lane, str(error), "project-cleanup-gate")
    if lane["dirty_state"] != "clean":
        return _cleanup_blocked(lane, f"dirty/Unknown worktree 保留现场: {lane['dirty_state']}", "project-cleanup-gate")
    if project["status"] != "passed":
        return _cleanup_blocked(lane, "project cleanup gate 未通过", "project-cleanup-gate")
    if project["fan_in_state"] != expected:
        return _cleanup_blocked(lane, "project lane 尚未完成对应 integrated/consumed fan-in", "project-cleanup-gate")
    if release["active_writer"] is not False:
        return _cleanup_blocked(lane, "active writer 或其状态 Unknown，禁止 release/rm", "worker-release")
    if release["released"] is not True or release["status"] not in {"released", "already_released"}:
        return _cleanup_blocked(lane, "worker-release 未获得正面 readback", "worker-release")
    if (
        archive["status"] not in {"archived", "already_archived"}
        or archive["complete"] is not True
        or archive["output_readback"] is not True
    ):
        return _cleanup_blocked(lane, "archive/output readback 不完整，保留 worktree", "archive-readback")
    if worktree["removed"] is not True or worktree["worktree_present"] is not False:
        return _cleanup_blocked(lane, "worktree rm 未获得正面 readback", "worktree-rm")
    if worktree["branch_present"] is not False:
        return _cleanup_blocked(lane, "cleanup 后 Git branch 仍存在或状态 Unknown", "git-branch-readback")
    return {
        "status": "ready",
        "operation": CLEANUP_OPERATION,
        "authority": False,
        "project_lane_transition": "unchanged",
        "project_state": "unchanged",
        "next_project_state": "closed",
        "preserve": False,
        "lane_id": lane["lane_id"],
        "cleanup_order": list(CLEANUP_STEPS),
        "release_vs_project_close": {
            "release": "verified",
            "project_lane": "pending coordinator close readback",
        },
        "readback": {
            "project": project,
            "release": release,
            "archive": archive,
            "worktree": worktree,
            "prior": prior,
        },
    }


def validate(request: Any) -> dict[str, Any]:
    if not isinstance(request, dict):
        raise ProjectLifecycleError("request 必须是 object")
    operation = request.get("operation")
    if operation == PROJECT_FAN_IN_OPERATION:
        return validate_project_fan_in(request)
    if operation == CLEANUP_OPERATION:
        return validate_cleanup(request)
    raise ProjectLifecycleError("operation 必须是 project-fan-in 或 cleanup")


def _git(repo: Path, *arguments: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
        env.pop(name, None)
    command = ["git", "-C", str(cwd or repo), *arguments]
    result = subprocess.run(command, text=True, capture_output=True, env=env)
    if check and result.returncode != 0:
        raise AssertionError(f"git command failed: {' '.join(command)}\n{result.stderr}")
    return result


def _write_json(path: Path, value: Any) -> str:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return str(path)


def _settlement_document(identity: dict[str, str]) -> dict[str, Any]:
    return {
        "authority": False,
        "identity": identity,
        "project_lane_transition": "unchanged",
    }


def _fan_request(
    root: Path,
    *,
    lane: dict[str, Any],
    identity: dict[str, str],
    integration: dict[str, Any],
    project_status: str = "passed",
    dirty_state: str = "clean",
) -> dict[str, Any]:
    evidence = _write_json(root / f"{lane['lane_id']}-fan.json", {"kind": "project-fan-in"})
    settlement = _write_json(root / f"{lane['lane_id']}-settlement.json", _settlement_document(identity))
    review_status = "passed" if lane["output_mode"] in {"commit", "verdict"} else "not_applicable"
    return {
        "operation": PROJECT_FAN_IN_OPERATION,
        "lane": {**lane, "dirty_state": dirty_state},
        "orca": {
            **identity,
            "work_item": lane["work_item"],
            "settled": True,
            "worker_done": True,
            "fleet_verdict": True,
            "fifo_ack": True,
            "project_lane_transition": "unchanged",
            "reference": settlement,
        },
        "project": {
            "status": project_status,
            "work_item": lane["work_item"],
            "fan_in_state": lane["state"],
            "source": _write_json(root / f"{lane['lane_id']}-project.json", {"status": project_status}),
        },
        "review": {
            "status": review_status,
            "fixed_point": lane["base_commit"] if review_status == "passed" else None,
            "source": _write_json(root / f"{lane['lane_id']}-review.json", {"status": review_status}),
        },
        "git": {
            "worktree_path": lane["worktree"],
            "branch": lane["branch"],
            "base_commit": lane["base_commit"],
            "head_commit": lane["head_commit"],
            "terminal_commit": lane["head_commit"] if lane["output_mode"] == "commit" else None,
            "dirty_state": dirty_state,
            "worktree_clean": dirty_state == "clean",
            "source": _write_json(root / f"{lane['lane_id']}-git.json", {"dirty_state": dirty_state}),
        },
        "integration": integration,
        "evidence": evidence,
    }


def _cleanup_request(root: Path, *, lane: dict[str, Any], prior_state: str, completed_steps: list[str], archive_complete: Any = True, removed: Any = True, branch_present: Any = False) -> dict[str, Any]:
    def source(name: str, value: Any) -> str:
        return _write_json(root / f"{lane['lane_id']}-{name}.json", {"value": value})

    return {
        "operation": CLEANUP_OPERATION,
        "lane": lane,
        "project": {
            "status": "passed",
            "work_item": lane["work_item"],
            "fan_in_state": OUTPUT_MODES[lane["output_mode"]],
            "source": source("cleanup-gate", "passed"),
        },
        "release": {
            "status": "released",
            "active_writer": False,
            "released": True,
            "source": source("release", "released"),
        },
        "archive": {
            "status": "archived" if archive_complete is True else "pending",
            "complete": archive_complete,
            "output_readback": archive_complete,
            "source": source("archive", archive_complete),
        },
        "worktree": {
            "path": lane["worktree"],
            "branch": lane["branch"],
            "removed": removed,
            "worktree_present": False if removed is True else True,
            "branch_present": branch_present,
            "source": source("worktree", {"removed": removed, "branch_present": branch_present}),
        },
        "prior": {"state": prior_state, "completed_steps": completed_steps},
        "sequence": list(CLEANUP_STEPS),
    }


def _self_test() -> None:
    """覆盖真实临时 worktree 的成功、冲突、dirty、archive 与 retry。"""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repo = root / "repo"
        repo.mkdir()
        _git(repo, "init", "-b", "main")
        _git(repo, "config", "user.email", "test@example.invalid")
        _git(repo, "config", "user.name", "Project Lifecycle Test")
        (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
        _git(repo, "add", "seed.txt")
        _git(repo, "commit", "-m", "seed")
        base = _git(repo, "rev-parse", "HEAD").stdout.strip()
        integration = root / "integration"
        execution = root / "execution"
        _git(repo, "worktree", "add", "-b", "integration", str(integration), base)
        _git(repo, "worktree", "add", "-b", "worker", str(execution), base)
        (execution / "change.txt").write_text("change\n", encoding="utf-8")
        _git(repo, "add", "change.txt", cwd=execution)
        _git(repo, "commit", "-m", "worker change", cwd=execution)
        terminal_commit = _git(repo, "rev-parse", "HEAD", cwd=execution).stdout.strip()
        _git(repo, "cherry-pick", terminal_commit, cwd=integration)
        integration_head = _git(repo, "rev-parse", "HEAD", cwd=integration).stdout.strip()
        lane = {
            "lane_id": "lane-114-123",
            "work_item": "#123",
            "output_mode": "commit",
            "state": "terminal",
            "base_commit": base,
            "head_commit": terminal_commit,
            "worktree": str(execution),
            "branch": "worker",
            "dirty_state": "clean",
        }
        identity = {
            "run_id": "run-123",
            "task_id": "task-123",
            "dispatch_id": "dispatch-123",
            "terminal_handle": "term-worker-123",
        }
        integration_sources = _write_json(root / "integration.json", {"head": integration_head})
        fan = _fan_request(
            root,
            lane=lane,
            identity=identity,
            integration={
                "status": "passed",
                "cherry_pick": "completed",
                "focused_checks": "passed",
                "conflict": False,
                "sequence": INTEGRATION_SEQUENCES["commit"],
                "source": integration_sources,
            },
        )
        accepted = validate_project_fan_in(fan)
        assert accepted["status"] == "ready" and accepted["next_project_state"] == "integrated"
        assert accepted["project_lane_transition"] == "unchanged"
        incomplete_cherry_pick = copy.deepcopy(fan)
        incomplete_cherry_pick["integration"]["cherry_pick"] = "not_completed"
        assert (
            validate_project_fan_in(incomplete_cherry_pick)["status"]
            == "integration_checks_failed"
        )
        no_project_gate = copy.deepcopy(fan)
        no_project_gate["project"]["status"] = "Unknown"
        assert validate_project_fan_in(no_project_gate)["status"] == "blocked"

        for mode in ("artifact", "checks", "verdict"):
            mode_path = root / f"{mode}-worker"
            mode_branch = f"{mode}-worker"
            _git(repo, "worktree", "add", "-b", mode_branch, str(mode_path), base)
            mode_lane = {
                **lane,
                "lane_id": f"lane-114-123-{mode}",
                "output_mode": mode,
                "head_commit": None,
                "worktree": str(mode_path),
                "branch": mode_branch,
            }
            mode_source = _write_json(root / f"{mode}-integration.json", {"status": "not_applicable"})
            mode_request = _fan_request(
                root,
                lane=mode_lane,
                identity=identity,
                integration={
                    "status": "not_applicable",
                    "cherry_pick": "not_applicable",
                    "focused_checks": "not_applicable",
                    "conflict": False,
                    "sequence": INTEGRATION_SEQUENCES[mode],
                    "source": mode_source,
                },
            )
            mode_result = validate_project_fan_in(mode_request)
            assert mode_result["status"] == "ready" and mode_result["next_project_state"] == "consumed"
            _git(repo, "worktree", "remove", str(mode_path))
            _git(repo, "branch", "-D", mode_branch)

        integrated_lane = {**lane, "state": "integrated"}
        _git(repo, "worktree", "remove", str(execution))
        _git(repo, "branch", "-D", "worker")
        cleanup = _cleanup_request(root, lane=integrated_lane, prior_state="integrated", completed_steps=[])
        closed = validate_cleanup(cleanup)
        assert closed["status"] == "ready" and closed["next_project_state"] == "closed"
        assert closed["release_vs_project_close"]["project_lane"] == "pending coordinator close readback"
        duplicate = copy.deepcopy(cleanup)
        duplicate["lane"]["state"] = "closed"
        duplicate["prior"] = {"state": "closed", "completed_steps": list(CLEANUP_STEPS)}
        assert validate_cleanup(duplicate)["status"] == "deduplicated"

        dirty = root / "dirty"
        _git(repo, "worktree", "add", "-b", "dirty-worker", str(dirty), base)
        (dirty / "uncommitted.txt").write_text("dirty\n", encoding="utf-8")
        dirty_lane = {**integrated_lane, "worktree": str(dirty), "branch": "dirty-worker", "dirty_state": "dirty"}
        dirty_result = validate_cleanup(
            _cleanup_request(root, lane=dirty_lane, prior_state="integrated", completed_steps=[])
        )
        assert dirty_result["status"] == "close_pending" and dirty.is_dir()
        unknown_lane = {**dirty_lane, "dirty_state": UNKNOWN}
        unknown_result = validate_cleanup(
            _cleanup_request(root, lane=unknown_lane, prior_state="integrated", completed_steps=[])
        )
        assert unknown_result["status"] == "close_pending" and dirty.is_dir()
        _git(repo, "worktree", "remove", "--force", str(dirty))
        _git(repo, "branch", "-D", "dirty-worker")

        archive_retry = root / "archive-retry"
        _git(repo, "worktree", "add", "-b", "archive-worker", str(archive_retry), base)
        retry_lane = {**integrated_lane, "worktree": str(archive_retry), "branch": "archive-worker"}
        pending = validate_cleanup(
            _cleanup_request(root, lane=retry_lane, prior_state="integrated", completed_steps=[], archive_complete=False)
        )
        assert pending["status"] == "close_pending" and archive_retry.is_dir()
        branch_left = validate_cleanup(
            _cleanup_request(root, lane=retry_lane, prior_state="integrated", completed_steps=[], branch_present=True)
        )
        assert branch_left["status"] == "close_pending" and branch_left["retry_from"] == "git-branch-readback"
        _git(repo, "worktree", "remove", str(archive_retry))
        _git(repo, "branch", "-D", "archive-worker")
        retry_lane["state"] = "close_pending"
        retry = validate_cleanup(
            _cleanup_request(
                root,
                lane=retry_lane,
                prior_state="close_pending",
                completed_steps=["project-cleanup-gate", "worker-release"],
            )
        )
        assert retry["status"] == "ready"

        conflict_integration = root / "conflict-integration"
        conflict_execution = root / "conflict-execution"
        _git(repo, "worktree", "add", "-b", "conflict-integration", str(conflict_integration), base)
        _git(repo, "worktree", "add", "-b", "conflict-worker", str(conflict_execution), base)
        (conflict_integration / "same.txt").write_text("integration\n", encoding="utf-8")
        _git(repo, "add", "same.txt", cwd=conflict_integration)
        _git(repo, "commit", "-m", "integration conflict", cwd=conflict_integration)
        (conflict_execution / "same.txt").write_text("worker\n", encoding="utf-8")
        _git(repo, "add", "same.txt", cwd=conflict_execution)
        _git(repo, "commit", "-m", "worker conflict", cwd=conflict_execution)
        conflict_commit = _git(repo, "rev-parse", "HEAD", cwd=conflict_execution).stdout.strip()
        conflict = _git(repo, "cherry-pick", conflict_commit, cwd=conflict_integration, check=False)
        assert conflict.returncode != 0
        _git(repo, "cherry-pick", "--abort", cwd=conflict_integration)
        conflict_lane = {**lane, "worktree": str(conflict_execution), "branch": "conflict-worker", "head_commit": conflict_commit}
        conflict_request = _fan_request(
            root,
            lane=conflict_lane,
            identity=identity,
            integration={
                "status": "integration_conflict",
                "cherry_pick": "not_completed",
                "focused_checks": "not_applicable",
                "conflict": True,
                "sequence": INTEGRATION_SEQUENCES["commit"],
                "source": integration_sources,
            },
        )
        assert validate_project_fan_in(conflict_request)["status"] == "integration_conflict"
        _git(repo, "worktree", "remove", "--force", str(conflict_execution))
        _git(repo, "worktree", "remove", "--force", str(conflict_integration))
        _git(repo, "branch", "-D", "conflict-worker")
        _git(repo, "branch", "-D", "conflict-integration")


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "self-test":
        _self_test()
        print("orca project lifecycle: pass")
        return 0
    if len(sys.argv) == 3 and sys.argv[1] == "validate":
        try:
            request_path = Path(sys.argv[2]).expanduser()
            if not request_path.is_absolute():
                raise ProjectLifecycleError("request path 必须是绝对路径")
            result = validate(json.loads(request_path.read_text(encoding="utf-8")))
        except (OSError, UnicodeError, json.JSONDecodeError, ProjectLifecycleError) as error:
            print(json.dumps({"status": "blocked", "reason": str(error)}, ensure_ascii=False, sort_keys=True))
            return 1
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result["status"] in {"ready", "deduplicated"} else 1
    print(f"Usage: {sys.argv[0]} self-test | validate <absolute-request.json>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
