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
TICKET_SIZING = ROOT / "skills" / "ticket-sizing"

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
            "Coordinator Pane",
            "只有用户显式要求新 Workspace",
            "不切换 Coordinator Pane 当前目录的 branch",
            "coordinator_runtime: pi-cli | codex-cli | claude-cli",
            "dispatch_runtime: herdr",
            "references/model-role-routing.md",
            "scripts/model_config.py validate <config>",
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
            "references/code-review-evidence-preflight.md",
            "Review fixed point: <Execution Base commit>",
            "Review Evidence Bundle",
            "写 `consumed`",
            "不静默回落",
        ),
    )
    require(
        CORE / "references" / "dispatch-runtime-routing.md",
        (
            "worker kind 完全由 registry 或 canonical config 的 `agent`",
            "Bootstrap Gearshift Policy",
            "pi → `herdr-pi-pane`",
            "codex → `herdr-codex-pane`",
            "claude → `herdr-claude-pane`",
            "默认复用 coordinator 当前所在的 Herdr Workspace",
            "只有用户显式要求新 Workspace",
            "HERDR_WORKSPACE_ID",
            "herdr pane current --current",
            "workspace 解析是 maximal safe batch 的唯一串行前置",
            "整批成功/失败项都完成 startup readback",
            "先按 registry 判断 existing/replacement",
            "active recovery 不重验 model catalog",
            "证据不一致时写 `stale`",
            "replacement 启动失败写 `blocked`",
            "禁止运行 setup",
            "仅首次创建新 work-item lane",
        ),
    )
    runtime_routing_text = (CORE / "references" / "dispatch-runtime-routing.md").read_text()
    if "创建、恢复或替换任何 worker lane 前读取" in runtime_routing_text:
        record("runtime routing must not apply the new-lane config Gate to recovery/replacement")
    require(
        CORE / "references" / "pane-lifecycle-rules.md",
        (
            "每个 worker tab 最多 4 pane",
            "溢出依次 `X-2`、`X-3`",
            "HITL lane 与其他 lane 共用 X tab 容量",
            "coordinator pane 不作为 worker pane",
            "--cwd <Execution Worktree>",
        ),
    )
    require(
        CORE / "references" / "integration-worktree-management.md",
        (
            "Map Integration Worktree/branch 不存在时创建独立 worktree 与 branch",
            "不在 coordinator pane 的 cwd 切换 branch",
            "base_commit: <SOURCE_HEAD>",
            "whole-change Review fixed point",
        ),
    )
    legacy_workspace_rules = {
        CORE / "SKILL.md": ("Herdr Workspace 只在首次 lane 前懒创建",),
        CORE / "references" / "dispatch-runtime-routing.md": ("每个 map 一个 Herdr Workspace",),
        CORE / "references" / "integration-worktree-management.md": ("Herdr Workspace 到第一条 configured lane 才懒创建",),
    }
    for path, phrases in legacy_workspace_rules.items():
        text = path.read_text()
        for phrase in phrases:
            if phrase in text:
                record(f"legacy per-map workspace rule restored: {path.relative_to(ROOT)}: {phrase}")
    legacy_topology_rules = {
        ROOT / "CONTEXT.md": ("HITL lanes get a `G-#<ticket>` tab",),
        CORE / "references" / "pane-lifecycle-rules.md": (
            "每条新 lane 默认在目标 Workspace 新建 tab",
            "一 lane一 tab",
            "`G-#<ticket>`",
            "HITL lane用独立 tab",
            "HITL lane 用独立 tab",
        ),
        CORE / "references" / "execution-worktree-integration.md": ("`G-#` tab",),
        CORE / "SKILL.md": ("为每条 lane 新建 tab/pane",),
    }
    for path, phrases in legacy_topology_rules.items():
        text = path.read_text()
        for phrase in phrases:
            if phrase in text:
                record(f"legacy one-lane-per-tab rule restored: {path.relative_to(ROOT)}: {phrase}")
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
            "<!-- wayfinder-lane-registry:v3 -->",
            "Legacy v2 Recovery",
            "缺失的 Bootstrap/Gearshift 字段解释为 disabled/none",
            "不读取当前 Worker Role Configuration",
            "role: planning | design | frontend | backend | testing | review | map",
            "output_mode: commit | artifact | checks | verdict | none",
            "bootstrap_model:",
            "gearshift_mode: off | opt_in | all_eligible | none",
            "gearshift_eligibility: off | ticket-label:<label> | all-eligible | ineligible | none",
            "gearshift_shift_id:",
            "gearshift_evidence_ref:",
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
            "作为 whole-change Review fixed point",
            "后续 Integration 不改写",
        ),
    )
    require(
        CORE / "SKILL.md",
        (
            "existing lane recovery",
            "先于新 lane 配置 Gate",
            "replacement 继续沿 registry route",
            "只有本轮首次创建新 work-item lane",
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
            "code-review Review Evidence Bundle readback",
            "`artifact`",
            "`checks`",
            "`verdict`",
            "Review Evidence Bundle readback",
            "只有 `commit` mode 进入 cherry-pick",
        ),
    )
    require(
        CORE / "references" / "execution-worktree-integration.md",
        (
            "Commit Mode",
            "Artifact / Checks / Verdict Modes",
            "内嵌 code-review 的",
            "Review fixed point 等于 lane base commit",
            "不要求 commit、不 cherry-pick",
            "Review fixed point 等于 map registry base commit",
            "bundle 七文件在 fan-in 时可读",
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
            "version 3",
            "六个角色全部必填",
            "Bootstrap Gearshift Policy",
            "off | opt_in | all_eligible",
            "bootstrap.model/effort",
            "pi --list-models",
            "codex debug models",
            "ANTHROPIC_DEFAULT_{FABLE,HAIKU,OPUS,SONNET}_MODEL",
            "ANTHROPIC_MODEL",
            "CLAUDE_CODE_SUBAGENT_MODEL",
            "CLAUDE_CODE_EFFORT_LEVEL",
            "--approve --model \"$model\" --thinking \"$effort\"",
            "--gearshift-profile delivery-bootstrap",
            "--gearshift-target \"$model\"",
            "delivery-pipeline/bootstrap-slice",
            "GEARSHIFT_ARMED <json>",
            "GEARSHIFT_STATUS <json>",
            "GEARSHIFT_RESUMED <json>",
            "model_reasoning_effort",
            "--model \"$model\" --effort \"$effort\"",
        ),
    )
    schema = extract_schema_example(routing)
    if schema.get("version") != 3:
        record("model-role schema version must be 3")
    gearshift = schema.get("gearshift") or {}
    if set(gearshift) != {"mode", "optInLabel"}:
        record("model-role schema gearshift keys must be mode/optInLabel")
    roles = schema.get("roles") or {}
    if set(roles) != ROLES:
        record(f"model-role schema must define exactly {sorted(ROLES)}, got {sorted(roles)}")
    base_fields = {"agent", "model", "effort"}
    for role, value in roles.items():
        allowed = base_fields | ({"bootstrap"} if role in {"frontend", "backend"} else set())
        if not base_fields.issubset(value) or set(value) - allowed:
            record(f"role {role} has invalid version 3 fields")
        if "bootstrap" in value and set(value["bootstrap"]) != {"model", "effort"}:
            record(f"role {role} bootstrap must define model/effort")
    if "orchestration" in routing.read_text() or "orchestration" in (SETUP / "SKILL.md").read_text():
        record("coordinator/orchestration must not appear as a configured worker role")

    require(
        SETUP / "SKILL.md",
        (
            "../delivery-pipeline/references/model-role-routing.md",
            "executable validator",
            "不派发 lane",
            "pi --list-models",
            "codex debug models",
            "~/.claude/settings.json",
            "Gearshift Core",
            "--gearshift-profile",
            "--gearshift-target",
            "scripts/model_config.py validate",
            "不把 version 2 或非法 version 3 当作完成",
            "existing lane recovery 不属于",
            "Skill 不提供默认",
            "原子写目标 config",
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


def check_bootstrap_adapter() -> None:
    adapter = CORE / "adapters" / "bootstrap-trigger.ts"
    verifier = ROOT / "scripts" / "verify-bootstrap-adapter.mjs"
    if not adapter.exists():
        record("missing Delivery Pipeline Bootstrap Trigger Adapter")
        return
    require(
        adapter,
        (
            'const ADAPTER_ID = "delivery-pipeline/bootstrap-slice"',
            'pi.registerTool({',
            'name: TOOL_NAME',
            'pi.events.on(GEARSHIFT.discover',
            'pi.events.on(GEARSHIFT.armed',
            'pi.events.emit(GEARSHIFT.ready',
            'verifiedEvidence:',
            'pi.appendEntry(ENTRY_TYPE',
            'No declared canonical-owner path retains a verified edit/write mutation after the red check',
            'remainingWork',
        ),
    )
    if not verifier.exists():
        record("missing bootstrap adapter verifier")
        return
    result = subprocess.run(
        ["node", str(verifier)],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        record(f"bootstrap adapter verifier failed: {result.stdout}{result.stderr}")


def check_packets() -> None:
    packet = CORE / "assets" / "HERDR_ROLE_DISPATCH_PACKET.md"
    require(
        packet,
        (
            "Role：<planning | design | frontend | backend | testing | review>",
            "Output mode：<commit | artifact | checks | verdict>",
            "Agent：<pi | codex | claude>",
            "Model：<ordinary Target Model id>",
            "Effort：<ordinary Target effort>",
            "Gearshift mode：<off | opt_in | all_eligible>",
            "Gearshift enabled：<true | false>",
            "Gearshift eligibility：<off | ticket-label:label | all-eligible | ineligible>",
            "Gearshift profile：<delivery-bootstrap | none>",
            "Bootstrap Source：<model + effort | none>",
            "Gearshift Shift ID：<full id from GEARSHIFT_ARMED json | none>",
            "Gearshift Projection：<mode/enabled/eligibility/shift-id/source/target/adapter/state/evidence-ref | none>",
            "Owner skill name",
            "Owner skill SKILL.md：<absolute resolved path>",
            "Owner skill invocation label",
            "Review fixed point：<execution-base-commit | map-registry-base-commit | none>",
            "Review evidence preflight：<absolute delivery-pipeline/references/code-review-evidence-preflight.md | none>",
            "先完整读取 Owner skill SKILL.md，回报 frontmatter name 与 resolved path",
            "preflight bundle 完成前不派生 Standards/Spec 子审查",
            "Review evidence：<fixed-point/head/bundle-readback | none>",
            "FINAL_REPORT_BEGIN",
            "FINAL_REPORT_END",
        ),
    )
    require(
        CORE / "references" / "code-review-evidence-preflight.md",
        (
            "`implement` owner",
            "`commit` lane",
            "`verdict` lane",
            "Map Integration Worktree",
            "Review Evidence Bundle",
            "diff.patch",
            "commits.txt",
            "changed-paths.txt",
            "fixed-point-added-paths.txt",
            "worktree-state.txt",
            "untracked additions",
            "NO_STAGED_FILES=true|false",
            "commands.txt",
            "review-only/no-acceptance",
            "正常路径不产生索取 Git/path 输出的 supervisor 往返",
        ),
    )


def check_lane_wakeup() -> None:
    packet = CORE / "assets" / "HERDR_ROLE_DISPATCH_PACKET.md"
    require(
        packet,
        (
            "Lane ID：",
            "LANE_DONE <lane_id>",
        ),
    )
    lifecycle = CORE / "references" / "pane-lifecycle-rules.md"
    require(
        lifecycle,
        (
            "scripts/lane-watch.sh",
            "LANE_DONE <lane_id>",
            "`done` 事件",
        ),
    )
    code_blocks = re.findall(r"```(?:bash|sh|text)?\n(.*?)\n```", lifecycle.read_text(), re.DOTALL)
    if any("--until done" in block for block in code_blocks):
        record("pane-lifecycle-rules.md still relies on the unreliable `herdr agent wait --until done` listener")
    watcher = CORE / "scripts" / "lane-watch.sh"
    if not watcher.exists():
        record("missing lane watcher: skills/delivery-pipeline/scripts/lane-watch.sh")
        return
    watcher_text = watcher.read_text()
    require(
        watcher,
        (
            "LANE_DONE",
            "herdr pane read",
            "herdr agent prompt",
        ),
    )
    for banned in ("w26:p1", "xcodebuild", "feature/map-", "pagugu"):
        if banned in watcher_text:
            record(f"lane-watch.sh carries session-specific hardcode: {banned}")
    subprocess.run(["bash", "-n", str(watcher)], check=True)


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
            "../delivery-pipeline/references/code-review-evidence-preflight.md",
            "Review Evidence Bundle",
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
            "Review Evidence Bundle readback",
            "Review fixed point 等于 lane base commit",
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
            "Review fixed point：<execution-base-commit | map-registry-base-commit | none>",
            "Review evidence preflight：<absolute delivery-pipeline/references/code-review-evidence-preflight.md | none>",
            "preflight bundle 完成前不派生 Standards/Spec 子审查",
            "Review evidence：<fixed-point/head/bundle-readback | none>",
            "FINAL_REPORT_BEGIN",
            "FINAL_REPORT_END",
        ),
    )
    for path in (APP / "SKILL.md", APP / "references" / "codex-app-dispatch.md"):
        check_skill_links(path)


def check_tree_ownership() -> None:
    retired = (
        ROOT / "skills" / "delivery-pipeline-pi",
        ROOT / "claude" / "skills",
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
            "Review Evidence Bundle",
            "Reviewers consume the same bundle with read/search access",
            "Worker Role Configuration",
            "exactly six worker roles",
            "Bootstrap Handoff",
            "Bootstrap Checkpoint",
            "Bootstrap Gearshift Policy",
            "Gearshift Projection",
            "current calling session is the coordinator",
            "Coordinator Pane",
            "new workspace requires explicit user request",
            "map isolation belongs to Map Integration Worktrees and Execution Worktrees",
            "skills/delivery-pipeline-codex-app",
            "There are no built-in agent/model/effort defaults",
            "repository file overlap is an Integration risk",
            "all lane types share the same worker-tab capacity pool",
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
        ROOT / "README.md",
        (
            "coordinator's current workspace by default",
            "new workspace is created only when the user explicitly requests one",
            "coordinator pane remains a control plane",
        ),
    )
    require(
        ROOT / "README.zh-CN.md",
        (
            "coordinator 当前 Workspace",
            "只有用户显式要求时才创建新 Workspace",
            "Coordinator Pane 只承担调度",
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
    require(
        ROOT / "docs" / "adr" / "0005-current-workspace-first-herdr-dispatch.md",
        (
            "Status:** Accepted",
            "Coordinator Pane 当前所在的 Herdr Session 与 Workspace",
            "只有用户显式要求时才创建新 Workspace",
            "Coordinator Pane 只承担调度",
            "取代 ADR-0001",
        ),
    )
    require(
        ROOT / "docs" / "adr" / "0006-worker-tab-capacity-and-naming.md",
        (
            "Status:** Accepted",
            "每个 worker tab 最多 4 pane",
            "X-#391·#392",
            "HITL lane 与其他 lane 共用同一容量池",
            "取代 ADR-0005",
            "current-workspace-first 前提",
        ),
    )
    require(
        ROOT / "docs" / "adr" / "0007-optional-pi-gearshift-bootstrap.md",
        (
            "Pi Gearshift optional and Adapter-owned",
            "Status:** Accepted",
            "version 3",
            "frontend/backend",
            "Bootstrap Checkpoint",
            "generic Gearshift package never owns tracker",
        ),
    )


def check_pruned_policy() -> None:
    roots = (CORE, APP, SETUP, TICKET_SIZING)
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
    if not os.access(ROOT / "scripts" / "validate.py", os.X_OK):
        record("validator must remain executable")


def main() -> None:
    check_manifest()
    check_frontmatter()
    check_core_contract()
    check_runtime_neutrality()
    check_model_contract()
    check_bootstrap_adapter()
    check_packets()
    check_lane_wakeup()
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
