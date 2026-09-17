#!/usr/bin/env python3
"""Phase 2B provider mutation 模拟合同检查；不是真实 provider 验收。"""

from __future__ import annotations

import copy
import hashlib
import importlib
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
gate = importlib.import_module("provider_mutation")
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
            "work_item": "126",
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
            "work_item": "126",
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
            "scope": "isolated test issue comment",
            "evidence": write("packet.json", json.dumps({"packet": True})),
        }

        def capability(
            command: str, *, provider: str = "github", login: str = "Dimon94"
        ) -> dict:
            return {
                "provider": provider,
                "command": command,
                "reference": "gh CLI manual (2.78.0)",
                "cli_version_readback": version_readback,
                "identity_readback": identity_readback,
                "expected_identity": login,
            }

        idempotency = {
            "key": "map-114-lane-1-126-test-comment",
            "retry_rule": "readback-first",
            "prior_readback": None,
        }
        marker = gate.idempotency_marker(idempotency["key"])
        dedupe_empty = {"readback": write("issue-view-empty.json", "no marker here")}
        dedupe_hit = {"readback": write("issue-view-hit.txt", "body\n" + marker)}

        def tracker_request(**overrides) -> dict:
            request = {
                "operation": "tracker-mutate",
                "lane": copy.deepcopy(lane),
                "binding": dict(binding),
                "capability": capability("gh issue comment"),
                "authorization": dict(authorization),
                "target": {"repository": "owner/repo", "issue": 1},
                "idempotency": dict(idempotency),
                "dedupe": dict(dedupe_empty),
            }
            for key_path, value in overrides.items():
                node = request
                parts = key_path.split(".")
                for part in parts[:-1]:
                    node = node.setdefault(part, {})
                node[parts[-1]] = value
            return request

        def assert_blocked(request: dict, fragment: str) -> None:
            outcome = gate.validate(request)
            assert outcome["status"] == "blocked", outcome
            assert fragment in outcome["reason"], outcome
            assert outcome["authority"] == False
            assert outcome["mutations"] == []
            assert outcome["project_lane_transition"] == "unchanged"

        def assert_ready(request: dict, action: str) -> None:
            outcome = gate.validate(request)
            assert outcome["status"] == "ready", outcome
            assert outcome.get("action") == action, outcome
            assert outcome["authority"] == False
            assert outcome["mutations"] == []
            assert outcome["scope"] == "phase2-operation-only"

        # tracker-read：只读，不要求授权/幂等；gh api 只允许 GET。
        read_request = tracker_request(
            operation="tracker-read",
            capability=capability("gh issue view"),
            authorization=None,
            idempotency=None,
            dedupe=None,
        )
        assert_ready(read_request, "execute-readonly")
        api_post = tracker_request(
            operation="tracker-read",
            capability=capability("gh api"),
            authorization=None,
            idempotency=None,
            dedupe=None,
            **{"target.method": "POST", "target.endpoint": "/repos/o/r/issues"},
        )
        assert_blocked(api_post, "只允许 GET")

        # tracker-mutate 幂等：readback-first，marker 命中需 resume。
        assert_ready(tracker_request(), "execute-idempotent-mutation")
        hit = tracker_request(dedupe=dict(dedupe_hit))
        assert_blocked(hit, "禁止盲重发")
        resume = tracker_request(dedupe=dict(dedupe_hit), resume=True)
        assert_ready(resume, "consume-existing-mutation")
        missing_resume = tracker_request(resume=True)
        assert_blocked(missing_resume, "resume")
        blind = tracker_request(**{"idempotency.retry_rule": "blind-retry"})
        assert_blocked(blind, "readback-first")
        unbound = tracker_request(**{"idempotency.key": "unrelated"})
        assert_blocked(unbound, "map/work item")

        # capability/identity：登录身份不一致、版本 readback 缺失均 blocked。
        wrong_login = tracker_request(**{"capability.expected_identity": "Other"})
        assert_blocked(wrong_login, "登录身份")
        missing_version = tracker_request(capability_cli_version_readback=None)
        missing_version["capability"]["cli_version_readback"] = None
        assert_blocked(missing_version, "cli_version_readback")
        closed_command = tracker_request(capability=capability("gh pr merge"))
        assert_blocked(closed_command, "闭集外")

        # artifact publish：内容一致 dedup，同名异内容 fail-closed。
        artifact_file = write("evidence.md", "phase2b evidence\n")
        artifact_sha = hashlib.sha256(Path(artifact_file).read_bytes()).hexdigest()
        listing_empty = write_json("listing-empty.json", {"artifacts": []})
        listing_same = write_json(
            "listing-same.json",
            {"artifacts": [{"name": "evidence.md", "sha256": artifact_sha}]},
        )
        listing_conflict = write_json(
            "listing-conflict.json",
            {"artifacts": [{"name": "evidence.md", "sha256": "0" * 64}]},
        )

        def publish_request(listing: str, sha: str = artifact_sha) -> dict:
            return {
                "operation": "artifact-publish",
                "lane": copy.deepcopy(lane),
                "binding": dict(binding),
                "authorization": dict(authorization),
                "idempotency": dict(idempotency),
                "artifact": {
                    "path": artifact_file,
                    "kind": "evidence",
                    "sha256": sha,
                },
                "output_mode": "artifact",
                "destination": {"dir": str(root)},
                "dedupe": {"listing_readback": listing},
            }

        assert_ready(publish_request(listing_empty), "publish-artifact")
        assert_ready(publish_request(listing_same), "deduplicated")
        assert_blocked(publish_request(listing_conflict), "同名不同内容")
        assert_blocked(publish_request(listing_empty, sha="0" * 64), "不一致")
        bad_mode = publish_request(listing_empty)
        bad_mode["output_mode"] = "commit"
        assert_blocked(bad_mode, "不允许")

        # artifact-read：sha 必须匹配，不要求授权。
        read_artifact = publish_request(listing_empty)
        read_artifact.update(
            operation="artifact-read",
            authorization=None,
            idempotency=None,
            output_mode=None,
            destination=None,
            dedupe=None,
        )
        assert_ready(read_artifact, "execute-readonly")
        bad_read = copy.deepcopy(read_artifact)
        bad_read["artifact"]["sha256"] = "0" * 64
        assert_blocked(bad_read, "不一致")

        # archive/delete 边界：cleanup gate verdict + review evidence。
        retire = {
            "operation": "artifact-archive",
            "lane": copy.deepcopy(lane),
            "binding": dict(binding),
            "authorization": dict(authorization),
            "artifact": {"path": artifact_file},
            "cleanup_gate": {
                "verdict": "pass",
                "evidence": write("cleanup.json", "{}"),
            },
            "review_evidence": {
                "verdict": write("review-verdict.txt", "consumed"),
            },
        }
        assert_ready(retire, "archive-artifact")
        retire_delete = copy.deepcopy(retire)
        retire_delete["operation"] = "artifact-delete"
        assert_ready(retire_delete, "delete-artifact")
        no_cleanup = copy.deepcopy(retire)
        no_cleanup["cleanup_gate"] = None
        assert_blocked(no_cleanup, "cleanup_gate")

        # pr-ready：draft→ready；非 draft 幂等 deduplicated；非 OPEN blocked。
        pr_base = {
            "operation": "pr-ready",
            "lane": copy.deepcopy(lane),
            "binding": dict(binding),
            "capability": capability("gh pr ready"),
            "authorization": dict(authorization),
            "target": {"repository": "owner/repo", "pull_request": 42},
            "idempotency": dict(idempotency),
        }
        draft = write_json("pr-draft.json", {"state": "OPEN", "isDraft": True})
        open_ready = write_json("pr-open.json", {"state": "OPEN", "isDraft": False})
        merged = write_json("pr-merged.json", {"state": "MERGED", "isDraft": False})
        draft_request = copy.deepcopy(pr_base)
        draft_request["state_readback"] = draft
        assert_ready(draft_request, "mark-ready-for-review")
        ready_request = copy.deepcopy(pr_base)
        ready_request["state_readback"] = open_ready
        assert_ready(ready_request, "deduplicated")
        merged_request = copy.deepcopy(pr_base)
        merged_request["state_readback"] = merged
        assert_blocked(merged_request, "不盲操作")

        # verify-result：非 success fail-closed；marker 必须在 readback 中。
        receipt = write("mutation-receipt.txt", "gh issue comment 1 --body ...\n")
        result_readback = write_json(
            "result-readback.json",
            {"body": "done " + marker, "comments": []},
        )
        verify = {
            "operation": "verify-result",
            "lane": copy.deepcopy(lane),
            "binding": dict(binding),
            "evidence": {
                "outcome": "success",
                "mutation_receipt": receipt,
                "result_readback": result_readback,
                "idempotency_key": idempotency["key"],
                "artifacts": [artifact_file],
                "captured_at": "2026-09-17T00:00:00Z",
            },
        }
        assert_ready(verify, "evidence-bound")
        unknown = copy.deepcopy(verify)
        unknown["evidence"]["outcome"] = "unknown"
        assert_blocked(unknown, "fail-closed")
        no_marker = copy.deepcopy(verify)
        no_marker["evidence"]["result_readback"] = write_json(
            "result-readback-missing.json", {"body": "no marker"}
        )
        assert_blocked(no_marker, "幂等 marker")

        # 结构性约束：未知 operation / binding 不一致 / 请求不被改写。
        assert_blocked({"operation": "nope"}, "未知 operation")
        bad_binding = tracker_request()
        bad_binding["binding"]["lane_id"] = "lane-2"
        assert_blocked(bad_binding, "binding")
        for malformed in (
            {"operation": "tracker-mutate", "lane": None},
            {"operation": "artifact-publish", "lane": copy.deepcopy(lane)},
        ):
            outcome = gate.validate(malformed)
            assert outcome["status"] == "blocked" and outcome["mutations"] == []
        frozen = copy.deepcopy(verify)
        gate.validate(verify)
        assert verify == frozen, "validate 不得改写 caller 请求"

    print(
        "Orca provider mutation gate check: PASS (simulated; native acceptance not-run/Unknown)"
    )


if __name__ == "__main__":
    main()
