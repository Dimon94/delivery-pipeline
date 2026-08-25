#!/usr/bin/env python3
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "skills" / "delivery-pipeline"
APP = ROOT / "skills" / "delivery-pipeline-codex-app"
SETUP = ROOT / "skills" / "delivery-pipeline-setup"
PANE_DISPATCH = ROOT / "claude" / "skills" / "pane-dispatch"

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
ROLES = {"planning", "design", "frontend", "backend", "testing", "review"}
OUTPUT_MODES = {"commit", "artifact", "checks", "verdict", "none"}
STATES = {
    "created", "running", "awaiting_human", "terminal", "consumed", "integrated",
    "blocked", "setup_blocked", "integration_conflict", "integration_checks_failed",
    "path_conflict", "stale", "close_pending", "test_decision_paused",
    "rebase_in_progress", "push_failed", "cleanup_in_progress", "closed",
}
ERRORS: list[str] = []


def record(message: str) -> None:
    ERRORS.append(message)


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def frontmatter(path: Path) -> dict[str, str]:
    if not path.exists():
        fail(f"missing skill: {path.relative_to(ROOT)}")
    match = re.match(r"^---\n(.*?)\n---\n", path.read_text(), re.DOTALL)
    if not match:
        fail(f"invalid frontmatter: {path.relative_to(ROOT)}")
    result: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, separator, value = line.partition(":")
        if not separator:
            fail(f"invalid frontmatter line: {path.relative_to(ROOT)}: {line}")
        result[key.strip()] = value.strip()
    return result


def require(path: Path, strings: tuple[str, ...]) -> None:
    if not path.exists():
        record(f"missing file: {path.relative_to(ROOT)}")
        return
    content = " ".join(path.read_text().split())
    for item in strings:
        if " ".join(item.split()) not in content:
            record(f"missing invariant in {path.relative_to(ROOT)}: {item}")


def check_skill_links(path: Path) -> None:
    for token in re.findall(r"`([^`]+\.md)`", path.read_text()):
        if token.startswith(("references/", "assets/", "../")):
            target = (path.parent / token).resolve()
            if not target.exists():
                record(f"missing reference from {path.relative_to(ROOT)}: {token}")


def check_manifest() -> None:
    manifest = json.loads((ROOT / "skill-bundle.json").read_text())
    if manifest.get("format") != "multi-runtime-skill-bundle/v2":
        record("bundle format must be multi-runtime-skill-bundle/v2")
    if manifest.get("name") != "delivery-pipeline":
        record("bundle name mismatch")
    if manifest.get("entrypoints") != {
        "cli": "skills/delivery-pipeline/SKILL.md",
        "codexApp": "skills/delivery-pipeline-codex-app/SKILL.md",
        "setup": "skills/delivery-pipeline-setup/SKILL.md",
    }:
        record("v2 entrypoints mismatch")
    if manifest.get("install") != {
        "sharedSkillDirectory": "skills/delivery-pipeline",
        "codexAppSkillDirectory": "skills/delivery-pipeline-codex-app",
        "setupSkillDirectory": "skills/delivery-pipeline-setup",
    }:
        record("v2 install directories mismatch")
    if [item.get("name") for item in manifest.get("requires") or []] != DEPENDENCIES:
        record("dependency order mismatch")


def check_frontmatter() -> None:
    expected = (
        (CORE / "SKILL.md", "delivery-pipeline"),
        (APP / "SKILL.md", "delivery-pipeline-codex-app"),
        (SETUP / "SKILL.md", "delivery-pipeline-setup"),
    )
    for path, name in expected:
        fm = frontmatter(path)
        if fm.get("name") != name:
            record(f"frontmatter name mismatch: {path.relative_to(ROOT)}")
        if fm.get("disable-model-invocation") != "true":
            record(f"skill must remain user-invoked: {path.relative_to(ROOT)}")
        if not fm.get("description"):
            record(f"skill description missing: {path.relative_to(ROOT)}")
        check_skill_links(path)


