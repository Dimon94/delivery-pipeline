#!/usr/bin/env python3
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

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
    "created",
    "running",
    "awaiting_human",
    "terminal",
    "consumed",
    "integrated",
    "blocked",
    "setup_blocked",
    "integration_conflict",
    "integration_checks_failed",
    "path_conflict",
    "stale",
    "close_pending",
    "test_decision_paused",
    "rebase_in_progress",
    "push_failed",
    "cleanup_in_progress",
    "closed",
}
ERRORS: list[str] = []


def record(message: str) -> None:
    ERRORS.append(message)


def fail(message: str) -> NoReturn:
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
    # pi-lens-ignore: unchecked-throwing-call-python
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
            "~/.config/delivery-pipeline/model-roles.json",
            "scripts/model_config.py validate <config>",
            "version 2",
            "agent`、`model`、`effort",
            "Dispatch Handoff",
            "Execution Worktree",
            "Integration",
            "assets/HERDR_ROLE_DISPATCH_PACKET.md",
            "references/code-review-evidence-preflight.md",
            "Review fixed point: <Execution Base commit>",
            "Review Evidence Bundle",
            "不静默回落",
        ),
    )
    require(
        CORE / "references" / "dispatch-runtime-routing.md",
        (
            "worker kind 完全由 version 2/3 role config",
            "pi → `herdr-pi-pane`",
            "codex → `herdr-codex-pane`",
            "claude → `herdr-claude-pane`",
            "默认复用 coordinator 当前所在的 Herdr Workspace",
            "只有用户显式要求新 Workspace",
            "HERDR_WORKSPACE_ID",
            "herdr pane current --current",
            "workspace 解析是 maximal safe batch 的唯一串行前置",
            "整批成功/失败项都完成 startup readback",
        ),
    )
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
        CORE / "references" / "dispatch-runtime-routing.md": (
            "每个 map 一个 Herdr Workspace",
        ),
        CORE / "references" / "integration-worktree-management.md": (
            "Herdr Workspace 到第一条 configured lane 才懒创建",
        ),
    }
    for path, phrases in legacy_workspace_rules.items():
        text = path.read_text()
        for phrase in phrases:
            if phrase in text:
                record(
                    f"legacy per-map workspace rule restored: {path.relative_to(ROOT)}: {phrase}"
                )
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
                record(
                    f"legacy one-lane-per-tab rule restored: {path.relative_to(ROOT)}: {phrase}"
                )
    require(
        CORE / "references" / "frontier-lanes.md",
        (
            "普通 repo 文件路径重叠只进入 Integration 冲突检测",
            "maximal safe batch",
            "Role Binding",
            "| AFK discovery/research、spec、tickets gate worker | `planning` | `artifact` |",
            "| grilling/prototype HITL | `design` | `artifact` |",
            "| design implementation | `design` | `commit` |",
            "| frontend implementation | `frontend` | `commit` |",
            "| backend/other implementation | `backend` | `commit` |",
            "| whole-change tests | `testing` | `checks` |",
            "| code review | `review` | `verdict` |",
            "HERDR_ROLE_DISPATCH_PACKET.md",
            "整批成功 lanes 完成 startup",
            "落点拓扑与容量只按 `pane-lifecycle-rules.md` 的「拓扑与命名」执行",
            "`working` 确认后立即按 `pane-lifecycle-rules.md` 挂 `lane-watch.sh` watcher",
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
            "作为 whole-change Review fixed point",
            "后续 Integration 不改写",
        ),
    )
    registry_text = registry.read_text()
    state_match = re.search(r"^state: (.+)$", registry_text, re.MULTILINE)
    mode_match = re.search(r"^output_mode: (.+)$", registry_text, re.MULTILINE)
    if (
        not state_match
        or {part.strip() for part in state_match.group(1).split("|")} != STATES
    ):
        record("lane-registry state enum is not closed over every documented state")
    if (
        not mode_match
        or {part.strip() for part in mode_match.group(1).split("|")} != OUTPUT_MODES
    ):
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


