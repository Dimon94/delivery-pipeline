#!/usr/bin/env python3
"""canonical checkpoint：采集隔离 Git 现场并安全消费起步信号。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from typing import Any


CHECKPOINT_VERSION = 1
FINGERPRINT_FIELD = "checkpoint_sha256"
COMPONENT_FIELDS = ("content", "mode", "staged", "snapshot")
SIGNALS = {"PREWALK_READY", "WORKER_STOPPED"}
UNKNOWN = "Unknown"
PHASES = ("starting", "execution", "direct")
EXECUTION_MODES = {"legacy", "staged", "direct"}
EXECUTION_SOURCES = {"role-config", "ticket", "map", "user-config"}
TOOL_ACCEPTANCE_FIELDS = {"accepted", "status", "source"}
TOOL_ACCEPTANCE_STATUSES = {"accepted", "rejected", UNKNOWN}
OBSERVATION_IDENTITY_FIELDS = (
    "runtime", "session_id", "coordinator_thread_id", "coordinator_host_id",
)

REQUIRED_FIELDS = {
    "checkpoint_version", "lane_id", "work_item", "runtime", "session_id",
    "coordinator_thread_id", "coordinator_host_id", "cli_version",
    "execution_worktree", "execution_branch", "base_commit", "head_commit",
    "phase", "development_mode", "mode_source", "phase_plan",
    "requested_model", "requested_effort", "tool_acceptance",
    "actual_model", "actual_effort", "actual_readback_source",
    "actual_readback_at", "first_edit", "checks", "todo", "decision",
    "evidence", "checkpoint_path", "snapshot", "component_sha256", FINGERPRINT_FIELD,
}


class CheckpointError(ValueError):
    """输入、现场或持久化证据不能安全核验。"""


def _git_env() -> dict[str, str]:
    env = os.environ.copy()
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
        env.pop(name, None)
    return env


def canonical_bytes(value: object) -> bytes:
    """返回 UTF-8、键排序、紧凑且拒绝 NaN 的 JSON。"""
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise CheckpointError(f"JSON 类型不可支持或不可确定: {error}") from error


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def checkpoint_sha256(document: dict[str, Any]) -> str:
    """整体指纹永远排除自身字段，避免自引用。"""
    if not isinstance(document, dict):
        raise CheckpointError("checkpoint 顶层必须是 object")
    unsigned = {key: value for key, value in document.items()
                if key != FINGERPRINT_FIELD}
    return _sha256(unsigned)


def _run_git(root: Path, *args: str, check: bool = True) -> bytes:
    result = subprocess.run(["git", "-C", str(root), *args], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, check=False, env=_git_env())
    if check and result.returncode:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise CheckpointError(f"Git 命令失败: {' '.join(args)}: {detail}")
    return result.stdout


def _nul_paths(raw: bytes) -> list[str]:
    return [os.fsdecode(item) for item in raw.split(b"\0") if item]


def _git_top(root: Path) -> Path:
    root = root.expanduser().resolve(strict=True)
    actual = Path(os.fsdecode(_run_git(root, "rev-parse", "--show-toplevel").strip())).resolve()
    if actual != root:
        raise CheckpointError("worktree 必须是 Git 顶层目录")
    return root


def _safe_path(root: Path, name: str) -> Path:
    # abspath 规范化 `..` 但不跟随 symlink，才能保留 symlink 的 mode/content 证据。
    path = Path(os.path.abspath(root / name))
    if not path.is_relative_to(root) or not path.parent.resolve(strict=False).is_relative_to(root):
        raise CheckpointError(f"Git 路径越出 worktree: {name}")
    return path


def _branch(root: Path) -> str:
    value = _run_git(root, "symbolic-ref", "--short", "-q", "HEAD", check=False).strip()
    return os.fsdecode(value) if value else "HEAD"


def _common_dir(root: Path) -> str:
    value = os.fsdecode(_run_git(root, "rev-parse", "--path-format=absolute",
                                  "--git-common-dir").strip())
    return str(Path(value).resolve())


def _file_record(path: Path) -> dict[str, Any]:
    mode = path.lstat().st_mode
    if stat.S_ISLNK(mode):
        body = os.fsencode(os.readlink(path))
        kind = "symlink"
    elif stat.S_ISREG(mode):
        body = path.read_bytes()
        kind = "file"
    else:
        raise CheckpointError(f"不支持的 dirty 文件类型: {path}")
    return {
        "content_sha256": hashlib.sha256(body).hexdigest(),
        "deleted": False,
        "kind": kind,
        "mode": stat.S_IMODE(mode),
    }


def snapshot_worktree(worktree: str | Path, *, required_ignored: list[str] | tuple[str, ...] = ()) -> dict[str, Any]:
    """读取未提交现场；ignored 不作为 dirty 输入，仅保存指纹并 fail-closed。"""
    root = _git_top(Path(worktree))
    dirty_names = set(_nul_paths(_run_git(root, "diff", "--name-only", "-z", "HEAD")))
    staged = sorted(set(_nul_paths(_run_git(root, "diff", "--cached", "--name-only", "-z", "HEAD"))))
    dirty_names.update(staged)
    dirty_names.update(_nul_paths(_run_git(root, "ls-files", "--others", "--exclude-standard", "-z")))
    dirty: dict[str, dict[str, Any]] = {}
    for name in sorted(dirty_names):
        path = _safe_path(root, name)
        if not path.exists() and not path.is_symlink():
            dirty[name] = {"content_sha256": None, "deleted": True, "kind": "deleted", "mode": None}
        else:
            dirty[name] = _file_record(path)

    ignored = sorted(set(_nul_paths(_run_git(root, "ls-files", "--others", "--ignored",
                                               "--exclude-standard", "-z"))))
    if set(required_ignored) & set(ignored):
        raise CheckpointError("ignored 交付输入未纳入 checkpoint，无法安全继续")
    ignored_fingerprints = {
        name: _file_record(_safe_path(root, name)) for name in ignored
    }
    index_diff = _run_git(root, "diff", "--cached", "--binary", "HEAD")
    worktree_diff = _run_git(root, "diff", "--binary", "HEAD")
    return {
        "branch": _branch(root),
        "common_dir": _common_dir(root),
        "dirty": dirty,
        "head": os.fsdecode(_run_git(root, "rev-parse", "HEAD").strip()),
        "ignored": {"delivery_input": "none" if not ignored else UNKNOWN,
                    "fingerprints": ignored_fingerprints, "paths": ignored},
        "index_sha256": hashlib.sha256(index_diff).hexdigest(),
        "staged": staged,
        "worktree": str(root),
        "working_tree_diff_sha256": hashlib.sha256(worktree_diff).hexdigest(),
    }


def _component_material(snapshot: dict[str, Any]) -> dict[str, object]:
    dirty = snapshot["dirty"]
    content = {name: {"content_sha256": item["content_sha256"], "deleted": item["deleted"]}
               for name, item in sorted(dirty.items())}
    modes = {name: {"kind": item["kind"], "mode": item["mode"], "deleted": item["deleted"]}
             for name, item in sorted(dirty.items())}
    staged = {"index_sha256": snapshot["index_sha256"], "paths": snapshot["staged"]}
    return {"content": content, "mode": modes, "staged": staged, "snapshot": snapshot}


def _component_hashes(snapshot: dict[str, Any]) -> dict[str, str]:
    material = _component_material(snapshot)
    return {name: _sha256(material[name]) for name in COMPONENT_FIELDS}


def _nonempty_text(value: object, field: str, *, allow_unknown: bool = True) -> None:
    if not isinstance(value, str) or not value.strip():
        raise CheckpointError(f"checkpoint 缺失或类型不支持: {field}")
    if not allow_unknown and value.strip().lower() == UNKNOWN.lower():
        raise CheckpointError(f"checkpoint 不允许 Unknown: {field}")


def _is_unknown(value: object) -> bool:
    return isinstance(value, str) and value.strip().lower() == UNKNOWN.lower()


def _validate_snapshot(snapshot: object) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        raise CheckpointError("snapshot 必须是 object")
    if any(not isinstance(key, str) for key in snapshot):
        raise CheckpointError("snapshot key 类型不支持")
    expected = {"branch", "common_dir", "dirty", "head", "ignored", "index_sha256",
                "staged", "worktree", "working_tree_diff_sha256"}
    if set(snapshot) != expected:
        raise CheckpointError("snapshot 字段不完整或包含 unsupported 字段")
    for field in ("branch", "common_dir", "head", "index_sha256", "worktree",
                  "working_tree_diff_sha256"):
        _nonempty_text(snapshot[field], f"snapshot.{field}", allow_unknown=False)
    staged = snapshot["staged"]
    if not isinstance(staged, list) or any(not isinstance(item, str) for item in staged):
        raise CheckpointError("snapshot.staged 类型不支持")
    if staged != sorted(set(staged)):
        raise CheckpointError("snapshot.staged 必须按路径排序且去重")
    ignored = snapshot["ignored"]
    if not isinstance(ignored, dict) or set(ignored) != {"delivery_input", "fingerprints", "paths"}:
        raise CheckpointError("snapshot.ignored 缺少排除状态")
    if (not isinstance(ignored["delivery_input"], str)
            or ignored["delivery_input"] not in {"none", UNKNOWN}):
        raise CheckpointError("ignored 交付输入状态不支持")
    if not isinstance(ignored["paths"], list) or any(not isinstance(item, str) for item in ignored["paths"]):
        raise CheckpointError("snapshot.ignored.paths 类型不支持")
    if ignored["paths"] != sorted(set(ignored["paths"])):
        raise CheckpointError("snapshot.ignored.paths 必须按路径排序且去重")
    if ((ignored["delivery_input"] == "none") != (not ignored["paths"])):
        raise CheckpointError("ignored 交付输入状态与路径清单不一致")
    fingerprints = ignored["fingerprints"]
    if (not isinstance(fingerprints, dict)
            or any(not isinstance(key, str) for key in fingerprints)
            or list(fingerprints) != sorted(fingerprints)):
        raise CheckpointError("snapshot.ignored.fingerprints 必须按路径排序")
    if set(fingerprints) != set(ignored["paths"]):
        raise CheckpointError("snapshot.ignored.fingerprints 与路径清单不一致")
    for name, item in fingerprints.items():
        if not isinstance(item, dict) or set(item) != {"content_sha256", "deleted", "kind", "mode"}:
            raise CheckpointError(f"snapshot.ignored unsupported 字段: {name}")
        if item["deleted"] is not False or item["kind"] not in {"file", "symlink"}:
            raise CheckpointError(f"snapshot.ignored 文件类型不支持: {name}")
        if type(item["mode"]) is not int:
            raise CheckpointError(f"snapshot.ignored 文件模式不支持: {name}")
        _nonempty_text(item["content_sha256"], f"snapshot.ignored.{name}.content_sha256", allow_unknown=False)
    dirty = snapshot["dirty"]
    if not isinstance(dirty, dict) or any(not isinstance(key, str) for key in dirty):
        raise CheckpointError("snapshot.dirty 必须是按路径排序的 object")
    if list(dirty) != sorted(dirty):
        raise CheckpointError("snapshot.dirty 必须按路径排序")
    for name, item in dirty.items():
        if not isinstance(name, str) or not isinstance(item, dict):
            raise CheckpointError("snapshot.dirty 类型不支持")
        if set(item) != {"content_sha256", "deleted", "kind", "mode"}:
            raise CheckpointError(f"snapshot.dirty unsupported 字段: {name}")
        if type(item["deleted"]) is not bool or not isinstance(item["kind"], str):
            raise CheckpointError(f"snapshot.dirty 类型不支持: {name}")
        if item["deleted"]:
            if item["kind"] != "deleted" or item["mode"] is not None or item["content_sha256"] is not None:
                raise CheckpointError(f"删除项必须显式记录: {name}")
        else:
            if item["kind"] not in {"file", "symlink"} or type(item["mode"]) is not int:
                raise CheckpointError(f"snapshot.dirty 文件模式不支持: {name}")
            _nonempty_text(item["content_sha256"], f"snapshot.dirty.{name}.content_sha256", allow_unknown=False)
    return snapshot


def validate_checkpoint(document: object, *, worktree: str | Path | None = None,
                        expected_lane: str | None = None,
                        expected_base: str | None = None) -> dict[str, Any]:
    """严格校验持久 checkpoint；Unknown 是显式证据，不是缺省值。"""
    if not isinstance(document, dict):
        raise CheckpointError("checkpoint 顶层必须是 object")
    if any(not isinstance(key, str) for key in document):
        raise CheckpointError("checkpoint key 类型不支持")
    if set(document) != REQUIRED_FIELDS:
        missing = sorted(REQUIRED_FIELDS - set(document))
        extra = sorted(set(document) - REQUIRED_FIELDS)
        raise CheckpointError(f"checkpoint 字段不匹配: missing={missing}, extra={extra}")
    if type(document["checkpoint_version"]) is not int or document["checkpoint_version"] != CHECKPOINT_VERSION:
        raise CheckpointError("拒绝旧版本或 unsupported checkpoint version")
    for field in ("lane_id", "work_item", "runtime", "session_id", "coordinator_thread_id",
                  "coordinator_host_id", "execution_worktree", "execution_branch", "base_commit",
                  "head_commit", "phase", "development_mode", "mode_source"):
        _nonempty_text(document[field], field, allow_unknown=False)
    for field in ("cli_version", "actual_model", "actual_effort", "actual_readback_source",
                  "actual_readback_at"):
        _nonempty_text(document[field], field)
    for field in ("requested_model", "requested_effort"):
        _nonempty_text(document[field], field, allow_unknown=False)
    for field in ("execution_worktree", "checkpoint_path"):
        if not Path(document[field]).is_absolute():
            raise CheckpointError(f"{field} 必须是绝对路径")
    if worktree is not None:
        _ensure_external(Path(document["checkpoint_path"]), worktree)
    if expected_lane is not None and document["lane_id"] != expected_lane:
        raise CheckpointError("checkpoint lane_id 不匹配")
    if expected_base is not None and document["base_commit"] != expected_base:
        raise CheckpointError("checkpoint base_commit 不匹配")
    phase = document["phase"]
    development_mode = document["development_mode"]
    mode_source = document["mode_source"]
    if phase not in PHASES:
        raise CheckpointError("phase 不属于冻结阶段")
    if development_mode not in EXECUTION_MODES:
        raise CheckpointError("development_mode 不属于冻结执行方式")
    if mode_source not in EXECUTION_SOURCES:
        raise CheckpointError("mode_source 不属于冻结来源")
    if development_mode == "staged" and phase == "direct":
        raise CheckpointError("staged 计划不能标记 direct 阶段")
    if development_mode in {"legacy", "direct"} and phase != "direct":
        raise CheckpointError("legacy/direct 计划只能标记 direct 阶段")
    phase_plan = document["phase_plan"]
    if not isinstance(phase_plan, dict) or set(phase_plan) != set(PHASES):
        raise CheckpointError("phase_plan 必须完整包含 starting/execution/direct")
    for stage, pair in phase_plan.items():
        if not isinstance(stage, str) or not isinstance(pair, dict) or set(pair) != {"model", "effort"}:
            raise CheckpointError("phase_plan 含 unsupported 字段或类型")
        _nonempty_text(pair["model"], f"phase_plan.{stage}.model", allow_unknown=False)
        _nonempty_text(pair["effort"], f"phase_plan.{stage}.effort", allow_unknown=False)
    if phase_plan[phase] != {"model": document["requested_model"],
                             "effort": document["requested_effort"]}:
        raise CheckpointError("phase_plan 当前阶段与 requested model/effort 不一致")
    tool_acceptance = document["tool_acceptance"]
    if not isinstance(tool_acceptance, dict) or set(tool_acceptance) != TOOL_ACCEPTANCE_FIELDS:
        raise CheckpointError("tool_acceptance 必须明确 accepted/status/source")
    accepted = tool_acceptance["accepted"]
    status = tool_acceptance["status"]
    if accepted is not True and accepted is not False and accepted is not None:
        raise CheckpointError("tool_acceptance.accepted 类型不支持")
    if not isinstance(status, str) or status not in TOOL_ACCEPTANCE_STATUSES:
        raise CheckpointError("tool_acceptance.status 不支持")
    if ((status == "accepted" and accepted is not True)
            or (status == "rejected" and accepted is not False)
            or (status == UNKNOWN and accepted is not None)):
        raise CheckpointError("tool_acceptance accepted/status 不一致")
    _nonempty_text(tool_acceptance["source"], "tool_acceptance.source")
    first_edit = document["first_edit"]
    if not isinstance(first_edit, list) or not first_edit or any(not isinstance(item, str) for item in first_edit):
        raise CheckpointError("first_edit 必须是非空路径列表")
    if first_edit != sorted(set(first_edit)):
        raise CheckpointError("first_edit 必须按路径排序且去重")
    checks = document["checks"]
    if not isinstance(checks, list) or not checks:
        raise CheckpointError("checks 必须是非空列表")
    for check in checks:
        if not isinstance(check, dict) or set(check) != {"command", "result"}:
            raise CheckpointError("checks 项字段不支持")
        _nonempty_text(check["command"], "checks.command", allow_unknown=False)
        _nonempty_text(check["result"], "checks.result")
    for field in ("todo", "evidence"):
        values = document[field]
        if not isinstance(values, list) or not values or any(not isinstance(item, str) or not item.strip() for item in values):
            raise CheckpointError(f"{field} 必须是非空文本列表")
    decision = document["decision"]
    if not isinstance(decision, dict) or set(decision) != {"critical_design_unknown", "reason"}:
        raise CheckpointError("decision 必须明确 critical_design_unknown")
    if type(decision["critical_design_unknown"]) is not bool:
        raise CheckpointError("decision.critical_design_unknown 类型不支持")
    _nonempty_text(decision["reason"], "decision.reason")
    snapshot = _validate_snapshot(document["snapshot"])
    if any(path not in snapshot["dirty"] for path in first_edit):
        raise CheckpointError("first_edit 必须属于当前 dirty snapshot")
    if snapshot["head"] != document["head_commit"] or snapshot["branch"] != document["execution_branch"]:
        raise CheckpointError("checkpoint Git HEAD/branch 与 snapshot 不一致")
    if snapshot["worktree"] != document["execution_worktree"]:
        raise CheckpointError("checkpoint Execution Worktree 与 snapshot 不一致")
    components = document["component_sha256"]
    if not isinstance(components, dict) or set(components) != set(COMPONENT_FIELDS):
        raise CheckpointError("component_sha256 字段不完整")
    expected_components = _component_hashes(snapshot)
    if components != expected_components:
        raise CheckpointError("component SHA-256 不匹配")
    if document[FINGERPRINT_FIELD] != checkpoint_sha256(document):
        raise CheckpointError("整体 checkpoint SHA-256 不匹配")
    if worktree is not None:
        current = snapshot_worktree(worktree)
        if current != snapshot:
            raise CheckpointError("checkpoint 已过期：Git/dirty/index snapshot 改变")
        result = subprocess.run(["git", "-C", str(Path(worktree).resolve(strict=True)),
                                 "merge-base", "--is-ancestor", document["base_commit"],
                                 document["head_commit"]], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, check=False, env=_git_env())
        if result.returncode:
            raise CheckpointError("base_commit 不是 HEAD 的祖先")
    return document


def build_checkpoint(payload: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    """由 worker 首改现场构造新版本，不改写旧 checkpoint。"""
    if not isinstance(payload, dict):
        raise CheckpointError("checkpoint payload 必须是 object")
    _validate_snapshot(snapshot)
    snapshot = json.loads(canonical_bytes(snapshot))
    document = dict(payload)
    document["checkpoint_version"] = CHECKPOINT_VERSION
    document["snapshot"] = snapshot
    document["component_sha256"] = _component_hashes(snapshot)
    document[FINGERPRINT_FIELD] = checkpoint_sha256(document)
    return validate_checkpoint(document)


def _ensure_external(path: Path, worktree: str | Path | None) -> None:
    if not path.is_absolute():
        raise CheckpointError("checkpoint path 必须是绝对路径")
    if worktree is not None and path.resolve(strict=False).is_relative_to(Path(worktree).resolve(strict=True)):
        raise CheckpointError("checkpoint 必须位于 repo 外")


def write_checkpoint(path: str | Path, document: dict[str, Any], *, worktree: str | Path | None = None) -> Path:
    """同目录 flush+fsync 后原子替换，并 fsync 父目录。"""
    target = Path(path).expanduser()
    validate_checkpoint(document, worktree=worktree)
    _ensure_external(target, document["execution_worktree"])
    if Path(document["checkpoint_path"]).resolve(strict=False) != target.resolve(strict=False):
        raise CheckpointError("checkpoint path 与持久化目标不一致")
    parent = target.parent
    if not parent.is_dir():
        raise CheckpointError(f"checkpoint 父目录不存在: {parent}")
    if target.exists():
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise CheckpointError(f"拒绝覆盖不可读的旧 checkpoint: {error}") from error
        if not isinstance(existing, dict) or existing.get("checkpoint_version") != CHECKPOINT_VERSION:
            raise CheckpointError("拒绝就地补造旧版本 checkpoint")
        validate_checkpoint(existing)
        if Path(existing["checkpoint_path"]).resolve(strict=False) != target.resolve(strict=False):
            raise CheckpointError("既有 checkpoint 坐标与目标不一致")
        if existing[FINGERPRINT_FIELD] != document[FINGERPRINT_FIELD]:
            raise CheckpointError("拒绝覆盖既有 checkpoint；更新须使用新 artifact 路径")
    temp_name: str | None = None
    try:
        fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=parent)
        with os.fdopen(fd, "wb") as stream:
            stream.write(canonical_bytes(document))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, target)
        temp_name = None
        directory_fd = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError as error:
        if temp_name is not None:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
        raise CheckpointError(f"checkpoint 原子写失败，未登记成功引用: {error}") from error
    return target


def read_checkpoint(path: str | Path, *, worktree: str | Path | None = None,
                    expected_lane: str | None = None,
                    expected_base: str | None = None) -> dict[str, Any]:
    target = Path(path).expanduser()
    _ensure_external(target, worktree)
    if not target.is_file():
        raise CheckpointError("checkpoint 路径不是普通文件")
    try:
        raw = target.read_bytes()
        document = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CheckpointError(f"checkpoint 持久读回失败: {error}") from error
    result = validate_checkpoint(document, worktree=worktree, expected_lane=expected_lane,
                                 expected_base=expected_base)
    if raw != canonical_bytes(result):
        raise CheckpointError("checkpoint 不是确定性紧凑 UTF-8 JSON")
    if Path(result["checkpoint_path"]).resolve(strict=False) != target.resolve(strict=False):
        raise CheckpointError("checkpoint artifact path 与读回目标不一致")
    return result


def parse_signal(line: str) -> tuple[str, str, str]:
    if not isinstance(line, str):
        raise CheckpointError("阶段信号必须是文本")
    parts = line.strip().split(maxsplit=2)
    if (len(parts) != 3 or parts[0] not in SIGNALS or not parts[1].strip()
            or not parts[2].strip() or not Path(parts[2]).is_absolute()):
        raise CheckpointError("unsupported 或缺失阶段信号")
    return parts[0], parts[1], parts[2]


def _blocked(signal: str, checkpoint_path: str, reason: str) -> dict[str, Any]:
    return {"action": "blocked", "can_continue": False, "checkpoint_path": checkpoint_path,
            "fan_in": False, "send_request": None, "signal": signal, "reason": reason}


def _observation_matches(document: dict[str, Any], observation: dict[str, Any]) -> bool:
    return all(observation.get(field) == document[field]
               and isinstance(observation.get(field), str)
               and observation[field].strip()
               and not _is_unknown(observation[field])
               for field in OBSERVATION_IDENTITY_FIELDS)


def _tool_is_accepted(document: dict[str, Any]) -> bool:
    result = document["tool_acceptance"]
    return (result["accepted"] is True and result["status"] == "accepted"
            and not _is_unknown(result["source"]))


def _ignored_is_safe(document: dict[str, Any]) -> bool:
    ignored = document["snapshot"]["ignored"]
    return ignored["delivery_input"] == "none" and ignored["paths"] == []


def evaluate_signal(document: dict[str, Any], line: str, observation: dict[str, Any]) -> dict[str, Any]:
    """只返回核验动作；不发送接续、不触发 Terminal fan-in。"""
    persisted = read_checkpoint(document["checkpoint_path"], worktree=document["execution_worktree"])
    if persisted != document:
        raise CheckpointError("阶段信号 checkpoint 未完成持久读回")
    signal, lane_id, checkpoint_path = parse_signal(line)
    if lane_id != document["lane_id"]:
        raise CheckpointError("阶段信号 lane_id 不匹配")
    if checkpoint_path != document["checkpoint_path"]:
        raise CheckpointError("阶段信号 checkpoint path 不匹配")
    if not isinstance(observation, dict):
        raise CheckpointError("runtime observation 必须是 object")
    if not _observation_matches(document, observation):
        return _blocked(signal, checkpoint_path, "runtime/session/coordinator 身份缺失或不匹配")
    if not _tool_is_accepted(document):
        return _blocked(signal, checkpoint_path, "tool acceptance 被拒绝或 Unknown")
    if not _ignored_is_safe(document):
        return _blocked(signal, checkpoint_path, "ignored 交付输入未确认无关")
    if signal == "PREWALK_READY":
        status = observation.get("status")
        if _is_unknown(status) or status is None or _is_unknown(observation.get("writer_active")):
            return _blocked(signal, checkpoint_path, "PREWALK_READY 的 runtime 状态 Unknown")
        return {"action": "await-stop", "can_continue": False, "checkpoint_path": checkpoint_path,
                "fan_in": False, "send_request": None, "signal": signal}

    status = observation.get("status")
    writer_active = observation.get("writer_active")
    if status == "active":
        return {"action": "wait-for-stop", "can_continue": False, "checkpoint_path": checkpoint_path,
                "fan_in": False, "send_request": None, "signal": signal}
    if status is None or _is_unknown(status) or writer_active is not False:
        return _blocked(signal, checkpoint_path, "停止或单写者状态 Unknown")
    if observation.get("ready_seen") is not True:
        return _blocked(signal, checkpoint_path, "PREWALK_READY 尚未核验")
    if status not in {"idle", "stopped"} or observation.get("stop_evidence") is not True:
        return _blocked(signal, checkpoint_path, "缺少可核验停止证据")
    if document["decision"]["critical_design_unknown"]:
        return _blocked(signal, checkpoint_path, "关键设计 Unknown")
    if any(_is_unknown(document[field]) for field in
           ("actual_model", "actual_effort", "actual_readback_source", "actual_readback_at")):
        return {"action": "ready-with-runtime-unknown", "can_continue": False,
                "checkpoint_path": checkpoint_path, "fan_in": False, "send_request": None,
                "signal": signal, "reason": "实际 model/effort Unknown，保留现场"}
    return {"action": "ready-for-coordinator", "can_continue": True,
            "checkpoint_path": checkpoint_path, "fan_in": False, "send_request": None,
            "signal": signal}


def self_test() -> None:
    document = {"阶段": "starting", "lane_id": "map-95-issue-101"}
    expected = b'{"lane_id":"map-95-issue-101","\xe9\x98\xb6\xe6\xae\xb5":"starting"}'
    assert canonical_bytes(document) == expected
    fingerprint = checkpoint_sha256(document)
    assert checkpoint_sha256({**document, FINGERPRINT_FIELD: fingerprint}) == fingerprint
    assert parse_signal("PREWALK_READY lane /tmp/checkpoint.json") == (
        "PREWALK_READY", "lane", "/tmp/checkpoint.json")
    try:
        parse_signal("LANE_DONE lane")
    except CheckpointError:
        pass
    else:
        raise AssertionError("unsupported signal was accepted")


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("self-test")
    snapshot_parser = subparsers.add_parser("snapshot")
    snapshot_parser.add_argument("worktree")
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("path")
    validate_parser.add_argument("--worktree")
    signal_parser = subparsers.add_parser("signal")
    signal_parser.add_argument("path")
    signal_parser.add_argument("line")
    signal_parser.add_argument("observation", help="JSON runtime observation")
    args = parser.parse_args()
    try:
        if args.command == "self-test":
            self_test()
            print(canonical_bytes({"valid": True}).decode())
        elif args.command == "snapshot":
            print(canonical_bytes(snapshot_worktree(args.worktree)).decode())
        elif args.command == "validate":
            result = read_checkpoint(args.path, worktree=args.worktree)
            print(canonical_bytes({"valid": True, "checkpoint_sha256": result[FINGERPRINT_FIELD]}).decode())
        else:
            document = read_checkpoint(args.path)
            result = evaluate_signal(document, args.line, json.loads(args.observation))
            print(canonical_bytes(result).decode())
        return 0
    except (CheckpointError, OSError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(_main())