def check_core_contract() -> None:
    require(
        CORE / "SKILL.md",
        (
            "唯一 canonical CLI/Herdr 编排主干",
            "当前调用会话就是 coordinator",
            "coordinator_runtime: pi-cli | codex-cli | claude-cli",
            "dispatch_runtime: herdr",
            "~/.config/delivery-pipeline/model-roles.json",
            "scripts/model_config.py validate <config>",
            "version 2",
            "agent`、`model`、`effort",
            "planning",
            "design",
            "frontend",
            "backend",
            "testing",
            "review",
            "maximal safe batch",
            "Dispatch Handoff",
            "Execution Worktree",
            "Integration",
            "assets/HERDR_ROLE_DISPATCH_PACKET.md",
            "Role-aware Fan-in / Integration",
            "output_mode: artifact",
            "output_mode: commit",
            "output_mode: checks",
            "output_mode: verdict",
            "写 `consumed`",
            "不静默回落",
        ),
    )
    require(
        CORE / "references" / "dispatch-runtime-routing.md",
        (
            "worker kind 完全由 version 2 role config",
            "pi → `herdr-pi-pane`",
            "codex → `herdr-codex-pane`",
            "claude → `herdr-claude-pane`",
            "workspace 解析是 maximal safe batch 的唯一串行前置",
            "整批成功/失败项都完成 startup readback",
        ),
    )
    require(
        CORE / "references" / "frontier-lanes.md",
        (
            "普通 repo 文件路径重叠只进入 Integration 冲突检测",
            "Role Binding",
            "HERDR_ROLE_DISPATCH_PACKET.md",
            "整批成功 lanes 完成 startup",
        ),
    )
    registry = CORE / "references" / "lane-registry.md"
    require(
        registry,
        (
            "<!-- wayfinder-lane-registry:v2 -->",
            "role: planning | design | frontend | backend | testing | review | map",
            "output_mode: commit | artifact | checks | verdict | none",
            "runtime: herdr-pi-pane | herdr-codex-pane | herdr-claude-pane | orchestrator",
            "integration_conflict",
            "integration_checks_failed",
            "path_conflict",
            "stale",
            "test_decision_paused",
            "rebase_in_progress",
            "push_failed",
            "cleanup_in_progress",
            "test_strategy:",
            "agent_permission_mode: approve | danger-full-access | dangerously-skip-permissions | none",
            "model_evidence:",
        ),
    )
    registry_text = registry.read_text()
    state_match = re.search(r"^state: (.+)$", registry_text, re.MULTILINE)
    mode_match = re.search(r"^output_mode: (.+)$", registry_text, re.MULTILINE)
    if not state_match or {part.strip() for part in state_match.group(1).split("|")} != STATES:
        record("lane-registry state enum is not closed over every documented state")
    if not mode_match or {part.strip() for part in mode_match.group(1).split("|")} != OUTPUT_MODES:
        record("lane-registry output_mode enum mismatch")
    require(
        CORE / "references" / "child-monitoring.md",
        (
            "Role-aware Terminal Outcomes",
            "`commit`",
            "`artifact`",
            "`checks`",
            "`verdict`",
            "只有 `commit` mode 进入 cherry-pick",
        ),
    )
    require(
        CORE / "references" / "execution-worktree-integration.md",
        (
            "Commit Mode",
            "Artifact / Checks / Verdict Modes",
            "不要求 commit、不 cherry-pick",
            "成功写 `consumed`",
            "integrated` 或 `consumed",
        ),
    )


def check_runtime_neutrality() -> None:
    app_only = re.compile(
        r"codex-thread|create_thread|list_threads|read_thread|wait_threads|"
        r"send_message_to_thread|set_thread_(?:title|archived)|list_archived_threads|"
        r"App-managed|Codex App"
    )
    owner_sigil = re.compile(
        r"\$(?:wayfinder|to-spec|to-tickets|implement|code-review|"
        r"resolving-merge-conflicts|grilling|prototype|research|domain-modeling)\b"
    )
    claude_locator = re.compile(r"/mattpocock-skills:")
    hardcoded_model = re.compile(
        r"junbo/kimi-k3|gpt-5\.6|claude-(?:opus|sonnet|haiku)-\d",
        re.IGNORECASE,
    )
    for root in (CORE, SETUP):
        for path in sorted(root.rglob("*.md")):
            for lineno, line in enumerate(path.read_text().splitlines(), 1):
                if root == CORE and app_only.search(line):
                    record(f"App transport leaked into canonical core: {path.relative_to(ROOT)}:{lineno}")
                if owner_sigil.search(line) or claude_locator.search(line):
                    record(f"runtime-specific owner locator in neutral skill: {path.relative_to(ROOT)}:{lineno}")
                if hardcoded_model.search(line):
                    record(f"hard-coded model default in skill/config contract: {path.relative_to(ROOT)}:{lineno}")


