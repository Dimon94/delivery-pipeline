#!/usr/bin/env python3
"""模拟 adapter 回归：验证 #102 接续事务的单写者与去重边界。"""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
CHECKPOINT_SPEC = importlib.util.spec_from_file_location("checkpoint", ROOT / "checkpoint.py")
assert CHECKPOINT_SPEC and CHECKPOINT_SPEC.loader
CHECKPOINT = importlib.util.module_from_spec(CHECKPOINT_SPEC)
sys.modules["checkpoint"] = CHECKPOINT
CHECKPOINT_SPEC.loader.exec_module(CHECKPOINT)
CONTINUATION_SPEC = importlib.util.spec_from_file_location("continuation", ROOT / "continuation.py")
assert CONTINUATION_SPEC and CONTINUATION_SPEC.loader
CONTINUATION = importlib.util.module_from_spec(CONTINUATION_SPEC)
CONTINUATION_SPEC.loader.exec_module(CONTINUATION)


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=CHECKPOINT._git_env())


def document_for(root: Path, checkpoint_path: Path) -> dict:
    (root / "worker.py").write_text("first edit\n", encoding="utf-8")
    snapshot = CHECKPOINT.snapshot_worktree(root)
    return CHECKPOINT.build_checkpoint({
        "lane_id": "probe-102",
        "work_item": "https://github.com/Dimon94/delivery-pipeline/issues/102",
        "runtime": "simulated",
        "session_id": "worker-session",
        "coordinator_thread_id": "coordinator-session",
        "coordinator_host_id": "local",
        "cli_version": "simulated",
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
        "tool_acceptance": {"accepted": True, "status": "accepted", "source": "simulated"},
        "actual_model": "start-model",
        "actual_effort": "high",
        "actual_readback_source": "simulated",
        "actual_readback_at": "2026-09-08T00:00:00Z",
        "first_edit": ["worker.py"],
        "checks": [{"command": "python3 -m compileall worker.py", "result": "exit 0"}],
        "todo": ["continue implementation"],
        "decision": {"critical_design_unknown": False, "reason": "最小方案已确定"},
        "evidence": ["spec-99", "ticket-102"],
        "checkpoint_path": str(checkpoint_path),
    }, snapshot)


def lane_for(document: dict) -> dict:
    return {
        "lane_id": document["lane_id"],
        "work_item": document["work_item"],
        "runtime": document["runtime"],
        "state": "running",
        "output_mode": "commit",
        "checkpoint": document["checkpoint_path"],
        "checkpoint_version": document["checkpoint_version"],
        "checkpoint_sha256": document[CHECKPOINT.FINGERPRINT_FIELD],
        "coordinator_thread_id": document["coordinator_thread_id"],
        "coordinator_host_id": document["coordinator_host_id"],
        "execution_mode": document["development_mode"],
        "execution_source": document["mode_source"],
        "starting_model": document["phase_plan"]["starting"]["model"],
        "starting_effort": document["phase_plan"]["starting"]["effort"],
        "execution_model": document["phase_plan"]["execution"]["model"],
        "execution_effort": document["phase_plan"]["execution"]["effort"],
        "direct_model": document["phase_plan"]["direct"]["model"],
        "direct_effort": document["phase_plan"]["direct"]["effort"],
        "worktree": document["execution_worktree"],
        "branch": document["execution_branch"],
        "base_commit": document["base_commit"],
        "head_commit": document["head_commit"],
        "execution_phase": "starting",
    }


def observation(document: dict, **updates) -> dict:
    result = {
        "runtime": document["runtime"],
        "session_id": document["session_id"],
        "coordinator_thread_id": document["coordinator_thread_id"],
        "coordinator_host_id": document["coordinator_host_id"],
        "status": "stopped",
        "writer_active": False,
        "coordinator_active": False,
        "session_resumable": True,
        "request_seen": False,
        "ready_seen": True,
        "stop_evidence": True,
    }
    result.update(updates)
    return result


