#!/usr/bin/env python3
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODEX_ROOT = ROOT / "skills" / "delivery-pipeline"
CLAUDE_ROOT = ROOT / "claude" / "skills" / "delivery-pipeline"
CODEX_SKILL = CODEX_ROOT / "SKILL.md"
CLAUDE_SKILL = CLAUDE_ROOT / "SKILL.md"
PANE_DISPATCH_CLAUDE = ROOT / "claude" / "skills" / "pane-dispatch"
CODEX_DISPATCH_ROUTING = CODEX_ROOT / "references" / "dispatch-runtime-routing.md"
RUNTIME_DISPATCH_ADR = ROOT / "docs" / "adr" / "0002-runtime-aware-dispatch.md"

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
    "resolving-merge-conflicts",
    "herdr",
]


ERRORS: list[str] = []


def record(message: str) -> None:
    """Collect a violation instead of aborting, so one run reports every failure.

    Fail-fast hid the true blast radius of 2238745: eight broken invariants
    across both trees surfaced as a single error line.
    """
    ERRORS.append(message)


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
    """Assert each string appears in `path`, ignoring how prose is line-wrapped.

    Whitespace is collapsed on both sides so an invariant that happens to straddle
    a line break still matches. Wrapping carries no meaning in these documents, and
    a red light nobody believes is how 2238745 shipped.
    """
    content = " ".join(path.read_text().split())
    for item in strings:
        if " ".join(item.split()) not in content:
            record(f"missing invariant in {path.relative_to(ROOT)}: {item}")


def skill_ref(tree: Path, name: str) -> str:
    """Return the skill invocation form that `tree` must use.

    Codex resolves skills as `$name`; Claude Code resolves the plugin-namespaced
    `/mattpocock-skills:name`. Asserting the sigil rather than the bare name also
    removes a false positive: bare `/wayfinder` matched the substring inside
    `references/wayfinder-frontier-loop.md`, so that invariant never tested
    anything.
    """
    return f"${name}" if tree == CODEX_ROOT else f"/mattpocock-skills:{name}"




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


def check_runtime_boundaries() -> None:
    """Codex-side files must not carry Claude Code plugin locators.

    `/mattpocock-skills:<name>` only resolves inside Claude Code, where the plugin
    supplies the skill. A Codex pane fed that string has nothing to resolve it against,
    so it belongs to the Claude tree only. Owners reach Codex through the three-field
    dispatch contract in references/owner-skill-resolution.md instead.
    """
    locator = re.compile(r"/mattpocock-skills:")
    for path in sorted(CODEX_ROOT.rglob("*.md")):
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if locator.search(line):
                record(
                    "Claude plugin locator in Codex tree (only resolves in Claude "
                    "Code; pass owners as absolute SKILL.md paths instead): "
                    f"{path.relative_to(ROOT)}:{lineno}:{line.strip()}"
                )


def check_owner_dispatch_contract() -> None:
    """Every dispatch packet must carry the full three-field owner contract.

    The contract exists in references/owner-skill-resolution.md, but a packet that
    omits the fields lets a child start a stage without a resolved owner. Assert the
    fields on all packets in both trees, not just the ones that happened to be covered.
    """
    for root in (CODEX_ROOT, CLAUDE_ROOT):
        for packet in sorted((root / "assets").glob("*DISPATCH_PACKET.md")):
            require(
                packet,
                (
                    "Owner skill name",
                    "Owner skill SKILL.md：<absolute resolved path>",
                    "Owner skill invocation label",
                    "先完整读取 Owner skill SKILL.md，回报 frontmatter name 与 resolved path",
                ),
            )
        require(
            root / "references" / "owner-skill-resolution.md",
            (
                # Line-wrapped in the source; match only up to the wrap point.
                "Missing or mismatched owner path blocks that",
                "do not silently replace its contract with generic behavior",
            ),
        )


