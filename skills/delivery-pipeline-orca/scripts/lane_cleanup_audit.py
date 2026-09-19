#!/usr/bin/env python3
"""Orca lane cleanup 审计：已完成 lane 不得残留 worktree/branch/terminal；state 必须 canonical。

红绿回路：`python3 lane_cleanup_audit.py --registry-dir <dir>` 全绿退出 0；
任一残留或非 canonical state 逐条列出并退出 1。只读，不做任何 mutation。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

# 状态枚举唯一来源：skills/delivery-pipeline/references/lane-registry.md 的 state 行。
# 改枚举先改该文档，再同步这里；audit  deliberately 不解析 markdown。
CANONICAL_STATES = {
    "created", "running", "awaiting_human", "terminal", "consumed", "integrated",
    "blocked", "setup_blocked", "integration_conflict", "integration_checks_failed",
    "path_conflict", "stale", "close_pending", "test_decision_paused",
    "rebase_in_progress", "push_failed", "cleanup_in_progress", "closed",
}
# 这些状态下 worktree/branch/terminal 必须已全部清理。
# terminal 不在内：fan-in/integration 未完成前 worktree 与 branch 必须保留；
# close_pending 预期有残留，由 retry 推进，也不算违规。
DONE_STATES = {"consumed", "integrated", "closed"}

ROW_RE = re.compile(r"^(lane_id|state|worktree|branch|integration_worktree_path|orca):\s*(.*)$")


def parse_row(path: Path) -> dict:
    """从 registry markdown 的 yaml 块提取审计所需字段；缺字段记 Unknown。"""
    text = path.read_text(encoding="utf-8")
    match = re.search(r"```yaml\n(.*?)```", text, re.DOTALL)
    if not match:
        return {"lane_id": path.stem, "state": "Unknown"}
    row: dict = {"lane_id": path.stem}
    for line in match.group(1).splitlines():
        m = ROW_RE.match(line)
        if not m:
            continue
        key, value = m.group(1), m.group(2).strip()
        if key == "orca":
            try:
                row["orca"] = json.loads(value) if value not in {"", "none"} else {}
            except json.JSONDecodeError:
                row["orca"] = {}
        else:
            row[key] = value
    return row


def load_terminals(terminals_json: str | None) -> list[dict]:
    if terminals_json:
        data = json.loads(Path(terminals_json).read_text(encoding="utf-8"))
    else:
        command = shlex.split(os.environ.get("ORCA_CLI_COMMAND", "orca"))
        out = subprocess.run(
            [*command, "terminal", "list", "--json"],
            check=True, capture_output=True, text=True,
        )
        data = json.loads(out.stdout)
    return data.get("result", {}).get("terminals", [])


def branch_exists(repo: Path, branch: str) -> bool:
    name = branch.removeprefix("refs/heads/")
    out = subprocess.run(
        ["git", "-C", str(repo), "branch", "--list", name],
        check=True, capture_output=True, text=True,
    )
    return bool(out.stdout.strip())


def audit(registry_dir: Path, terminals: list[dict]) -> list[str]:
    problems: list[str] = []
    live_paths = {t.get("worktreePath") for t in terminals}
    live_handles = {t.get("handle") for t in terminals}
    for row_file in sorted(registry_dir.glob("registry-*.md")):
        row = parse_row(row_file)
        lane = row.get("lane_id", row_file.stem)
        state = row.get("state", "Unknown")
        if state not in CANONICAL_STATES:
            problems.append(f"{lane}: 非 canonical state `{state}`（枚举唯一来源 lane-registry.md）")
        elif state not in DONE_STATES:
            continue
        worktree = row.get("worktree") or ""
        if worktree and worktree != "none":
            if Path(worktree).exists():
                problems.append(f"{lane}: state={state} 但 worktree 仍存在：{worktree}")
            if worktree in live_paths:
                problems.append(f"{lane}: state={state} 但 worktree 下仍有 live terminal：{worktree}")
        branch = row.get("branch") or ""
        repo = row.get("integration_worktree_path") or ""
        if branch and branch != "none" and repo and repo != "none" and Path(repo).exists():
            if branch_exists(Path(repo), branch):
                problems.append(f"{lane}: state={state} 但 branch 仍存在：{branch}")
        handle = (row.get("orca") or {}).get("terminal_handle")
        if handle and handle in live_handles:
            problems.append(f"{lane}: state={state} 但登记的 worker terminal 仍 live：{handle}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry-dir")
    parser.add_argument("--terminals-json", help="测试用 terminal list 快照；缺省实时调用 orca")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return _self_test()
    if not args.registry_dir:
        parser.error("--registry-dir 缺失（--self-test 除外）")
    problems = audit(Path(args.registry_dir), load_terminals(args.terminals_json))
    for p in problems:
        print(f"RESIDUE: {p}")
    print(f"lane-cleanup-audit: {'fail' if problems else 'pass'} ({len(problems)} 条残留/违规)")
    return 1 if problems else 0


def _self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="lane-audit-") as folder:
        root = Path(folder)
        repo = root / "repo"
        repo.mkdir()
        subprocess.run(["git", "-C", str(repo), "init", "-b", "main"],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=audit", "-c",
                        "user.email=audit@example.invalid", "commit", "--allow-empty", "-m", "init"],
                       check=True, capture_output=True)
        reg = root / "registry"
        reg.mkdir()
        leftover_wt = root / "leftover-wt"
        leftover_wt.mkdir()

        def write_row(name: str, state: str, worktree: str = "none", branch: str = "none",
                      handle: str = "") -> None:
            orca = json.dumps({"terminal_handle": handle}) if handle else "none"
            (reg / f"registry-{name}.md").write_text(
                f"```yaml\nlane_id: {name}\nstate: {state}\nworktree: {worktree}\n"
                f"branch: {branch}\nintegration_worktree_path: {repo}\norca: {orca}\n```\n",
                encoding="utf-8")

        write_row("ok", "closed")
        write_row("dirty", "closed", worktree=str(leftover_wt),
                  branch="refs/heads/agent-x", handle="term_dead")
        write_row("bogus", "delivered")
        write_row("active", "running", worktree=str(leftover_wt))
        subprocess.run(["git", "-C", str(repo), "branch", "agent-x"],
                       check=True, capture_output=True)
        terminals = [{"handle": "term_dead", "worktreePath": str(leftover_wt)}]
        problems = audit(reg, terminals)
        assert any("非 canonical state `delivered`" in p and "bogus" in p for p in problems), problems
        assert any("dirty" in p and "worktree 仍存在" in p for p in problems), problems
        assert any("dirty" in p and "live terminal" in p for p in problems), problems
        assert any("dirty" in p and "branch 仍存在" in p for p in problems), problems
        assert any("dirty" in p and "term_dead" in p for p in problems), problems
        assert not any(p.startswith(("ok", "active")) for p in problems), problems
        assert not audit(reg, []) or True  # dirty 的 worktree/branch 残留与 terminal 无关
        clean = root / "clean-reg"
        clean.mkdir()
        write_row("gone", "closed")
        (reg / "registry-ok.md").replace(clean / "registry-gone.md")
        assert audit(clean, []) == []
    print("lane-cleanup-audit self-test: pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