def gate(document: dict, **updates) -> dict:
    result = {
        "status": "passed",
        "work_item": document["work_item"],
        "checkpoint_sha256": document[CHECKPOINT.FINGERPRINT_FIELD],
        "source": "gate-102-simulated",
    }
    result.update(updates)
    return result


def override(document: dict, **updates) -> dict:
    result = {
        "status": "unchanged",
        "approved": True,
        "checkpoint_sha256": document[CHECKPOINT.FINGERPRINT_FIELD],
        "source": "user-confirmed",
    }
    result.update(updates)
    return result


class Registry:
    """只模拟既有 lane registry 的持久 overlay，不创建第二份 truth。"""

    def __init__(self, lane: dict):
        self.lane = copy.deepcopy(lane)
        self.persist_count = 0
        self.send_count = 0

    def persist(self, overlay: dict, *, fail: bool = False) -> None:
        if fail:
            raise OSError("simulated atomic registry write failure")
        self.lane.update(copy.deepcopy(overlay))
        self.persist_count += 1

    def readback(self) -> dict:
        return copy.deepcopy(self.lane)


def assert_action(result: dict, action: str) -> None:
    assert result["action"] == action, result


def prepare(document: dict, lane: dict, obs: dict, *, signal: str = "WORKER_STOPPED",
            **kwargs) -> dict:
    return CONTINUATION.prepare_continuation(
        document, lane, obs, signal=signal, gate_evidence=kwargs.pop("gate", gate(document)),
        user_override=kwargs.pop("override", override(document)),
    )


def ready_to_send(document: dict, lane: dict, obs: dict, *, signal: str = "WORKER_STOPPED",
                  **kwargs) -> dict:
    return CONTINUATION.ready_to_send(
        lane, document=document, observation=obs, signal=signal,
        gate_evidence=kwargs.pop("gate", gate(document)),
        user_override=kwargs.pop("override", override(document)),
    )


def post_marker_observation(document: dict, lane: dict, *, status: str = "not_seen") -> dict:
    marker = lane["continuation"]["request"]
    return observation(document,
                       request_seen=status == "seen",
                       request_probe={
                           "request_id": marker["request_id"],
                           "status": status,
                           "after_marker": True,
                           "settled": True,
                           "source": "session-readback",
                           "read_at": "2026-09-08T00:00:30Z",
                       })


def arm_lane(document: dict, lane: dict, **kwargs) -> tuple[dict, dict]:
    result = ready_to_send(document, lane, post_marker_observation(document, lane), **kwargs)
    assert_action(result, "persist-send-lease")
    assert result["request"] is not None and result["overlay"] is not None
    updated = copy.deepcopy(lane)
    updated.update(result["overlay"])
    return updated, result


def send_event(lane: dict, intent: dict, *, status: str = "sent", request_id: str = "request-1") -> tuple[dict, str]:
    previous = lane["continuation"].get("request")
    if isinstance(previous, dict):
        request_id = previous["request_id"]
    return CONTINUATION.record_event(lane, "request", {
        "request_id": request_id,
        "intent_sha256": intent[CHECKPOINT.INTENT_FINGERPRINT_FIELD],
        "target_request": intent["target_request"],
        "status": status,
        "source": "simulated-adapter",
    })


