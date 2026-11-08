#!/usr/bin/env python3
"""Lane / map 的 Git 收尾：删 worktree 与 branch 并 readback，打印应写回 registry 的状态。

transport 释放归所属壳；本脚本只做 runtime 无关的 Git 部分，不改 registry、不 force。

用法：closeout.py lane <registry.md> [--lane-id ID] [--repo DIR] [--branch B ...]
      closeout.py map <map-registry-dir> [--remote origin] [--main main] [--delete-remote]
      closeout.py audit <registry-dir>...      # 只读；有残留退出 1
      closeout.py self-test

输出首行：`CLOSEOUT <id> closed` 或 `CLOSEOUT <id> close_pending: <原因>`（退出 1）。
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

MARKER = "<!-- wayfinder-lane-registry:v2 -->"
KEY_RE = re.compile(r"^([a-z_]+):\s*(.*)$")
CLEANABLE = {"integrated", "consumed", "cleanup_in_progress", "close_pending", "closed"}
DONE = {"integrated", "consumed", "closed"}
HELD = {"blocked", "superseded", "stale", "path_conflict", "integration_conflict",
        "integration_checks_failed", "close_pending", "setup_blocked"}


# ---------- registry ----------

def parse_rows(path: Path) -> list[dict]:
    """每个 marker 后的连续 `key: value` 行为一行；兼容带/不带 ```yaml 围栏。"""
    rows, lines = [], path.read_text(encoding="utf-8", errors="replace").splitlines()
    i = 0
    while i < len(lines):
        if lines[i].strip() != MARKER:
            i += 1
            continue
        i += 1
        row: dict = {"_file": str(path)}
        started = False
        while i < len(lines):
            line = lines[i]
            if line.startswith("```"):
                if started:
                    break
                i += 1
                continue
            if line.strip() == MARKER:
                break
            m = KEY_RE.match(line)
            if m:
                started = True
                v = m.group(2).strip().strip('"')
                row[m.group(1)] = None if v in ("", "none") else v
            elif started and not line.strip():
                break
            i += 1
        if row.get("lane_id") and "<" not in (row.get("work_item") or ""):
            rows.append(row)
    return rows


def registry_files(d: Path) -> list[Path]:
    files = [p for p in d.iterdir() if p.is_file() and p.suffix == ".md"
             and (p.name.startswith("registry") or p.name == "lane-registry.md")]
    return sorted(files, key=lambda p: p.stat().st_mtime)


def latest_rows(d: Path) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for f in registry_files(d):
        for row in parse_rows(f):
            latest[row["lane_id"]] = row
    return latest


# ---------- git ----------

# hook 等调用方继承的 GIT_DIR/GIT_INDEX_FILE 会把命令指向别的仓，一律剥掉。
ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}

