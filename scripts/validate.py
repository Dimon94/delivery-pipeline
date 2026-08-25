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
TASK_COORDINATE_TITLE = CODEX_ROOT / "references" / "task-coordinate-title.md"
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


def check_pane_lifecycle_single_source() -> None:
    """Each tree defines pane lifecycle rules in exactly one reference.

    投递机制、落点验证、lifecycle 配对和 listener 挂载前提只能在
    pane-lifecycle-rules.md 中出现完整命令块；其他文件以指针引用，
    不再内联。防止 6857f83 式的双端人工对齐漂移。
    """
    # Command blocks that define the pane lifecycle.  If any file other than
    # the reference contains one of these as an executable command, it's a
    # duplicated inline block.  We match the command prefix followed by
    # whitespace/newline to avoid matching prose mentions in backticks.
    lifecycle_commands = (
        'herdr agent prompt "$agent_name" "完整读取',
        "--wait --until working --timeout 15000",
    )

    for tree_name, tree_root, reference_path in (
        (
            "Claude",
            PANE_DISPATCH_CLAUDE,
            PANE_DISPATCH_CLAUDE / "references" / "pane-lifecycle-rules.md",
        ),
        (
            "Codex",
            CODEX_ROOT,
            CODEX_ROOT / "references" / "pane-lifecycle-rules.md",
        ),
    ):
        if not reference_path.exists():
            record(
                f"missing pane lifecycle reference in {tree_name} tree: "
                f"{reference_path.relative_to(ROOT)}"
            )
            continue

        for path in sorted(tree_root.rglob("*.md")):
            if path == reference_path:
                continue
            content = " ".join(path.read_text().split())
            for cmd in lifecycle_commands:
                if cmd in content:
                    record(
                        f"{tree_name} tree: {path.relative_to(ROOT)} contains "
                        f"inline lifecycle command '{cmd}' (should only be in "
                        f"pane-lifecycle-rules.md)"
                    )
                    break


def pane_dispatch_files() -> list[Path]:
    """Every file that carries the pane dispatch sequence, in both trees."""
    return [
        PANE_DISPATCH_CLAUDE / "SKILL.md",
        PANE_DISPATCH_CLAUDE / "references" / "pane-lifecycle-rules.md",
        PANE_DISPATCH_CLAUDE / "references" / "pane-placement-rules.md",
        CODEX_ROOT / "references" / "pane-lifecycle-rules.md",
    ]


def check_batch_dispatch_concurrency() -> None:
    """Both trees must state one batch concurrency semantics.

    The serial unit is the batch-level workspace/tab resolution prerequisite,
    not the pane: after it completes, same-batch panes create/start/deliver
    concurrently, working confirmation runs once as an aggregate parallel wait
    at batch end, and serial fan-in stays at Integration. Prevents the drift
    where the routing doc promised batch concurrency while pane-dispatch
    demanded pane-by-pane serial dispatch.
    """
    for path in (
        CODEX_ROOT / "references" / "frontier-lanes.md",
        CLAUDE_ROOT / "references" / "frontier-lanes.md",
    ):
        require(
            path,
            (
                "无前序依赖的 ready tickets 同批并发派发",
                "普通 repo 文件路径重叠只进入 Integration 冲突检测",
                "整批 Dispatch Handoff",
            ),
        )
    for path in (
        PANE_DISPATCH_CLAUDE / "SKILL.md",
        PANE_DISPATCH_CLAUDE / "references" / "pane-placement-rules.md",
    ):
        require(
            path,
            (
                "workspace 解析是批级唯一串行前置",
                "并发发出",
                "聚合 working 确认",
                "聚合 readback",
            ),
        )
        content = " ".join(path.read_text().split())
        if "每个 pane 必须走完这个序列才能开始下一个" in content:
            record(
                f"{path.relative_to(ROOT)} still requires pane-by-pane serial "
                "dispatch; the serial unit is the batch-level workspace "
                "prerequisite, not the pane"
            )