def check_dispatch_runtime_routing() -> None:
    """Use Codex App threads when present and Herdr for CLI panes.

    The dispatch invariant spans the entrypoint, operational reference, registry,
    and domain model. Checking all four prevents an apparently-correct router from
    handing execution to stale pane-only recovery or cleanup prose later in the run.
    """
    require(
        CODEX_SKILL,
        (
            "调度运行时",
            "`references/dispatch-runtime-routing.md`",
            "`codex-thread`",
            "`herdr-codex-pane`",
            "`herdr-claude-pane`",
        ),
    )
    if not CODEX_DISPATCH_ROUTING.exists():
        record(
            "missing Codex dispatch runtime owner: "
            f"{CODEX_DISPATCH_ROUTING.relative_to(ROOT)}"
        )
    else:
        require(
            CODEX_DISPATCH_ROUTING,
            (
                "显式指令优先",
                "Codex App 原生调度",
                "Codex CLI 原生 thread 能力是 Unknown",
                "list_projects",
                "create_thread",
                "list_threads",
                "read_thread",
                "wait_threads",
                "send_message_to_thread",
                "startingState",
                "clientThreadId",
                "runtime: codex-thread",
                "runtime: herdr-codex-pane",
                "runtime: herdr-claude-pane",
                "$herdr",
                "active writer",
            ),
        )
    require(
        CODEX_ROOT / "references" / "frontier-lanes.md",
        (
            "调度运行时",
            "ticket domain 不改写调度运行时",
            "codex-thread",
            "herdr-codex-pane",
            "herdr-claude-pane",
        ),
    )
    require(
        CODEX_ROOT / "references" / "lane-registry.md",
        (
            "runtime: subagent | codex-thread | herdr-codex-pane | herdr-claude-pane | orchestrator",
            "coordinator_runtime:",
            "dispatch_runtime:",
            "host_id:",
        ),
    )
    require(
        CLAUDE_SKILL,
        (
            "Coordinator Runtime",
            "`references/dispatch-runtime-routing.md`",
            "`coordinator_runtime: claude-cli`",
            "`dispatch_runtime: herdr`",
        ),
    )
    require(
        CLAUDE_ROOT / "references" / "dispatch-runtime-routing.md",
        (
            "coordinator_runtime: claude-cli",
            "dispatch_runtime: herdr",
            "herdr-codex-pane",
            "herdr-claude-pane",
            "/pane-dispatch",
            "active writer",
        ),
    )
    require(
        CLAUDE_ROOT / "references" / "lane-registry.md",
        (
            "coordinator_runtime: claude-cli",
            "dispatch_runtime: herdr",
        ),
    )
    require(
        ROOT / "CONTEXT.md",
        (
            "调度运行时",
            "Codex App 原生 Dispatch",
            "Herdr Dispatch",
        ),
    )
    require(
        ROOT / "README.zh-CN.md",
        (
            "Codex App 原生 task/worktree",
            "Herdr/Codex CLI",
        ),
    )
    if not RUNTIME_DISPATCH_ADR.exists():
        record(f"missing runtime dispatch ADR: {RUNTIME_DISPATCH_ADR.relative_to(ROOT)}")
    else:
        require(
            RUNTIME_DISPATCH_ADR,
            (
                "Status:** Accepted",
                "Codex App",
                "Herdr",
                "ADR-0001",
            ),
        )


