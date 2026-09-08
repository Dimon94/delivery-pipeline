#!/usr/bin/env python3
"""Codex CLI 精确 session resume adapter 的最小回归检查。"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parents[2]
GIT_REPO_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")
GIT_CONFIG_VARS = ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_SYSTEM")
REPO_ENV = os.environ.copy()
for name in GIT_REPO_VARS:
    REPO_ENV.pop(name, None)
COMMON_GIT_DIR = Path(subprocess.check_output(
    ["git", "rev-parse", "--git-common-dir"],
    cwd=REPO_ROOT, text=True, env=REPO_ENV).strip()).resolve()
COMMON_CONFIG = COMMON_GIT_DIR / "config"
INTENT = "a" * 64
SPEC = importlib.util.spec_from_file_location("codex_cli_adapter", ROOT / "codex_cli_adapter.py")
assert SPEC and SPEC.loader
ADAPTER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ADAPTER
SPEC.loader.exec_module(ADAPTER)


def rejects(**changes: object) -> None:
    request = {
        "request_id": "request-" + INTENT,
        "intent_sha256": INTENT,
        "session_id": "018f47a0-1b2c-7d3e-8f40-123456789abc",
        "worktree": "/tmp/codex-canary",
        "target_request": {"model": "gpt-5.6-luna", "effort": "max"},
        **changes,
    }
    try:
        ADAPTER.resume_request(request)
    except ADAPTER.CodexAdapterError:
        return
    raise AssertionError(f"应拒绝无效 request: {changes}")


def isolated_git_env(folder: Path) -> dict[str, str]:
    """让 fixture 的 Git 配置与共享 common config 完全隔离。"""
    env = os.environ.copy()
    for name in GIT_REPO_VARS:
        env.pop(name, None)
    env.update({
        "GIT_CONFIG_GLOBAL": str(folder / "global.config"),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_SYSTEM": os.devnull,
    })
    return env


def isolated_snapshot(worktree: Path, env: dict[str, str]) -> dict[str, object]:
    """让 checkpoint 内部 Git 读取同一隔离 config，拒绝宿主定位变量。"""
    names = (*GIT_REPO_VARS, *GIT_CONFIG_VARS)
    previous = {name: os.environ.get(name) for name in names}
    try:
        for name in GIT_REPO_VARS:
            os.environ.pop(name, None)
        for name in GIT_CONFIG_VARS:
            os.environ[name] = env[name]
        return ADAPTER.CHECKPOINT.snapshot_worktree(worktree)
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def main() -> None:
    common_config_before = COMMON_CONFIG.read_bytes()
    request = {
        "request_id": "request-" + INTENT,
        "intent_sha256": INTENT,
        "session_id": "018f47a0-1b2c-7d3e-8f40-123456789abc",
        "worktree": "/tmp/codex-canary",
        "target_request": {"model": "gpt-5.6-luna", "effort": "max"},
    }
    assert ADAPTER.resume_request(request) == {
        "agent_kind": "codex",
        "native_args": [
            "resume", "018f47a0-1b2c-7d3e-8f40-123456789abc",
            "--model", "gpt-5.6-luna",
            "-c", 'model_reasoning_effort="max"',
            "-s", "danger-full-access", "-a", "never",
            "-C", "/tmp/codex-canary", "--no-alt-screen",
        ],
        "request_id": "request-" + INTENT,
        "session_id": "018f47a0-1b2c-7d3e-8f40-123456789abc",
        "worktree": "/tmp/codex-canary",
    }
    rejects(session_id="--last")
    rejects(target_request={"model": "gpt-5.6-luna", "effort": "Unknown"})
    rejects(target_request={"model": "unknown", "effort": "max"})
    rejects(intent_sha256="b" * 64)
    with tempfile.TemporaryDirectory(prefix="codex-adapter-check-") as folder:
        folder_path = Path(folder)
        root = Path(folder) / "worktree"
        git_dir = folder_path / "gitdir"
        git_env = isolated_git_env(folder_path)
        assert not any(name in git_env for name in GIT_REPO_VARS)
        root.mkdir()
        subprocess.run(["git", "-C", str(root), "init", "-q",
                        "--separate-git-dir", str(git_dir)],
                       check=True, env=git_env)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "adapter-check"],
                       check=True, env=git_env)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "adapter-check@example.invalid"],
                       check=True, env=git_env)
        (root / "worker.py").write_text("print('first edit')\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "worker.py"], check=True, env=git_env)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "base", "--no-verify"],
                       check=True, env=git_env)
        (root / "worker.py").write_text("print('first edit')\nprint('dirty')\n", encoding="utf-8")
        snapshot = isolated_snapshot(root, git_env)
        checkpoint_path = root.parent / "registry" / "checkpoint.json"
        checkpoint_path.parent.mkdir()
        document = ADAPTER.CHECKPOINT.build_checkpoint({
            "lane_id": "probe-105",
            "work_item": "https://github.com/Dimon94/delivery-pipeline/issues/105",
            "runtime": "herdr-codex-pane",
            "session_id": "018f47a0-1b2c-7d3e-8f40-123456789abc",
            "coordinator_thread_id": "coordinator-session",
            "coordinator_host_id": "local",
            "cli_version": "codex-cli 0.153.0",
            "execution_worktree": snapshot["worktree"],
            "execution_branch": snapshot["branch"],
            "base_commit": snapshot["head"],
            "head_commit": snapshot["head"],
            "phase": "starting",
            "development_mode": "staged",
            "mode_source": "user-config",
            "phase_plan": {
                "starting": {"model": "gpt-5.6-sol", "effort": "high"},
                "execution": {"model": "gpt-5.6-luna", "effort": "max"},
                "direct": {"model": "gpt-5.6-sol", "effort": "high"},
            },
            "requested_model": "gpt-5.6-sol",
            "requested_effort": "high",
            "tool_acceptance": {"accepted": True, "status": "accepted", "source": "runtime"},
            "actual_model": "gpt-5.6-sol",
            "actual_effort": "high",
            "actual_readback_source": "turn-context",
            "actual_readback_at": "2026-09-08T00:00:00Z",
            "first_edit": ["worker.py"],
            "checks": [{"command": "python3 -m compileall worker.py", "result": "exit 0"}],
            "todo": ["continue implementation"],
            "decision": {"critical_design_unknown": False, "reason": "adapter seam"},
            "evidence": ["issue-105"],
            "checkpoint_path": str(checkpoint_path),
        }, snapshot)
        ADAPTER.CHECKPOINT.write_checkpoint(checkpoint_path, document, worktree=root)
        intent = ADAPTER.CHECKPOINT.build_continuation_intent(document)
        canonical = {
            "request_id": "request-" + intent[ADAPTER.CHECKPOINT.INTENT_FINGERPRINT_FIELD],
            "intent_sha256": intent[ADAPTER.CHECKPOINT.INTENT_FINGERPRINT_FIELD],
            "target_request": intent["target_request"],
        }
        bound = ADAPTER.resume_from_checkpoint(document, canonical)
        assert bound["session_id"] == document["session_id"]
        assert bound["checkpoint_sha256"] == document["checkpoint_sha256"]
        edited_target = {"model": "gpt-6-astra", "effort": "high"}
        edited_intent = ADAPTER.CHECKPOINT.build_continuation_intent(
            document, target_request=edited_target)
        edited_request = {
            "request_id": "request-" + edited_intent[ADAPTER.CHECKPOINT.INTENT_FINGERPRINT_FIELD],
            "intent_sha256": edited_intent[ADAPTER.CHECKPOINT.INTENT_FINGERPRINT_FIELD],
            "target_request": edited_target,
        }
        edited_bound = ADAPTER.resume_from_checkpoint(document, edited_request)
        assert edited_bound["native_args"][3:7] == ["gpt-6-astra", "-c", 'model_reasoning_effort="high"', "-s"]
        assert ADAPTER.resume_from_checkpoint(document, edited_request) == edited_bound
    assert COMMON_CONFIG.read_bytes() == common_config_before, \
        "adapter fixture 不得修改共享 common .git/config"
    print("codex-cli-adapter: pass (exact resume args, no --last, explicit model/effort)")


if __name__ == "__main__":
    main()
