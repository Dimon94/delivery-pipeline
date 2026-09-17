#!/usr/bin/env python3
"""Phase 2A browser/automation 模拟合同检查；不是 Orca 真机验收。"""

from __future__ import annotations

import copy
import importlib
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
browser_gate = importlib.import_module("browser_gate")
empty_overlay = importlib.import_module("registry_overlay").empty_overlay


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()

        def native(
            name: str, result: dict, *, runtime: str = "runtime-1", ok: bool = True
        ) -> str:
            path = root / (name + ".json")
            document = {"ok": ok, "_meta": {"runtimeId": runtime}}
            if ok:
                document["result"] = result
            else:
                document["error"] = result
            path.write_text(json.dumps(document))
            return str(path)

        def schema(name: str, commands: list[str]) -> str:
            path = root / (name + ".json")
            path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "commandCount": len(commands),
                        "commands": [{"command": command} for command in commands],
                    }
                )
            )
            return str(path)

        commands = [
            "snapshot",
            "screenshot",
            "get",
            "tab create",
            "tab show",
            "tab list",
            "tab close",
            "goto",
            "click",
            "fill",
            "eval",
            "automations list",
            "automations runs",
            "automations show",
            "automations create",
            "automations run",
            "automations edit",
        ]
        capability_schema = schema("agent-context", commands)
        host_readback = native("status", {"result": True})

        def require_capability(entry: dict, required: str) -> dict:
            path = root / ("status-" + required.replace(".", "-") + ".json")
            path.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "result": {"runtime": {"capabilities": [required]}},
                        "_meta": {"runtimeId": "runtime-1"},
                    }
                )
            )
            return {**entry, "host_readback": str(path), "require": required}

        lane = {
            "runtime": "orca",
            "dispatch_runtime": "orca",
            "coordinator_runtime": "orca-terminal",
            "lane_id": "lane-1",
            "work_item": "issue-125",
            "worktree": str(root),
            "branch": "worker",
            "agent": "pi",
            "orca": empty_overlay(),
        }
        lane["orca"].update(
            run_id="run-1",
            task_id="task-1",
            dispatch_id="dispatch-1",
            terminal_handle="term-1",
            worktree_selector="path:" + str(root),
            execution_host="local",
            attempt_index=0,
        )
        binding = {
            "lane_id": "lane-1",
            "work_item": "issue-125",
            "run_id": "run-1",
            "task_id": "task-1",
            "dispatch_id": "dispatch-1",
            "terminal_handle": "term-1",
            "execution_host": "local",
        }
        capability = {
            "command": "screenshot",
            "schema": capability_schema,
            "host_readback": host_readback,
            "runtime_id": "runtime-1",
            "reference": "orca-cli",
        }
        authorization = {
            "approved": True,
            "scope": "isolated /tmp test page",
            "evidence": native("packet", {"subject": "packet"}),
        }
        artifact = root / "shot.png"
        artifact.write_bytes(b"png")

        def request(operation: str, **extra) -> dict:
            return {
                "operation": operation,
                "lane": lane,
                "binding": binding,
                "capability": capability,
                **extra,
            }

        # browser-read：只读闭集，不需要授权；screenshot 必须声明 artifact。
        result = browser_gate.validate(
            request(
                "browser-read", artifact={"path": str(artifact), "kind": "screenshot"}
            )
        )
        assert result["status"] == "ready" and result["action"] == "execute-readonly", (
            result
        )
        assert result["authority"] is False and result["mutations"] == []
        assert result["project_lane_transition"] == "unchanged", result
        missing_artifact = browser_gate.validate(request("browser-read"))
        assert missing_artifact["status"] == "blocked", missing_artifact
        assert "声明 artifact" in missing_artifact["reason"], missing_artifact
        shot_capability = require_capability(capability, "browser.screencast.v1")
        result = browser_gate.validate(
            request(
                "browser-read",
                capability=shot_capability,
                artifact={"path": str(artifact), "kind": "screenshot"},
            )
        )
        assert result["status"] == "ready", result
        read_no_artifact = copy.deepcopy(capability)
        read_no_artifact["command"] = "snapshot"
        result = browser_gate.validate(
            request("browser-read", capability=read_no_artifact)
        )
        assert result["status"] == "ready", result

        # capability：闭集外命令、schema 缺命令、runtime 不一致均 blocked。
        for probe in (
            request("browser-read", capability={**capability, "command": "mouse down"}),
            request(
                "browser-read",
                capability={**capability, "schema": schema("shrink", ["snapshot"])},
            ),
            request(
                "browser-read", capability={**capability, "runtime_id": "runtime-2"}
            ),
            request(
                "browser-read",
                capability={
                    **capability,
                    "host_readback": native("other", {}, runtime="runtime-9"),
                },
            ),
        ):
            result = browser_gate.validate(probe)
            assert result["status"] == "blocked" and result["authority"] is False, (
                result
            )

        # browser-write：无授权/假授权 blocked；有授权 + 幂等合同 ready。
        write_capability = {**capability, "command": "click"}
        write = request(
            "browser-write",
            capability=write_capability,
            target={"url": "http://127.0.0.1:18125/"},
            idempotency={
                "key": "click-go",
                "retry_rule": "readback-first",
                "prior_readback": None,
            },
        )
        missing_auth = browser_gate.validate(write)
        assert missing_auth["status"] == "blocked", missing_auth
        for bad_auth in (
            {"approved": False, "scope": "x", "evidence": authorization["evidence"]},
            {"approved": True, "scope": "", "evidence": authorization["evidence"]},
            {"approved": True, "scope": "x", "evidence": "/nonexistent.pdf"},
        ):
            result = browser_gate.validate({**write, "authorization": bad_auth})
            assert result["status"] == "blocked", result
        result = browser_gate.validate({**write, "authorization": authorization})
        assert (
            result["status"] == "ready"
            and result["action"] == "execute-authorized-write"
        ), result
        # 幂等：retry 必须先读回；坏 readback / 非 readback-first 均 blocked。
        retry = {
            **write,
            "authorization": authorization,
            "idempotency": {
                "key": "click-go",
                "retry_rule": "readback-first",
                "prior_readback": native("tab-show", {"tab": {"url": "u"}}),
            },
        }
        result = browser_gate.validate(retry)
        assert result["status"] == "ready", result
        bad_retry = copy.deepcopy(retry)
        bad_retry["idempotency"]["prior_readback"] = native(
            "lost", {"code": "x"}, ok=False
        )
        assert browser_gate.validate(bad_retry)["status"] == "blocked"
        bad_rule = copy.deepcopy(retry)
        bad_rule["idempotency"]["retry_rule"] = "blind-retry"
        assert browser_gate.validate(bad_rule)["status"] == "blocked"

        # browser-navigate：tab create/goto 必须声明 target.url；闭集外写命令 blocked。
        navigate = request(
            "browser-navigate",
            capability={**capability, "command": "tab create"},
            target={"url": "http://127.0.0.1:18125/"},
            idempotency={
                "key": "open-page",
                "retry_rule": "readback-first",
                "prior_readback": None,
            },
        )
        result = browser_gate.validate(navigate)
        assert result["status"] == "ready" and result["action"] == "execute-navigate", (
            result
        )
        no_url = copy.deepcopy(navigate)
        del no_url["target"]
        assert browser_gate.validate(no_url)["status"] == "blocked"
        write_in_nav = {**navigate, "capability": {**capability, "command": "fill"}}
        assert browser_gate.validate(write_in_nav)["status"] == "blocked"

        # automation-create：授权 + 有界 schedule + 去重读回。
        create = request(
            "automation-create",
            authorization=authorization,
            capability={**capability, "command": "automations create"},
            automation={"name": "issue-125-probe", "schedule": {"kind": "one-shot"}},
            dedupe={
                "list_readback": native("auto-list", {"automations": [], "items": []})
            },
        )
        result = browser_gate.validate(create)
        assert (
            result["status"] == "ready"
            and result["action"] == "create-bounded-automation"
        ), result
        unbounded = copy.deepcopy(create)
        unbounded["automation"]["schedule"] = {"kind": "interval", "every": "5m"}
        assert browser_gate.validate(unbounded)["status"] == "blocked"
        bounded_interval = copy.deepcopy(create)
        bounded_interval["automation"]["schedule"] = {
            "kind": "interval",
            "every": "5m",
            "max_runs": 2,
        }
        assert browser_gate.validate(bounded_interval)["status"] == "ready"
        duplicate = copy.deepcopy(create)
        duplicate["dedupe"]["list_readback"] = native(
            "auto-list-dupe",
            {
                "automations": [
                    {"id": "auto-1", "name": "issue-125-probe", "enabled": True}
                ],
                "items": [],
            },
        )
        assert browser_gate.validate(duplicate)["status"] == "blocked"
        resume = copy.deepcopy(duplicate)
        resume["resume"] = True
        result = browser_gate.validate(resume)
        assert (
            result["status"] == "ready"
            and result["action"] == "consume-existing-automation"
        ), result
        no_auth = copy.deepcopy(create)
        del no_auth["authorization"]
        assert browser_gate.validate(no_auth)["status"] == "blocked"

        # automation-run：在途 job 去重；resume 消费原 job。
        run = request(
            "automation-run",
            authorization=authorization,
            capability={**capability, "command": "automations run"},
            automation_id="auto-1",
            dedupe={"runs_readback": native("runs", {"runs": []})},
        )
        result = browser_gate.validate(run)
        assert (
            result["status"] == "ready" and result["action"] == "trigger-automation"
        ), result
        inflight = copy.deepcopy(run)
        inflight["dedupe"]["runs_readback"] = native(
            "runs-busy",
            {"runs": [{"id": "job-1", "automationId": "auto-1", "status": "running"}]},
        )
        assert browser_gate.validate(inflight)["status"] == "blocked"
        # Orca 原生在途状态(dispatching/dispatched)同样必须 fail-closed。
        for native_status in ("dispatching", "dispatched"):
            native_inflight = copy.deepcopy(run)
            native_inflight["dedupe"]["runs_readback"] = native(
                f"runs-{native_status}",
                {
                    "runs": [
                        {
                            "id": "job-1",
                            "automationId": "auto-1",
                            "status": native_status,
                        }
                    ]
                },
            )
            assert browser_gate.validate(native_inflight)["status"] == "blocked", (
                native_status
            )
        resume_run = copy.deepcopy(inflight)
        resume_run["resume"] = True
        result = browser_gate.validate(resume_run)
        assert (
            result["status"] == "ready" and result["action"] == "consume-existing-job"
        ), result

        # automation-pause：必须读回当前 active 状态。
        pause = request(
            "automation-pause",
            authorization=authorization,
            capability={**capability, "command": "automations edit"},
            automation_id="auto-1",
            state_readback=native(
                "auto-show", {"automation": {"id": "auto-1", "enabled": True}}
            ),
        )
        result = browser_gate.validate(pause)
        assert result["status"] == "ready" and result["action"] == "pause-automation", (
            result
        )
        paused = copy.deepcopy(pause)
        paused["state_readback"] = native(
            "auto-paused", {"automation": {"id": "auto-1", "enabled": False}}
        )
        assert browser_gate.validate(paused)["status"] == "blocked"

        # verify-result：成功证据绑定；Unknown/timeout/host-loss/坏 receipt 全 fail-closed。
        evidence = {
            "input_receipt": native("click-receipt", {"clicked": "e3"}),
            "result_readback": native("eval-readback", {"result": "clicked:x"}),
            "artifacts": [str(artifact)],
            "captured_at": "2026-09-16T13:50:00Z",
            "outcome": "success",
        }
        verify = request(
            "verify-result",
            capability={**capability, "command": "click"},
            evidence=evidence,
        )
        result = browser_gate.validate(verify)
        assert result["status"] == "ready" and result["action"] == "evidence-bound", (
            result
        )
        verify_req = copy.deepcopy(verify)
        verify_req["capability"] = require_capability(
            verify["capability"], "browser.clientHost.automation.v1"
        )
        assert browser_gate.validate(verify_req)["status"] == "ready"
        for outcome in ("failed", "unknown", "timeout", "host-loss"):
            probe = copy.deepcopy(verify)
            probe["evidence"]["outcome"] = outcome
            result = browser_gate.validate(probe)
            assert result["status"] == "blocked" and result["authority"] is False, (
                outcome,
                result,
            )
        bad_receipt = copy.deepcopy(verify)
        bad_receipt["evidence"]["input_receipt"] = native(
            "err", {"code": "browser_error"}, ok=False
        )
        assert browser_gate.validate(bad_receipt)["status"] == "blocked"
        wrong_runtime = copy.deepcopy(verify)
        wrong_runtime["evidence"]["result_readback"] = native(
            "foreign", {"result": "x"}, runtime="runtime-9"
        )
        assert browser_gate.validate(wrong_runtime)["status"] == "blocked"
        missing_artifact_file = copy.deepcopy(verify)
        missing_artifact_file["evidence"]["artifacts"] = ["/nonexistent/shot.png"]
        assert browser_gate.validate(missing_artifact_file)["status"] == "blocked"

        # 结构畸形与输入不可变。
        for malformed in (
            None,
            [],
            {},
            {"operation": "release"},
            {"operation": "browser-read", "lane": None},
        ):
            result = browser_gate.validate(malformed)
            assert result["status"] == "blocked" and result["mutations"] == []
        frozen = copy.deepcopy(verify)
        browser_gate.validate(verify)
        assert verify == frozen, "validate 不得改写 caller 请求"

    print(
        "Orca browser gate check: PASS (simulated; native acceptance not-run/Unknown)"
    )


if __name__ == "__main__":
    main()