def extract_schema_example(path: Path) -> dict:
    match = re.search(r"```json\n(.*?)\n```", path.read_text(), re.DOTALL)
    if not match:
        fail(f"missing JSON schema example: {path.relative_to(ROOT)}")
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as error:
        fail(f"invalid JSON schema example in {path.relative_to(ROOT)}: {error}")


def check_model_contract() -> None:
    routing = CORE / "references" / "model-role-routing.md"
    require(
        routing,
        (
            "schema version 2",
            "六个角色全部必填",
            "agent`、`model`、`effort",
            "skill 与 reference 不提供默认 agent/model/effort",
            "pi --list-models",
            "codex debug models",
            "ANTHROPIC_DEFAULT_FABLE_MODEL",
            "ANTHROPIC_DEFAULT_HAIKU_MODEL",
            "ANTHROPIC_DEFAULT_OPUS_MODEL",
            "ANTHROPIC_DEFAULT_SONNET_MODEL",
            "ANTHROPIC_MODEL",
            "CLAUDE_CODE_SUBAGENT_MODEL",
            "CLAUDE_CODE_EFFORT_LEVEL",
            "--approve --model \"$model\" --thinking \"$effort\"",
            "model_reasoning_effort",
            "--model \"$model\" --effort \"$effort\"",
        ),
    )
    schema = extract_schema_example(routing)
    if schema.get("version") != 2:
        record("model-role schema version must be 2")
    roles = schema.get("roles") or {}
    if set(roles) != ROLES:
        record(f"model-role schema must define exactly {sorted(ROLES)}, got {sorted(roles)}")
    for role, value in roles.items():
        if set(value) != {"agent", "model", "effort"}:
            record(f"role {role} must define exactly agent/model/effort")
    if "orchestration" in routing.read_text() or "orchestration" in (SETUP / "SKILL.md").read_text():
        record("coordinator/orchestration must not appear as a configured worker role")
    if "user-confirmed" in routing.read_text() or "user-confirmed" in (SETUP / "SKILL.md").read_text():
        record("Claude setup must select from settings.json env candidates; user-confirmed side channel is undefined")

    require(
        SETUP / "SKILL.md",
        (
            "version 2",
            "不派发 lane",
            "pi --list-models",
            "codex debug models",
            "~/.claude/settings.json",
            "ANTHROPIC_DEFAULT_FABLE_MODEL",
            "ANTHROPIC_DEFAULT_HAIKU_MODEL",
            "ANTHROPIC_DEFAULT_OPUS_MODEL",
            "ANTHROPIC_DEFAULT_SONNET_MODEL",
            "ANTHROPIC_MODEL",
            "CLAUDE_CODE_SUBAGENT_MODEL",
            "CLAUDE_CODE_EFFORT_LEVEL",
            "scripts/model_config.py validate",
            "顶层 key 精确为 `version` + `roles`",
            "role key 精确",
            "每个 role object 的 key 精确",
            "agent 属于 `pi|codex|claude`",
            "不把非法既有 v2 文件当作完成",
            "Claude model只从 settings.json env候选选择",
            "不提供内置默认",
            "用户必须明确选择全部六角色",
            "写入并 readback",
        ),
    )
    config_validator = SETUP / "scripts" / "model_config.py"
    if not config_validator.exists() or not os.access(config_validator, os.X_OK):
        record("model_config.py must exist and remain executable")
    else:
        result = subprocess.run(
            [sys.executable, str(config_validator), "self-test"],
            text=True,
            capture_output=True,
        )
        if result.returncode != 0:
            record(f"model config fixture self-test failed: {result.stdout}{result.stderr}")


