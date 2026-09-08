#!/usr/bin/env python3
"""分派 CLI 的可观察行为检查；隔离临时 Git repo，无 App 请求。"""
import copy
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

HELPER = Path(__file__).with_name("prewalk.py")


def git_env():
    env = os.environ.copy()
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
        env.pop(name, None)
    return env


def call(command, data, success=True, extra_env=None):
    env = git_env()
    env.update(extra_env or {})
    result = subprocess.run([sys.executable, str(HELPER), command], input=json.dumps(data),
                            text=True, capture_output=True, env=env)
    assert (result.returncode == 0) == success, result.stderr or result.stdout
    return json.loads(result.stdout) if success else result.stderr


def check():
    review = {"worktree": "unused", "base_commit": "unused", "head_commit": "unused",
              "review_scope": "implementation",
              "owner": {"name": "code-review", "skill_path": "/resolved/code-review/SKILL.md",
                        "invocation_label": "$code-review"}, "reviews": {}}
    assert "缺少独立两轴结论" in call("review", review, False)
    coordinator = call("coordinator", {"model": "gpt-5.6-sol", "effort": "high", "source": "turn_context"})
    assert coordinator["action"] == "verified"
    for model, effort, source in (("gpt-5.6-sol", "low", "turn_context"),
                                  ("gpt-6-astra", "high", "turn_context"),
                                  ("gpt-5.6-sol", "high", "")):
        observed = call("coordinator", {"model": model, "effort": effort, "source": source})
        assert observed["action"] == ("verified" if source else "Unknown")
        assert observed["model"] == (model if source else "Unknown")
    sizing = call("subagent", {"work": "ticket-sizing", "active_count": 0, "source": "live list", "read_only": False})
    assert sizing["request"] == {"model": "gpt-5.6-sol", "reasoning_effort": "high", "fork_turns": "none"}
    assert sizing["read_only"] is True
    assert call("subagent", {"work": "ticket-sizing", "active_count": 3, "source": "live list", "read_only": False})["action"] == "wait"
    support = call("subagent", {"work": "assistance", "active_count": 0, "source": "live list", "read_only": True})
    assert support["request"] == {"model": "gpt-5.6-luna", "reasoning_effort": "max", "fork_turns": "none"}
    assert support["read_only"] is True
    opinion = call("subagent", {"work": "second-opinion", "active_count": 0, "source": "live list", "read_only": False})
    assert opinion["request"]["model"] == "gpt-6-astra" and opinion["read_only"] is True
    for work in ("testing", "integration"):
        delegated = call("subagent", {"work": work, "active_count": 0, "source": "live list", "read_only": False})
        assert delegated["request"] == {"model": "gpt-5.6-luna", "reasoning_effort": "max", "fork_turns": "none"}
        assert delegated["read_only"] is (work == "testing")
        call("subagent", {"work": work, "active_count": 1, "source": "live list", "read_only": False}, False)
    call("subagent", {"work": "integration", "active_count": 0, "source": "live list", "read_only": True}, False)
    assert call("subagent", {"work": "assistance", "active_count": 3, "source": "live list", "read_only": False})["request"] is None
    assert call("subagent", {"work": "review", "active_count": 2, "source": "live list", "read_only": True})["action"] == "wait"
    assert call("subagent", {"work": "review", "active_count": 0, "source": "live list", "read_only": True})["action"] == "invoke-owner"
    call("subagent", {"work": "assistance", "active_count": -1, "source": "live list", "read_only": True}, False)
    call("subagent", {"work": "assistance", "active_count": 0, "source": "", "read_only": True}, False)
    # #638/#642：原型的实施建议没有 Spec/拆票证据，不能创建实施 lane。
    for mode in ("sol-luna", "sol-sol", "sol-direct"):
        call("resolve", {"role": "frontend", "output_mode": "commit", "ticket_mode": mode}, False)
    gate = {"work_item": "ticket-643", "map": "map-638", "gate_evidence": {
        "readback": "fixture tracker snapshot 2026-09-07", "discovery": "decision resolution and user confirmation",
        "spec": {"url": "spec-650", "source_map": "map-638", "body": "spec body",
                 "owner_run": "to-spec artifact", "confirmation": "user confirmed testing seams"},
        "ticket": {"url": "ticket-643", "parent": "spec-650", "body": "ticket body",
                   "owner_run": "to-tickets artifact", "sizing": "ticket-sizing per-ticket assessment artifact", "confirmation": "user approved breakdown", "dependencies": []}}}
    base = {"role": "backend", "output_mode": "commit", **gate}
    core_helper = HELPER.resolve().parents[2] / "delivery-pipeline/scripts/implementation_gate.py"
    for payload, expected in ((gate, 0), ({"work_item": "ticket-643"}, 1)):
        result = subprocess.run([sys.executable, str(core_helper)], input=json.dumps(payload),
                                text=True, capture_output=True)
        assert result.returncode == expected, result.stderr or result.stdout
    for stage in ("spec", "ticket"):
        for field in ("url", "body", "owner_run", "confirmation"):
            bad = copy.deepcopy(base)
            bad["gate_evidence"][stage][field] = "Unknown"
            call("resolve", bad, False)
    for stage, field, value in (("ticket", "parent", "map-638"), ("ticket", "url", "other-ticket"),
                                ("ticket", "dependencies", None), ("spec", "source_map", "other-map")):
        bad = copy.deepcopy(base)
        bad["gate_evidence"][stage][field] = value
        call("resolve", bad, False)
    for field in ("readback", "discovery"):
        bad = copy.deepcopy(base)
        del bad["gate_evidence"][field]
        call("resolve", bad, False)
    standalone = copy.deepcopy(base)
    del standalone["map"]
    assert call("resolve", standalone)["action"] == "create"
    assert call("resolve", {"existing_lane": {"model": "old"}})["action"] == "recover"
    missing_sizing = copy.deepcopy(base)
    del missing_sizing["gate_evidence"]["ticket"]["sizing"]
    call("resolve", missing_sizing, False)
    default = call("resolve", base)
    assert default["overlay"]["development_mode"] == "sol-luna"
    assert default["request"] == {"model": "gpt-5.6-sol", "thinking": "high"}
    assert call("resolve", {**base, "map_mode": "sol-sol"})["overlay"]["mode_source"] == "map"
    for legacy_mode in ("astra-luna", "astra-sol"):
        call("resolve", {**base, "ticket_mode": legacy_mode}, False)
    direct = call("resolve", {**base, "ticket_mode": "sol-direct", "map_mode": "sol-luna"})
    assert direct["request"] == {"model": "gpt-5.6-sol", "thinking": "high"}
    assert direct["overlay"]["execution_phase"] == "executing"
    assert call("resolve", {**base, "existing_lane": {"model": "old"}})["request"] is None
    assert call("resolve", {"role": "review", "output_mode": "verdict"})["action"] == "not-applicable"
    call("resolve", {**base, "ticket_mode": "invalid"}, False)
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder) / "repo"
        root.mkdir()
        def git(*args):
            subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True,
                           env=git_env())
        git("init", "-b", "probe")
        git("-c", "user.name=Probe", "-c", "user.email=probe@example.invalid", "commit", "--allow-empty", "-m", "base")
        git("checkout", "--detach")
        (root / "worker.py").write_text("first edit\n")
        snap = call("snapshot", {"worktree": str(root)})
        assert call("snapshot", {"worktree": str(root)}, extra_env={
            "GIT_DIR": str(root / ".git"), "GIT_WORK_TREE": str(root / "elsewhere"),
            "GIT_INDEX_FILE": str(root / "bogus-index"), "GIT_COMMON_DIR": str(root / "bogus-common")}) == snap
        lane = {**default["overlay"], "lane_id": "probe", "thread_id": "same-task", "host_id": "local",
                "coordinator_thread_id": "coordinator-task", "coordinator_host_id": "local",
                "worktree": str(root), "state": "running", "base_commit": snap["head"]}
        legacy_dirty = {}
        for name, item in snap["dirty"].items():
            if item["deleted"]:
                legacy_dirty[name] = {"deleted": True}
            else:
                kind = stat.S_IFLNK if item["kind"] == "symlink" else stat.S_IFREG
                legacy_dirty[name] = {"mode": kind | item["mode"], "sha256": item["content_sha256"]}
        legacy_snapshot = {key: snap[key] for key in
                           ("worktree", "head", "branch", "common_dir", "index_sha256")}
        legacy_snapshot["dirty"] = legacy_dirty
        legacy_snapshot["ignored"] = {"delivery_input": "none"}
        legacy_path = Path(folder) / "legacy-checkpoint.json"
        legacy_checkpoint = {"lane_id": lane["lane_id"], "thread_id": lane["thread_id"],
                             "host_id": lane["host_id"], "base_commit": lane["base_commit"],
                             "first_edit": ["worker.py"], "snapshot": legacy_snapshot,
                             "todo": ["finish"], "checks": ["start passed"],
                             "evidence": ["spec"], "decision": {
                                 "critical_design_unknown": False, "reason": "minimal"}}
        legacy_path.write_text(json.dumps(legacy_checkpoint))
        legacy_lane = {**lane, "development_mode": "astra-luna",
                       "checkpoint_format": "legacy-app-v0",
                       "checkpoint": str(legacy_path)}
        legacy_data = {**gate, "lane": legacy_lane, "checkpoint": legacy_checkpoint,
                       "checkpoint_path": str(legacy_path), "legacy_checkpoint": True,
                       "observation": {"thread_id": "same-task", "host_id": "local",
                                       "status": "idle", "source": "probe"}}
        legacy = call("prepare", legacy_data)
        assert legacy["overlay"]["checkpoint_format"] == "legacy-app-v0"
        assert legacy["overlay"]["checkpoint_sha256"] == "Unknown"
        critical_legacy = copy.deepcopy(legacy_data)
        critical_legacy["checkpoint"]["decision"] = {
            "critical_design_unknown": True, "reason": "unresolved architecture"}
        legacy_path.write_text(json.dumps(critical_legacy["checkpoint"]))
        critical_error = json.loads(call("prepare", critical_legacy, False))
        assert "关键设计 Unknown" in critical_error["error"] and "request" not in critical_error
        legacy_path.write_text(json.dumps(legacy_checkpoint))
        for bad_decision in (None, "Unknown", {},
                             {"critical_design_unknown": "Unknown", "reason": "minimal"},
                             {"critical_design_unknown": False, "reason": "Unknown"}):
            bad_legacy = copy.deepcopy(legacy_data)
            bad_legacy["checkpoint"]["decision"] = bad_decision
            legacy_path.write_text(json.dumps(bad_legacy["checkpoint"]))
            decision_error = json.loads(call("prepare", bad_legacy, False))
            assert "legacy decision" in decision_error["error"] and "request" not in decision_error
        legacy_path.write_text(json.dumps(legacy_checkpoint))
        call("prepare", {**legacy_data, "lane": lane}, False)
        mismatch_lane = {**legacy_lane, "checkpoint": str(Path(folder) / "other.json")}
        assert "path 不匹配" in call("prepare", {**legacy_data, "lane": mismatch_lane}, False)
        ignored_legacy = copy.deepcopy(legacy_data)
        ignored_legacy["checkpoint"]["snapshot"]["ignored"] = {"delivery_input": "Unknown"}
        legacy_path.write_text(json.dumps(ignored_legacy["checkpoint"]))
        assert "legacy ignored" in call("prepare", ignored_legacy, False)
        legacy_path.write_text(json.dumps(legacy_checkpoint))
        without_legacy = copy.deepcopy(legacy_data)
        del without_legacy["legacy_checkpoint"]
        call("prepare", without_legacy, False)
        path = Path(folder) / "checkpoint.json"
        payload = {
            "lane_id": lane["lane_id"], "work_item": gate["work_item"], "runtime": "codex-thread",
            "session_id": lane["thread_id"], "coordinator_thread_id": lane["coordinator_thread_id"],
            "coordinator_host_id": lane["coordinator_host_id"], "cli_version": "Unknown",
            "execution_worktree": snap["worktree"], "execution_branch": snap["branch"],
            "base_commit": snap["head"], "head_commit": snap["head"], "phase": "starting",
            "development_mode": "staged", "mode_source": "user-config",
            "phase_plan": {"starting": {"model": "gpt-5.6-sol", "effort": "high"},
                           "execution": {"model": "gpt-5.6-luna", "effort": "max"},
                           "direct": {"model": "gpt-5.6-sol", "effort": "high"}},
            "requested_model": "gpt-5.6-sol", "requested_effort": "high",
            "tool_acceptance": {"accepted": True, "status": "accepted", "source": "host readback"},
            "actual_model": "gpt-5.6-sol", "actual_effort": "high",
            "actual_readback_source": "host turn context", "actual_readback_at": "2026-09-08T00:00:00Z",
            "first_edit": ["worker.py"], "checks": [{"command": "compile worker.py", "result": "exit 0"}],
            "todo": ["finish"], "decision": {"critical_design_unknown": False, "reason": "minimal"},
            "evidence": ["spec"], "checkpoint_path": str(path),
        }
        checkpoint = call("checkpoint", {"worktree": str(root), "checkpoint_path": str(path),
                                         "payload": payload})
        assert checkpoint["checkpoint_sha256"]
        assert path.read_text() == json.dumps(checkpoint, ensure_ascii=False, sort_keys=True,
                                              separators=(",", ":"))
        data = {**gate, "lane": lane, "checkpoint": checkpoint, "checkpoint_path": str(path),
                "observation": {"thread_id": "same-task", "host_id": "local", "status": "idle", "source": "probe"}}
        bad = copy.deepcopy(data)
        del bad["checkpoint"]["first_edit"]
        path.write_text(json.dumps(bad["checkpoint"], ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        call("prepare", bad, False)
        for field, value in (("first_edit", ["unrelated.py"]), ("base_commit", "wrong-base")):
            bad = copy.deepcopy(data)
            bad["checkpoint"][field] = value
            path.write_text(json.dumps(bad["checkpoint"], ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            call("prepare", bad, False)
        path.write_text(json.dumps(checkpoint, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        missing_gate = copy.deepcopy(data)
        del missing_gate["gate_evidence"]
        call("prepare", missing_gate, False)
        prepared = call("prepare", data)
        assert prepared["action"] == "persist-before-send"
        assert prepared["request"]["threadId"] == "same-task"
        assert prepared["request"]["model"] == "gpt-5.6-luna"
        assert prepared["request"]["thinking"] == "max"
        assert prepared["overlay"]["requested_effort"] == "max"
        assert prepared["overlay"]["model"] == "Unknown"
        assert prepared["overlay"]["checkpoint_sha256"] == checkpoint["checkpoint_sha256"]
        assert "起步轮限制已结束" in prepared["request"]["prompt"]
        assert "不得取消或中断正式 reviewer" in prepared["request"]["prompt"]
        assert "resolved owner 和 review_scope" in prepared["request"]["prompt"]
        assert "不得报告 completed" in prepared["request"]["prompt"]
        assert "持久恢复证据" in call("prepare", {
            **data, "lane": {**lane, "development_mode": "astra-luna"}}, False)
        assert call("prepare", {**data, "lane": prepared["overlay"]})["request"] is None
        assert call("prepare", {**data, "lane": {**lane, "execution_phase": "executing"}})["request"] is None
        sol_path = Path(folder) / "sol-checkpoint.json"
        sol_payload = copy.deepcopy(payload)
        sol_payload["checkpoint_path"] = str(sol_path)
        sol_payload["phase_plan"]["execution"] = {"model": "gpt-5.6-sol", "effort": "high"}
        sol_checkpoint = call("checkpoint", {"worktree": str(root), "checkpoint_path": str(sol_path),
                                             "payload": sol_payload})
        sol = call("prepare", {**data, "lane": {**lane, "development_mode": "sol-sol"},
                               "checkpoint": sol_checkpoint, "checkpoint_path": str(sol_path)})
        assert sol["request"]["model"] == "gpt-5.6-sol"
        assert sol["request"]["thinking"] == "high"
        legacy = call("prepare", {**data, "lane": {**lane, "development_mode": "astra-luna"}})
        assert legacy["request"]["model"] == "gpt-5.6-luna"
        pending = call("prepare", {**data, "observation": {**data["observation"], "status": "active"}})
        assert pending["action"] == "wait-for-stop" and pending["request"] is None
        assert pending["target"] == {"threadId": "same-task", "hostId": "local"}
        for field, value in (("status", "Unknown"), ("thread_id", "other"), ("source", "")):
            bad = copy.deepcopy(data)
            bad["observation"][field] = value
            call("prepare", bad, False)
        call("prepare", {**data, "lane": {**lane, "state": "integrated"}}, False)
        (root / "worker.py").write_text("changed after checkpoint\n")
        assert "已过期" in call("prepare", data, False)
        (root / "worker.py").write_text("first edit\n")
        git("add", "worker.py")
        assert "已过期" in call("prepare", data, False)
        git("reset")
        (root / "extra.txt").write_text("untracked")
        assert "已过期" in call("prepare", data, False)
        (root / "extra.txt").unlink()
        (root / ".gitignore").write_text("ignored.txt\n")
        (root / "ignored.txt").write_text("delivery input\n")
        ignored_path = Path(folder) / "ignored-checkpoint.json"
        ignored_payload = copy.deepcopy(payload)
        ignored_payload["checkpoint_path"] = str(ignored_path)
        call("checkpoint", {"worktree": str(root), "checkpoint_path": str(ignored_path),
                            "payload": ignored_payload, "required_ignored": ["ignored.txt"]}, False)
        ignored_checkpoint = call("checkpoint", {"worktree": str(root),
                                                  "checkpoint_path": str(ignored_path),
                                                  "payload": ignored_payload})
        ignored_data = {**data, "checkpoint": ignored_checkpoint, "checkpoint_path": str(ignored_path)}
        assert "ignored 交付输入" in call("prepare", ignored_data, False)
        (root / "ignored.txt").unlink()
        (root / ".gitignore").unlink()
        critical_path = Path(folder) / "critical-checkpoint.json"
        critical_payload = copy.deepcopy(payload)
        critical_payload["checkpoint_path"] = str(critical_path)
        critical_payload["decision"] = {"critical_design_unknown": True, "reason": "still unknown"}
        critical_checkpoint = call("checkpoint", {"worktree": str(root),
            "checkpoint_path": str(critical_path), "payload": critical_payload})
        critical_data = {**data, "checkpoint": critical_checkpoint,
                         "checkpoint_path": str(critical_path)}
        assert "关键设计 Unknown" in call("prepare", critical_data, False)
        git("add", "worker.py")
        git("-c", "user.name=Probe", "-c", "user.email=probe@example.invalid", "commit", "-m", "candidate")
        head = call("snapshot", {"worktree": str(root)})["head"]
        owner = {"name": "code-review", "skill_path": "/resolved/code-review/SKILL.md",
                 "invocation_label": "$code-review"}
        receipt = {"worktree": str(root), "worker_id": "worker", "base_commit": snap["head"],
                   "head_commit": head, "review_scope": "implementation", "owner": owner, "reviews": {}}
        for name in ("standards", "spec"):
            receipt["reviews"][name] = {"reviewer_id": name, "source": "host turn result",
                "status": "completed", "verdict": "pass", "verdict_text": "无阻断项",
                "blocking_findings": 0, "review_scope": "implementation",
                "base_commit": snap["head"], "head_commit": head}
        reviewed = call("review", receipt)
        assert reviewed["review_scope"] == "implementation" and reviewed["owner"] == owner
        whole_receipt = copy.deepcopy(receipt)
        whole_receipt["review_scope"] = "whole-change"
        for axis in whole_receipt["reviews"].values():
            axis["review_scope"] = "whole-change"
        whole_change = call("review", whole_receipt)
        assert whole_change["review_scope"] == "whole-change"
        for field, value in (("status", "interrupted"), ("status", "running"),
                             ("verdict", "self-approved"), ("blocking_findings", 1),
                             ("blocking_findings", False), ("head_commit", snap["head"]),
                             ("review_scope", "whole-change"),
                             ("reviewer_id", "worker"), ("reviewer_id", "standards"),
                             ("source", ""), ("verdict_text", "Unknown")):
            bad = copy.deepcopy(receipt)
            bad["reviews"]["spec"][field] = value
            call("review", bad, False)
        for field in ("owner", "review_scope"):
            bad = copy.deepcopy(receipt)
            del bad[field]
            call("review", bad, False)
        (root / "worker.py").write_text("changed after review")
        call("review", receipt, False)
    print("prewalk dispatch: pass (coordinator, spec/tickets gate, Sol modes, canonical checkpoint, legacy recovery, ignored, review independence)")


if __name__ == "__main__":
    check()
