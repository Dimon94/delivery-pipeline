#!/usr/bin/env python3
"""app_dispatch.py 的可观察行为检查；隔离临时 Git repo，无 App 请求。"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HELPER = Path(__file__).with_name("app_dispatch.py")
GATE = {
    "work_item": "ticket-643",
    "map": "map-638",
    "gate_evidence": {
        "readback": "fixture tracker snapshot 2026-09-07",
        "discovery": "decision resolution and user confirmation",
        "spec": {"url": "spec-650", "source_map": "map-638", "body": "spec body",
                 "owner_run": "to-spec artifact", "confirmation": "user confirmed testing seams"},
        "ticket": {"url": "ticket-643", "parent": "spec-650", "body": "ticket body",
                   "owner_run": "to-tickets artifact", "confirmation": "user approved breakdown",
                   "dependencies": []},
    },
}


def env():
    e = os.environ.copy()
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
        e.pop(name, None)
    return e


def call(command, data, success=True):
    r = subprocess.run([sys.executable, str(HELPER), command], input=json.dumps(data),
                       text=True, capture_output=True, env=env())
    assert (r.returncode == 0) == success, (command, r.stderr or r.stdout)
    return json.loads(r.stdout) if success else r.stderr


def check():
    configured = call("models", {})["config"]
    assert configured["default_mode"] in configured["modes"]
    assert all(m["kind"] == "direct" for m in configured["modes"].values())
    planning = call("model", {"work": "planning"})
    assert planning["target"]["model"] == configured["work"]["planning"]["model"]

    unknown = call("coordinator", {"model": "x", "effort": "high", "source": ""})
    assert unknown["action"] == "Unknown"
    verified = call("coordinator", {"model": "x", "effort": "high", "source": "host settings"})
    assert verified["action"] == "verified" and verified["model"] == "x"

    base = {"task": "backend", "output_mode": "commit", **GATE}
    created = call("resolve", base)
    assert created["action"] == "create" and created["overlay"]["execution_kind"] == "direct"
    assert created["overlay"]["mode_source"] == "default" and created["overlay"]["model"] == "Unknown"
    assert created["request"]["model"] == created["overlay"]["requested_model"]
    override = call("resolve", {**base, "model_overrides": {"direct": {"model": "direct-test", "effort": "low", "source": "user", "scope": "direct"}}})
    assert override["request"] == {"model": "direct-test", "thinking": "low"}
    assert "只跑 direct" in call("resolve", {**base, "model_overrides": {"starting": {"model": "a", "effort": "low"}}}, False)
    assert "非法 development_mode" in call("resolve", {**base, "ticket_mode": "astra-sol"}, False)
    recovered = call("resolve", {"existing_lane": {"model": "old"}})
    assert recovered["action"] == "recover" and recovered["request"] is None
    assert call("resolve", {"task": "review", "output_mode": "verdict"})["action"] == "not-applicable"
    call("resolve", {**base, "gate_evidence": {}}, False)

    sub = {"source": "host list", "read_only": False}
    assert call("subagent", {**sub, "work": "second-opinion", "active_count": 3})["action"] == "wait"
    assist = call("subagent", {**sub, "work": "assistance", "active_count": 0, "read_only": True})
    assert assist["action"] == "spawn" and assist["read_only"] is True
    assert assist["request"]["fork_turns"] == "none"
    assert call("subagent", {**sub, "work": "testing", "active_count": 0})["read_only"] is True
    assert call("subagent", {**sub, "work": "integration", "active_count": 0})["read_only"] is False
    call("subagent", {**sub, "work": "integration", "active_count": 1}, False)
    rv = call("subagent", {**sub, "work": "review", "active_count": 0, "review_scope": "implementation"})
    assert rv["action"] == "invoke-owner" and rv["required_slots"] == 2

    with tempfile.TemporaryDirectory() as tmp:
        g = lambda *a: subprocess.run(["git", "-C", tmp, *a], check=True, capture_output=True, text=True, env=env()).stdout.strip()
        g("init", "-q"); g("config", "user.email", "t@e"); g("config", "user.name", "t")
        Path(tmp, "a").write_text("1"); g("add", "a"); g("commit", "-qm", "a")
        base_commit = g("rev-parse", "HEAD")
        Path(tmp, "a").write_text("2"); g("commit", "-qam", "b")
        head = g("rev-parse", "HEAD")
        review = {"worktree": tmp, "base_commit": base_commit, "head_commit": head,
                  "review_scope": "implementation",
                  "owner": {"name": "code-review", "skill_path": "/resolved/code-review/SKILL.md",
                            "invocation_label": "$code-review"},
                  "reviews": {}}
        assert "缺少独立两轴结论" in call("review", review, False)
        axis = lambda r: {"reviewer_id": r, "source": "host", "verdict_text": "pass", "status": "completed",
                          "verdict": "pass", "blocking_findings": 0, "review_scope": "implementation",
                          "base_commit": base_commit, "head_commit": head}
        review = {**review, "worker_id": "w", "reviews": {"standards": axis("r1"), "spec": axis("r2")}}
        assert call("review", review)["action"] == "review-passed"
        assert "必须独立" in call("review", {**review, "worker_id": "r1"}, False)
        Path(tmp, "a").write_text("dirty")
        assert "待集成代码已变化" in call("review", review, False)
    print("app_dispatch check: pass")


if __name__ == "__main__":
    check()