def check_packets() -> None:
    packet = CORE / "assets" / "HERDR_ROLE_DISPATCH_PACKET.md"
    require(
        packet,
        (
            "Role：<planning | design | frontend | backend | testing | review>",
            "Output mode：<commit | artifact | checks | verdict>",
            "Agent：<pi | codex | claude>",
            "Model：<configured native model id>",
            "Effort：<configured native effort>",
            "Owner skill name",
            "Owner skill SKILL.md：<absolute resolved path>",
            "Owner skill invocation label",
            "先完整读取 Owner skill SKILL.md，回报 frontmatter name 与 resolved path",
            "FINAL_REPORT_BEGIN",
            "FINAL_REPORT_END",
        ),
    )


def check_app_shell() -> None:
    require(
        APP / "SKILL.md",
        (
            "薄 delta",
            "../delivery-pipeline/SKILL.md",
            "coordinator_runtime: codex-app",
            "dispatch_runtime: codex-app",
            "跳过 canonical CLI 主干的 model-role 配置 gate",
            "canonical 的六个 delegated roles 全部使用 `runtime: codex-thread`",
            "planning → `output_mode: artifact`",
            "design/frontend/backend implementation → `output_mode: commit`",
            "testing → `output_mode: checks`",
            "review → `output_mode: verdict`",
            "App-managed Execution Worktree",
            "references/codex-app-dispatch.md",
            "assets/APP_ROLE_DISPATCH_PACKET.md",
        ),
    )
    require(
        APP / "references" / "codex-app-dispatch.md",
        (
            "list_projects",
            "create_thread",
            "list_threads",
            "read_thread",
            "wait_threads",
            "send_message_to_thread",
            "set_thread_title",
            "set_thread_archived",
            "list_archived_threads",
            "runtime: codex-thread",
            "App Registry Overlay",
            "project_id:",
            "host_id:",
            "thread_id:",
            "thread_archived:",
            "Role-aware Fan-in",
            "非 commit lane 不要求 commit",
            "task-coordinate-title.md",
        ),
    )
    require(
        APP / "assets" / "APP_ROLE_DISPATCH_PACKET.md",
        (
            "Codex App",
            "Role：<planning | design | frontend | backend | testing | review>",
            "Output mode：<commit | artifact | checks | verdict>",
            "Owner skill name",
            "Owner skill SKILL.md：<absolute resolved path>",
            "FINAL_REPORT_BEGIN",
            "FINAL_REPORT_END",
        ),
    )
    for path in (APP / "SKILL.md", APP / "references" / "codex-app-dispatch.md"):
        check_skill_links(path)


def check_tree_ownership() -> None:
    retired = (
        ROOT / "skills" / "delivery-pipeline-pi",
        ROOT / "claude" / "skills" / "delivery-pipeline",
    )
    for path in retired:
        if path.exists():
            record(f"retired duplicate runtime tree restored: {path.relative_to(ROOT)}")
    for path in (
        CORE / "references" / "codex-app-dispatch.md",
        CORE / "references" / "task-coordinate-title.md",
        CORE / "assets" / "ISSUE_IMPLEMENT_DISPATCH_PACKET.md",
        APP / "assets" / "ISSUE_IMPLEMENT_DISPATCH_PACKET.md",
    ):
        if path.exists():
            record(f"App-owned file leaked into canonical core: {path.relative_to(ROOT)}")


def check_installer() -> None:
    install_path = ROOT / "scripts" / "install.sh"
    text = install_path.read_text()
    require(
        install_path,
        (
            'link_skill "$ROOT/skills/delivery-pipeline"',
            '"$CODEX_HOME_DIR/skills/delivery-pipeline"',
            '"$CLAUDE_HOME_DIR/skills/delivery-pipeline"',
            '"$PI_HOME_DIR/agent/skills/delivery-pipeline"',
            'link_skill "$ROOT/skills/delivery-pipeline-setup"',
            '"$CODEX_HOME_DIR/skills/delivery-pipeline-setup"',
            '"$CLAUDE_HOME_DIR/skills/delivery-pipeline-setup"',
            '"$PI_HOME_DIR/agent/skills/delivery-pipeline-setup"',
            'link_skill "$ROOT/skills/delivery-pipeline-codex-app"',
            '"$CODEX_HOME_DIR/skills/delivery-pipeline-codex-app"',
            'rm -rf "$PI_HOME_DIR/agent/skills/delivery-pipeline-pi"',
        ),
    )
    if text.count('link_skill "$ROOT/skills/delivery-pipeline"') != 3:
        record("canonical core must be installed from one source into exactly three CLI homes")
    if text.count('link_skill "$ROOT/skills/delivery-pipeline-setup"') != 3:
        record("setup skill must be installed into exactly three CLI homes")
    if text.count('link_skill "$ROOT/skills/delivery-pipeline-codex-app"') != 1:
        record("Codex App shell must be installed exactly once")
    subprocess.run(["bash", "-n", str(install_path)], check=True)