def check_prompt_branches() -> None:
    # 提示合同静态回归；不冒充真实 runtime 执行验收。
    require(
        CORE / "SKILL.md",
        (
            "恢复既有 lane 不依赖当前 worker 配置",
            "新建 lane 前",
            "references/gate-state-machine.md",
        ),
    )
    require(
        CORE / "references" / "dispatch-runtime-routing.md",
        (
            "恢复既有 lane 直接进入“恢复与切换”",
            "replacement 验证 stored agent/model/effort 的实时可用性",
        ),
    )
    gates = CORE / "references" / "gate-state-machine.md"
    require(gates, ("Role-aware Fan-in / Integration", "写 `consumed`"))
    gate_names = re.findall(r"^\| `([^`]+)` \|", gates.read_text(), re.MULTILINE)
    if gate_names != [
        "discovery",
        "spec",
        "tickets",
        "dispatch",
        "execute",
        "collect",
        "integrate",
        "testing",
        "review",
        "test-decision",
        "rebase",
        "remote-review",
    ]:
        record(
            "gate table must include testing/review/test-decision/rebase in delivery order"
        )
    require(
        CORE / "references" / "test-decision-and-rebase.md",
        (
            "先读 map registry 的 `test_strategy`",
            "范围与风险未变化时复用",
            "未知是否仍适用",
            "测试选择不授予 remote publication authority",
        ),
    )
    require(
        TICKET_SIZING / "SKILL.md",
        (
            "独立验收",
            "Execution Worktree",
            "合并",
            "累计消耗不等于同时占用的上下文",
            "每张候选票必须主动给出 token 预测",
            "预测区间不能用 Unknown 代替",
            "上下文峰值预测（tokens）",
            "执行预算（tokens）",
            "最终回复也必须展示逐票预测",
            "拆票流程的 owner 是 `to-tickets`",
        ),
    )
    for path in (TICKET_SIZING / "SKILL.md", TICKET_SIZING / "agents" / "openai.yaml"):
        if re.search(r"150k|1\.5|smart zone", path.read_text(), re.IGNORECASE):
            record(f"uncalibrated fixed sizing policy: {path.relative_to(ROOT)}")


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
                    record(
                        f"App transport leaked into canonical core: {path.relative_to(ROOT)}:{lineno}"
                    )
                if owner_sigil.search(line) or claude_locator.search(line):
                    record(
                        f"runtime-specific owner locator in neutral skill: {path.relative_to(ROOT)}:{lineno}"
                    )
                if hardcoded_model.search(line):
                    record(
                        f"hard-coded model default in skill/config contract: {path.relative_to(ROOT)}:{lineno}"
                    )


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
            "version 3",
            "default_mode",
            "starting",
            "execution",
            "direct",
            "本票 → map → 用户配置",
            "不得把起步模型的请求回显当成执行模型已运行",
            "六个角色全部必填",
            "agent`、`model`、`effort",
            "skill 与 reference 不提供默认 agent/model/effort",
            "顶层只有 `version` 与 `roles`",
            "roles key 与六角色精确相等",
            "每个 role object 只有 `agent`、`model`、`effort`",
            "agent 属于 `pi|codex|claude`",
            "Setup 只允许从这些 `*_MODEL` / `ANTHROPIC_MODEL` / `CLAUDE_CODE_SUBAGENT_MODEL` 候选中选择",
            "settings.json env 候选与 CLI effort 枚举",
            "frontier-lanes.md",
            "pi --list-models",
            "codex debug models",
            "ANTHROPIC_DEFAULT_FABLE_MODEL",
            "ANTHROPIC_DEFAULT_HAIKU_MODEL",
            "ANTHROPIC_DEFAULT_OPUS_MODEL",
            "ANTHROPIC_DEFAULT_SONNET_MODEL",
            "ANTHROPIC_MODEL",
            "CLAUDE_CODE_SUBAGENT_MODEL",
            "CLAUDE_CODE_EFFORT_LEVEL",
            '--approve --model "$model" --thinking "$effort"',
            "model_reasoning_effort",
            '--model "$model" --effort "$effort"',
        ),
    )
    schema = extract_schema_example(routing)
    if schema.get("version") != 2:
        record("model-role schema version must be 2")
    roles = schema.get("roles") or {}
    if set(roles) != ROLES:
        record(
            f"model-role schema must define exactly {sorted(ROLES)}, got {sorted(roles)}"
        )
    for role, value in roles.items():
        if set(value) != {"agent", "model", "effort"}:
            record(f"role {role} must define exactly agent/model/effort")
    if (
        "orchestration" in routing.read_text()
        or "orchestration" in (SETUP / "SKILL.md").read_text()
    ):
        record("coordinator/orchestration must not appear as a configured worker role")
    if (
        "user-confirmed" in routing.read_text()
        or "user-confirmed" in (SETUP / "SKILL.md").read_text()
    ):
        record(
            "Claude setup must select from settings.json env candidates; user-confirmed side channel is undefined"
        )

    require(
        SETUP / "SKILL.md",
        (
            "version 2",
            "version 3",
            "default_mode",
            "starting/execution/direct",
            "本票 → map → 用户配置",
            "不能静默生成 direct 启动请求",
            "不派发 lane",
            "../delivery-pipeline/references/model-role-routing.md",
            "scripts/model_config.py validate",
            "配置结构与实时 evidence 都通过",
            "非法配置进入初始化",
            "合法配置仅在用户明确要求重配时覆盖",
            "不提供内置默认",
            "用户明确选择全部六角色",
            "写入并 readback",
        ),
    )
    config_validator = SETUP / "scripts" / "model_config.py"
    # pi-lens-ignore: unchecked-throwing-call-python
    if not config_validator.exists() or not os.access(config_validator, os.X_OK):
        record("model_config.py must exist and remain executable")
    else:
        result = subprocess.run(
            [sys.executable, str(config_validator), "self-test"],
            text=True,
            capture_output=True,
        )
        if result.returncode != 0:
            record(
                f"model config fixture self-test failed: {result.stdout}{result.stderr}"
            )


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
            "同一完整 marker 只唤醒一次",
        ),
    )
    lifecycle = CORE / "references" / "pane-lifecycle-rules.md"
    require(
        lifecycle,
        (
            "scripts/lane-watch.sh",
            "LANE_DONE <lane_id>",
            "`done` 事件",
            "PREWALK_READY <lane_id> <checkpoint_path>",
            "watcher 不退出并继续监听 LANE_DONE",
        ),
    )
    code_blocks = re.findall(
        r"```(?:bash|sh|text)?\n(.*?)\n```", lifecycle.read_text(), re.DOTALL
    )
    if any("--until done" in block for block in code_blocks):
        record(
            "pane-lifecycle-rules.md still relies on the unreliable `herdr agent wait --until done` listener"
        )
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
    subprocess.run([sys.executable, str(CORE / "scripts" / "lane_watch_check.py")], check=True)