def main() -> None:
    manifest = json.loads((ROOT / "skill-bundle.json").read_text())
    if manifest.get("format") != "codex-claude-skill-bundle/v1":
        fail("bundle format mismatch")
    if manifest.get("name") != "delivery-pipeline":
        fail("bundle name mismatch")
    if manifest.get("entrypoints") != {
        "codex": "skills/delivery-pipeline/SKILL.md",
        "claude": "claude/skills/delivery-pipeline/SKILL.md",
    }:
        fail("entrypoints mismatch")
    if [item.get("name") for item in manifest.get("requires") or []] != DEPENDENCIES:
        fail("dependency order mismatch")

    codex_fm = frontmatter(CODEX_SKILL)
    claude_fm = frontmatter(CLAUDE_SKILL)
    for fm, label in ((codex_fm, "Codex"), (claude_fm, "Claude")):
        if fm.get("name") != "delivery-pipeline":
            fail(f"{label} skill name mismatch")
        if not fm.get("description", "").startswith("Orchestrate a loose idea"):
            fail(f"{label} description does not expose the resumable chain")
    if codex_fm.get("disable-model-invocation") != "true":
        fail("Codex skill must remain user-invoked")

    common = (
        "idea/map -> discovery -> spec -> implementation tickets",
        "maximal safe batch",
        "worktree",
        "summary PR/MR",
        "最早未完成",
    )
    # Stage owners are spelled differently per runtime: Codex resolves `$name`, Claude Code
    # resolves the plugin locator. See skill_ref, check_runtime_boundaries and
    # owner-skill-resolution.md.
    stage_owners = ("wayfinder", "to-spec", "to-tickets", "implement")
    require(
        CODEX_SKILL,
        common
        + tuple(skill_ref(CODEX_ROOT, name) for name in stage_owners)
        + ("fresh Codex", "Source owner projectId"),
    )
    require(
        CLAUDE_SKILL,
        common
        + tuple(skill_ref(CLAUDE_ROOT, name) for name in stage_owners)
        + (
            "/pane-dispatch",
            "attached waiter",
        ),
    )
    for root, skill in ((CODEX_ROOT, CODEX_SKILL), (CLAUDE_ROOT, CLAUDE_SKILL)):
        require(
            skill,
            (
                "不评估 ticket 大小",
                f"`{skill_ref(root, 'to-tickets')}` 已发布的 tickets 直接作为待分配 "
                "execution graph",
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
                f"属于 `{skill_ref(root, 'to-tickets')}` 的产物所有权",
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
        ("thread_id:", "project_id:", "runtime: subagent | codex-thread"),
    )
    require(
        CLAUDE_ROOT / "references" / "child-monitoring.md",
        (
            "/pane-dispatch",
            "FINAL_REPORT_END",
            "listener",
            "running pane 无条件通过 `/pane-dispatch` skill 挂到新 lead listener",
        ),
    )
    require(
        CODEX_ROOT / "references" / "child-monitoring.md",
        (
            "Agent` tool",
            "run_in_background: true",
            "FINAL_REPORT_BEGIN",
        ),
    )

    check_references(CODEX_SKILL)
    check_references(CLAUDE_SKILL)
    check_pruned_policy()
    check_runtime_boundaries()
    check_owner_dispatch_contract()
    check_dispatch_runtime_routing()

    metadata = CODEX_ROOT / "agents" / "openai.yaml"
    require(
        metadata,
        (
            'display_name: "Delivery Pipeline"',
            'short_description: "Resume Wayfinder delivery from any issue"',
            "$delivery-pipeline",
            "allow_implicit_invocation: false",
        ),
    )

    install = (ROOT / "scripts" / "install.sh").read_text()
    require(
        ROOT / "scripts" / "install.sh",
        # Owners reach workers as dispatcher-resolved absolute paths (03), so
        # install.sh carries no dependency gate; only the symlink-install
        # mechanics themselves remain invariant here.
        ('ln -s "$source" "$dest"',),
    )

    subprocess.run(["bash", "-n", str(ROOT / "scripts" / "install.sh")], check=True)
    if not os.access(ROOT / "scripts" / "validate.py", os.X_OK):
        record("validator must remain executable")

    # Check pane-dispatch skill (Claude-only)
    pane_dispatch_skill = PANE_DISPATCH_CLAUDE / "SKILL.md"
    if not pane_dispatch_skill.exists():
        fail("pane-dispatch skill missing in Claude tree")

    pane_dispatch_fm = frontmatter(pane_dispatch_skill)
    if pane_dispatch_fm.get("name") != "pane-dispatch":
        fail("pane-dispatch skill name mismatch")
    if pane_dispatch_fm.get("disable-model-invocation") != "true":
        fail("pane-dispatch must have disable-model-invocation: true")

    check_references(pane_dispatch_skill)

    # Scan pane-dispatch for pruned policy violations
    pane_dispatch_files = list(PANE_DISPATCH_CLAUDE.rglob("*.md"))
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
    for path in pane_dispatch_files:
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if any(pattern.search(line) for pattern in forbidden):
                hits.append(f"{path.relative_to(ROOT)}:{lineno}:{line}")
    if hits:
        fail("pane-dispatch contains pruned policy violations:\n" + "\n".join(hits))

    if ERRORS:
        fail(
            f"{len(ERRORS)} violation(s):\n"
            + "\n".join(f"  - {item}" for item in ERRORS)
        )
    print("bundle: pass")


if __name__ == "__main__":
    main()
