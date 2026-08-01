#!/usr/bin/env python3
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODEX_ROOT = ROOT / "skills" / "wayfinder-implement-orchestrator"
CLAUDE_ROOT = ROOT / "claude" / "skills" / "wayfinder-implement-orchestrator"
CODEX_SKILL = CODEX_ROOT / "SKILL.md"
CLAUDE_SKILL = CLAUDE_ROOT / "SKILL.md"

DEPENDENCIES = [
    "wayfinder",
    "grilling",
    "domain-modeling",
    "prototype",
    "research",
    "to-spec",
    "to-tickets",
    "implement",
    "code-review",
]


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def frontmatter(path: Path) -> dict[str, str]:
    match = re.match(r"^---\n(.*?)\n---\n", path.read_text(), re.DOTALL)
    if not match:
        fail(f"invalid frontmatter: {path.relative_to(ROOT)}")
    result = {}
    for line in match.group(1).splitlines():
        key, separator, value = line.partition(":")
        if not separator:
            fail(f"invalid frontmatter line: {path.relative_to(ROOT)}: {line}")
        result[key.strip()] = value.strip()
    return result


def require(path: Path, strings: tuple[str, ...]) -> None:
    content = path.read_text()
    for item in strings:
        if item not in content:
            fail(f"missing invariant in {path.relative_to(ROOT)}: {item}")


def check_references(path: Path) -> None:
    for relative in re.findall(r"`((?:references|assets)/[^`]+)`", path.read_text()):
        if not (path.parent / relative).exists():
            fail(f"missing reference from {path.relative_to(ROOT)}: {relative}")


def check_pruned_policy() -> None:
    active = [
        ROOT / "README.md",
        ROOT / "README.zh-CN.md",
        *CODEX_ROOT.rglob("*.md"),
        *CLAUDE_ROOT.rglob("*.md"),
    ]
    forbidden = (
        re.compile(r"估时"),
        re.compile(r"估档"),
        re.compile(r"不拆理由"),
        re.compile(r"\bS/M/L/XL\b"),
        re.compile(r"\bXL\s*票"),
        re.compile(r"estimate-log", re.IGNORECASE),
        re.compile(r"ticket-split-coverage", re.IGNORECASE),
        re.compile(r"split proposal", re.IGNORECASE),
        re.compile(r"五因子"),
        re.compile(r"六面普查"),
        re.compile(r"小型化跳过"),
        re.compile(r"大小适合"),
        re.compile(r"route classifier", re.IGNORECASE),
        re.compile(r"claude-native"),
        re.compile(r"herdr wait agent-status"),
        re.compile(r"herdr agent start --cwd"),
    )
    hits = []
    for path in active:
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if any(pattern.search(line) for pattern in forbidden):
                hits.append(f"{path.relative_to(ROOT)}:{lineno}:{line}")
    if hits:
        fail("removed ticket policy remains:\n" + "\n".join(hits))

    retired = (
        CODEX_ROOT / "references" / "ticket-split-coverage.md",
        CODEX_ROOT / "references" / "map-dashboard.md",
        CODEX_ROOT / "assets" / "map-dashboard-shell.html",
        CLAUDE_ROOT / "references" / "ticket-split-coverage.md",
        CLAUDE_ROOT / "references" / "map-dashboard.md",
        CLAUDE_ROOT / "assets" / "map-dashboard-shell.html",
    )
    for path in retired:
        if path.exists():
            fail(f"retired policy file restored: {path.relative_to(ROOT)}")


