#!/usr/bin/env python3
"""Orca recovery 薄层：只核验 readback，不执行 mutation，不另建状态库。

所有 ready 都只是 caller-declared 结构证据；coordinator 核验 native provenance 后
仍须沿原生合同执行。Unknown 不授权 stop/abandon/retry/release。
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Any

import registry_overlay as REGISTRY
import worker_lifecycle as WORKER

CORE = Path(__file__).resolve().parents[2] / "delivery-pipeline" / "scripts"
sys.path.insert(0, str(CORE))
CHECKPOINT = importlib.import_module("checkpoint")
CONTINUATION = importlib.import_module("continuation")

Error = WORKER.WorkerLifecycleError
text = WORKER._known_text
at = WORKER._at
boolean = WORKER._known_bool


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise Error(reason)


def native(path: Any) -> tuple[dict[str, Any], str]:
    """只读原生 envelope；错误 receipt 不能当成功 readback。"""
    _, document = WORKER._read_json_object(path, "native source")
    require(boolean(document.get("ok"), "native ok"), "native readback 未成功")
    result = at(document, ("result",), "native source")
    require(isinstance(result, dict), "native result 必须为 object")
    runtime = text(at(document, ("_meta", "runtimeId"), "native source"), "runtimeId")
    return result, runtime


def lane_row(request: dict[str, Any]) -> dict[str, Any]:
    lane = REGISTRY.validate_markers(request["lane"], kind="lane")
    for field in ("lane_id", "work_item", "worktree", "branch", "agent"):
        text(lane.get(field), field)
    for field in REGISTRY.ATTEMPT_FIELDS:
        if field == "attempt_index":
            require(type(lane["orca"][field]) is int and lane["orca"][field] >= 0,
                    "attempt_index Unknown")
        else:
            text(lane["orca"][field], field)
    for field in ("run_id", "task_id"):
        text(lane["orca"][field], field)
    return lane


def attempt(request: dict[str, Any], lane: dict[str, Any]) -> tuple[dict, dict, str]:
    """绑定当前 Run/Task/Dispatch/terminal/host/worktree，fleet 优先于 PTY。"""
    show, runtime = native(request["worker_show"])
    fleet, fleet_runtime = native(request["worker_list"])
    require(runtime == fleet_runtime, "worker-show/worker-list runtime 不一致")
    identity = lane["orca"]
    WORKER._previous_attempt(request.get("previous_attempt"), identity,
                             at(show, ("dispatch", "retryOfDispatchId"), "worker-show"))
    WORKER._native_identity(show, {
        "run_id": ("dispatch", "runId"), "task_id": ("dispatch", "taskId"),
        "dispatch_id": ("dispatch", "id"), "terminal_handle": ("dispatch", "assigneeHandle"),
        "execution_host": ("dispatch", "hostScope", "hostId"),
    }, identity, "worker-show")
    WORKER._native_identity(show, {
        "dispatch_id": ("worker", "dispatchId"),
        "terminal_handle": ("worker", "agentTerminalHandle"),
    }, identity, "worker-show")
    worktree_id = text(at(show, ("worker", "worktreeId"), "worker-show"), "worktreeId")
    terminal = at(show, ("terminal",), "worker-show")
    require(isinstance(terminal, dict), "terminal identity Unknown，保留现场")
    for field, expected in (("handle", identity["terminal_handle"]),
                            ("executionHostId", identity["execution_host"]),
                            ("worktreePath", lane["worktree"])):
        require(terminal.get(field) == expected, f"terminal {field} 不一致")
    require(identity["worktree_selector"] in (worktree_id, "id:" + worktree_id, "path:" + lane["worktree"]),
            "恢复必须使用具体 Execution Worktree selector，不能再次 new-child/current")
    require(terminal.get("branch") in (lane["branch"], "refs/heads/" + lane["branch"]),
            "Execution branch 不一致")
    require(at(show, ("worker", "startOptions", "agent"), "worker-show") == lane["agent"],
            "agent 与冻结配置不一致")
    require(not boolean(at(fleet, ("page", "hasMore"), "worker-list"), "page.hasMore"),
            "fleet 未枚举完整，先读取剩余页")
    workers = at(fleet, ("workers",), "worker-list")
    require(isinstance(workers, list) and all(isinstance(row, dict) for row in workers),
            "worker-list workers 不完整")
    matches = [row for row in workers if row.get("dispatchId") == identity["dispatch_id"]]
    require(len(matches) == 1, "当前 Dispatch 不唯一或不可读")
    worker = matches[0]
    for field, native_field in (("run_id", "runId"), ("task_id", "taskId"),
                                ("terminal_handle", "agentTerminalHandle")):
        require(worker.get(native_field) == identity[field], f"fleet {field} 不一致")
    for row in workers:
        require(row.get("runId") == identity["run_id"], "fleet 包含其他 Run")
        resource = at(row, ("resource",), "fleet")
        require(isinstance(resource, dict), "fleet resource Unknown")
        other_worktree = text(resource.get("worktreeId"), "fleet worktreeId")
        if row is not worker and other_worktree == worktree_id:
            require(at(row, ("projection", "liveness", "verdict"), "fleet") == "exited",
                    "Execution Worktree 存在 active/Unknown writer")
    require(at(worker, ("resource", "worktreeId"), "fleet") == worktree_id,
            "fleet Execution Worktree 不一致")
    require(at(worker, ("resource", "ownerDispatchId"), "fleet") == identity["dispatch_id"],
            "terminal ownership 已转移，禁止旧 Dispatch 操作")
    for source in (worker, show):
        projection = at(source, ("projection",), "native projection")
        for field, key in (("run_id", "runId"), ("task_id", "taskId"), ("dispatch_id", "dispatchId")):
            require(at(projection, (key,), "projection") == identity[field], "projection identity 不一致")
        require(at(projection, ("host", "id"), "projection") == identity["execution_host"],
                "projection host 不一致")
        require(at(projection, ("liveness", "verdict"), "projection") in {"live", "exited"},
                "unverifiable/host contact loss：只允许 inspect")
    return show, worker, runtime


def no_writer(show: dict, worker: dict) -> None:
    require(at(worker, ("projection", "liveness", "verdict"), "fleet") == "exited",
            "未正面排除旧 writer")
    require(at(show, ("projection", "liveness", "verdict"), "worker-show") == "exited",
            "worker-show 未正面排除旧 writer")


def settled_mutation(lane: dict) -> None:
    mutation = lane["orca"]["mutation"]
    if mutation is not None:
        require(mutation["request_id"] is not None and mutation["receipt_reference"] is not None,
                "mutation outcome Unknown：先 request-show，不覆盖 intent")
        receipt, _ = native(mutation["receipt_reference"])
        if "state" in receipt:
            require(receipt.get("state") == "completed", "request outcome 尚未 completed")
            receipt = at(receipt, ("receipt",), "request-show")
        require(at(receipt, ("mutation", "requestId"), "mutation receipt") == mutation["request_id"],
                "mutation receipt request ID 不一致")


def retry(request: dict[str, Any]) -> dict[str, Any]:
    lane = lane_row(request)
    show, worker, _ = attempt(request, lane)
    no_writer(show, worker)
    require(boolean(request.get("approved"), "approved"), "retry 需要明确决策")
    settled_mutation(lane)
    state = at(show, ("worker", "state"), "worker-show")
    require(state in {"failed", "stopped"} and worker.get("workerState") == state,
            "仅正面 failed/stopped 允许 retry")
    failures = at(show, ("dispatch", "failureCount"), "worker-show")
    require(type(failures) is int and 0 <= failures < 3,
            "Orca 原生三次连续失败 circuit-break 或计数 Unknown；禁止换 Run/Task 绕过")
    identity = lane["orca"]
    expected = {"task_id": identity["task_id"], "retry_of": identity["dispatch_id"],
                "worktree_selector": identity["worktree_selector"], "worktree": lane["worktree"],
                "execution_host": identity["execution_host"], "agent": lane["agent"]}
    require(request.get("placement") == expected, "retry 必须显式重复 Task/placement/agent/Execution Worktree/host")
    return {"action": "retry-same-task", "placement": expected, "run_id": identity["run_id"]}


def response_lost(request: dict[str, Any]) -> dict[str, Any]:
    # response lost 可能发生在 Task/Dispatch 首次 ID 返回前，不能要求完整 attempt。
    lane = REGISTRY.validate_markers(request["lane"], kind="lane")
    mutation = lane["orca"]["mutation"]
    if not isinstance(mutation, dict) or mutation.get("request_id") is None:
        return {"status": "blocked", "action": "inspect", "reason": "request ID 丢失；枚举已有 Run/Task/Dispatch，禁止盲重发"}
    result, runtime = native(request["request_show"])
    require(runtime == text(request.get("runtime_id"), "runtime_id"), "request-show runtime 不一致")
    require(result.get("requestId") == mutation["request_id"], "request-show request ID 不一致")
    state = result.get("state")
    if state == "absent":
        return {"status": "blocked", "action": "inspect", "reason": "absent 不证明未执行"}
    method = text(request.get("method"), "method")
    require(result.get("method") == method, "request-show method 不一致")
    require(method.removeprefix("orchestration.").replace("-", "").replace(".", "").lower()
            == mutation["operation"].removeprefix("orchestration.").replace("-", "").replace(".", "").lower(),
            "request method 与已持久 mutation operation 不一致")
    if state == "completed":
        receipt = at(result, ("receipt",), "request-show")
        require(isinstance(receipt, dict), "completed 缺原 receipt")
        require(at(receipt, ("mutation", "requestId"), "receipt") == mutation["request_id"],
                "receipt request ID 不一致")
        require(receipt.get("runId") == lane["orca"]["run_id"], "receipt Run 不一致")
        for field, key in (("task_id", "taskId"), ("dispatch_id", "dispatchId")):
            if key in receipt and lane["orca"][field] is not None:
                require(receipt[key] == lane["orca"][field], f"receipt {field} 不一致")
        return {"action": "consume-original-receipt", "receipt": receipt,
                "reference": request["request_show"]}
    if state == "pending":
        if not request.get("retry_contract") or boolean(request.get("original_live"), "original_live"):
            return {"status": "blocked", "action": "inspect", "reason": "pending：等待原命令或核验版本匹配 retry-request 合同"}
        WORKER._readable_absolute(request["retry_contract"], "retry contract")
        return {"action": "join-original-request", "retry_request": mutation["request_id"],
                "reason": "只按原合同恢复完全相同命令；不创建新 request"}
    raise Error("request outcome Unknown；保留 intent")


def restart(request: dict[str, Any]) -> dict[str, Any]:
    lane = lane_row(request)
    show, worker, runtime = attempt(request, lane)
    no_writer(show, worker)
    settled_mutation(lane)
    parent = REGISTRY.validate_markers(request["map"], kind="map")
    run, run_runtime = native(request["run_show"])
    tasks, task_runtime = native(request["task_list"])
    terminal, terminal_runtime = native(request["coordinator_terminal"])
    require(runtime == run_runtime == task_runtime == terminal_runtime, "重启 readback runtime 不一致")
    require(tasks.get("runId") == lane["orca"]["run_id"], "task-list Run 不一致")
    rows = at(tasks, ("tasks",), "task-list")
    require(isinstance(rows, list) and all(isinstance(row, dict) for row in rows), "Task readback 不完整")
    matches = [row for row in rows if row.get("id") == lane["orca"]["task_id"]]
    require(len(matches) == 1 and matches[0].get("run_id") == lane["orca"]["run_id"],
            "Task 身份缺失/冲突，不重新 task-create")
    coordinator = at(terminal, ("terminal",), "coordinator terminal")
    require(not boolean(request.get("coordinator_writer_active"), "coordinator_writer_active"),
            "旧 coordinator writer 未排除")
    observed_run = at(run, ("run", "id"), "run-show")
    observed_terminal = at(run, ("run", "coordinator_handle"), "run-show")
    require(at(coordinator, ("handle",), "terminal") == observed_terminal, "Run coordinator terminal 不一致")
    host = at(coordinator, ("executionHostId",), "terminal")
    recovered = REGISTRY.recover_map(parent, observed_run_id=observed_run,
        observed_coordinator_host_id=host, observed_coordinator_terminal_handle=observed_terminal,
        writer_active=False)
    require(recovered["status"] == "ready", recovered.get("reason", "Run origin 冲突；先完成原生 run-use takeover readback"))
    recovered = REGISTRY.recover_lane(lane, map_row=parent, observed_run_id=observed_run,
        observed_task_id=show["dispatch"]["taskId"], writer_active=False)
    require(recovered["status"] == "ready", recovered.get("reason", "Task identity 不一致"))
    coordinates = {field: lane["orca"][field] for field in REGISTRY.ATTEMPT_FIELDS}
    recovered = REGISTRY.recover_attempt(lane, observed_coordinates=coordinates, writer_active=False)
    require(recovered["status"] == "ready", recovered.get("reason", "attempt identity 不一致"))
    return {"action": "resume-existing", "run_id": observed_run, "task_id": lane["orca"]["task_id"],
            "dispatch_id": lane["orca"]["dispatch_id"], "create_run": False,
            "create_task": False, "create_dispatch": False}


def cancel(request: dict[str, Any]) -> dict[str, Any]:
    lane = lane_row(request)
    show, worker, _ = attempt(request, lane)
    require(at(worker, ("resource", "ownershipState"), "fleet") == "owned"
            and at(show, ("projection", "resource", "state"), "worker-show") == "owned",
            "user-owned/retained/released terminal 不授权 stop")
    require(boolean(request.get("approved"), "approved"), "仅显式取消允许请求 worker-stop")
    settled_mutation(lane)
    return {"action": "stop-exact-dispatch", "dispatch_id": lane["orca"]["dispatch_id"],
            "preserve_worktree": True, "reason": "stop 后重新读回；abandon 不证明停止，cleanup 另走项目 gate"}


def checkpoint_binding(request: dict[str, Any], lane: dict[str, Any]) -> dict[str, Any]:
    document = CHECKPOINT.read_checkpoint(lane["checkpoint"], worktree=lane["worktree"],
                                          expected_lane=lane["lane_id"])
    require(document["runtime"] == "orca" and document["work_item"] == lane["work_item"],
            "checkpoint runtime/work item 不一致")
    for field in ("coordinator_thread_id", "coordinator_host_id", "checkpoint_sha256"):
        require(document[field] == lane.get(field), f"checkpoint {field} 与 lane 不一致")
    binding_path = WORKER._readable_absolute(request["binding"], "checkpoint evidence")
    require(any(Path(item).is_absolute() and Path(item).resolve() == Path(binding_path)
                for item in document["evidence"]),
            "Orca binding 必须在既有 checkpoint.evidence 内")
    _, binding = WORKER._read_json_object(binding_path, "Orca binding")
    for field in ("run_id", "task_id", "dispatch_id", "terminal_handle", "execution_host", "worktree_selector"):
        require(binding.get(field) == lane["orca"][field], f"checkpoint evidence {field} 不一致")
    for field, expected in (("lane_id", lane["lane_id"]), ("work_item", lane["work_item"]),
                            ("worktree", lane["worktree"]), ("provider_session_id", document["session_id"])):
        require(binding.get(field) == expected, f"checkpoint evidence {field} 不一致")
    require(document["session_id"] not in {lane["orca"][field] for field in ("run_id", "task_id", "dispatch_id", "terminal_handle")},
            "Task/Dispatch/terminal 不能冒充 provider session")
    WORKER._readable_absolute(binding.get("provider_session_source"), "provider session proof")
    return document


def question(request: dict[str, Any]) -> dict[str, Any]:
    lane = lane_row(request)
    _, _, runtime = attempt(request, lane)
    document = checkpoint_binding(request, lane)
    delivery, delivery_runtime = native(request["delivery"])
    require(runtime == delivery_runtime, "question readback runtime 不一致")
    require(delivery.get("runId") == lane["orca"]["run_id"], "message Run 不一致")
    messages = at(delivery, ("messages",), "delivery")
    require(isinstance(messages, list) and all(isinstance(row, dict) for row in messages), "messages 不完整")
    matches = [row for row in messages if row.get("id") == request.get("message_id")]
    require(len(matches) == 1, "question/escalation message ID 不唯一")
    message = matches[0]
    require(message.get("type") in {"question", "escalation"}, "仅 question/escalation 走此入口")
    require(message.get("run_id") == lane["orca"]["run_id"]
            and message.get("from_handle") in {lane["orca"]["terminal_handle"],
                                               "dispatch:" + lane["orca"]["dispatch_id"]},
            "message sender/Run 不一致")
    # ask 不支持 --payload：问题正文携带同样的结构化 context；escalation 使用 payload。
    payload = message.get("payload") if message["type"] == "escalation" else message.get("body")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as error:
            raise Error("question/escalation context 不是 JSON") from error
    require(isinstance(payload, dict), "question/escalation 缺结构化绑定")
    for field, expected in (("taskId", lane["orca"]["task_id"]), ("dispatchId", lane["orca"]["dispatch_id"]),
                            ("lane_id", lane["lane_id"]), ("work_item", lane["work_item"]),
                            ("checkpoint_sha256", document[CHECKPOINT.FINGERPRINT_FIELD])):
        require(at(payload, (field,), "message") == expected, f"message {field} 不一致")
    reply = request.get("reply")
    if reply is not None:
        reply_result, reply_runtime = native(reply)
        require(reply_runtime == runtime, "reply readback runtime 不一致")
        require(reply_result.get("messageId") == message["id"], "ask resume 必须绑定原 message ID")
        for field in ("timedOut", "cancelled", "connectionLost"):
            require(not boolean(reply_result.get(field), field), "question 尚无明确 reply")
        text(reply_result.get("answer"), "reply answer")
        return {"action": "reply-recorded", "message_id": message["id"], "reference": reply}
    return {"action": "awaiting-human", "message_id": message["id"],
            "reason": "沿原 durable question 等 reply；timeout 不重新 ask，不自动 retry/release"}


def staged(request: dict[str, Any]) -> dict[str, Any]:
    lane = lane_row(request)
    attempt(request, lane)
    settled_mutation(lane)
    document = checkpoint_binding(request, lane)
    # 原生同 session 证据归 provider；不能用 worker-start --terminal 或模型参数回显代替。
    _, provider = WORKER._read_json_object(request["provider_readback"], "provider readback")
    require(provider.get("status") == "verified" and boolean(provider.get("same_session"), "same_session"),
            "native same-session capability Unknown")
    require(provider.get("agent") == lane["agent"] and provider.get("session_id") == document["session_id"],
            "provider session/agent 不一致")
    require(provider.get("worktree") == lane["worktree"], "provider Execution Worktree 不一致")
    transport = text(provider.get("transport"), "provider transport")
    require("worker-start" not in transport and "herdr" not in transport,
            "不以 worker-start --terminal 伪称换模，不回退 Herdr")
    WORKER._readable_absolute(provider.get("source"), "native same-session source")
    observation = provider.get("observation")
    if not isinstance(observation, dict):
        raise Error("provider observation Unknown")
    require(observation.get("session_id") == document["session_id"], "observation session 不一致")
    # 复用完整停止/Git/hash/gate/send lease 状态机，不复制其状态或另存 receipt。
    result = CONTINUATION.prepare_continuation(document, lane, observation,
        signal=request["signal"], gate_evidence=request["gate_evidence"], user_override=request["user_override"])
    result["status"] = "blocked" if result.get("overlay") is None else "ready"
    result["transport_executed"] = False
    return result


def validate(request: Any) -> dict[str, Any]:
    base = {"authority": False, "mutations": [], "project_lane_transition": "unchanged"}
    try:
        require(isinstance(request, dict), "request 必须为 object")
        handlers = {"retry": retry, "response-lost": response_lost, "restart": restart,
                    "cancel": cancel, "question": question, "staged": staged}
        operation = request.get("operation")
        require(isinstance(operation, str) and operation in handlers, "未知 recovery operation")
        return {"status": "ready", **handlers[operation](request), **base}
    except (Error, REGISTRY.OverlayError, CHECKPOINT.CheckpointError,
            CONTINUATION.ContinuationError, KeyError, TypeError, ValueError, OSError, RuntimeError) as error:
        return {"status": "blocked", "action": "inspect", "reason": str(error), **base}


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] != "check":
        print(f"Usage: {sys.argv[0]} check <absolute-request.json>", file=sys.stderr)
        return 2
    try:
        _, request = WORKER._read_json_object(sys.argv[2], "request")
        result = validate(request)
    except Error as error:
        result = {"status": "blocked", "reason": str(error), "authority": False, "mutations": []}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
