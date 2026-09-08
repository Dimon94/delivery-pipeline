#!/usr/bin/env python3
"""Claude Code 接续 adapter 的最小回归检查。"""

from pathlib import Path
import importlib.util
import json
import os
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("claude_adapter", ROOT / "claude_adapter.py")
assert SPEC and SPEC.loader
ADAPTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ADAPTER)
SETUP_SPEC = importlib.util.spec_from_file_location(
    "delivery_pipeline_model_config",
    ROOT.parents[1] / "delivery-pipeline-setup" / "scripts" / "model_config.py",
)
assert SETUP_SPEC and SETUP_SPEC.loader
MODEL_CONFIG = importlib.util.module_from_spec(SETUP_SPEC)
SETUP_SPEC.loader.exec_module(MODEL_CONFIG)


def rejects(payload: dict) -> None:
    try:
        ADAPTER.resume_plan(payload)
    except ADAPTER.ClaudeAdapterError:
        return
    raise AssertionError("unsafe Claude continuation was accepted")


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                   env=ADAPTER.CHECKPOINT._git_env())


def fixture(directory: Path) -> tuple[dict, Path]:
    root = directory / "execution"
    root.mkdir()
    git(root, "init", "-b", "canary-104")
    git(root, "config", "user.name", "claude-adapter-check")
    git(root, "config", "user.email", "claude-adapter@example.invalid")
    (root / "base.txt").write_text("base\n", encoding="utf-8")
    git(root, "add", "base.txt")
    # 临时 fixture 的基线提交不应递归触发本仓 pre-commit → validate → 本检查。
    git(root, "commit", "--no-verify", "-m", "base")
    (root / "worker.py").write_text("first edit\n", encoding="utf-8")
    snapshot = ADAPTER.CHECKPOINT.snapshot_worktree(root)
    checkpoint_path = directory / "registry" / "checkpoint.json"
    checkpoint_path.parent.mkdir()
    document = ADAPTER.CHECKPOINT.build_checkpoint({
        "lane_id": "map-95-issue-104",
        "work_item": "https://github.com/Dimon94/delivery-pipeline/issues/104",
        "runtime": "herdr-claude-pane",
        "session_id": "123e4567-e89b-12d3-a456-426614174000",
        "coordinator_thread_id": "coordinator-104",
        "coordinator_host_id": "local",
        "cli_version": "2.1.259",
        "execution_worktree": snapshot["worktree"],
        "execution_branch": snapshot["branch"],
        "base_commit": snapshot["head"],
        "head_commit": snapshot["head"],
        "phase": "starting",
        "development_mode": "staged",
        "mode_source": "user-config",
        "phase_plan": {
            "starting": {"model": "starting-model", "effort": "high"},
            "execution": {"model": "claude-sonnet-4-6", "effort": "max"},
            "direct": {"model": "direct-model", "effort": "high"},
        },
        "requested_model": "starting-model",
        "requested_effort": "high",
        "tool_acceptance": {"accepted": True, "status": "accepted", "source": "runtime"},
        "actual_model": "starting-model",
        "actual_effort": "high",
        "actual_readback_source": "turn-context",
        "actual_readback_at": "2026-09-08T00:00:00Z",
        "first_edit": ["worker.py"],
        "checks": [{"command": "python3 -m compileall worker.py", "result": "exit 0"}],
        "todo": ["continue implementation"],
        "decision": {"critical_design_unknown": False, "reason": "最小方案已确定"},
        "evidence": ["spec-99", "ticket-104"],
        "checkpoint_path": str(checkpoint_path),
    }, snapshot)
    ADAPTER.CHECKPOINT.write_checkpoint(checkpoint_path, document, worktree=root)
    return document, checkpoint_path


def payload_for(document: dict, checkpoint_path: Path) -> dict:
    target = {"model": "claude-sonnet-4-6", "effort": "max"}
    intent = ADAPTER.CHECKPOINT.build_continuation_intent(document, target_request=target)
    intent_sha = intent[ADAPTER.CHECKPOINT.INTENT_FINGERPRINT_FIELD]
    return {
        "runtime": document["runtime"],
        "session_id": document["session_id"],
        "checkpoint_path": str(checkpoint_path),
        "request": {
            "request_id": "request-" + intent_sha,
            "intent_sha256": intent_sha,
            "target_request": target,
        },
        "observation": {
            "runtime": document["runtime"],
            "session_id": document["session_id"],
            "coordinator_thread_id": document["coordinator_thread_id"],
            "coordinator_host_id": document["coordinator_host_id"],
            "status": "stopped",
            "writer_active": False,
            "coordinator_active": False,
            "session_resumable": True,
            "ready_seen": True,
            "stop_evidence": True,
            "source": "native-stop-readback",
            "read_at": "2026-09-08T00:00:01Z",
        },
        "tui_probe": {
            "status": "unavailable",
            "source": "HERDR_ENV=unset",
            "read_at": "2026-09-08T00:00:02Z",
        },
        "effort_evidence": {
            "source": "claude --help 2.1.259",
            "values": ["low", "medium", "high", "xhigh", "max"],
        },
    }


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="claude-adapter-104-") as folder:
        document, checkpoint_path = fixture(Path(folder))
        payload = payload_for(document, checkpoint_path)
        plan = ADAPTER.resume_plan(payload)
        dispatch_plan = MODEL_CONFIG.continuation_request(payload)
        assert dispatch_plan == plan
        payload_path = Path(folder) / "continuation.json"
        payload_path.write_text(json.dumps(payload), encoding="utf-8")
        cli = subprocess.run(
            [sys.executable, str(ROOT.parents[1] / "delivery-pipeline-setup" / "scripts" / "model_config.py"),
             "resume", "--request", str(payload_path)],
            check=False, text=True, capture_output=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        assert cli.returncode == 0, cli.stderr
        assert json.loads(cli.stdout) == plan
        assert plan["action"] == "resume-same-session"
        assert plan["argv"] == [
            "--resume", payload["session_id"],
            "--model", "claude-sonnet-4-6",
            "--effort", "max",
            "--dangerously-skip-permissions",
        ]
        assert "--fork-session" not in plan["argv"]
        assert plan["actual_model"] == plan["actual_effort"] == "Unknown"
        assert plan["prompt"] == (
            "沿原 session 与原 packet 接续；读取 checkpoint " + str(checkpoint_path) + "；"
            "完成剩余实现、检查与 owner 交付。"
        )
        assert "nonce" not in plan["prompt"].lower()
        assert plan["checkpoint_sha256"] == document["checkpoint_sha256"]
        assert plan["execution_worktree"] == document["execution_worktree"]

        rejects({**payload, "runtime": "herdr-codex-pane"})
        rejects({**payload, "session_id": "recent"})
        rejects({**payload, "request": {**payload["request"],
                 "target_request": {"model": "claude-sonnet-4-6", "effort": "Unknown"}}})
        rejects({**payload, "tui_probe": {**payload["tui_probe"], "status": "available"}})
        rejects({**payload, "observation": {**payload["observation"], "writer_active": True}})
        rejects({**payload, "effort_evidence": {"source": "probe", "values": ["low"]}})
        rejects({**payload, "request": {**payload["request"], "intent_sha256": "a" * 64,
                 "request_id": "request-" + "a" * 64}})
        worker = Path(document["execution_worktree"]) / "worker.py"
        worker.write_text("changed\n", encoding="utf-8")
        rejects(payload)
        print("claude-adapter: pass (production caller, checkpoint/Git, single-writer, TUI, effort, exact session, no fork)")


if __name__ == "__main__":
    main()
