#!/usr/bin/env python3
"""Phase 1E 模拟合同检查；不是 Orca 真机验收。"""

from __future__ import annotations

import copy
import importlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
recovery = importlib.import_module("recovery")
empty_overlay = importlib.import_module("registry_overlay").empty_overlay


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()

        def native(name: str, result: dict) -> str:
            path = root / (name + ".json")
            path.write_text(json.dumps({"ok": True, "result": result,
                                        "_meta": {"runtimeId": "runtime-1"}}))
            return str(path)

        lane = {"runtime": "orca", "dispatch_runtime": "orca",
                "coordinator_runtime": "orca-terminal", "lane_id": "lane-1",
                "work_item": "issue-124", "worktree": str(root), "branch": "worker",
                "agent": "pi", "orca": empty_overlay()}
        lane["orca"].update(run_id="run-1", task_id="task-1", dispatch_id="dispatch-1",
                            terminal_handle="term-1", worktree_selector="path:" + str(root),
                            execution_host="local", attempt_index=0)
        projection = {"runId": "run-1", "taskId": "task-1", "dispatchId": "dispatch-1",
                      "host": {"id": "local"}, "liveness": {"verdict": "exited"},
                      "resource": {"state": "owned"}}
        show = {"dispatch": {"id": "dispatch-1", "runId": "run-1", "taskId": "task-1",
                             "assigneeHandle": "term-1", "failureCount": 1, "retryOfDispatchId": None,
                             "hostScope": {"hostId": "local"}},
                "worker": {"dispatchId": "dispatch-1", "state": "failed",
                           "agentTerminalHandle": "term-1", "worktreeId": "wt-1",
                           "startOptions": {"worktree": "path:" + str(root), "agent": "pi"}},
                "terminal": {"handle": "term-1", "executionHostId": "local",
                             "worktreePath": str(root), "branch": "refs/heads/worker"},
                "projection": projection}
        worker = {"dispatchId": "dispatch-1", "taskId": "task-1", "runId": "run-1",
                  "agentTerminalHandle": "term-1", "workerState": "failed",
                  "resource": {"worktreeId": "wt-1", "ownerDispatchId": "dispatch-1", "ownershipState": "owned"},
                  "projection": projection}
        fleet = {"workers": [worker], "page": {"hasMore": False}}
        request = {"operation": "retry", "lane": lane,
                   "worker_show": native("show", show), "worker_list": native("fleet", fleet),
                   "approved": True, "placement": {"task_id": "task-1", "retry_of": "dispatch-1",
                       "worktree_selector": "path:" + str(root), "execution_host": "local",
                       "worktree": str(root), "agent": "pi"}}
        original = copy.deepcopy(request)
        assert recovery.validate(request)["action"] == "retry-same-task"
        assert request == original
        stopped_show, stopped_fleet = copy.deepcopy(show), copy.deepcopy(fleet)
        stopped_show["worker"]["state"] = stopped_fleet["workers"][0]["workerState"] = "stopped"
        assert recovery.validate(dict(request, worker_show=native("stopped-show", stopped_show),
            worker_list=native("stopped-fleet", stopped_fleet)))["action"] == "retry-same-task"
        for state in ("ready", "idle", "timeout", "outcome_unknown", "unverifiable"):
            changed = copy.deepcopy(show)
            changed["worker"]["state"] = state
            check = dict(request, worker_show=native("unknown", changed))
            result = recovery.validate(check)
            assert result["status"] == "blocked" and result["mutations"] == [], result
        for verdict in ("live", "unverifiable", "Unknown", None):
            changed = copy.deepcopy(fleet)
            changed["workers"][0]["projection"]["liveness"]["verdict"] = verdict
            result = recovery.validate(dict(request, worker_list=native("bad-fleet", changed)))
            assert result["status"] == "blocked" and result["mutations"] == []
        for field, value in (("task_id", "new-task"), ("execution_host", "other"),
                             ("worktree", "/wrong"), ("agent", "codex")):
            changed = copy.deepcopy(request)
            changed["placement"][field] = value
            assert recovery.validate(changed)["status"] == "blocked"
        changed = copy.deepcopy(show)
        changed["dispatch"]["failureCount"] = 3
        assert recovery.validate(dict(request, worker_show=native("circuit", changed)))["status"] == "blocked"
        changed = copy.deepcopy(fleet)
        changed["workers"].append({**worker, "dispatchId": "other", "projection": {
            **projection, "dispatchId": "other", "liveness": {"verdict": "live"}}})
        assert recovery.validate(dict(request, worker_list=native("writer", changed)))["status"] == "blocked"
        cancel = dict(request, operation="cancel")
        assert recovery.validate(cancel)["action"] == "stop-exact-dispatch"
        assert recovery.validate(dict(cancel, approved=False))["status"] == "blocked"
        user_owned = copy.deepcopy(fleet)
        user_owned["workers"][0]["resource"]["ownershipState"] = "user_owned"
        assert recovery.validate(dict(cancel, worker_list=native("user-owned", user_owned)))["status"] == "blocked"

        mutation_lane = copy.deepcopy(lane)
        mutation_lane["orca"]["mutation"] = {"operation": "check", "request_id": "req-1",
                                               "receipt_reference": None}
        lost = {"operation": "response-lost", "lane": mutation_lane,
                "method": "orchestration.check", "runtime_id": "runtime-1"}
        for state, action in (("completed", "consume-original-receipt"),
                              ("pending", "inspect"), ("absent", "inspect")):
            result: dict = {"requestId": "req-1", "state": state, "method": "orchestration.check"}
            if state == "completed":
                result["receipt"] = {"runId": "run-1", "mutation": {"requestId": "req-1"}}
            observed: dict = dict(lost, request_show=native("request", result))
            assert recovery.validate(observed)["action"] == action
            if state == "pending":
                reference = root / "guide.md"
                reference.write_text("模拟原生 retry-request 合同")
                observed.update(original_live=False, retry_contract=str(reference))
                resumed = recovery.validate(observed)
                assert resumed["action"] == "join-original-request" and resumed["retry_request"] == "req-1"
        lost["lane"]["orca"]["mutation"]["request_id"] = None
        assert recovery.validate(lost)["action"] == "inspect"
        assert recovery.validate({"operation": "restart", "lane": lane})["status"] == "blocked"
        assert recovery.validate({"operation": "staged", "lane": lane})["status"] == "blocked"
        # 复用共享 continuation 的 Git/checkpoint fixture，不复制其状态机。
        fixture = importlib.import_module("continuation_check")
        worktree = root / "worktree"
        worktree.mkdir()
        for args in (("init",), ("config", "user.email", "probe@example.invalid"),
                     ("config", "user.name", "probe"), ("commit", "--allow-empty", "-m", "base")):
            # git hook 会导出 GIT_DIR/GIT_INDEX_FILE 等变量；fixture 是新 repo，必须剥离。
            env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
            subprocess.run(["git", "-C", str(worktree), *args], check=True,
                           capture_output=True, env=env)
        document = fixture.document_for(worktree, root / "checkpoint.json")
        document["runtime"] = "orca"
        stage_lane = fixture.lane_for(document)
        stage_lane.update(dispatch_runtime="orca", coordinator_runtime="orca-terminal", agent="pi",
                          orca=copy.deepcopy(lane["orca"]))
        stage_lane["orca"]["worktree_selector"] = "path:" + str(worktree)
        binding = {field: stage_lane["orca"][field] for field in (
            "run_id", "task_id", "dispatch_id", "terminal_handle", "worktree_selector", "execution_host")}
        binding.update(lane_id=document["lane_id"], work_item=document["work_item"],
                       worktree=str(worktree), provider_session_id=document["session_id"],
                       provider_session_source=request["worker_show"])
        binding_path = root / "binding.json"
        binding_path.write_text(json.dumps(binding))
        document["evidence"].append(str(root) + "/./binding.json")
        document["checkpoint_sha256"] = recovery.CHECKPOINT.checkpoint_sha256(document)
        recovery.CHECKPOINT.write_checkpoint(root / "checkpoint.json", document, worktree=worktree)
        stage_lane["checkpoint_sha256"] = document["checkpoint_sha256"]
        stage_show = copy.deepcopy(show)
        stage_show["terminal"].update(worktreePath=str(worktree), branch=document["execution_branch"])
        stage_show["worker"]["state"] = "ready"
        stage_fleet = copy.deepcopy(fleet)
        stage_fleet["workers"][0]["workerState"] = "ready"
        provider = {"status": "verified", "same_session": True, "agent": "pi",
                    "session_id": document["session_id"], "worktree": str(worktree),
                    "transport": "simulated-same-session", "source": request["worker_show"],
                    "observation": fixture.observation(document)}
        provider_path = root / "provider.json"
        provider_path.write_text(json.dumps(provider))
        staged = {"operation": "staged", "lane": stage_lane, "binding": str(binding_path),
                  "worker_show": native("stage-show", stage_show), "worker_list": native("stage-fleet", stage_fleet),
                  "provider_readback": str(provider_path), "signal": "WORKER_STOPPED",
                  "gate_evidence": fixture.gate(document), "user_override": fixture.override(document)}
        result = recovery.validate(staged)
        assert result["action"] == "persist-before-send", result
        stage_lane.update(result["overlay"])
        result = recovery.validate(staged)
        assert result["action"] == "persist-request-before-send", result
        stage_lane.update(result["overlay"])
        provider["observation"] = fixture.post_marker_observation(document, stage_lane)
        provider_path.write_text(json.dumps(provider))
        result = recovery.validate(staged)
        assert result["action"] == "persist-send-lease", result
        stage_lane.update(result["overlay"])
        replay = recovery.validate(staged)
        assert replay["action"] == "readback-after-lease" and replay["status"] == "blocked", replay
        assert replay["mutations"] == [] and not replay["authority"]
        provider["transport"] = "orca orchestration worker-start --terminal"
        provider_path.write_text(json.dumps(provider))
        assert recovery.validate(staged)["status"] == "blocked"

        context = {"taskId": "task-1", "dispatchId": "dispatch-1", "lane_id": document["lane_id"],
                   "work_item": document["work_item"], "checkpoint_sha256": document["checkpoint_sha256"]}
        message = {"id": "msg-1", "run_id": "run-1", "from_handle": "dispatch:dispatch-1", "type": "question",
                   "body": json.dumps({**context, "question": "批准接续？"})}
        question = {"operation": "question", "lane": stage_lane, "binding": str(binding_path),
                    "worker_show": staged["worker_show"], "worker_list": staged["worker_list"],
                    "delivery": native("delivery", {"runId": "run-1", "messages": [message]}),
                    "message_id": "msg-1"}
        assert recovery.validate(question)["action"] == "awaiting-human"
        # 同一个原生 ask 还必须能通过完整 FIFO 的 shared message parser。
        recovery.WORKER._message({"message_id": "msg-1", "run_id": "run-1",
            "from_handle": "dispatch:dispatch-1", "subject": "Question", "body": message["body"],
            "type": "question", "payload": None}, 0, "run-1", {"term-1": lane["orca"]})
        reply = {"messageId": "msg-1", "answer": "批准", "timedOut": False,
                 "cancelled": False, "connectionLost": False}
        assert recovery.validate(dict(question, reply=native("reply", reply)))["action"] == "reply-recorded"
        assert recovery.validate(dict(question, reply=native("timeout", {**reply, "timedOut": True})))["status"] == "blocked"
        escalation = {**message, "type": "escalation", "payload": json.dumps(context)}
        assert recovery.validate(dict(question, delivery=native("escalation", {
            "runId": "run-1", "messages": [escalation]})))["action"] == "awaiting-human"
        message["body"] = json.dumps({**context, "dispatchId": "stale-dispatch"})
        question["delivery"] = native("stale-delivery", {"runId": "run-1", "messages": [message]})
        assert recovery.validate(question)["status"] == "blocked"
        # checkpoint 过期与误用 Task ID 都不能触发 transport。
        (worktree / "worker.py").write_text("changed after checkpoint")
        assert recovery.validate(staged)["status"] == "blocked"
        parent = {"runtime": "orchestrator", "dispatch_runtime": "orca", "coordinator_runtime": "orca-terminal",
                  "orca": empty_overlay()}
        parent["orca"].update(run_id="run-1", coordinator_terminal_handle="coord-1", coordinator_host_id="local")
        restarted = dict(request, operation="restart", map=parent, coordinator_writer_active=False,
            run_show=native("run", {"run": {"id": "run-1", "coordinator_handle": "coord-1"}}),
            task_list=native("tasks", {"runId": "run-1", "tasks": [{"id": "task-1", "run_id": "run-1"}]}),
            coordinator_terminal=native("coordinator", {"terminal": {"handle": "coord-1", "executionHostId": "local"}}))
        assert recovery.validate(restarted)["action"] == "resume-existing"
        assert recovery.validate(dict(restarted, coordinator_writer_active="Unknown"))["status"] == "blocked"
        pending_lane = copy.deepcopy(lane)
        pending_lane["orca"]["mutation"] = {"operation": "worker-start", "request_id": "req-unknown",
                                            "receipt_reference": native("pending-receipt", {"state": "pending"})}
        assert recovery.validate(dict(restarted, lane=pending_lane))["status"] == "blocked"
        for operation in ("retry", "cancel", "restart"):
            unknown_fleet = copy.deepcopy(fleet)
            unknown_fleet["workers"][0]["projection"]["liveness"]["verdict"] = "unverifiable"
            check = dict(restarted, operation=operation, worker_list=native("unverifiable", unknown_fleet))
            before = copy.deepcopy(check)
            result = recovery.validate(check)
            assert result["status"] == "blocked" and result["mutations"] == [] and check == before
        sparse = copy.deepcopy(lane)
        sparse["orca"]["task_id"] = sparse["orca"]["dispatch_id"] = None
        sparse["orca"]["mutation"] = {"operation": "task-create", "request_id": "req-create", "receipt_reference": None}
        result = recovery.validate({"operation": "response-lost", "lane": sparse,
            "runtime_id": "runtime-1", "method": "orchestration.taskCreate",
            "request_show": native("created", {"requestId": "req-create", "state": "completed",
                "method": "orchestration.taskCreate", "receipt": {"runId": "run-1", "taskId": "task-new",
                    "mutation": {"requestId": "req-create"}}})})
        assert result["action"] == "consume-original-receipt", result
        for malformed in (None, [], {}, {"operation": "release"}, {"operation": "retry", "lane": None}):
            result = recovery.validate(malformed)
            assert result["status"] == "blocked" and result["mutations"] == []
    print("Orca recovery check: PASS (simulated; native acceptance not-run/Unknown)")


if __name__ == "__main__":
    main()