def git(repo: str, *args: str, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(["git", f"--git-dir={repo}", *args], text=True,
                          capture_output=True, check=check, env=ENV)


def common_dir(path: str | None) -> str | None:
    if not path or not Path(path).is_dir():
        return None
    r = subprocess.run(["git", "-C", path, "rev-parse", "--path-format=absolute",
                        "--git-common-dir"], text=True, capture_output=True, env=ENV)
    return r.stdout.strip() if r.returncode == 0 else None


def worktrees(repo: str) -> dict[str, str | None]:
    """path -> branch（refs/heads/ 已去掉；detached 为 None）。"""
    out, cur = {}, None
    for line in git(repo, "worktree", "list", "--porcelain").stdout.splitlines():
        if line.startswith("worktree "):
            cur = os.path.realpath(line[9:])
            out[cur] = None
        elif line.startswith("branch ") and cur:
            out[cur] = line[7:].removeprefix("refs/heads/")
    return out


def branch_exists(repo: str, branch: str) -> bool:
    return git(repo, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}").returncode == 0


def remove_worktree(repo: str, path: str | None) -> str | None:
    """返回失败原因；成功或本就不存在返回 None。"""
    if not path:
        return None
    real = os.path.realpath(path)
    if real not in worktrees(repo):
        return None
    if not Path(real).is_dir():
        git(repo, "worktree", "prune")
        return None if real not in worktrees(repo) else f"worktree 登记无法 prune: {path}"
    dirty = subprocess.run(["git", "-C", real, "status", "--porcelain"], text=True,
                           capture_output=True, env=ENV).stdout.strip()
    if dirty:
        return f"worktree dirty: {path}"
    r = git(repo, "worktree", "remove", real)
    return None if r.returncode == 0 else f"worktree remove 失败: {r.stderr.strip()}"


def delete_branch(repo: str, branch: str | None) -> str | None:
    if not branch or not branch_exists(repo, branch):
        return None
    holders = [p for p, b in worktrees(repo).items() if b == branch]
    if holders:
        return f"branch {branch} 仍被 worktree 检出: {holders[0]}"
    r = git(repo, "branch", "-D", branch)
    return None if r.returncode == 0 else f"branch -D 失败: {r.stderr.strip()}"


def readback(repo: str, path: str | None, branches: list[str]) -> str | None:
    if path and os.path.realpath(path) in worktrees(repo):
        return f"readback: worktree 仍登记 {path}"
    left = [b for b in branches if b and branch_exists(repo, b)]
    return f"readback: branch 仍存在 {', '.join(left)}" if left else None


def report(ident: str, reason: str | None, notes: list[str] = ()) -> int:
    print(f"CLOSEOUT {ident} " + (f"close_pending: {reason}" if reason else "closed"))
    for n in notes:
        print(f"  note: {n}")
    return 1 if reason else 0


def map_row(rows: dict[str, dict]) -> dict | None:
    maps = [r for r in rows.values() if r.get("role") == "map"]
    return maps[-1] if maps else None


def claimed(rows: dict[str, dict], skip: dict | None = None) -> tuple[set[str], set[str]]:
    """Integration 坐标与未结束 lane 占用的 worktree/branch；它们不归单条已完成 lane 删除。"""
    paths, branches = set(), set()
    for r in rows.values():
        if r is skip:
            continue
        if r.get("integration_worktree_path"):
            paths.add(os.path.realpath(r["integration_worktree_path"]))
        if r.get("integration_branch"):
            branches.add(r["integration_branch"])
        if r.get("state") not in DONE or r.get("output_mode") == "integration":
            if r.get("worktree") and r.get("role") != "map":
                paths.add(os.path.realpath(r["worktree"]))
            if r.get("branch") and r.get("role") != "map":
                branches.add(r["branch"])
    return paths, branches | {"main", "master"}


def resolve_repo(explicit: str | None, *paths: str | None) -> str | None:
    if explicit:
        return common_dir(explicit)
    for p in paths:
        c = common_dir(p)
        if c:
            return c
    return None


# ---------- commands ----------

def cmd_lane(a) -> int:
    path = Path(a.registry)
    rows = [r for r in parse_rows(path) if not a.lane_id or r["lane_id"] == a.lane_id]
    ids = {r["lane_id"] for r in rows}
    if len(ids) != 1:
        return report(a.lane_id or path.name, f"registry 需唯一 lane，实得 {sorted(ids) or '无'}")
    row = rows[-1]
    ident, state, stage = row["lane_id"], row.get("state"), row.get("release_stage")
    if stage and stage != "deployed":
        return report(ident, f"独立票模式 release_stage={stage}，deployed 前只释放 transport")
    if state not in CLEANABLE and not (state == "terminal" and stage == "deployed"):
        return report(ident, f"state={state} 不可 cleanup")
    if row.get("output_mode") == "integration":
        return report(ident, None, ["merger lane 共用 Map Integration Worktree，由 map closeout 删除"])
    peers = latest_rows(path.parent)
    peers[ident] = row
    m = map_row(peers) or {}
    repo = resolve_repo(a.repo, row.get("worktree"), row.get("integration_worktree_path"),
                        m.get("integration_worktree_path"), m.get("worktree"))
    if not repo:
        return report(ident, "无法定位 repo；传 --repo")
    branches = [b for b in [row.get("branch"), *a.branch] if b]
    held_paths, held_branches = claimed(peers, skip=row)
    if row.get("integration_worktree_path"):
        held_paths.add(os.path.realpath(row["integration_worktree_path"]))
    if held_branches & set(branches):
        return report(ident, f"branch 被 Integration 或未结束 lane 占用: {sorted(held_branches & set(branches))}")
    if row.get("worktree") and os.path.realpath(row["worktree"]) in held_paths:
        return report(ident, None, ["worktree 被 Integration 或未结束 lane 占用，本 lane 不删"])
    reason = remove_worktree(repo, row.get("worktree"))
    for b in branches:
        reason = reason or delete_branch(repo, b)
    return report(ident, reason or readback(repo, row.get("worktree"), branches))


def merged(repo: str, branch: str, target: str) -> bool:
    if git(repo, "merge-base", "--is-ancestor", branch, target).returncode == 0:
        return True
    tree = git(repo, "merge-tree", "--write-tree", target, branch)
    target_tree = git(repo, "rev-parse", f"{target}^{{tree}}").stdout.strip()
    return tree.returncode == 0 and tree.stdout.split()[0] == target_tree  # squash/rebase 合入


def cmd_map(a) -> int:
    d = Path(a.registry_dir)
    rows = latest_rows(d)
    m = map_row(rows)
    if not m:
        return report(d.name, "目录内无 role: map 行")
    ident, notes = m["lane_id"], []
    open_lanes = [f"{k}={r.get('state')}" for k, r in rows.items()
                  if r is not m and r.get("state") not in ("closed", "superseded")]
    if open_lanes:
        return report(ident, f"lane 未 closed: {', '.join(open_lanes)}")
    notes += [f"superseded 保留: {k} {r.get('worktree')}" for k, r in rows.items()
              if r.get("state") == "superseded" and r.get("worktree")]
    path, branch = m.get("integration_worktree_path"), m.get("integration_branch")
    if not branch:
        return report(ident, None, notes + ["无 Integration branch（独立票模式），无需删除"])
    repo = resolve_repo(a.repo, path, m.get("worktree"))
    if not repo:
        return report(ident, "无法定位 repo；传 --repo")
    if branch_exists(repo, branch):
        fetch = git(repo, "fetch", a.remote, a.main)
        target = f"{a.remote}/{a.main}"
        if fetch.returncode != 0:
            return report(ident, f"fetch 失败: {fetch.stderr.strip()}")
        if not merged(repo, branch, target):
            return report(ident, f"{branch} 尚未合入 {target}")
    reason = remove_worktree(repo, path) or delete_branch(repo, branch)
    reason = reason or readback(repo, path, [branch])
    remote_ref = git(repo, "ls-remote", "--heads", a.remote, branch).stdout.strip()
    if not reason and remote_ref:
        if a.delete_remote:
            r = git(repo, "push", a.remote, "--delete", branch)
            if r.returncode != 0:
                reason = f"远端删除失败: {r.stderr.strip()}"
        else:
            notes.append(f"远端 {a.remote}/{branch} 保留；获 remote authority 后加 --delete-remote")
    return report(ident, reason, notes)


def cmd_audit(a) -> int:
    dirs: list[Path] = []
    for raw in a.registry_dir:
        p = Path(raw)
        dirs += [p] if registry_files(p) else [c for c in sorted(p.iterdir())
                                                 if c.is_dir() and registry_files(c)]
    residue = held = 0
    for d in dirs:
        rows = latest_rows(d)
        m = map_row(rows) or {}
        held_paths, held_branches = claimed(rows)
        for k, r in rows.items():
            state, stage = r.get("state"), r.get("release_stage")
            repo = resolve_repo(None, r.get("worktree"), r.get("integration_worktree_path"),
                                m.get("integration_worktree_path"), m.get("worktree"))
            if r is m:
                targets = [(m.get("integration_worktree_path"), m.get("integration_branch"))] \
                    if state == "closed" else []
            elif r.get("output_mode") == "integration":
                continue
            elif state in DONE and not (stage and stage != "deployed"):
                wt = r.get("worktree")
                targets = [(None if wt and os.path.realpath(wt) in held_paths else wt, r.get("branch"))]
            else:
                if state in HELD and r.get("worktree") and Path(r["worktree"]).is_dir():
                    held += 1
                    print(f"HELD {d.name}/{k} {state} {r['worktree']}")
                continue
            for wt, br in targets:
                if wt and Path(wt).is_dir() and (not repo or os.path.realpath(wt) in worktrees(repo)):
                    residue += 1
                    print(f"RESIDUE {d.name}/{k} {state} worktree {wt}")
                if br and repo:
                    side = git(repo, "for-each-ref", "--format=%(refname:short)",
                               f"refs/heads/{br}", f"refs/heads/{br}-*").stdout.split()
                    for b in side:
                        if b in held_branches and r is not m:
                            continue
                        residue += 1
                        print(f"RESIDUE {d.name}/{k} {state} branch {b}")
    print(f"AUDIT {'fail' if residue else 'pass'} residue={residue} held={held}")
    return 1 if residue else 0


# ---------- self-test ----------

def self_test() -> int:
    def sh(cwd, *args):
        subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True, env=ENV)

    def row(**kv):
        return MARKER + "\n```yaml\n" + "".join(f"{k}: {v}\n" for k, v in kv.items()) + "```\n"

    def run(*args):
        r = subprocess.run([sys.executable, __file__, *args], text=True, capture_output=True, env=ENV)
        return r.returncode, r.stdout

    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        env_git = ["git", "-c", "user.email=t@t", "-c", "user.name=t"]
        sh(t, "git", "init", "-q", "--bare", "remote.git")
        sh(t, "git", "clone", "-q", "remote.git", "src")
        src = t / "src"
        sh(src, "git", "checkout", "-q", "-b", "main")
        sh(src, *env_git, "commit", "-q", "--allow-empty", "-m", "base")
        sh(src, "git", "push", "-q", "-u", "origin", "main")
        integ, lane, dirty = t / "integ", t / "lane", t / "dirty"
        sh(src, "git", "worktree", "add", "-q", "-b", "feature/map-1", str(integ))
        sh(src, "git", "worktree", "add", "-q", "-b", "pi/issue-2", str(lane))
        sh(src, "git", "branch", "pi/issue-2-before-rebase")
        sh(src, "git", "worktree", "add", "-q", "-b", "pi/issue-3", str(dirty))
        (dirty / "x").write_text("x")
        reg = t / "reg"
        reg.mkdir()
        (reg / "registry-map.md").write_text(row(lane_id="map-1", role="map", state="running",
            work_item="u", integration_worktree_path=integ, integration_branch="feature/map-1"))
        (reg / "registry-2.md").write_text(row(lane_id="l2", role="backend", state="integrated",
            work_item="u", worktree=lane, branch="pi/issue-2"))
        (reg / "registry-3.md").write_text(row(lane_id="l3", role="backend", state="integrated",
            work_item="u", worktree=dirty, branch="pi/issue-3"))
        (reg / "registry-4.md").write_text(row(lane_id="l4", role="backend", state="terminal",
            work_item="u", worktree="none", branch="pi/issue-4", release_stage="merged"))
        (reg / "registry-m.md").write_text(row(lane_id="merger", role="backend", state="closed",
            output_mode="integration", work_item="u", worktree=integ, branch="feature/map-1"))
        checks = []
        code, out = run("lane", str(reg / "registry-m.md"))
        checks.append(("merger lane 不删 Integration", code == 0 and integ.exists()))
        code, out = run("audit", str(reg))
        checks.append(("audit 红: done lane 残留树+侧分支", code == 1 and "pi/issue-2-before-rebase" in out))
        code, out = run("lane", str(reg / "registry-2.md"), "--branch", "pi/issue-2-before-rebase")
        checks.append(("lane 清理 closed", code == 0 and "l2 closed" in out and not lane.exists()))
        code, out = run("lane", str(reg / "registry-3.md"))
        checks.append(("dirty fail closed", code == 1 and "dirty" in out and dirty.exists()))
        code, out = run("lane", str(reg / "registry-4.md"))
        checks.append(("release_stage 未 deployed 拒绝", code == 1 and "release_stage" in out))
        code, out = run("lane", str(reg / "registry-2.md"), "--branch", "feature/map-1")
        checks.append(("拒删 Integration branch", code == 1 and "占用" in out))
        code, out = run("map", str(reg))
        checks.append(("map: lane 未 closed 拒绝", code == 1 and "未 closed" in out))
        sh(src, "git", "worktree", "remove", "--force", str(dirty))
        sh(src, "git", "branch", "-D", "pi/issue-3")
        for n in ("2", "3"):
            p = reg / f"registry-{n}.md"
            p.write_text(p.read_text().replace("state: integrated", "state: closed"))
        (reg / "registry-4.md").unlink()
        (integ / "f").write_text("f")
        sh(integ, "git", "add", "f")
        sh(integ, *env_git, "commit", "-q", "-m", "feat")
        sh(integ, "git", "push", "-q", "origin", "feature/map-1")
        code, out = run("map", str(reg))
        checks.append(("map: 未合入拒绝", code == 1 and "尚未合入" in out and integ.exists()))
        sh(src, "git", "merge", "-q", "--squash", "feature/map-1")
        sh(src, *env_git, "commit", "-q", "-m", "squash")
        sh(src, "git", "push", "-q", "origin", "main")
        code, out = run("map", str(reg))
        checks.append(("map: squash 合入后 closed 且提示远端", code == 0 and "map-1 closed" in out
                       and "--delete-remote" in out and not integ.exists()))
        code, out = run("map", str(reg), "--delete-remote", "--repo", str(src))
        gone = not subprocess.run(["git", "ls-remote", "--heads", "origin", "feature/map-1"],
                                  cwd=src, text=True, capture_output=True, env=ENV).stdout.strip()
        checks.append(("map: 重入幂等并删远端", code == 0 and gone))
        p = reg / "registry-map.md"
        p.write_text(p.read_text().replace("state: running", "state: closed"))
        code, out = run("audit", str(reg))
        checks.append(("audit 绿", code == 0 and "AUDIT pass" in out))
    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("PASS " if ok else "FAIL ") + name)
    return 1 if bad else 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("lane")
    s.add_argument("registry")
    s.add_argument("--lane-id")
    s.add_argument("--repo")
    s.add_argument("--branch", action="append", default=[], help="壳登记的额外 branch，可重复")
    s = sub.add_parser("map")
    s.add_argument("registry_dir")
    s.add_argument("--repo")
    s.add_argument("--remote", default="origin")
    s.add_argument("--main", default="main")
    s.add_argument("--delete-remote", action="store_true")
    s = sub.add_parser("audit")
    s.add_argument("registry_dir", nargs="+")
    sub.add_parser("self-test")
    a = p.parse_args()
    return {"lane": cmd_lane, "map": cmd_map, "audit": cmd_audit,
            "self-test": lambda _: self_test()}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