def main() -> None:
    manifest = json.loads((ROOT / "skill-bundle.json").read_text())
    if manifest.get("format") != "codex-claude-skill-bundle/v1":
        fail("bundle format mismatch")
    if manifest.get("name") != "wayfinder-implement-orchestrator":
        fail("bundle name mismatch")
    if manifest.get("entrypoints") != {
        "codex": "skills/wayfinder-implement-orchestrator/SKILL.md",
        "claude": "claude/skills/wayfinder-implement-orchestrator/SKILL.md",
    }:
        fail("entrypoints mismatch")
    if [item.get("name") for item in manifest.get("requires") or []] != DEPENDENCIES:
        fail("dependency order mismatch")

    codex_fm = frontmatter(CODEX_SKILL)
    claude_fm = frontmatter(CLAUDE_SKILL)
    for fm, label in ((codex_fm, "Codex"), (claude_fm, "Claude")):
        if fm.get("name") != "wayfinder-implement-orchestrator":
            fail(f"{label} skill name mismatch")
        if not fm.get("description", "").startswith("Orchestrate a loose idea"):
            fail(f"{label} description does not expose the resumable chain")
    if codex_fm.get("disable-model-invocation") != "true":
        fail("Codex skill must remain user-invoked")

    common = (
        "idea/map -> discovery -> spec -> implementation tickets",
        "/wayfinder",
        "/to-spec",
        "/to-tickets",
        "/implement",
        "maximal safe batch",
        "worktree",
        "summary PR/MR",
        "最早未完成",
    )
    require(CODEX_SKILL, common + ("fresh Codex", "Source owner projectId"))
    require(
        CLAUDE_SKILL,
        common
        + (
            "/herdr",
            "attached waiter",
        ),
    )
    for skill in (CODEX_SKILL, CLAUDE_SKILL):
        require(
            skill,
            (
                "不评估 ticket 大小",
                "`/to-tickets` 已发布的 tickets 直接作为待分配 execution graph",
                "不增加内容质量或拆票复审 gate",
            ),
        )

    for root in (CODEX_ROOT, CLAUDE_ROOT):
        require(
            root / "references" / "gate-state-machine.md",
            (
                "从任意 Issue 重建",
                "向上追踪 parent",
                "向下读取",
                "最早未完成的 gate",
                "discovery -> spec -> tickets",
                "Stage Ownership",
                "不得因 ticket 大小",
                "属于 `/to-tickets` 的产物所有权",
            ),
        )
        require(
            root / "references" / "frontier-lanes.md",
            (
                "maximal safe batch",
                "每张 implementation ticket",
                "独立 worktree",
                "不领取 sibling",
                "Terminal Fan-in",
                "ready 计算不读取 ticket 长度",
            ),
        )
        require(
            root / "references" / "lane-registry.md",
            (
                "<!-- wayfinder-lane-registry:v1 -->",
                "worktree:",
                "branch:",
                "base_commit:",
                "updated_at:",
                "Fresh-session Recovery",
                "active writer",
            ),
        )
        require(
            root / "references" / "owner-skill-resolution.md",
            (
                "user-invoked skills",
                "Owner skill name",
                "Owner skill SKILL.md",
                "Owner skill invocation label",
                "read the passed `SKILL.md` completely",
                "must not trigger a fallback workflow",
            ),
        )
        require(
            root / "assets" / "GATE_CHILD_DISPATCH_PACKET.md",
            (
                "$to-spec" if root == CODEX_ROOT else "/to-spec",
                "Parent links",
                "Owner skill SKILL.md：<absolute resolved path>",
                "不依赖 child catalog",
            ),
        )

    require(
        CODEX_ROOT / "assets" / "ISSUE_IMPLEMENT_DISPATCH_PACKET.md",
        (
            "Owner skill name：implement",
            "Owner skill SKILL.md：<absolute resolved path>",
            "不依赖 child catalog",
            "只处理这张 ticket",
            "send_message_to_thread",
        ),
    )
    require(
        CLAUDE_ROOT / "assets" / "CODEX_PANE_DISPATCH_PACKET.md",
        (
            "$implement",
            "Owner skill name：implement",
            "Owner skill SKILL.md：<absolute resolved path>",
            "不依赖 Codex pane catalog",
            "只处理这张 ticket",
            "Codex pane",
            "FINAL_REPORT_BEGIN",
            "FINAL_REPORT_END",
        ),
    )
    for packet in (
        CLAUDE_ROOT / "assets" / "GATE_CHILD_DISPATCH_PACKET.md",
        CLAUDE_ROOT / "assets" / "WAYFINDER_TICKET_DISPATCH_PACKET.md",
        CLAUDE_ROOT / "assets" / "WAYFINDER_GRILLING_DISPATCH_PACKET.md",
    ):
        require(packet, ("FINAL_REPORT_BEGIN", "FINAL_REPORT_END"))
    require(
        CLAUDE_ROOT / "references" / "lane-registry.md",
        (
            "pane_id:",
            "workspace_id:",
            "tab_id:",
            "waiter_owner:",
            "terminal_report_pending",
            "integrated -> close_pending -> closed",
        ),
    )
    require(
        CODEX_ROOT / "references" / "lane-registry.md",
        ("thread_id:", "project_id:", "runtime: codex-thread"),
    )
    require(
        CLAUDE_ROOT / "references" / "child-monitoring.md",
        (
            "/herdr",
            "FINAL_REPORT_END",
            "listener",
            "running pane 无条件通过 `/herdr` skill 挂到新 lead listener",
        ),
    )
    require(
        CODEX_ROOT / "references" / "child-monitoring.md",
        (
            "coordinator-owned `wait_threads`",
            "缺失此消息不影响 `wait_threads`",
            "用最新 cursor 继续 `wait_threads`",
        ),
    )

    check_references(CODEX_SKILL)
    check_references(CLAUDE_SKILL)
    check_pruned_policy()

    metadata = CODEX_ROOT / "agents" / "openai.yaml"
    require(
        metadata,
        (
            'display_name: "Wayfinder Implement Orchestrator"',
            'short_description: "Resume Wayfinder delivery from any issue"',
            "$wayfinder-implement-orchestrator",
            "allow_implicit_invocation: false",
        ),
    )

    install = (ROOT / "scripts" / "install.sh").read_text()
    require(
        ROOT / "scripts" / "install.sh",
        (
            "DEPENDENCIES=(wayfinder grilling domain-modeling prototype research "
            "to-spec to-tickets implement code-review)",
            'for dep in "${DEPENDENCIES[@]}"',
            "expose_codex_dependencies",
            'ln -s "$source" "$dest"',
        ),
    )

    subprocess.run(["bash", "-n", str(ROOT / "scripts" / "install.sh")], check=True)
    if not os.access(ROOT / "scripts" / "validate.py", os.X_OK):
        fail("validator must remain executable")
    print("bundle: pass")


if __name__ == "__main__":
    main()