def check_context_and_docs() -> None:
    require(
        ROOT / "CONTEXT.md",
        (
            "Configured Planning Lane",
            "Worker Role Configuration",
            "exactly six worker roles",
            "current calling session is the coordinator",
            "skills/delivery-pipeline-codex-app",
            "There are no built-in agent/model/effort defaults",
            "repository file overlap is an Integration risk",
        ),
    )
    require(
        ROOT / "AGENTS.md",
        (
            "Canonical CLI/Herdr 主干",
            "delivery-pipeline-codex-app",
            "Canonical 主干保持 runtime-neutral",
            "`codex-thread` 只存在于 delivery-pipeline-codex-app 树",
        ),
    )
    for readme in (ROOT / "README.md", ROOT / "README.zh-CN.md"):
        require(
            readme,
            (
                "delivery-pipeline-setup",
                "delivery-pipeline-codex-app",
                "model-roles.json",
                "planning",
                "design",
                "frontend",
                "backend",
                "testing",
                "review",
            ),
        )
    require(
        ROOT / "docs" / "adr" / "0004-config-driven-runtime-routing.md",
        (
            "Status:** Accepted",
            "current calling session is always the coordinator",
            "exactly six worker roles",
            "skills/delivery-pipeline-codex-app",
            "supersedes ADR-0003",
        ),
    )


def check_pruned_policy() -> None:
    roots = (CORE, APP, SETUP, ROOT / "claude" / "skills" / "pane-dispatch")
    forbidden = (
        re.compile(r"估时"),
        re.compile(r"估档"),
        re.compile(r"不拆理由"),
        re.compile(r"\bS/M/L/XL\b"),
        re.compile(r"ticket-split-coverage", re.IGNORECASE),
        re.compile(r"route classifier", re.IGNORECASE),
        re.compile(r"herdr wait agent-status"),
        re.compile(r"herdr agent start --cwd"),
    )
    for root in roots:
        for path in root.rglob("*.md"):
            for lineno, line in enumerate(path.read_text().splitlines(), 1):
                if any(pattern.search(line) for pattern in forbidden):
                    record(f"pruned policy restored: {path.relative_to(ROOT)}:{lineno}:{line}")


def check_metadata_and_helpers() -> None:
    require(
        CORE / "agents" / "openai.yaml",
        (
            'display_name: "Delivery Pipeline"',
            "$delivery-pipeline",
            "allow_implicit_invocation: false",
        ),
    )
    require(
        APP / "agents" / "openai.yaml",
        (
            'display_name: "Delivery Pipeline (Codex App)"',
            "$delivery-pipeline-codex-app",
            "allow_implicit_invocation: false",
        ),
    )
    pane_fm = frontmatter(PANE_DISPATCH / "SKILL.md")
    if pane_fm.get("name") != "pane-dispatch":
        record("pane-dispatch compatibility helper name mismatch")
    if not os.access(ROOT / "scripts" / "validate.py", os.X_OK):
        record("validator must remain executable")


def main() -> None:
    check_manifest()
    check_frontmatter()
    check_core_contract()
    check_runtime_neutrality()
    check_model_contract()
    check_packets()
    check_app_shell()
    check_tree_ownership()
    check_installer()
    check_context_and_docs()
    check_pruned_policy()
    check_metadata_and_helpers()

    if ERRORS:
        fail(f"{len(ERRORS)} violation(s):\n" + "\n".join(f"  - {item}" for item in ERRORS))
    print("bundle: pass")


if __name__ == "__main__":
    main()