def check_app_shell() -> None:
    require(APP / "references" / "codex-app-dispatch.md", (
        "scripts/prewalk.py review", "独立 Review 放行", "不验证宿主来源真实性",
        "review_scope: implementation | whole-change",
    ))
    require(APP / "assets" / "APP_ROLE_DISPATCH_PACKET.md", (
        "Review scope：<implementation | whole-change | none>", "不写 completed",
        "不能把 blocked 当作无需处理",
    ))
    if not os.access(APP / "scripts" / "prewalk.py", os.X_OK):
        record("App prewalk helper must be executable")
    subprocess.run([sys.executable, str(APP / "scripts" / "check_prewalk.py")], check=True)
    require(APP / "SKILL.md", ("每次调用的执行核验", "subagent 入口"))
    require(APP / "references" / "development-mode.md", (
        "scripts/prewalk.py coordinator", "scripts/prewalk.py subagent", "active_count", "invoke-owner",
        "宿主更低上限仍优先", "不改其他 repo 或全局配置",
        "每次启动或恢复前", "work.coordinator", "用户明确选择优先", "该入口不限制模型",
        "canonical build/write/read", "legacy_checkpoint: true",
        "review_scope: implementation | whole-change",
    ))
    require(APP / "assets" / "APP_ROLE_DISPATCH_PACKET.md", (
        "执行 helper：", "absolute resolved", "每次调用的执行核验",
    ))
    # App 请求值与运行证据分离；这只是提示合同检查。
    require(APP / "references" / "development-mode.md", (
        "config/models.json", "review_models", "model_override",
        "second opinion", "reasoning_effort", "thinking",
        "Testing 与 Integration 分两次串行",
        "service tier 沿宿主默认",
        "不启用 fast", "用户确认", "只读",
    ))
    require(ROOT / ".codex" / "config.toml", (
        "enabled = true", "max_concurrent_threads_per_session = 3",
    ))
    for path in [APP / "SKILL.md", APP / "scripts/prewalk.py", *APP.glob("references/*.md"),
                 APP / "assets/APP_ROLE_DISPATCH_PACKET.md", ROOT / ".codex/config.toml"]:
        if re.search(r"gpt-\d|default_subagent_model\s*=|default_subagent_reasoning_effort\s*=", path.read_text()):
            record(f"App 模型值必须只存在于 config/models.json: {path.relative_to(ROOT)}")
    # 仅验证 App 接续合同完整性；不证明宿主已执行模型切换。
    require(APP / "references" / "development-mode.md", (
        "default_mode", "phase_plan", "phase_targets", "execution_target",
        "PREWALK_READY", "send_message_to_thread", "phase: switching",
        "不能盲目重发", "尚未做 App 端到端模型 readback", "`evaluate_signal`",
    ))
    require(APP / "references" / "codex-app-dispatch.md", (
        "development_mode:", "mode_source:", "execution_phase:", "checkpoint:",
        "## Prewalk 中间回传", "不进入 Terminal fan-in",
    ))
    require(APP / "assets" / "APP_ROLE_DISPATCH_PACKET.md", (
        "Development mode：", "Mode source：", "Execution phase：", "Checkpoint：", "Lane registry：",
        "Checkpoint format/hash：", "PREWALK_READY 后停止",
    ))
    require(APP / "SKILL.md", ("references/development-mode.md",))
    require(APP / "references" / "codex-app-dispatch.md", (
        "requested_model:", "requested_effort:", "model: Unknown",
        "effort: Unknown", "model_evidence: Unknown", "checkpoint_sha256:", "旧 lane",
    ))
    require(APP / "assets" / "APP_ROLE_DISPATCH_PACKET.md", (
        "开发模式合同：", "Requested model：", "Requested effort：",
        "review_scope: implementation", "review_scope: whole-change",
    ))
    formal_review_model = re.compile(
        r"(?:implementation|whole-change).*(?:Review|审查).*(?:gpt-5|\bAstra\b|\bSol\b|\bLuna\b)|"
        r"(?:gpt-5|\bAstra\b|\bSol\b|\bLuna\b).*(?:implementation|whole-change).*(?:Review|审查)",
        re.IGNORECASE,
    )
    for path in (
        ROOT / "docs" / "adr" / "0007-codex-app-development-mode.md",
        APP / "SKILL.md",
        APP / "assets" / "APP_ROLE_DISPATCH_PACKET.md",
        APP / "references" / "codex-app-dispatch.md",
        APP / "references" / "development-mode.md",
    ):
        content = path.read_text()
        for phrase in ("正式 Astra Review", "implementation 两轴使用 Astra", "whole-change 两轴使用 Sol"):
            if phrase in content:
                record(f"App formal Review hard-codes owner model: {path.relative_to(ROOT)}: {phrase}")
        for lineno, line in enumerate(content.splitlines(), 1):
            if formal_review_model.search(line):
                record(f"App formal Review hard-codes owner model: {path.relative_to(ROOT)}:{lineno}")
    require(
        APP / "SKILL.md",
        (
            "薄 delta",
            "../delivery-pipeline/SKILL.md",
            "coordinator_runtime: codex-app",
            "dispatch_runtime: codex-app",
            "跳过 canonical CLI 主干的 model-role 配置 gate",
            "canonical 六个 role 与 output mode 保持不变",
            "planning → `output_mode: artifact`",
            "design/frontend/backend implementation → `output_mode: commit`",
            "testing → `output_mode: checks`",
            "review → `output_mode: verdict`",
            "Testing 与 Review 不另建 App task/worktree",
            "Integration 由 coordinator 单独串行委派配置中 integration 模型",
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
            "coordinator_thread_id:",
            "coordinator_host_id:",
            "## Terminal 回传",
            "最终回复前调用 `send_message_to_thread`",
            "发送失败或结果 Unknown",
            "timeoutMs: 0",
            "重复通知",
            "Role-aware Fan-in",
            "Review Evidence Bundle readback",
            "Review fixed point 等于 lane base commit",
            "非 commit lane 不要求 commit",
            "completed` 是 FINAL_REPORT outcome，不是 registry state",
            "同一次 fan-in",
            "关闭 tracker 或派发下一 ready lane 前",
            "task-coordinate-title.md",
        ),
    )
    require(
        APP / "assets" / "APP_ROLE_DISPATCH_PACKET.md",
        (
            "Codex App",
            "Coordinator host：",
            "Terminal 回传合同：",
            "最终回复前",
            "completed 与 blocked",
            "FINAL_REPORT 已回传",
            "Role：<planning | design | frontend | backend | testing | review>",
            "Output mode：<commit | artifact | checks | verdict>",
            "Owner skill name",
            "Owner skill SKILL.md：<absolute resolved path>",
            "Review fixed point：<execution-base-commit | map-registry-base-commit | none>",
            "Review evidence preflight：<absolute delivery-pipeline/references/code-review-evidence-preflight.md | none>",
            "preflight bundle 完成前不派生 Standards/Spec 子审查",
            "Review evidence：<fixed-point/head/bundle-readback | none>",
            "报告 outcome，不是 registry state",
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
            record(
                f"App-owned file leaked into canonical core: {path.relative_to(ROOT)}"
            )


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
        record(
            "canonical core must be installed from one source into exactly three CLI homes"
        )
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
                    record(
                        f"pruned policy restored: {path.relative_to(ROOT)}:{lineno}:{line}"
                    )


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
    # pi-lens-ignore: unchecked-throwing-call-python
    if not os.access(ROOT / "scripts" / "validate.py", os.X_OK):
        record("validator must remain executable")


def check_checkpoint_contract() -> None:
    helper = CORE / "scripts" / "checkpoint.py"
    probe = CORE / "scripts" / "checkpoint_check.py"
    continuation = CORE / "scripts" / "continuation.py"
    continuation_probe = CORE / "scripts" / "continuation_check.py"
    pi_adapter = CORE / "scripts" / "pi_adapter.py"
    pi_adapter_probe = CORE / "scripts" / "pi_adapter_check.py"
    codex_adapter = CORE / "scripts" / "codex_cli_adapter.py"
    codex_adapter_probe = CORE / "scripts" / "codex_cli_adapter_check.py"
    for path in (helper, probe, continuation, continuation_probe,
                 pi_adapter, pi_adapter_probe, codex_adapter, codex_adapter_probe):
        if not path.exists():
            record(f"missing checkpoint helper: {path.relative_to(ROOT)}")
    if helper.exists():
        result = subprocess.run([sys.executable, str(helper), "self-test"],
                                text=True, capture_output=True)
        if result.returncode != 0:
            record(f"checkpoint helper self-test failed: {result.stdout}{result.stderr}")
    if probe.exists():
        result = subprocess.run([sys.executable, str(probe)],
                                text=True, capture_output=True,
                                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        if result.returncode != 0:
            record(f"checkpoint isolation check failed: {result.stdout}{result.stderr}")
    if continuation_probe.exists():
        result = subprocess.run([sys.executable, str(continuation_probe)],
                                text=True, capture_output=True,
                                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        if result.returncode != 0:
            record(f"continuation isolation check failed: {result.stdout}{result.stderr}")
    if pi_adapter.exists():
        result = subprocess.run([sys.executable, str(pi_adapter), "self-test"],
                                text=True, capture_output=True,
                                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        if result.returncode != 0:
            record(f"Pi adapter self-test failed: {result.stdout}{result.stderr}")
    if pi_adapter_probe.exists():
        result = subprocess.run([sys.executable, str(pi_adapter_probe)],
                                text=True, capture_output=True,
                                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        if result.returncode != 0:
            record(f"Pi adapter isolation check failed: {result.stdout}{result.stderr}")
    if codex_adapter_probe.exists():
        result = subprocess.run([sys.executable, str(codex_adapter_probe)],
                                text=True, capture_output=True,
                                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        if result.returncode != 0:
            record(f"Codex CLI adapter check failed: {result.stdout}{result.stderr}")
    require(
        CORE / "assets" / "HERDR_ROLE_DISPATCH_PACKET.md",
        (
            "Checkpoint：<repo-external absolute checkpoint path | none>",
            "PREWALK_READY <lane_id> <checkpoint_path>",
            "WORKER_STOPPED <lane_id> <checkpoint_path>",
            "不发送接续请求",
        ),
    )
    require(
        CORE / "references" / "lane-registry.md",
        (
            "checkpoint_version:",
            "checkpoint_sha256:",
            "component_sha256",
            "ignored 路径只保存内容/模式指纹",
            "ready-for-coordinator",
        ),
    )
    require(
        codex_adapter,
        (
            "resume_from_checkpoint",
            "herdr-codex-pane",
            "model_reasoning_effort",
            "禁止 --last",
        ),
    )


def check_claude_adapter_contract() -> None:
    helper = CORE / "scripts" / "claude_adapter.py"
    probe = CORE / "scripts" / "claude_adapter_check.py"
    setup = SETUP / "scripts" / "model_config.py"
    for path in (helper, probe):
        if not path.exists():
            record(f"missing Claude adapter helper: {path.relative_to(ROOT)}")
    if probe.exists():
        result = subprocess.run(
            [sys.executable, str(probe)],
            text=True,
            capture_output=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        if result.returncode != 0:
            record(f"Claude adapter check failed: {result.stdout}{result.stderr}")
    if setup.exists():
        result = subprocess.run(
            [sys.executable, str(setup), "self-test"],
            text=True,
            capture_output=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        if result.returncode != 0:
            record(f"Claude dispatch caller check failed: {result.stdout}{result.stderr}")
    require(
        helper,
        (
            "resume-same-session",
            "herdr-claude-pane",
            "checkpoint/Git readback",
            "coordinator_active",
            "tui_probe",
            "effort_evidence",
            '"--resume"',
            '"--dangerously-skip-permissions"',
            '"actual_model": UNKNOWN',
            '"actual_effort": UNKNOWN',
        ),
    )
    require(
        CORE / "references" / "model-role-routing.md",
        (
            "Claude staged continuation adapter",
            "精确原生 session",
            "实际 model/effort",
            "model_config.py start",
            "resume --request <payload.json>",
        ),
    )
    require(
        setup,
        (
            "def continuation_request",
            "delivery-pipeline",
            '"resume"',
            "codex_cli_adapter.resume_from_checkpoint",
            "build_tui_switch(request)",
            'plan.get("capability") != "verified"',
        ),
    )
    require(
        CORE / "references" / "gate-state-machine.md",
        (
            "PREWALK_READY",
            "WORKER_STOPPED",
            "不新增业务 gate",
            "不提前接续或 fan-in",
        ),
    )
    require(
        CORE / "scripts" / "continuation.py",
        (
            "prepare_continuation",
            "ready_to_send",
            "record_event",
            "record_terminal",
            "record_fan_in",
            "persist-before-send",
            "dispatching",
            "send-authorized",
            "send-unknown",
        ),
    )
    require(
        CORE / "scripts" / "codex_cli_adapter.py",
        (
            "resume_from_checkpoint",
            "herdr-codex-pane",
            "model_reasoning_effort",
            "禁止 --last",
        ),
    )
    require(
        CORE / "references" / "lane-registry.md",
        (
            "continuation: <single persisted continuation overlay-or-none>",
            "`request`、`tool_acceptance`、`new_turn`、`actual_model`",
            "configuration_unchanged: true",
            "当前 `checkpoint_sha256`、`work_item` 和非空 `source`",
            "terminal.outcome: blocked",
            "`commit` 只可 `integrated`",
            "`turn_id`",
            "`readback_at`",
            "`after_marker: true`",
            "`settled: true`",
            "authorization: inherited-dispatch",
        ),
    )


def main() -> None:
    check_manifest()
    check_frontmatter()
    check_core_contract()
    check_prompt_branches()
    check_runtime_neutrality()
    check_model_contract()
    check_packets()
    check_lane_wakeup()
    check_app_shell()
    check_tree_ownership()
    check_installer()
    check_context_and_docs()
    check_pruned_policy()
    check_metadata_and_helpers()
    check_checkpoint_contract()
    check_claude_adapter_contract()

    if ERRORS:
        fail(
            f"{len(ERRORS)} violation(s):\n"
            + "\n".join(f"  - {item}" for item in ERRORS)
        )
    print("bundle: pass")


if __name__ == "__main__":
    main()
