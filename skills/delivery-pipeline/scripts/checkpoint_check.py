#!/usr/bin/env python3
"""隔离 Git 与模拟 runtime 的 checkpoint 回归检查。"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile


HELPER = Path(__file__).with_name("checkpoint.py")
SPEC = importlib.util.spec_from_file_location("delivery_checkpoint", HELPER)
assert SPEC and SPEC.loader
CHECKPOINT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKPOINT)


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=CHECKPOINT._git_env())


def rejects(callable_, *args, **kwargs) -> str:
    try:
        callable_(*args, **kwargs)
    except CHECKPOINT.CheckpointError as error:
        return str(error)
    raise AssertionError(f"expected rejection from {callable_.__name__}")


def document_for(snapshot: dict, checkpoint_path: Path) -> dict:
    return CHECKPOINT.build_checkpoint({
        "lane_id": "probe-101",
        "work_item": "https://github.com/Dimon94/delivery-pipeline/issues/101",
        "runtime": "herdr-codex-pane",
        "session_id": "worker-session",
        "coordinator_thread_id": "coordinator-session",
        "coordinator_host_id": "local",
        "cli_version": "Unknown",
        "execution_worktree": snapshot["worktree"],
        "execution_branch": snapshot["branch"],
        "base_commit": snapshot["head"],
        "head_commit": snapshot["head"],
        "phase": "starting",
        "development_mode": "staged",
        "mode_source": "user-config",
        "phase_plan": {
            "starting": {"model": "start-model", "effort": "high"},
            "execution": {"model": "execution-model", "effort": "max"},
            "direct": {"model": "direct-model", "effort": "high"},
        },
        "requested_model": "start-model",
        "requested_effort": "high",
        "tool_acceptance": {"accepted": True, "status": "accepted", "source": "runtime"},
        "actual_model": "start-model",
        "actual_effort": "high",
        "actual_readback_source": "turn-context",
        "actual_readback_at": "2026-09-08T00:00:00Z",
        "first_edit": ["worker.py"],
        "checks": [{"command": "python3 -m compileall worker.py", "result": "exit 0"}],
        "todo": ["continue implementation"],
        "decision": {"critical_design_unknown": False, "reason": "最小方案已确定"},
        "evidence": ["spec-99", "ticket-101"],
        "checkpoint_path": str(checkpoint_path),
    }, snapshot)


def with_update(document: dict, **updates) -> dict:
    result = copy.deepcopy(document)
    result.update(updates)
    result[CHECKPOINT.FINGERPRINT_FIELD] = CHECKPOINT.checkpoint_sha256(result)
    return result


def observation(document: dict, **updates) -> dict:
    result = {
        "runtime": document["runtime"],
        "session_id": document["session_id"],
        "coordinator_thread_id": document["coordinator_thread_id"],
        "coordinator_host_id": document["coordinator_host_id"],
    }
    result.update(updates)
    return result


def signal_for(document: dict, name: str) -> str:
    return f"{name} {document['lane_id']} {document['checkpoint_path']}"


def persist_variant(directory: Path, root: Path, document: dict, name: str, **updates) -> dict:
    path = directory / "registry" / f"{name}.json"
    variant = with_update(document, checkpoint_path=str(path), **updates)
    CHECKPOINT.write_checkpoint(path, variant, worktree=root)
    return variant


def check() -> None:
    with tempfile.TemporaryDirectory(prefix="checkpoint-101-") as folder:
        directory = Path(folder)
        root = directory / "execution"
        root.mkdir()
        git(root, "init", "-b", "main")
        git(root, "config", "user.name", "checkpoint-probe")
        git(root, "config", "user.email", "checkpoint@example.invalid")
        (root / "base.txt").write_text("base\n", encoding="utf-8")
        (root / "deleted.txt").write_text("delete me\n", encoding="utf-8")
        git(root, "add", "base.txt", "deleted.txt")
        git(root, "commit", "-m", "base")
        git(root, "checkout", "--detach")
        (root / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
        (root / "ignored.txt").write_text("must not enter checkpoint\n", encoding="utf-8")
        (root / "worker.py").write_text("first edit\n", encoding="utf-8")
        snapshot = CHECKPOINT.snapshot_worktree(root)
        assert snapshot["branch"] == "HEAD"
        assert snapshot["staged"] == []
        assert snapshot["dirty"]["worker.py"]["kind"] == "file"
        assert snapshot["ignored"]["paths"] == ["ignored.txt"]
        assert snapshot["ignored"]["delivery_input"] == "Unknown"
        assert snapshot["ignored"]["fingerprints"]["ignored.txt"]["kind"] == "file"
        assert "deleted.txt" not in snapshot["dirty"]
        rejects(CHECKPOINT.snapshot_worktree, root, required_ignored=["ignored.txt"])

        (root / "ignored.txt").unlink()
        (root / ".gitignore").unlink()
        snapshot = CHECKPOINT.snapshot_worktree(root)
        assert snapshot["ignored"] == {"delivery_input": "none", "fingerprints": {}, "paths": []}

        (root / "deleted.txt").unlink()
        deleted_snapshot = CHECKPOINT.snapshot_worktree(root)
        assert deleted_snapshot["dirty"]["deleted.txt"] == {
            "content_sha256": None, "deleted": True, "kind": "deleted", "mode": None}
        (root / "deleted.txt").write_text("delete me\n", encoding="utf-8")
        snapshot = CHECKPOINT.snapshot_worktree(root)
        checkpoint_path = directory / "registry" / "checkpoint.json"
        checkpoint_path.parent.mkdir()
        document = document_for(snapshot, checkpoint_path)
        intent = CHECKPOINT.build_continuation_intent(document)
        assert intent == CHECKPOINT.build_continuation_intent(document)
        changed_target = with_update(document, phase_plan={
            **document["phase_plan"],
            "execution": {"model": "other-model", "effort": "max"},
        })
        assert (CHECKPOINT.build_continuation_intent(changed_target)[CHECKPOINT.INTENT_FINGERPRINT_FIELD]
                != intent[CHECKPOINT.INTENT_FINGERPRINT_FIELD])
        CHECKPOINT.write_checkpoint(checkpoint_path, document, worktree=root)
        assert checkpoint_path.read_bytes() == CHECKPOINT.canonical_bytes(document)
        assert CHECKPOINT.read_checkpoint(checkpoint_path, worktree=root,
                                          expected_lane="probe-101", expected_base=snapshot["head"]) == document
        checkpoint_path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
        rejects(CHECKPOINT.read_checkpoint, checkpoint_path, worktree=root)
        CHECKPOINT.write_checkpoint(checkpoint_path, document, worktree=root)

        ready = signal_for(document, "PREWALK_READY")
        stopped = signal_for(document, "WORKER_STOPPED")
        assert CHECKPOINT.evaluate_signal(document, ready,
                                          observation(document, status="active", writer_active=True))["action"] == "await-stop"
        assert CHECKPOINT.evaluate_signal(document, ready,
                                          observation(document, status="Unknown", writer_active=False))["action"] == "blocked"
        assert CHECKPOINT.evaluate_signal(document, ready,
                                          observation(document, status="stopped", writer_active=False))["can_continue"] is False
        assert CHECKPOINT.evaluate_signal(document, stopped,
                                          observation(document, status="active", writer_active=True))["action"] == "wait-for-stop"
        assert CHECKPOINT.evaluate_signal(document, stopped,
                                          observation(document, status="Unknown", writer_active=False))["action"] == "blocked"
        assert CHECKPOINT.evaluate_signal(document, stopped,
                                          observation(document, status="stopped", writer_active=False,
                                                      stop_evidence=True, ready_seen=False))["action"] == "blocked"
        assert CHECKPOINT.evaluate_signal(document, stopped,
                                          observation(document, status="stopped", writer_active=False,
                                                      stop_evidence=True, ready_seen=True))["action"] == "ready-for-coordinator"
        ready_result = CHECKPOINT.evaluate_signal(document, stopped,
                                                   observation(document, status="stopped", writer_active=False,
                                                               stop_evidence=True, ready_seen=True))
        assert ready_result["send_request"] is None and ready_result["fan_in"] is False
        mismatch = observation(document, status="stopped", writer_active=False,
                               stop_evidence=True, ready_seen=True, session_id="other-session")
        assert CHECKPOINT.evaluate_signal(document, stopped, mismatch)["action"] == "blocked"
        unknown_identity = observation(document, status="stopped", writer_active=False,
                                       stop_evidence=True, ready_seen=True, runtime="Unknown")
        assert CHECKPOINT.evaluate_signal(document, stopped, unknown_identity)["action"] == "blocked"
        original_bytes = checkpoint_path.read_bytes()
        rejected_tool = with_update(document, tool_acceptance={
            "accepted": False, "status": "rejected", "source": "runtime"})
        rejects(CHECKPOINT.write_checkpoint, checkpoint_path, rejected_tool, worktree=root)
        assert checkpoint_path.read_bytes() == original_bytes
        rejected_tool = persist_variant(directory, root, document, "rejected-tool",
                                        tool_acceptance=rejected_tool["tool_acceptance"])
        assert CHECKPOINT.evaluate_signal(rejected_tool, signal_for(rejected_tool, "WORKER_STOPPED"),
                                          observation(rejected_tool, status="stopped", writer_active=False,
                                                      stop_evidence=True, ready_seen=True))["action"] == "blocked"
        unknown_tool = persist_variant(directory, root, document, "unknown-tool", tool_acceptance={
            "accepted": None, "status": "Unknown", "source": "Unknown"})
        assert CHECKPOINT.evaluate_signal(unknown_tool, signal_for(unknown_tool, "WORKER_STOPPED"),
                                          observation(unknown_tool, status="stopped", writer_active=False,
                                                      stop_evidence=True, ready_seen=True))["action"] == "blocked"
        rejects(CHECKPOINT.validate_checkpoint, with_update(document, tool_acceptance=["Unknown"]))
        missing_execution = copy.deepcopy(document)
        del missing_execution["phase_plan"]["execution"]
        missing_execution[CHECKPOINT.FINGERPRINT_FIELD] = CHECKPOINT.checkpoint_sha256(missing_execution)
        rejects(CHECKPOINT.validate_checkpoint, missing_execution)
        unsupported_mode = with_update(document, development_mode="sol-luna")
        rejects(CHECKPOINT.validate_checkpoint, unsupported_mode)
        ignored_root = root / ".gitignore"
        ignored_root.write_text("ignored.txt\n", encoding="utf-8")
        ignored_file = root / "ignored.txt"
        ignored_file.write_text("delivery input?\n", encoding="utf-8")
        ignored_snapshot = CHECKPOINT.snapshot_worktree(root)
        ignored_document = document_for(ignored_snapshot, directory / "registry" / "ignored-input.json")
        CHECKPOINT.write_checkpoint(ignored_document["checkpoint_path"], ignored_document, worktree=root)
        assert CHECKPOINT.evaluate_signal(ignored_document, signal_for(ignored_document, "WORKER_STOPPED"),
                                          observation(ignored_document, status="stopped", writer_active=False,
                                                      stop_evidence=True, ready_seen=True))["action"] == "blocked"
        ignored_file.write_text("changed delivery input\n", encoding="utf-8")
        rejects(CHECKPOINT.read_checkpoint, ignored_document["checkpoint_path"], worktree=root)
        ignored_file.unlink()
        ignored_root.unlink()
        unknown_runtime = persist_variant(directory, root, document, "unknown-runtime",
                                          actual_model="Unknown")
        assert CHECKPOINT.evaluate_signal(unknown_runtime, signal_for(unknown_runtime, "WORKER_STOPPED"),
                                          observation(unknown_runtime, status="stopped", writer_active=False,
                                                      stop_evidence=True, ready_seen=True))["action"] == "ready-with-runtime-unknown"
        unknown_runtime_spaced = persist_variant(directory, root, document, "unknown-runtime-spaced",
                                                 actual_model=" Unknown ")
        assert CHECKPOINT.evaluate_signal(unknown_runtime_spaced,
                                          signal_for(unknown_runtime_spaced, "WORKER_STOPPED"),
                                          observation(unknown_runtime_spaced, status="stopped",
                                                      writer_active=False, stop_evidence=True,
                                                      ready_seen=True))["action"] == "ready-with-runtime-unknown"
        unknown_source = persist_variant(directory, root, document, "unknown-source",
                                         actual_readback_source="Unknown")
        assert CHECKPOINT.evaluate_signal(unknown_source, signal_for(unknown_source, "WORKER_STOPPED"),
                                          observation(unknown_source, status="stopped", writer_active=False,
                                                      stop_evidence=True, ready_seen=True))["action"] == "ready-with-runtime-unknown"
        unknown_design = persist_variant(directory, root, document, "unknown-design",
                                         decision={"critical_design_unknown": True,
                                                   "reason": "关键设计 Unknown"})
        assert CHECKPOINT.evaluate_signal(unknown_design, signal_for(unknown_design, "WORKER_STOPPED"),
                                          observation(unknown_design, status="stopped", writer_active=False,
                                                      stop_evidence=True, ready_seen=True))["action"] == "blocked"
        CHECKPOINT.write_checkpoint(checkpoint_path, document, worktree=root)
        (root / "worker.py").write_text("changed\n", encoding="utf-8")
        rejects(CHECKPOINT.read_checkpoint, checkpoint_path, worktree=root)
        (root / "worker.py").write_text("first edit\n", encoding="utf-8")
        os.chmod(root / "worker.py", 0o755)
        rejects(CHECKPOINT.read_checkpoint, checkpoint_path, worktree=root)
        os.chmod(root / "worker.py", 0o644)
        git(root, "add", "worker.py")
        rejects(CHECKPOINT.read_checkpoint, checkpoint_path, worktree=root)
        git(root, "reset", "HEAD", "--", "worker.py")
        (root / "base.txt").write_text("staged change\n", encoding="utf-8")
        git(root, "add", "base.txt")
        (root / "base.txt").write_text("base\n", encoding="utf-8")
        staged_restored = CHECKPOINT.snapshot_worktree(root)
        assert staged_restored["staged"] == ["base.txt"]
        assert staged_restored["dirty"]["base.txt"]["content_sha256"] == hashlib.sha256(
            b"base\n").hexdigest()
        os.chmod(root / "base.txt", 0o600)
        assert CHECKPOINT.snapshot_worktree(root) != staged_restored
        os.chmod(root / "base.txt", 0o644)
        git(root, "reset", "HEAD", "--", "base.txt")
        fifo = root / "unsupported.fifo"
        os.mkfifo(fifo)
        rejects(CHECKPOINT._file_record, fifo)
        fifo.unlink()

        old = with_update(document, checkpoint_version=0)
        rejects(CHECKPOINT.validate_checkpoint, old)
        rejects(CHECKPOINT.validate_checkpoint, {1: "unsupported"})
        rejects(CHECKPOINT.write_checkpoint, root / "inside.json", document, worktree=root)
        rejects(CHECKPOINT.write_checkpoint, root / "inside-no-worktree.json", document)
        missing_parent = directory / "missing" / "checkpoint.json"
        rejects(CHECKPOINT.write_checkpoint, missing_parent, document)
        assert not missing_parent.exists()
        old_path = directory / "registry" / "old.json"
        old_path.write_text('{"checkpoint_version":0}', encoding="utf-8")
        old_document = dict(document, checkpoint_path=str(old_path))
        old_document[CHECKPOINT.FINGERPRINT_FIELD] = CHECKPOINT.checkpoint_sha256(old_document)
        rejects(CHECKPOINT.write_checkpoint, old_path, old_document, worktree=root)
        assert not (root / "inside.json").exists()
    print("checkpoint: pass (snapshot, hashes, atomic readback, stale/unsupported/ignored, signal boundary)")


if __name__ == "__main__":
    check()
