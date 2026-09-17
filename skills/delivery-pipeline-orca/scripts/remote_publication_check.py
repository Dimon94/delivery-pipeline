#!/usr/bin/env python3
"""Phase 4 remote publication 模拟合同检查；不是真实 provider 验收。"""

from __future__ import annotations

import copy
import importlib
import json
import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
gate = importlib.import_module("remote_publication")
empty_overlay = importlib.import_module("registry_overlay").empty_overlay


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()

        def write(name: str, content: str) -> str:
            path = root / name
            path.write_text(content)
            return str(path)

        def write_json(name: str, document: dict) -> str:
            return write(name, json.dumps(document))

        lane = {
            "runtime": "orca",
            "dispatch_runtime": "orca",
            "coordinator_runtime": "orca-terminal",
            "lane_id": "lane-1",
            "map": "114",
            "work_item": "128",
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
            "work_item": "128",
            "run_id": "run-1",
            "task_id": "task-1",
            "dispatch_id": "dispatch-1",
            "terminal_handle": "term-1",
            "execution_host": "local",
        }
        version_readback = write("gh-version.txt", "gh version 2.78.0\n")
        identity_readback = write_json("gh-identity.json", {"login": "Dimon94"})
        authorization = {
            "approved": True,
            "scope": "isolated test PR lifecycle",
            "evidence": write("packet.json", json.dumps({"packet": True})),
            "operation_authority": "user-confirmed push/merge scope in packet",
        }

        def capability(command: str, *, login: str = "Dimon94") -> dict:
            return {
                "provider": "github",
                "command": command,
                "reference": "gh CLI manual (2.78.0)",
                "cli_version_readback": version_readback,
                "identity_readback": identity_readback,
                "expected_identity": login,
            }

        idempotency = {
            "key": "map-114-lane-1-128-publication",
            "retry_rule": "readback-first",
            "prior_readback": None,
        }
        marker = gate.idempotency_marker(idempotency["key"])
        fan_in = {
            "integration": write_json("integration.json", {"state": "integrated"}),
            "testing": write_json("testing.json", {"verdict": "pass"}),
            "review": write_json("review.json", {"verdict": "pass"}),
            "artifacts": write_json("artifacts.json", {"paths": []}),
            "tracker": write_json("tracker.json", {"comment": True}),
            "cleanup": write_json("cleanup.json", {"state": "close_pending"}),
        }
        status_readback = write("git-status.txt", "clean\n")
        rev_parse_readback = write("rev-parse.txt", "abc123\n")

        def base_request(operation: str, command: str, **overrides) -> dict:
            request = {
                "operation": operation,
                "lane": copy.deepcopy(lane),
                "binding": copy.deepcopy(binding),
                "capability": capability(command),
                "target": {"repository": "Dimon94/delivery-pipeline"},
            }
            request.update(overrides)
            return request

        # publication-read：只读，无需授权
        read = base_request("publication-read", "git ls-remote")
        outcome = gate.validate(read)
        assert outcome["status"] == "ready" and outcome["action"] == "execute-readonly"
        assert not outcome["authority"] and outcome["mutations"] == []
        bad = base_request("publication-read", "gh pr create")
        assert gate.validate(bad)["status"] == "blocked"

        # branch-push：授权、branch 绑定与 remote readback 幂等
        def push_request(remote_head, **overrides) -> dict:
            request = base_request(
                "branch-push",
                "git push",
                authorization=copy.deepcopy(authorization),
                idempotency=copy.deepcopy(idempotency),
                local_state={
                    "branch": "worker",
                    "head": "abc123",
                    "status_readback": status_readback,
                    "rev_parse_readback": rev_parse_readback,
                },
                remote_readback=write_json(
                    "ls-remote.json", {"refs": {"worker": remote_head}}
                ),
            )
            request.update(overrides)
            return request

        outcome = gate.validate(push_request("abc123"))
        assert outcome["action"] == "deduplicated", outcome
        outcome = gate.validate(push_request(None))
        assert outcome["action"] == "push-new-branch", outcome
        outcome = gate.validate(
            push_request(
                "old456",
                ancestry_readback=write_json(
                    "ancestry.json", {"ancestor": "old456", "descendant": "abc123"}
                ),
            )
        )
        assert outcome["action"] == "push-fast-forward", outcome
        blocked = gate.validate(push_request("old456"))
        assert blocked["status"] == "blocked" and blocked["mutations"] == []
        # 无授权不 push；capability/spec 标签不自动授予权限
        no_auth = push_request(None)
        no_auth["authorization"]["operation_authority"] = ""
        assert gate.validate(no_auth)["status"] == "blocked"
        no_auth2 = push_request(None)
        del no_auth2["authorization"]
        assert gate.validate(no_auth2)["status"] == "blocked"
        # branch 与 lane 不一致 blocked
        wrong_branch = push_request(None)
        wrong_branch["local_state"]["branch"] = "other"
        assert gate.validate(wrong_branch)["status"] == "blocked"

        # pr-create：existing readback 幂等；response lost 恢复消费既有 PR
        def create_request(prs, **overrides) -> dict:
            request = base_request(
                "pr-create",
                "gh pr create",
                authorization=copy.deepcopy(authorization),
                idempotency=copy.deepcopy(idempotency),
                branch={"head": "worker", "base": "main"},
                existing_pr_readback=write_json("pr-list.json", {"prs": prs}),
                push_readback=write_json(
                    "pushed.json", {"refs": {"worker": "abc123"}}
                ),
            )
            request.update(overrides)
            return request

        outcome = gate.validate(create_request([]))
        assert outcome["action"] == "create-pr", outcome
        duplicate = gate.validate(
            create_request([{"headRefName": "worker", "state": "OPEN", "number": 9}])
        )
        assert duplicate["status"] == "blocked", duplicate
        resume = gate.validate(
            create_request(
                [
                    {
                        "headRefName": "worker",
                        "state": "OPEN",
                        "number": 9,
                        "body": marker,
                    }
                ],
                resume=True,
            )
        )
        assert resume["action"] == "consume-existing-pr", resume
        resume_missing = gate.validate(create_request([], resume=True))
        assert resume_missing["status"] == "blocked"
        resume_no_marker = gate.validate(
            create_request(
                [{"headRefName": "worker", "state": "OPEN", "number": 9}],
                resume=True,
            )
        )
        assert resume_no_marker["status"] == "blocked"
        # 未 push 不建 PR
        unpushed = create_request([])
        unpushed["push_readback"] = write_json("not-pushed.json", {"refs": {}})
        assert gate.validate(unpushed)["status"] == "blocked"

        # pr-update：OPEN + marker 幂等
        def update_request(pr_body: dict, **overrides) -> dict:
            request = base_request(
                "pr-update",
                "gh pr edit",
                authorization=copy.deepcopy(authorization),
                idempotency=copy.deepcopy(idempotency),
                branch={"head": "worker", "base": "main"},
                pr_readback=write_json("pr-view.json", pr_body),
            )
            request["target"]["pull_request"] = 9
            request.update(overrides)
            return request

        outcome = gate.validate(update_request({"state": "OPEN"}))
        assert outcome["action"] == "update-pr", outcome
        dedup = gate.validate(
            update_request({"state": "OPEN", "body": marker}, resume=True)
        )
        assert dedup["action"] == "deduplicated", dedup
        repeat = gate.validate(update_request({"state": "OPEN", "body": marker}))
        assert repeat["status"] == "blocked"
        closed = gate.validate(update_request({"state": "CLOSED"}))
        assert closed["status"] == "blocked"

        # pr-merge：fan-in + CI/review/conflict + readback 前置；MERGED 幂等
        def merge_request(pr_body: dict, **overrides) -> dict:
            request = base_request(
                "pr-merge",
                "gh pr merge",
                authorization=copy.deepcopy(authorization),
                idempotency=copy.deepcopy(idempotency),
                branch={"head": "worker", "base": "main"},
                merge_method="squash",
                pr_readback=write_json("pr-merge-view.json", pr_body),
                pr_evidence={
                    "ci": write_json("ci.json", {"conclusion": "success"}),
                    "review": write_json("reviews.json", {"state": "APPROVED"}),
                    "conflict": write_json("conflict.json", {"mergeable": True}),
                },
                fan_in=copy.deepcopy(fan_in),
            )
            request["target"]["pull_request"] = 9
            request.update(overrides)
            return request

        outcome = gate.validate(
            merge_request({"state": "OPEN", "mergeable": True, "headRefOid": "abc123"})
        )
        assert outcome["action"] == "merge-squash", outcome
        merged = gate.validate(
            merge_request({"state": "MERGED"}, resume=True)
        )
        assert merged["action"] == "deduplicated", merged
        repeat_merge = gate.validate(merge_request({"state": "MERGED"}))
        assert repeat_merge["status"] == "blocked", repeat_merge
        conflict = gate.validate(
            merge_request({"state": "OPEN", "mergeable": False, "headRefOid": "abc123"})
        )
        assert conflict["status"] == "blocked"
        closed_merge = gate.validate(merge_request({"state": "CLOSED"}, resume=True))
        assert closed_merge["status"] == "blocked"
        resume_open = gate.validate(
            merge_request({"state": "OPEN", "mergeable": True, "headRefOid": "abc123"}, resume=True)
        )
        assert resume_open["status"] == "blocked"
        # fan-in 缺证据 blocked；不回改 Phase 1-3 证据
        no_fan_in = merge_request({"state": "OPEN", "mergeable": True, "headRefOid": "abc123"})
        del no_fan_in["fan_in"]
        outcome = gate.validate(no_fan_in)
        assert outcome["status"] == "blocked"
        assert outcome["project_lane_transition"] == "unchanged"

        # remote-closeout：parity + merge + cleanup 合同；registry close_pending/closed
        def closeout_request(remote_head, registry_state="close_pending", **overrides) -> dict:
            request = base_request(
                "remote-closeout",
                "git push",
                authorization=copy.deepcopy(authorization),
                idempotency=copy.deepcopy(idempotency),
                branch={"head": "worker", "base": "main"},
                parity_readback=write_json(
                    "parity.json", {"local_head": "abc123", "remote_head": "abc123"}
                ),
                merge_readback=write_json("merged.json", {"state": "MERGED"}),
                fan_in=copy.deepcopy(fan_in),
                closeout_cleanup={
                    "worker_release": write_json("release.json", {"released": True}),
                    "archive_output": write_json("archive.json", {"archived": True}),
                    "worktree_cleanup": write_json("wt.json", {"removed": True}),
                    "registry": write_json("reg.json", {"state": registry_state}),
                },
                remote_readback=write_json(
                    "close-ls-remote.json", {"refs": {"worker": remote_head}}
                ),
                delete_branch=True,
            )
            request.update(overrides)
            return request

        outcome = gate.validate(closeout_request("abc123"))
        assert outcome["action"] == "delete-remote-branch", outcome
        dedup = gate.validate(closeout_request(None))
        assert dedup["action"] == "deduplicated", dedup
        # parity 未证实 blocked；Unknown 不越权
        unbalanced = closeout_request("abc123")
        unbalanced["parity_readback"] = write_json(
            "parity-bad.json", {"local_head": "abc123", "remote_head": "other"}
        )
        assert gate.validate(unbalanced)["status"] == "blocked"
        # 未 merge 不 closeout
        unmerged = closeout_request("abc123")
        unmerged["merge_readback"] = write_json("open.json", {"state": "OPEN"})
        assert gate.validate(unmerged)["status"] == "blocked"
        # registry 非 close_pending/closed blocked
        assert gate.validate(closeout_request("abc123", "running"))["status"] == "blocked"
        # 未声明 delete_branch 不盲删除
        no_delete = closeout_request("abc123")
        no_delete["delete_branch"] = False
        assert gate.validate(no_delete)["status"] == "blocked"

        # verify-result：只有 success 可绑定证据；timeout/Unknown fail-closed
        receipt = write("receipt.txt", "gh pr merge 9 --squash\n")
        readback = write_json("result.json", {"state": "MERGED", "body": marker})
        verify = base_request(
            "verify-result",
            "gh pr merge",
            evidence={
                "outcome": "success",
                "mutation_receipt": receipt,
                "result_readback": readback,
                "idempotency_key": idempotency["key"],
                "artifacts": [],
                "captured_at": "2026-09-17T00:00:00Z",
            },
        )
        outcome = gate.validate(verify)
        assert outcome["status"] == "ready" and outcome["action"] == "evidence-bound"
        for failed_outcome in ("timeout", "unknown", "network-loss", "failed"):
            failed = copy.deepcopy(verify)
            failed["evidence"]["outcome"] = failed_outcome
            outcome = gate.validate(failed)
            assert outcome["status"] == "blocked" and not outcome["authority"]
            assert outcome["project_lane_transition"] == "unchanged"
        missing_marker = copy.deepcopy(verify)
        missing_marker["evidence"]["result_readback"] = write_json(
            "no-marker.json", {"state": "MERGED"}
        )
        assert gate.validate(missing_marker)["status"] == "blocked"

        # 无 capability / 身份不一致 / 未知命令 一律 blocked
        no_capability = base_request("branch-push", "git push")
        assert gate.validate(no_capability)["status"] == "blocked"
        wrong_login = base_request("publication-read", "git ls-remote")
        wrong_login["capability"]["expected_identity"] = "someone-else"
        assert gate.validate(wrong_login)["status"] == "blocked"
        linear = base_request("pr-merge", "gh pr merge")
        linear["capability"]["provider"] = "linear"
        assert gate.validate(linear)["status"] == "blocked"

        # malformed：任何 operation 都不抛异常、不产生 mutation
        for malformed in (
            "not a dict",
            {"operation": "pr-merge", "lane": copy.deepcopy(lane)},
        ):
            outcome = gate.validate(malformed)
            assert outcome["status"] == "blocked" and outcome["mutations"] == []
        frozen = copy.deepcopy(verify)
        gate.validate(verify)
        assert verify == frozen, "validate 不得改写 caller 请求"

    print(
        "Orca remote publication gate check: PASS (simulated; native acceptance not-run/Unknown)"
    )


if __name__ == "__main__":
    main()