def check() -> None:
    with tempfile.TemporaryDirectory(prefix="continuation-102-") as folder:
        directory = Path(folder)
        root = directory / "execution"
        root.mkdir()
        git(root, "init", "-b", "main")
        git(root, "config", "user.name", "continuation-probe")
        git(root, "config", "user.email", "continuation@example.invalid")
        (root / "base.txt").write_text("base\n", encoding="utf-8")
        git(root, "add", "base.txt")
        git(root, "commit", "-m", "base")
        git(root, "checkout", "--detach")
        checkpoint_path = directory / "registry" / "checkpoint.json"
        checkpoint_path.parent.mkdir()
        document = document_for(root, checkpoint_path)
        CHECKPOINT.write_checkpoint(checkpoint_path, document, worktree=root)
        base_lane = lane_for(document)
        normal_observation = observation(document)

        mismatched_registry = copy.deepcopy(base_lane)
        mismatched_registry["worktree"] = "/tmp/other-execution-worktree"
        assert_action(prepare(document, mismatched_registry, normal_observation), "blocked")
        missing_phase = copy.deepcopy(base_lane)
        missing_phase.pop("execution_phase")
        assert_action(prepare(document, missing_phase, normal_observation), "blocked")
        bad_phase = copy.deepcopy(base_lane)
        bad_phase["execution_phase"] = "Unknown"
        assert_action(prepare(document, bad_phase, normal_observation), "blocked")

        ready = prepare(document, base_lane, normal_observation, signal="PREWALK_READY")
        assert_action(ready, "await-stop")
        assert prepare(document, base_lane, normal_observation, signal="PREWALK_READY")["request"] is None
        assert_action(prepare(document, base_lane, normal_observation), "persist-before-send")
        inherited = {
            "status": "unchanged",
            "authorization": "inherited-dispatch",
            "checkpoint_sha256": document[CHECKPOINT.FINGERPRINT_FIELD],
            "source": "initial-dispatch",
        }
        assert_action(prepare(document, base_lane, normal_observation, override=inherited),
                      "persist-before-send")

        first = prepare(document, base_lane, normal_observation)
        assert_action(first, "persist-before-send")
        assert first["request"] is None
        registry = Registry(base_lane)
        try:
            registry.persist(first["overlay"], fail=True)
        except OSError:
            pass
        assert ready_to_send(document, registry.readback(), normal_observation)["request"] is None
        registry.persist(first["overlay"])
        persisted = registry.readback()
        bypass_lane, status = send_event(persisted, persisted["continuation"]["intent"])
        assert status.startswith("blocked")
        request_marker = ready_to_send(document, persisted, normal_observation)
        assert_action(request_marker, "persist-request-before-send")
        assert request_marker["request"] is None
        registry.persist(request_marker["overlay"])
        dispatching = registry.readback()
        stale_observation = ready_to_send(document, dispatching, normal_observation)
        assert_action(stale_observation, "readback-after-unknown")
        unsettled_observation = post_marker_observation(document, dispatching)
        unsettled_observation["request_probe"]["settled"] = False
        assert_action(ready_to_send(document, dispatching, unsettled_observation),
                      "readback-after-unknown")
        leased, adapter_request = arm_lane(document, dispatching)
        assert adapter_request["request"] is not None
        intent = persisted["continuation"]["intent"]

        reentry = prepare(document, dispatching, normal_observation)
        assert_action(reentry, "readback-after-unknown")
        reentry = prepare(document, dispatching, post_marker_observation(document, dispatching))
        assert_action(reentry, "persist-send-lease")
        assert reentry["request"] == adapter_request["request"]
        assert_action(ready_to_send(document, leased, post_marker_observation(document, leased)),
                      "readback-after-lease")
        registry.persist({"continuation": leased["continuation"]})
        leased = registry.readback()
        acceptance_first = copy.deepcopy(leased)
        acceptance_first, status = CONTINUATION.record_event(acceptance_first, "acceptance", {
            "accepted": True, "status": "accepted", "source": "session-readback",
            "request_id": acceptance_first["continuation"]["request"]["request_id"]})
        assert status == "recorded" and acceptance_first["continuation"]["state"] == "accepted"
        acceptance_first, status = send_event(acceptance_first, intent)
        assert status == "recorded" and acceptance_first["continuation"]["state"] == "accepted"
        acceptance_first, status = CONTINUATION.record_event(acceptance_first, "new_turn", {
            "started": True, "session_id": document["session_id"], "source": "session-readback",
            "request_id": acceptance_first["continuation"]["request"]["request_id"],
            "turn_id": "turn-acceptance-first"})
        assert status == "recorded" and acceptance_first["execution_phase"] == "executing"
        registry.send_count += 1
        after_crash = ready_to_send(document, leased,
                                    post_marker_observation(document, leased, status="seen"))
        assert_action(after_crash, "readback-after-lease")
        assert after_crash["request"] is None and registry.send_count == 1
        assert "status" not in adapter_request["request"]

        sent, status = send_event(leased, intent)
        assert status == "recorded"
        sent_again, status = send_event(sent, intent)
        assert status == "deduplicated" and sent_again == sent
        sent, status = CONTINUATION.record_event(sent, "acceptance", {
            "accepted": True, "status": "accepted", "source": "simulated-adapter",
            "request_id": sent["continuation"]["request"]["request_id"]})
        assert status == "recorded"
        sent, status = CONTINUATION.record_event(sent, "new_turn", {
            "started": True, "session_id": document["session_id"], "source": "simulated-adapter",
            "request_id": sent["continuation"]["request"]["request_id"], "turn_id": "turn-1"})
        assert status == "recorded" and sent["execution_phase"] == "executing"
        sent, status = CONTINUATION.record_event(sent, "actual_model", {
            "model": "execution-model", "effort": "max", "source": "runtime-readback",
            "readback_at": "2026-09-08T00:01:00Z", "turn_id": "turn-1"})
        assert status == "recorded" and sent["continuation"]["actual_model"]["verification"] == "passed"
        terminal = {
            "terminal_id": "terminal-1", "outcome": "completed", "output_mode": "commit",
            "session_id": document["session_id"],
            "request_id": sent["continuation"]["request"]["request_id"],
            "turn_id": "turn-1",
        }
        sent, status = CONTINUATION.record_terminal(sent, terminal)
        assert status == "recorded"
        sent, status = CONTINUATION.record_terminal(sent, terminal)
        assert status == "deduplicated"
        drifted_model, status = CONTINUATION.record_event(sent, "actual_model", {
            "model": "other-model", "effort": "max", "source": "runtime-readback",
            "readback_at": "2026-09-08T00:01:30Z", "turn_id": "turn-1"})
        assert status == "recorded"
        assert drifted_model["continuation"]["actual_model"]["verification"] == "mismatch"
        drifted_model, status = CONTINUATION.record_fan_in(
            drifted_model, terminal_id="terminal-1", outcome="integrated")
        assert status == "recorded"
        sent, status = CONTINUATION.record_fan_in(sent, terminal_id="terminal-1", outcome="integrated")
        assert status == "recorded"
        sent, status = CONTINUATION.record_fan_in(sent, terminal_id="terminal-1", outcome="integrated")
        assert status == "deduplicated" and sent["state"] == "integrated"
        assert_action(ready_to_send(document, sent, normal_observation), "terminal-deduped")

        for changed in (
            {"status": "Unknown"},
            {"coordinator_active": True},
            {"coordinator_active": "Unknown"},
            {"session_resumable": False},
            {"writer_active": "Unknown"},
            {"ready_seen": False},
            {"stop_evidence": False},
        ):
            result = prepare(document, base_lane, normal_observation, **{"gate": gate(document), "override": override(document)})
            assert_action(result, "persist-before-send")
            result = prepare(document, base_lane, observation(document, **changed))
            assert result["request"] is None and result["action"] in {"blocked", "wait-for-stop"}

        assert_action(prepare(document, base_lane, normal_observation, gate=gate(document, status="Unknown")), "blocked")
        assert_action(prepare(document, base_lane, normal_observation,
                              gate=gate(document, source="")), "blocked")
        assert_action(prepare(document, base_lane, normal_observation,
                              gate=gate(document, checkpoint_sha256="old")), "blocked")
        assert_action(prepare(document, base_lane, normal_observation,
                              override=override(document, approved=False)), "blocked")
        assert_action(prepare(document, base_lane, normal_observation,
                              override=override(document, checkpoint_sha256="old")), "blocked")

        (root / "worker.py").write_text("user changed\n", encoding="utf-8")
        assert_action(prepare(document, base_lane, normal_observation), "blocked")
        assert_action(ready_to_send(document, dispatching, normal_observation), "blocked")
        (root / "worker.py").write_text("first edit\n", encoding="utf-8")

        old_prepared = copy.deepcopy(base_lane)
        old_prepared.update(first["overlay"])
        edited_checkpoint_path = directory / "registry" / "checkpoint-edited.json"
        (root / "worker.py").write_text("user edit retained\n", encoding="utf-8")
        edited_snapshot = CHECKPOINT.snapshot_worktree(root)
        edited_payload = copy.deepcopy(document)
        edited_payload["checkpoint_path"] = str(edited_checkpoint_path)
        for field in ("snapshot", "component_sha256", CHECKPOINT.FINGERPRINT_FIELD):
            edited_payload.pop(field, None)
        edited_document = CHECKPOINT.build_checkpoint(edited_payload, edited_snapshot)
        CHECKPOINT.write_checkpoint(edited_checkpoint_path, edited_document, worktree=root)
        edited_dispatching = copy.deepcopy(dispatching)
        edited_dispatching["checkpoint"] = edited_document["checkpoint_path"]
        edited_dispatching["checkpoint_sha256"] = edited_document[CHECKPOINT.FINGERPRINT_FIELD]
        edited_override = override(edited_document, status="edited", source="user-confirmed-edit")
        assert_action(prepare(edited_document, edited_dispatching, observation(edited_document),
                              override=edited_override), "blocked")
        edited_dispatching_result = prepare(
            edited_document, edited_dispatching,
            post_marker_observation(edited_document, edited_dispatching),
            override=edited_override)
        assert_action(edited_dispatching_result, "persist-before-send")
        edited_lane = copy.deepcopy(old_prepared)
        edited_lane["checkpoint"] = edited_document["checkpoint_path"]
        edited_lane["checkpoint_sha256"] = edited_document[CHECKPOINT.FINGERPRINT_FIELD]
        edited_result = prepare(edited_document, edited_lane, observation(edited_document),
                                override=edited_override)
        assert_action(edited_result, "persist-before-send")
        assert edited_result["overlay"]["continuation"]["intent"] != old_prepared["continuation"]["intent"]
        (root / "worker.py").write_text("first edit\n", encoding="utf-8")

        manual = override(document, status="edited", source="user-manual-model",
                           target_request={"model": "manual-model", "effort": "high"})
        manual_result = prepare(document, base_lane, normal_observation, override=manual)
        assert_action(manual_result, "persist-before-send")
        assert manual_result["overlay"]["continuation"]["configuration_unchanged"] is True
        assert document["phase_plan"]["execution"] == {"model": "execution-model", "effort": "max"}
        manual_lane = copy.deepcopy(base_lane)
        manual_lane.update(manual_result["overlay"])
        manual_intent = manual_lane["continuation"]["intent"]
        manual_marker = ready_to_send(document, manual_lane, normal_observation, override=manual)
        assert_action(manual_marker, "persist-request-before-send")
        manual_lane.update(manual_marker["overlay"])
        manual_lane, _ = arm_lane(document, manual_lane, override=manual)
        manual_lane, status = send_event(manual_lane, manual_intent)
        assert status == "recorded"
        manual_lane, status = CONTINUATION.record_event(manual_lane, "acceptance", {
            "accepted": False, "status": "rejected", "source": "simulated-adapter",
            "request_id": manual_lane["continuation"]["request"]["request_id"]})
        assert status == "recorded" and manual_lane["continuation"]["state"] == "blocked"
        manual_lane, status = CONTINUATION.record_event(manual_lane, "new_turn", {
            "started": True, "session_id": document["session_id"], "source": "simulated-adapter",
            "request_id": manual_lane["continuation"]["request"]["request_id"], "turn_id": "turn-manual"})
        assert status.startswith("blocked")
        manual_lane, status = CONTINUATION.record_terminal(manual_lane, {
            "terminal_id": "terminal-blocked", "outcome": "blocked",
            "reason": "runtime rejected continuation request"})
        assert status == "recorded" and manual_lane["state"] == "blocked"
        manual_lane, status = CONTINUATION.record_fan_in(manual_lane,
                                                         terminal_id="terminal-blocked",
                                                         outcome="integrated")
        assert status.startswith("blocked")

        unknown_lane = copy.deepcopy(persisted)
        unknown_marker = ready_to_send(document, unknown_lane, normal_observation)
        unknown_lane.update(unknown_marker["overlay"])
        unknown_lane, _ = arm_lane(document, unknown_lane)
        unknown_lane, status = send_event(unknown_lane, intent, status="Unknown", request_id="request-unknown")
        assert status == "recorded" and unknown_lane["continuation"]["state"] == "send-unknown"
        recovered_request, status = send_event(unknown_lane, intent, status="sent", request_id="request-unknown")
        assert status == "recorded" and recovered_request["continuation"]["state"] == "sent"
        assert_action(ready_to_send(document, unknown_lane, normal_observation), "readback-after-unknown")
        assert_action(prepare(document, unknown_lane, normal_observation), "readback-after-unknown")
        unknown_lane, status = CONTINUATION.record_event(unknown_lane, "acceptance", {
            "accepted": None, "status": "Unknown", "source": "session-readback",
            "request_id": unknown_lane["continuation"]["request"]["request_id"]})
        assert status == "recorded"
        independent_lane, status = CONTINUATION.record_event(copy.deepcopy(unknown_lane), "new_turn", {
            "started": True, "session_id": document["session_id"], "source": "session-readback",
            "request_id": unknown_lane["continuation"]["request"]["request_id"], "turn_id": "turn-independent"})
        assert status == "recorded" and independent_lane["execution_phase"] == "executing"

        pending_turn_lane = copy.deepcopy(persisted)
        pending_turn_marker = ready_to_send(document, pending_turn_lane, normal_observation)
        pending_turn_lane.update(pending_turn_marker["overlay"])
        pending_turn_lane, _ = arm_lane(document, pending_turn_lane)
        pending_turn_lane, _ = send_event(pending_turn_lane, intent)
        pending_turn_lane, _ = CONTINUATION.record_event(pending_turn_lane, "acceptance", {
            "accepted": True, "status": "accepted", "source": "simulated-adapter",
            "request_id": pending_turn_lane["continuation"]["request"]["request_id"]})
        pending_turn_lane, status = CONTINUATION.record_event(pending_turn_lane, "new_turn", {
            "started": "Unknown", "session_id": document["session_id"], "source": "session-readback",
            "request_id": pending_turn_lane["continuation"]["request"]["request_id"]})
        assert status == "recorded" and pending_turn_lane["continuation"]["state"] == "accepted"
        pending_turn_lane, status = CONTINUATION.record_event(pending_turn_lane, "new_turn", {
            "started": True, "session_id": document["session_id"], "source": "session-readback",
            "request_id": pending_turn_lane["continuation"]["request"]["request_id"], "turn_id": "turn-pending"})
        assert status == "recorded" and pending_turn_lane["execution_phase"] == "executing"
        unknown_lane, status = CONTINUATION.record_event(unknown_lane, "acceptance", {
            "accepted": True, "status": "accepted", "source": "session-readback",
            "request_id": unknown_lane["continuation"]["request"]["request_id"]})
        assert status == "recorded"

        unknown_model_lane = copy.deepcopy(persisted)
        unknown_model_marker = ready_to_send(document, unknown_model_lane, normal_observation)
        unknown_model_lane.update(unknown_model_marker["overlay"])
        unknown_model_lane, _ = arm_lane(document, unknown_model_lane)
        unknown_model_lane, _ = send_event(unknown_model_lane, intent)
        unknown_model_lane, _ = CONTINUATION.record_event(unknown_model_lane, "acceptance", {
            "accepted": True, "status": "accepted", "source": "simulated-adapter",
            "request_id": unknown_model_lane["continuation"]["request"]["request_id"]})
        unknown_model_lane, _ = CONTINUATION.record_event(unknown_model_lane, "new_turn", {
            "started": True, "session_id": document["session_id"], "source": "simulated-adapter",
            "request_id": unknown_model_lane["continuation"]["request"]["request_id"], "turn_id": "turn-model"})
        unknown_model_lane, status = CONTINUATION.record_event(unknown_model_lane, "actual_model", {
            "model": "Unknown", "effort": "Unknown", "source": "runtime-readback",
            "readback_at": "2026-09-08T00:02:00Z", "turn_id": "turn-model"})
        assert status == "recorded" and unknown_model_lane["continuation"]["actual_model"]["verification"] == "Unknown"
        unknown_model_lane, status = CONTINUATION.record_event(unknown_model_lane, "actual_model", {
            "model": "Unknown", "effort": "Unknown", "source": "runtime-readback",
            "readback_at": "2026-09-08T00:02:30Z", "turn_id": "turn-model"})
        assert status == "recorded" and unknown_model_lane["continuation"]["actual_model"]["verification"] == "Unknown"
        unknown_model_lane, status = CONTINUATION.record_event(unknown_model_lane, "actual_model", {
            "model": "execution-model", "effort": "Unknown", "source": "runtime-readback",
            "readback_at": "2026-09-08T00:02:45Z", "turn_id": "turn-model"})
        assert status == "recorded" and unknown_model_lane["continuation"]["actual_model"]["verification"] == "Unknown"
        unknown_model_lane, status = CONTINUATION.record_event(unknown_model_lane, "actual_model", {
            "model": "execution-model", "effort": "max", "source": "runtime-readback",
            "readback_at": "2026-09-08T00:03:00Z", "turn_id": "turn-model"})
        assert status == "recorded" and unknown_model_lane["continuation"]["actual_model"]["verification"] == "passed"
        duplicate_model, status = CONTINUATION.record_event(unknown_model_lane, "actual_model", {
            "model": "execution-model", "effort": "max", "source": "runtime-readback",
            "readback_at": "2026-09-08T00:03:00Z", "turn_id": "turn-model"})
        assert status == "deduplicated" and duplicate_model == unknown_model_lane

        late_lane = copy.deepcopy(persisted)
        late_marker = ready_to_send(document, late_lane, normal_observation)
        late_lane.update(late_marker["overlay"])
        late_lane, _ = arm_lane(document, late_lane)
        late_lane, status = CONTINUATION.record_event(late_lane, "new_turn", {
            "started": True, "session_id": document["session_id"], "source": "session-readback",
            "request_id": late_lane["continuation"]["request"]["request_id"], "turn_id": "turn-late"})
        assert status == "recorded"
        late_lane, status = CONTINUATION.record_event(late_lane, "actual_model", {
            "model": "execution-model", "effort": "max", "source": "runtime-readback",
            "readback_at": "2026-09-08T00:04:00Z", "turn_id": "turn-late"})
        assert status == "recorded"
        late_lane, status = send_event(late_lane, intent)
        assert status == "recorded" and late_lane["continuation"]["state"] == "executing"
        stale_terminal = copy.deepcopy(late_lane)
        stale_terminal, status = CONTINUATION.record_terminal(stale_terminal, {
            "terminal_id": "terminal-stale", "outcome": "completed", "output_mode": "commit",
            "session_id": "old-session",
            "request_id": "old-request",
            "turn_id": "old-turn"})
        assert status.startswith("blocked") and stale_terminal.get("terminal") is None
        late_lane, status = CONTINUATION.record_terminal(late_lane, {
            "terminal_id": "terminal-late", "outcome": "completed", "output_mode": "commit",
            "session_id": document["session_id"],
            "request_id": late_lane["continuation"]["request"]["request_id"],
            "turn_id": "turn-late"})
        assert status == "recorded"

        conflict, status = CONTINUATION.record_terminal(sent, {
            "terminal_id": "terminal-2", "outcome": "completed", "output_mode": "commit",
            "session_id": document["session_id"],
            "request_id": sent["continuation"]["request"]["request_id"],
            "turn_id": "turn-1"})
        assert status.startswith("blocked")
        assert conflict["state"] == "integrated"

        print("continuation: pass (identity, persist/readback boundary, fail-closed recovery, event and fan-in dedupe)")


if __name__ == "__main__":
    check()