def check_atomic_dispatch_sequence() -> None:
    """Bookkeeping must overlap agent cold start; listener stays anchored last.

    The reordered per-pane sequence is: pane create/split -> placement verification
    (only needs the pane to exist) -> agent start -> non-blocking packet delivery
    -> rename + tab label sync (runs during cold start) -> working confirmation
    -> listener mount. Delivery no longer inlines `--wait --until working`; that
    wait moved behind the bookkeeping as one confirmation step.
    """
    for path in pane_dispatch_files():
        content = " ".join(path.read_text().split())
        if '--wait --until working --timeout 15000' in content:
            record(
                f"{path.relative_to(ROOT)} still delivers the packet with an "
                "inline blocking `--wait --until working`; delivery must not "
                "block on cold start (working confirmation is a later unified step)"
            )
        if "投递不阻塞" not in content:
            record(
                f"{path.relative_to(ROOT)} is missing the non-blocking delivery "
                "invariant '投递不阻塞'"
            )
        if "Working 确认" not in content:
            record(
                f"{path.relative_to(ROOT)} is missing the unified working "
                "confirmation step 'Working 确认'"
            )

    skill_text = " ".join((PANE_DISPATCH_CLAUDE / "SKILL.md").read_text().split())
    sequence = (
        "**批级前置（唯一串行段）**",
        "**并发段 A**",
        "**并发段 B**",
        "**记账段**",
        "**聚合 working 确认**",
        "**Listener + 聚合 readback**",
    )
    positions = [skill_text.find(item) for item in sequence]
    if -1 in positions or positions != sorted(positions):
        record(
            "pane-dispatch SKILL.md batch pipeline order violated; expected "
            "批级前置 -> 并发段 A（create/split + 落点验证） -> 并发段 B（agent start + 投递） -> "
            f"记账段（rename + tab label） -> 聚合 working 确认 -> listener + 聚合 readback, "
            f"got positions {positions}"
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
            "按当前 gate 渐进加载 references",
            "同一 coordinator task 不因下一 lane 重读未变化的共享合同",
            "`references/dispatch-runtime-routing.md`",
            "`codex-thread`",
            "`herdr-codex-pane`",
            "`herdr-claude-pane`",
            "Task Coordinate Title",
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
                "set_thread_title",
                "set_thread_archived",
                "list_archived_threads",
                "thread_archived: false",
                "task-coordinate-title.md",
                "startingState",
                "clientThreadId",
                "runtime: codex-thread",
                "runtime: herdr-codex-pane",
                "runtime: herdr-claude-pane",
                "Codex App Herdr Bridge",
                "trusted_execution_bootstrap",
                "workspace trust",
                "external imports",
                "resolved owner skill",
                "agent send-keys",
                "blocked -> idle -> working",
                "visible Herdr session",
                "不调用、不修改 `$herdr` skill",
                "不要求 `HERDR_ENV=1`",
                "--dangerously-skip-permissions",
                "state: awaiting_human",
                "`agent prompt` accepted",
                "`idle -> working` 即 startup terminal",
                "并行 preflight snapshot",
                "`created -> awaiting_human`",
                "Dispatch Handoff 是 coordinator 本轮 terminal",
                "用户明确要求 monitor",
                "不等待首个业务问题",
                "不读取 routine terminal、可见屏幕或进程信息",
                "用户回到 Codex App 报告完成后",
                "先完成 capability probe，再向用户呈现 Herdr/Claude 选择",
                "同一次 approval 写为 `bootstrap_authority: trusted_execution_bootstrap`",
                "$herdr",
                "active writer",
                "同批 `codex-thread` 并行调用 `create_thread`",
                "同批 Herdr lanes 并行创建",
                "单条 lane 到达 `working` 不提前 yield",
            ),
        )
        routing_text = " ".join(CODEX_DISPATCH_ROUTING.read_text().split())
        if "首个范围内业务问题是 startup probe 的成功终点" in routing_text:
            record("legacy Herdr startup gate still waits for the first business question")
        if "对同批 1–8 个 running tasks 用一次 `wait_threads`" in routing_text:
            record("legacy Codex dispatch still waits on running tasks by default")
    if not TASK_COORDINATE_TITLE.exists():
        record(
            "missing Task Coordinate Title owner: "
            f"{TASK_COORDINATE_TITLE.relative_to(ROOT)}"
        )
    else:
        require(
            TASK_COORDINATE_TITLE,
            (
                "<map-key>-<role><work-item-key>-<short-summary>",
                "<map-key>-LEAD-<short-summary>",
                "`LEAD`",
                "`G`",
                "`X`",
                "`P`",
                "`R`",
                "`D`",
                "动作＋对象",
                "set_thread_title",
                "list_threads",
                "lane registry",
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
            "无前序依赖的 ready tickets 同批并发派发",
            "普通 repo 文件路径重叠只进入 Integration 冲突检测",
            "整批 Dispatch Handoff",
        ),
    )
    frontier_text = " ".join(
        (CODEX_ROOT / "references" / "frontier-lanes.md").read_text().split()
    )
    if "Herdr pane 都通过 Herdr Control Route 读取完整 final markers" in frontier_text:
        record("legacy Herdr fan-in still requires complete final markers")
    if "显式文件、migration、lock 或 external mutable resource 重叠" in frontier_text:
        record("普通 repo 文件路径重叠仍被错误当成 dispatch blocker")
    if "写集合无法证明相互独立" in frontier_text:
        record("无法证明 repo 写集合独立仍会把 safe batch 退化为单 lane")
    recovery_text = " ".join(
        (CODEX_ROOT / "references" / "test-decision-and-rebase.md").read_text().split()
    )
    if "重挂 listener" in recovery_text or "重新 attach listener" in recovery_text:
        record("legacy recovery still attaches monitoring after Dispatch Handoff")
    require(
        CODEX_ROOT / "references" / "lane-registry.md",
        (
            "runtime: subagent | codex-thread | herdr-codex-pane | herdr-claude-pane | orchestrator",
            "awaiting_human",
            "coordinator_runtime:",
            "dispatch_runtime:",
            "bootstrap_authority:",
            "herdr_session_name:",
            "herdr_session_owned:",
            "agent_permission_mode:",
            "map_run_authority:",
            "host_id:",
            "thread_archived:",
            "integrated -> close_pending -> closed",
            "list_archived_threads",
        ),
    )
    require(
        CODEX_ROOT / "references" / "child-monitoring.md",
        (
            "`dispatch-runtime-routing.md`",
            "`frontier-lanes.md`",
        ),
    )
    require(
        CODEX_ROOT / "references" / "frontier-lanes.md",
        (
            "Dispatch Handoff",
            "用户完成信号",
            "Git、tracker 与 artifact",
            "final marker 缺失字段记为 `Unknown`",
            "不要求 worker 重显",
            "自动重算并派发下一 ready frontier",
        ),
    )
    require(
        CODEX_ROOT / "references" / "wayfinder-frontier-loop.md",
        (
            "tracker transaction",
            "独立 writes 并行",
            "每个 dependency layer 一次聚合 readback",
            "同一 turn 不重复 Nowledge 或 contract lookup",
            "不把文档漂移修复放在发布/派发 critical path",
            "不把 canonical tracker scope 降级为 read-only",
            "map_run_authority: canonical_tracker_transitions",
            "resolution comment",
            "关闭 child",
            "Decisions-so-far / Out of scope gist",
            "dependency blocker",
            "follow-up decision ticket",
            "不等待用户回复“继续”",
            "先完成整个 maximal safe batch 的派发，再 yield",
        ),
    )
    require(
        CODEX_SKILL,
        (
            "无前序依赖的 ready tickets 同批并发派发",
            "整批完成 startup readback 后统一 Dispatch Handoff",
        ),
    )
    require(
        ROOT / "CONTEXT.md",
        (
            "Dispatch Handoff is batch-scoped",
            "repository file overlap is an Integration risk",
        ),
    )
    require(
        CODEX_ROOT / "references" / "owner-skill-resolution.md",
        (
            "coordinator 只解析 realpath、frontmatter name 和 direct reference paths",
            "coordinator 不把 owner body 加载进上下文",
            "child 完整读取",
        ),
    )
    require(
        CODEX_ROOT / "references" / "execution-worktree-integration.md",
        (
            "set_thread_archived({threadId, hostId, archived: true})",
            "list_archived_threads",
            "thread_archived: true",
            "state: close_pending",
            "integration_checks_failed` task 保持未归档",
        ),
    )
    require(
        CODEX_ROOT / "references" / "test-decision-and-rebase.md",
        (
            "integrated` / `close_pending",
            "list_archived_threads",
            "set_thread_archived",
            "Codex App execution tasks archived",
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
            "Herdr Session Target",
            "Trusted Execution Bootstrap",
            "HITL Handoff",
            "Codex Task Archive",
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
    check_pane_lifecycle_single_source()
    check_atomic_dispatch_sequence()
    check_batch_dispatch_concurrency()

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
    if pane_dispatch_fm.get("disable-model-invocation") == "true":
        fail("pane-dispatch must stay model-invocable: the lead dispatches panes via the Skill tool")

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
