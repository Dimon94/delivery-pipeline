#!/usr/bin/env python3
"""分派 CLI 的可观察行为检查；隔离临时 Git repo，无 App 请求。"""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile

HELPER = Path(__file__).with_name("prewalk.py")


def call(command, data, success=True):
    result = subprocess.run([sys.executable, str(HELPER), command], input=json.dumps(data),
                            text=True, capture_output=True)
    assert (result.returncode == 0) == success, result.stderr or result.stdout
    return json.loads(result.stdout) if success else result.stderr


def check():
    support = call("subagent", {"work": "assistance", "active_count": 0, "source": "live list", "read_only": True})
    assert support["request"] == {"model": "gpt-5.6-luna", "reasoning_effort": "high", "fork_turns": "none"}
    assert support["read_only"] is True
    opinion = call("subagent", {"work": "second-opinion", "active_count": 0, "source": "live list", "read_only": False})
    assert opinion["request"]["model"] == "gpt-6-astra" and opinion["read_only"] is True
    assert call("subagent", {"work": "assistance", "active_count": 3, "source": "live list", "read_only": False})["request"] is None
    assert call("subagent", {"work": "review", "active_count": 2, "source": "live list", "read_only": True})["action"] == "wait"
    assert call("subagent", {"work": "review", "active_count": 0, "source": "live list", "read_only": True})["action"] == "invoke-owner"
    call("subagent", {"work": "assistance", "active_count": -1, "source": "live list", "read_only": True}, False)
    call("subagent", {"work": "assistance", "active_count": 0, "source": "", "read_only": True}, False)
    base = {"role": "backend", "output_mode": "commit"}
    default = call("resolve", base)
    assert default["overlay"]["development_mode"] == "astra-luna"
    assert default["request"] == {"model": "gpt-6-astra", "thinking": "low"}
    assert call("resolve", {**base, "map_mode": "astra-sol"})["overlay"]["mode_source"] == "map"
    direct = call("resolve", {**base, "ticket_mode": "sol-direct", "map_mode": "astra-luna"})
    assert direct["request"] == {"model": "gpt-5.6-sol", "thinking": "high"}
    assert direct["overlay"]["execution_phase"] == "executing"
    assert call("resolve", {**base, "existing_lane": {"model": "old"}})["request"] is None
    assert call("resolve", {"role": "review", "output_mode": "verdict"})["action"] == "not-applicable"
    call("resolve", {**base, "ticket_mode": "invalid"}, False)
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder) / "repo"
        root.mkdir()
        def git(*args):
            subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
        git("init", "-b", "probe")
        git("-c", "user.name=Probe", "-c", "user.email=probe@example.invalid", "commit", "--allow-empty", "-m", "base")
        git("checkout", "--detach")
        (root / "worker.py").write_text("first edit\n")
        snap = call("snapshot", {"worktree": str(root)})
        lane = {**default["overlay"], "lane_id": "probe", "thread_id": "same-task", "host_id": "local",
                "worktree": str(root), "state": "running", "base_commit": snap["head"]}
        checkpoint = {k: lane[k] for k in ("lane_id", "thread_id", "host_id")}
        checkpoint.update(base_commit=lane["base_commit"], first_edit=["worker.py"], snapshot=snap, todo=["finish"], checks=["start passed"], evidence=["spec"], decision="minimal")
        path = Path(folder) / "checkpoint.json"
        path.write_text(json.dumps(checkpoint))
        data = {"lane": lane, "checkpoint": checkpoint, "checkpoint_path": str(path),
                "observation": {"thread_id": "same-task", "host_id": "local", "status": "idle", "source": "probe"}}
        bad = copy.deepcopy(data)
        del bad["checkpoint"]["first_edit"]
        path.write_text(json.dumps(bad["checkpoint"]))
        call("prepare", bad, False)
        for field, value in (("first_edit", ["unrelated.py"]), ("base_commit", "wrong-base")):
            bad = copy.deepcopy(data)
            bad["checkpoint"][field] = value
            path.write_text(json.dumps(bad["checkpoint"]))
            call("prepare", bad, False)
        path.write_text(json.dumps(checkpoint))
        prepared = call("prepare", data)
        assert prepared["action"] == "persist-before-send"
        assert prepared["request"]["threadId"] == "same-task"
        assert prepared["request"]["model"] == "gpt-5.6-luna"
        assert prepared["overlay"]["model"] == "Unknown"
        assert "起步轮限制已结束" in prepared["request"]["prompt"]
        assert call("prepare", {**data, "lane": prepared["overlay"]})["request"] is None
        assert call("prepare", {**data, "lane": {**lane, "execution_phase": "executing"}})["request"] is None
        sol = call("prepare", {**data, "lane": {**lane, "development_mode": "astra-sol"}})
        assert sol["request"]["model"] == "gpt-5.6-sol"
        pending = call("prepare", {**data, "observation": {**data["observation"], "status": "active"}})
        assert pending["action"] == "wait-for-stop" and pending["request"] is None
        assert pending["target"] == {"threadId": "same-task", "hostId": "local"}
        for field, value in (("status", "Unknown"), ("thread_id", "other"), ("source", "")):
            bad = copy.deepcopy(data)
            bad["observation"][field] = value
            call("prepare", bad, False)
        call("prepare", {**data, "lane": {**lane, "state": "integrated"}}, False)
        (root / "worker.py").write_text("changed after checkpoint\n")
        assert "检查点已过期" in call("prepare", data, False)
        (root / "worker.py").write_text("first edit\n")
        git("add", "worker.py")
        assert "检查点已过期" in call("prepare", data, False)
        git("reset")
        (root / "extra.txt").write_text("untracked")
        assert "检查点已过期" in call("prepare", data, False)
    print("prewalk dispatch: pass (modes, recovery, same-task, stopped, stale, duplicate, Unknown)")


if __name__ == "__main__":
    check()
