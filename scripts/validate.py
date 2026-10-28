#!/usr/bin/env python3
import json
import os
import re
import runpy
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "skills" / "delivery-pipeline"
APP = ROOT / "skills" / "delivery-pipeline-codex-app"
ORCA = ROOT / "skills" / "delivery-pipeline-orca"
ALMA = ROOT / "skills" / "delivery-pipeline-alma"
HERDR = ROOT / "skills" / "delivery-pipeline-herdr"
T3CODE = ROOT / "skills" / "delivery-pipeline-t3code"
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
    "orca-cli",
    "orchestration",
]
MODEL_CONFIG = runpy.run_path(
    str(SETUP / "scripts" / "model_config.py"),
    run_name="__model_config_validation__",
)
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
    "superseded",
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


def is_executable(path: Path) -> bool:
    try:
        return path.is_file() and os.access(path, os.X_OK)
    except OSError:
        return False


def check_skill_links(path: Path) -> None:
    for token in re.findall(r"`([^`]+\.md)`", path.read_text()):
        if token.startswith(("references/", "assets/", "../")):
            target = (path.parent / token).resolve()
            if not target.exists():
                record(f"missing reference from {path.relative_to(ROOT)}: {token}")


def check_manifest() -> None:
    try:
        manifest = json.loads((ROOT / "skill-bundle.json").read_text())
    except (OSError, json.JSONDecodeError) as error:
        record(f"bundle manifest is unreadable: {error}")
        return
    if manifest.get("format") != "multi-runtime-skill-bundle/v2":
        record("bundle format must be multi-runtime-skill-bundle/v2")
    if manifest.get("name") != "delivery-pipeline":
        record("bundle name mismatch")
    if manifest.get("entrypoints") != {
        "cli": "skills/delivery-pipeline/SKILL.md",
        "herdr": "skills/delivery-pipeline-herdr/SKILL.md",
        "codexApp": "skills/delivery-pipeline-codex-app/SKILL.md",
        "orca": "skills/delivery-pipeline-orca/SKILL.md",
        "t3code": "skills/delivery-pipeline-t3code/SKILL.md",
        "alma": "skills/delivery-pipeline-alma/SKILL.md",
        "setup": "skills/delivery-pipeline-setup/SKILL.md",
    }:
        record("v2 entrypoints mismatch")
    if manifest.get("install") != {
        "sharedSkillDirectory": "skills/delivery-pipeline",
        "herdrSkillDirectory": "skills/delivery-pipeline-herdr",
        "codexAppSkillDirectory": "skills/delivery-pipeline-codex-app",
        "orcaSkillDirectory": "skills/delivery-pipeline-orca",
        "t3codeSkillDirectory": "skills/delivery-pipeline-t3code",
        "almaSkillDirectory": "skills/delivery-pipeline-alma",
        "setupSkillDirectory": "skills/delivery-pipeline-setup",
    }:
        record("v2 install directories mismatch")
    if [item.get("name") for item in manifest.get("requires") or []] != DEPENDENCIES:
        record("dependency order mismatch")


def check_frontmatter() -> None:
    expected = (
        (CORE / "SKILL.md", "delivery-pipeline"),
        (HERDR / "SKILL.md", "delivery-pipeline-herdr"),
        (APP / "SKILL.md", "delivery-pipeline-codex-app"),
        (ORCA / "SKILL.md", "delivery-pipeline-orca"),
        (T3CODE / "SKILL.md", "delivery-pipeline-t3code"),
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
            "canonical 核心链路",
            "当前调用会话就是 coordinator",
            "不切换 coordinator 当前目录的 branch",
            "scripts/model_config.py validate <config>",
            "version 5",
            "agent`、`model`、`effort`",
            "Dispatch Handoff",
            "Execution Worktree",
            "Integration",
            "delivery-pipeline-herdr",
            "references/code-review-evidence-preflight.md",
            "fixed point（commit 为 Execution base，verdict 为 map registry base）",
            "Review Evidence Bundle",
            "不静默回落",
        ),
    )
    require(
        HERDR / "SKILL.md",
        (
            "先完整读取 canonical 主干",
            "coordinator_runtime: pi-cli | codex-cli | claude-cli",
            "dispatch_runtime: herdr",
            "只有用户显式要求新 Workspace 才创建",
            "assets/HERDR_ROLE_DISPATCH_PACKET.md",
        ),
    )
    require(
        HERDR / "references" / "dispatch-runtime-routing.md",
        (
            "worker kind 完全由 version 5 work config",
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
        HERDR / "references" / "pane-lifecycle-rules.md",
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
        HERDR / "references" / "dispatch-runtime-routing.md": (
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
        ROOT / "GLOSSARY.md": ("HITL lanes get a `G-#<ticket>` tab",),
        HERDR / "references" / "pane-lifecycle-rules.md": (
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
            "Task Binding",
            "| AFK discovery/research、spec、tickets gate worker | `planning` | `artifact` |",
            "| grilling/prototype HITL | `design` | `artifact` |",
            "| design implementation | `design` | `commit` |",
            "| frontend implementation | `frontend` | `commit` |",
            "| backend/other implementation | `backend` | `commit` |",
            "| whole-change tests | `testing` | `checks` |",
            "| code review | review 矩阵（见下） | `verdict` |",
            "落点拓扑、容量、worker kind 映射与 packet 模板只按所属壳的合同执行",
            "整批成功 lanes 完成 startup",
            "按所属壳的 terminal-signal 合同建立唤醒通道",
        ),
    )
    registry = CORE / "references" / "lane-registry.md"
    require(
        registry,
        (
            "<!-- wayfinder-lane-registry:v2 -->",
            "role: planning | design | frontend | backend | testing | review | map",
            "output_mode: commit | artifact | checks | verdict | none",
            "runtime: herdr-pi-pane | herdr-codex-pane | herdr-claude-pane | t3-task | orchestrator | orca",
            "coordinator_runtime: pi-cli | codex-cli | claude-cli | t3code | orca-terminal | none",
            "dispatch_runtime: herdr | t3code | orca | none",
            "orca: <opaque-overlay-or-none>",
            "Orca worker 使用 `runtime: orca`，map 仍使用 `runtime: orchestrator`",
            "两者都显式记录 `dispatch_runtime: orca`",
            "按持久化的 `runtime` 与 `dispatch_runtime` 选择原 transport",
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
        HERDR / "references" / "child-monitoring.md",
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
        HERDR / "references" / "dispatch-runtime-routing.md",
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
    schema_doc = CORE / "references" / "model-config-schema.md"
    require(
        schema_doc,
        (
            "version 5",
            "任务类型",
            "codex-app",
            "alma",
            "default_mode",
            "modes",
            "starting",
            "execution",
            "direct",
            "本票 → map → 配置 `default_mode`",
            "未知 key 拒绝",
            "legacy_execution",
            "migrate",
            "Transport 必需集",
            "standards",
            "spec",
            "skill 与 reference 不提供默认 agent/model/effort",
            "`pi|codex|claude|codex-app|alma`",
        ),
    )
    schema = extract_schema_example(schema_doc)
    if schema.get("version") != 5:
        record("model config schema version must be 5")
    if not {"work", "modes", "review"} <= set(schema):
        record("model config schema example must define work/modes/review")
    routing = CORE / "references" / "model-role-routing.md"
    require(
        routing,
        (
            "model-config-schema.md",
            "version 5",
            "migrate",
            "default_mode",
            "默认计划来自本任务类型的 work 项",
            "不得把起步模型的请求回显当成执行模型已运行",
            "agent`、`model`、`effort`",
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
            "Setup 只允许从这些 `*_MODEL` / `ANTHROPIC_MODEL` / `CLAUDE_CODE_SUBAGENT_MODEL` 候选中选择",
            "settings.json env 候选与 CLI effort 枚举",
            '--approve --model "$model" --thinking "$effort"',
            "model_reasoning_effort",
            '--model "$model" --effort "$effort"',
        ),
    )
    if (
        "orchestration" in routing.read_text()
        or "orchestration" in (SETUP / "SKILL.md").read_text()
    ):
        record("coordinator/orchestration must not appear as a configured worker task")
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
            "version 5",
            "default_mode",
            "starting/execution/direct",
            "显式点名 mode 时整体覆盖",
            "不能静默生成 direct 启动请求",
            "不派发 lane",
            "../delivery-pipeline/references/model-config-schema.md",
            "../delivery-pipeline/references/model-role-routing.md",
            "scripts/model_config.py validate",
            "scripts/model_config.py migrate",
            "配置结构与实时 evidence 都通过",
            "非法配置进入初始化",
            "合法配置仅在用户明确要求重配时覆盖",
            "不提供内置默认",
            "用户明确选择全部必需项",
            "写入并 readback",
            "~/.config/delivery-pipeline/model-roles.json",
        ),
    )
    config_validator = SETUP / "scripts" / "model_config.py"
    # pi-lens-ignore: unchecked-throwing-call-python
    if not is_executable(config_validator):
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
    packet = HERDR / "assets" / "HERDR_ROLE_DISPATCH_PACKET.md"
    require(
        packet,
        (
            "lane-registry.md",
            "version 5",
            "implementation mode/source 与阶段计划",
            "双轴 review 由 worker",
            "implementation fixed point",
            "whole-change 为 map registry base",
            "preflight bundle 完成前不派生 Standards/Spec 子审查",
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


def check_handoff_contract() -> None:
    registry = CORE / "references" / "lane-registry.md"
    content = registry.read_text()
    for title, expected in (
        ("派发模板", ("Lane ID", "Work item", "执行", "Owner", "Registry", "现场", "范围", "验收", "输入", "Worker 合同")),
        ("终态模板", ("Lane ID", "状态", "交付", "证据", "现场", "确认", "阻断", "下一步")),
        ("恢复模板", ("Map/Spec", "Registry", "Gate/状态", "现场", "证据", "下一步")),
    ):
        section = re.search(r"^### " + title + r"\n(.*?)(?=^### |^## |\Z)", content, re.M | re.S)
        block = re.search(r"```text\n(.*?)\n```", section[1], re.S) if section else None
        actual = tuple(line.split("：", 1)[0] for line in block[1].splitlines() if "：" in line) if block else ()
        if actual != expected:
            record(f"fixed handoff fields mismatch: {title}: {actual}")
    require(registry, (
        "FINAL_REPORT_BEGIN", "FINAL_REPORT_END", "Owner SKILL.md",
        "frontmatter name + resolved path", "to-spec、to-tickets、ticket-sizing 与用户确认",
        "请求值和实际模型 readback 分开留证", "三个固定模板", "不扩展交接字段",
        "cwd 必须为属于 Source repo 的 Execution Worktree", "HEAD 包含 base",
        "Review 的证据须可恢复 scope、owner、fixed point、HEAD、bundle",
    ))
    require(
        CORE / "references" / "lane-registry.md",
        (
            "## 轻量交接",
            "机器字段与指纹保持原合同",
            "Unknown、失败、权限与未决事项显式保留",
            "指针包含绝对路径或 tracker URL、读取条件、定点或字段",
            "helper 校验完整输入，模型只接收判定与必要字段",
            "写入 readback 仍逐项比较 expected/actual",
            "文件级哈希、component/checkpoint SHA256 和 ignored 指纹清单只留在机器工件",
            "base/head/交付 commit 的 Git SHA 保留为版本坐标",
        ),
    )
    for shell, filename, expected in (
        (HERDR, "HERDR_ROLE_DISPATCH_PACKET.md", ("Coordinator pane", "Worker pane")),
        (APP, "APP_ROLE_DISPATCH_PACKET.md", ("Coordinator task", "Coordinator host", "Terminal 回传合同")),
        (ORCA, "ORCA_ROLE_DISPATCH_PACKET.md", ("Orca runtime/host/terminal", "Coordinator terminal")),
    ):
        path = shell / "assets" / filename
        require(
            path,
            (
                "仅展开当前分支",
                "省略不适用项",
                "轻量交接",
                "## Worker 执行",
                "../../delivery-pipeline/references/lane-registry.md",
            ),
        )
        blocks = re.findall(r"```text\n(.*?)\n```", path.read_text(), re.S)
        actual = tuple(line.split("：", 1)[0] for line in blocks[0].splitlines()) if len(blocks) == 1 else ()
        if actual != expected:
            record(f"fixed transport fields mismatch: {filename}: {actual}")
        check_skill_links(path)
    require(
        CORE / "references" / "code-review-evidence-preflight.md",
        ("先读 fixed-point.txt、changed-paths.txt、worktree-state.txt", "按当前轴读取",
         "diff.patch 起始行号", "spec source 全部以绝对路径"),
    )


def read_contract_section(path: Path, title: str) -> str:
    """按标题读取完整章节，子节随父节加载；供合同检查与容量回放共用。"""
    text = path.read_text()
    headings = list(re.finditer(r"^(#{1,6}) (.+)$", text, re.M))
    matches = [h for h in headings if h[2] == title]
    if len(matches) != 1:
        raise ValueError(f"章节不唯一或缺失: {path.name} §{title}")
    start = matches[0]
    end = next((h.start() for h in headings if h.start() > start.start() and len(h[1]) <= len(start[1])), len(text))
    return text[start.start():end]


def check_context_loading() -> None:
    packet = APP / "assets" / "APP_ROLE_DISPATCH_PACKET.md"
    try:
        table = read_contract_section(packet, "按分支加载")
        branches = {}
        for line in table.splitlines():
            cells = line.split("|")
            if len(cells) != 4:
                continue
            key = cells[1].strip()
            refs = re.findall(r"`([^`]+\.md)` §([^；|\n]+)", cells[2])
            if refs:
                branches[key] = "\n".join(read_contract_section((packet.parent / p).resolve(), h.strip()) for p, h in refs)
        if set(branches) != {"全部", "commit", "staged", "planning", "内部委派", "正式 Review"}:
            raise ValueError("App 加载表缺少角色或阶段")
        direct = branches["全部"] + branches["commit"] + read_contract_section(packet, "Worker 执行")
        for required in ("Owner SKILL.md", "HEAD 包含 base", "to-spec", "ticket-sizing", "send_message_to_thread", "Unknown", "phase: executing"):
            if required not in direct:
                raise ValueError(f"direct 缺少必要合同: {required}")
        for unrelated in ("### Prewalk 接续", "legacy_checkpoint: true", "## 创建", "## 恢复、Archive 与 Cleanup"):
            if unrelated in direct:
                raise ValueError(f"direct 多加载分支: {unrelated}")
        for required in ("PREWALK_READY", "同一个 threadId/hostId", "不能盲目重发", "canonical build/write/read"):
            if required not in branches["staged"]:
                raise ValueError(f"staged 缺少恢复合同: {required}")
        for required in ("Standards/Spec", "Review Evidence Bundle", "blocking_findings", "不验证宿主来源真实性"):
            if required not in branches["正式 Review"]:
                raise ValueError(f"Review 缺少审查证据: {required}")
        if "外层 task terminal 后" in branches["正式 Review"]:
            raise ValueError("Review 多加载 coordinator output-mode fan-in")
        if "用户确认" not in branches["planning"] or "宿主更低上限仍优先" not in branches["内部委派"]:
            raise ValueError("planning/内部委派的必要边界缺失")
    except (OSError, ValueError) as error:
        record(str(error))
    require(CORE / "references" / "fresh-session-boundaries.md", (
        "## Coordinator Recovery", "全部 active writers", "独有业务约束", "原始审查", "不能代替",
        "原 task/session", "2k", "新事实", "先持久化", "原证据", "逐项 readback",
        "合同入口", "scripts/recovery_record.py show", "scripts/recovery_record.py set",
        "实时状态只从", "跨 map 教训",
    ))
    require(CORE / "SKILL.md", ("只读恢复记录的合同入口",))
    require(CORE / "references" / "lane-registry.md", ("合同入口 <file>§<section>", "artifacts_root"))
    require(CORE / "references" / "gate-state-machine.md", ("lane_graph.py --registry-root", "--format text"))
    if "worker 完整读这些当前入口" in (APP / "references" / "development-mode.md").read_text():
        record("App worker 仍被要求整读所有调度入口")
    for shell, name in ((HERDR, "HERDR_ROLE_DISPATCH_PACKET.md"), (ORCA, "ORCA_ROLE_DISPATCH_PACKET.md")):
        require(shell / "assets" / name, ("Worker 共同行为与终态模板", "完整 owner", "实施前置检查"))


def check_lane_wakeup() -> None:
    packet = HERDR / "assets" / "HERDR_ROLE_DISPATCH_PACKET.md"
    require(
        packet,
        (
            "LANE_DONE <lane_id>",
            "公共终态模板",
        ),
    )
    lifecycle = HERDR / "references" / "pane-lifecycle-rules.md"
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
    watcher = HERDR / "scripts" / "lane-watch.sh"
    if not watcher.exists():
        record("missing lane watcher: skills/delivery-pipeline-herdr/scripts/lane-watch.sh")
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
    subprocess.run(
        [sys.executable, str(HERDR / "scripts" / "lane_watch_check.py")], check=True
    )


def check_app_shell() -> None:
    require(
        APP / "references" / "codex-app-dispatch.md",
        (
            "scripts/prewalk.py review",
            "独立 Review 放行",
            "不验证宿主来源真实性",
            "review_scope: implementation | whole-change",
        ),
    )
    require(
        APP / "assets" / "APP_ROLE_DISPATCH_PACKET.md",
        (
            "review_scope: implementation",
            "review_scope: whole-change",
            "不写 completed",
            "不能把 blocked 当作无需处理",
        ),
    )
    if not is_executable(APP / "scripts" / "prewalk.py"):
        record("App prewalk helper must be executable")
    subprocess.run(
        [sys.executable, str(APP / "scripts" / "check_prewalk.py")], check=True
    )
    require(APP / "SKILL.md", ("每次调用的执行核验", "subagent 入口"))
    require(
        APP / "references" / "development-mode.md",
        (
            "scripts/prewalk.py coordinator",
            "scripts/prewalk.py subagent",
            "active_count",
            "invoke-owner",
            "宿主更低上限仍优先",
            "不改其他 repo 或全局配置",
            "每次启动或恢复前",
            "work.coordinator",
            "用户明确选择优先",
            "该入口不限制模型",
            "canonical build/write/read",
            "legacy_checkpoint: true",
            "review_scope: implementation | whole-change",
        ),
    )
    require(
        APP / "assets" / "APP_ROLE_DISPATCH_PACKET.md",
        (
            "config_path",
            "../scripts/prewalk.py",
            "每次调用的执行核验",
        ),
    )
    # App 请求值与运行证据分离；这只是提示合同检查。
    require(
        APP / "references" / "development-mode.md",
        (
            "config/models.json",
            "review_models",
            "model_override",
            "second opinion",
            "reasoning_effort",
            "thinking",
            "Testing 与 Integration 分两次串行",
            "service tier 沿宿主默认",
            "不启用 fast",
            "用户确认",
            "只读",
        ),
    )
    require(
        ROOT / ".codex" / "config.toml",
        (
            "enabled = true",
            "max_concurrent_threads_per_session = 3",
        ),
    )
    for path in [
        APP / "SKILL.md",
        APP / "scripts/prewalk.py",
        *APP.glob("references/*.md"),
        APP / "assets/APP_ROLE_DISPATCH_PACKET.md",
        ROOT / ".codex/config.toml",
    ]:
        if re.search(
            r"gpt-\d|default_subagent_model\s*=|default_subagent_reasoning_effort\s*=",
            path.read_text(),
        ):
            record(
                f"App 模型值必须只存在于 config/models.json: {path.relative_to(ROOT)}"
            )
    # 仅验证 App 接续合同完整性；不证明宿主已执行模型切换。
    require(
        APP / "references" / "development-mode.md",
        (
            "default_mode",
            "phase_plan",
            "phase_targets",
            "execution_target",
            "PREWALK_READY",
            "send_message_to_thread",
            "phase: switching",
            "不能盲目重发",
            "尚未做 App 端到端模型 readback",
            "`evaluate_signal`",
        ),
    )
    require(
        APP / "references" / "codex-app-dispatch.md",
        (
            "development_mode:",
            "mode_source:",
            "execution_phase:",
            "checkpoint:",
            "## Prewalk 中间回传",
            "不进入 Terminal fan-in",
        ),
    )
    require(
        APP / "assets" / "APP_ROLE_DISPATCH_PACKET.md",
        (
            "公共模板的 Registry",
            "phase_plan/phase_targets/execution_target",
            "恢复沿原冻结计划和 checkpoint",
            "PREWALK_READY 后停止",
        ),
    )
    require(APP / "SKILL.md", ("references/development-mode.md",))
    require(
        APP / "references" / "codex-app-dispatch.md",
        (
            "requested_model:",
            "requested_effort:",
            "model: Unknown",
            "effort: Unknown",
            "model_evidence: Unknown",
            "checkpoint_sha256:",
            "旧 lane",
        ),
    )
    require(
        APP / "assets" / "APP_ROLE_DISPATCH_PACKET.md",
        (
            "传当前请求值",
            "../references/development-mode.md",
            "review_scope: implementation",
            "review_scope: whole-change",
        ),
    )
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
        for phrase in (
            "正式 Astra Review",
            "implementation 两轴使用 Astra",
            "whole-change 两轴使用 Sol",
        ):
            if phrase in content:
                record(
                    f"App formal Review hard-codes owner model: {path.relative_to(ROOT)}: {phrase}"
                )
        for lineno, line in enumerate(content.splitlines(), 1):
            if formal_review_model.search(line):
                record(
                    f"App formal Review hard-codes owner model: {path.relative_to(ROOT)}:{lineno}"
                )
    require(
        APP / "SKILL.md",
        (
            "薄 delta",
            "../delivery-pipeline/SKILL.md",
            "coordinator_runtime: codex-app",
            "dispatch_runtime: codex-app",
            "config/models.json",
            "version 5",
            "canonical 任务类型与 output mode 保持不变",
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
            "公共终态模板",
            "../../delivery-pipeline/references/lane-registry.md",
            "owner 三字段",
            "preflight 绝对路径",
            "preflight bundle 完成前不派生 Standards/Spec 子审查",
        ),
    )
    for path in (APP / "SKILL.md", APP / "references" / "codex-app-dispatch.md"):
        check_skill_links(path)


def check_orca_contract() -> None:
    preflight = ORCA / "scripts" / "preflight.py"
    require(
        ORCA / "SKILL.md",
        (
            "严格绑定 Orca",
            "ORCA_CLI_COMMAND",
            "skills get orca-cli",
            "skills get orchestration",
            "agent-context",
            "skills installed --json",
            "scripts/preflight.py run",
            "model_config.py",
            "dispatch unavailable",
            "preflight-ready",
            "authority: false",
            "caller-declared",
            "target_host",
            "target + runtimeId",
            "实际读取命令",
            "not-run/Unknown",
            "registry_overlay.py apply",
            "record_native_coordinates",
            "record_readback",
            "不 fallback 到 Herdr 或 Codex App",
            "ORCA_ROLE_DISPATCH_PACKET.md",
            "orca-dispatch.md",
            "worker_lifecycle.py",
            "worker-start",
            "Execution Worktree",
            "FIFO",
            "worker-list",
            "project_lane_transition",
            "lane_cleanup_audit.py",
            "coordinator_terminal_handle",
            "唤醒责任在发送方",
        ),
    )
    require(
        preflight,
        (
            "resolve_orca_executable",
            "ORCA_SKILL_NAME",
            'path.name != "SKILL.md"',
            '"skills", "get", name, "--full"',
            '"agent-context"',
            '"status"',
            '"skills", "installed"',
            '"terminal", "show"',
            "MODEL_CONFIG",
            '"resolve"',
            '"freeze"',
            '"dispatch": "unavailable"',
            '"dispatch": "preflight-ready"',
            '"authority": False',
            '"fallback": False',
            "caller-declared; coordinator must validate native provenance",
            "目标 host identity",
            '"executable": executable',
            "shared agent/model/effort runtime readback",
            "staged native same-session capability",
        ),
    )
    overlay = ORCA / "scripts" / "registry_overlay.py"
    require(
        overlay,
        (
            "empty_overlay",
            "validate_overlay",
            "persist_overlay",
            "bind_map_run",
            "rebind_map_coordinator",
            "bind_lane_task",
            "bind_attempt",
            "record_mutation",
            "record_observation",
            "record_native_coordinates",
            "record_readback",
            "record_state",
            "STATE_PRIORS",
            "recover_map",
            "recover_lane",
            "recover_attempt",
            "apply_request",
            'sys.argv[1] == "apply"',
            "不从当前环境推断",
            "保留旧证据，不覆盖",
        ),
    )
    packet = ORCA / "assets" / "ORCA_ROLE_DISPATCH_PACKET.md"
    require(
        packet,
        (
            "# Orca 本地 worker dispatch packet",
            "冻结配置与完整 overlay 留在原 registry",
            "../references/orca-dispatch.md",
            "worker_done",
        ),
    )
    reference = ORCA / "references" / "orca-dispatch.md"
    require(
        reference,
        (
            "# Orca dispatch 与本地 worker 合同",
            "task-create",
            "worker-start",
            "worker-start` receipt",
            "`worker-show` readback",
            "Execution Worktree",
            "`deliveryId`",
            "sender terminal",
            "check --run <run_id> --wait",
            "check --ack <delivery_id>",
            "唤醒责任在发送方",
            "coordinator_terminal_handle",
            "worker-list --run <run_id>",
            "project lane integrated/closed",
            "project_lifecycle.py",
            "project-side",
            "project_lane_transition: unchanged",
            "Integration conflict",
            "close_pending",
            "archive/output readback",
            "git branch readback",
            "deduplicated",
            "lane_cleanup_audit.py",
        ),
    )
    audit_script = ORCA / "scripts" / "lane_cleanup_audit.py"
    require(
        audit_script,
        (
            "CANONICAL_STATES",
            "DONE_STATES",
            "def audit",
            "--registry-dir",
            "--self-test",
            "非 canonical state",
            "lane-registry.md",
        ),
    )
    if not is_executable(audit_script):
        record("Orca lane cleanup audit helper must exist and remain executable")
    else:
        result = subprocess.run(
            [sys.executable, str(audit_script), "--self-test"],
            text=True,
            capture_output=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        if result.returncode != 0:
            record(
                f"Orca lane cleanup audit self-test failed: {result.stdout}{result.stderr}"
            )
    lifecycle = ORCA / "scripts" / "worker_lifecycle.py"
    require(
        lifecycle,
        (
            "validate_startup",
            "validate_settlement",
            "bind_startup",
            "record_settlement",
            "worker-start",
            "worker_done",
            "worker-list",
            "requested_source",
            "effective_source",
            "integration_worktree",
            "bindings",
            "attempt_index",
            "retryOfDispatchId",
            "previous_attempt",
            "requested_source",
            "effective_source",
            "persistence_reference",
            "delivery_request_id",
            "ack_source",
            "post_ack_worker_list",
            "message_id",
            "fan_in_keys",
            "ack_id",
            "project_lane_transition",
            '"authority": False',
        ),
    )
    if not is_executable(lifecycle):
        record("Orca worker lifecycle helper must exist and remain executable")
    else:
        result = subprocess.run(
            [sys.executable, str(lifecycle), "self-test"],
            text=True,
            capture_output=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        if result.returncode != 0:
            record(
                f"Orca worker lifecycle self-test failed: {result.stdout}{result.stderr}"
            )
    project_lifecycle = ORCA / "scripts" / "project_lifecycle.py"
    require(
        project_lifecycle,
        (
            "validate_project_fan_in",
            "validate_cleanup",
            "project-fan-in",
            "worker-release",
            "archive-readback",
            "worktree-rm",
            "git-branch-readback",
            "integration_conflict",
            "integration_checks_failed",
            "close_pending",
            "deduplicated",
            "project_lane_transition",
            "authority",
            "不执行 Git",
        ),
    )
    if not is_executable(project_lifecycle):
        record("Orca project lifecycle helper must exist and remain executable")
    else:
        result = subprocess.run(
            [sys.executable, str(project_lifecycle), "self-test"],
            text=True,
            capture_output=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        if result.returncode != 0:
            record(
                f"Orca project lifecycle self-test failed: {result.stdout}{result.stderr}"
            )
    recovery = ORCA / "scripts" / "recovery.py"
    recovery_check = ORCA / "scripts" / "recovery_check.py"
    require(
        ORCA / "SKILL.md", ("references/orca-recovery.md", "scripts/recovery.py check")
    )
    require(
        ORCA / "references" / "orca-recovery.md",
        (
            "request-show",
            "retry-same-task",
            "not-run/Unknown",
            "worker-start --terminal",
            "continuation.record_event",
            "不发最终 `worker_done`",
        ),
    )
    for path in (recovery, recovery_check):
        if not is_executable(path):
            record(
                f"Orca recovery helper must exist and remain executable: {path.name}"
            )
    if recovery_check.exists():
        result = subprocess.run(
            [sys.executable, str(recovery_check)],
            text=True,
            capture_output=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        if result.returncode != 0:
            record(f"Orca recovery check failed: {result.stdout}{result.stderr}")
    browser_gate = ORCA / "scripts" / "browser_gate.py"
    browser_gate_check = ORCA / "scripts" / "browser_gate_check.py"
    require(
        ORCA / "SKILL.md",
        ("references/orca-browser-automation.md", "scripts/browser_gate.py check"),
    )
    require(
        ORCA / "references" / "orca-browser-automation.md",
        (
            "readback-first",
            "phase2-operation-only",
            "not-run/Unknown",
            "browser.screencast.v1",
            "consume-existing-automation",
        ),
    )
    for path in (browser_gate, browser_gate_check):
        if not is_executable(path):
            record(
                f"Orca browser gate helper must exist and remain executable: {path.name}"
            )
    if browser_gate_check.exists():
        result = subprocess.run(
            [sys.executable, str(browser_gate_check)],
            text=True,
            capture_output=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        if result.returncode != 0:
            record(f"Orca browser gate check failed: {result.stdout}{result.stderr}")
    provider_gate = ORCA / "scripts" / "provider_mutation.py"
    provider_gate_check = ORCA / "scripts" / "provider_mutation_check.py"
    require(
        ORCA / "SKILL.md",
        (
            "references/orca-provider-mutation.md",
            "scripts/provider_mutation.py check",
        ),
    )
    require(
        ORCA / "references" / "orca-provider-mutation.md",
        (
            "readback-first",
            "phase2-operation-only",
            "not-run/Unknown",
            "consume-existing-mutation",
            "deduplicated",
        ),
    )
    for path in (provider_gate, provider_gate_check):
        if not is_executable(path):
            record(
                f"Orca provider mutation gate helper must exist and remain executable: {path.name}"
            )
    if provider_gate_check.exists():
        result = subprocess.run(
            [sys.executable, str(provider_gate_check)],
            text=True,
            capture_output=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        if result.returncode != 0:
            record(
                f"Orca provider mutation gate check failed: {result.stdout}{result.stderr}"
            )
    publication_gate = ORCA / "scripts" / "remote_publication.py"
    publication_gate_check = ORCA / "scripts" / "remote_publication_check.py"
    require(
        ORCA / "SKILL.md",
        (
            "references/orca-remote-publication.md",
            "scripts/remote_publication.py check",
        ),
    )
    require(
        ORCA / "references" / "orca-remote-publication.md",
        (
            "readback-first",
            "phase4-publication-only",
            "not-run/Unknown",
            "consume-existing-pr",
            "deduplicated",
            "close_pending",
        ),
    )
    for path in (publication_gate, publication_gate_check):
        if not is_executable(path):
            record(
                f"Orca remote publication gate helper must exist and remain executable: {path.name}"
            )
    if publication_gate_check.exists():
        result = subprocess.run(
            [sys.executable, str(publication_gate_check)],
            text=True,
            capture_output=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        if result.returncode != 0:
            record(
                f"Orca remote publication gate check failed: {result.stdout}{result.stderr}"
            )
    if not is_executable(overlay):
        record("Orca registry overlay helper must exist and remain executable")
    else:
        result = subprocess.run(
            [sys.executable, str(overlay), "self-test"],
            text=True,
            capture_output=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        if result.returncode != 0:
            record(
                f"Orca registry overlay self-test failed: {result.stdout}{result.stderr}"
            )
    if not is_executable(preflight):
        record("Orca preflight helper must exist and remain executable")
    else:
        result = subprocess.run(
            [sys.executable, str(preflight), "self-test"],
            text=True,
            capture_output=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        if result.returncode != 0:
            record(f"Orca preflight self-test failed: {result.stdout}{result.stderr}")
    check_skill_links(ORCA / "SKILL.md")


def check_t3code_contract() -> None:
    for path in (
        T3CODE / "SKILL.md",
        T3CODE / "references" / "t3code-dispatch.md",
        T3CODE / "references" / "t3code-lifecycle.md",
        T3CODE / "assets" / "T3CODE_ROLE_DISPATCH_PACKET.md",
    ):
        check_skill_links(path)
    require(
        T3CODE / "SKILL.md",
        (
            "coordinator_runtime: t3code",
            "dispatch_runtime: t3code",
            'delegate_task(mode:"async", isolation:"worktree")',
            "`t3-task`",
            "coordinator 留在 Source Worktree",
            "staged 计划保持 `blocked`",
            "existing lane 始终按 registry runtime 恢复",
        ),
    )
    require(
        T3CODE / "references" / "t3code-dispatch.md",
        (
            "orchestrator_capabilities",
            "t3_worktree_status",
            "`attached: false`",
            "model_evidence: t3-capabilities",
            "`claudeAgent`",
            "`reasoningEffort`",
            "配置值原样使用",
            "t3 staged adapter unavailable",
            "clientRequestId: <lane_id>",
            "implementation_gate.py",
            "结束本轮",
        ),
    )
    require(
        T3CODE / "references" / "t3code-lifecycle.md",
        (
            "`task_status` 只读本线程派发的任务",
            "LANE_DONE <lane_id>",
            "hasPendingQuestion",
            "t3_pending_request",
            't3_thread_organize(threadId: child_thread_id, action: "archive")',
            "git worktree remove",
            "close_pending",
            "release_stage: deployed",
            "完成唤醒只投递给 `coordinator_thread_id`",
            "task_cancel(task_id)",
        ),
    )
    require(
        T3CODE / "assets" / "T3CODE_ROLE_DISPATCH_PACKET.md",
        (
            "lane-registry.md",
            "git switch --detach <base_sha>",
            "git rev-parse --git-common-dir",
            "preflight bundle 完成前不派生",
            "宿主原生 subagent",
            "LANE_DONE <lane_id>",
            "T3 初始分支",
        ),
    )
    t3_only = re.compile(
        r"delegate_task|task_status|t3_thread_|t3_worktree_|t3_pending_request|"
        r"orchestrator_capabilities"
    )
    for root in (CORE, SETUP, HERDR, APP, ORCA):
        for path in sorted(root.rglob("*.md")):
            for lineno, line in enumerate(path.read_text().splitlines(), 1):
                if t3_only.search(line):
                    record(
                        f"T3Code transport leaked outside its shell: {path.relative_to(ROOT)}:{lineno}"
                    )


def check_alma_shell() -> None:
    """ADR-0015：Alma Task transport 壳的硬约束。"""
    config = ALMA / "config" / "models.json"
    if not config.exists():
        record("Alma config must exist at skills/delivery-pipeline-alma/config/models.json")
    else:
        try:
            doc = json.loads(config.read_text())
        except json.JSONDecodeError as error:
            record(f"invalid JSON in Alma config: {error}")
        else:
            errors = MODEL_CONFIG["validate_document"](doc, "alma")
            if errors:
                record(f"Alma config validation failed: {errors}")
    require(
        ALMA / "SKILL.md",
        (
            "coordinator_runtime: alma-ui",
            "dispatch_runtime: alma-task",
            "agent: alma",
            "references/alma-dispatch.md",
            "config/models.json",
        ),
    )
    require(
        ALMA / "references" / "alma-dispatch.md",
        (
            "kind: direct",
            "resume 不保留上下文（ADR-0015）",
            "effort 只记录请求值（ADR-0015）",
            "coordinator cwd",
        ),
    )
    dispatch = ALMA / "references" / "alma-dispatch.md"
    if dispatch.exists():
        content = dispatch.read_text()
        if re.search(r"\bstaged\b.*mode", content, re.IGNORECASE):
            record(
                f"{dispatch.relative_to(ROOT)} 提及 staged，但 Alma resume 无上下文（ADR-0015）"
            )
    check_skill_links(ALMA / "SKILL.md")


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
    for path in (
        CORE / "assets" / "HERDR_ROLE_DISPATCH_PACKET.md",
        CORE / "references" / "pane-lifecycle-rules.md",
        CORE / "references" / "dispatch-runtime-routing.md",
        CORE / "references" / "child-monitoring.md",
        CORE / "scripts" / "lane-watch.sh",
        CORE / "scripts" / "lane_watch_check.py",
    ):
        if path.exists():
            record(
                f"Herdr-owned file leaked into canonical core: {path.relative_to(ROOT)}"
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
            'link_skill "$ROOT/skills/delivery-pipeline-herdr"',
            '"$CODEX_HOME_DIR/skills/delivery-pipeline-herdr"',
            '"$CLAUDE_HOME_DIR/skills/delivery-pipeline-herdr"',
            '"$PI_HOME_DIR/agent/skills/delivery-pipeline-herdr"',
            'link_skill "$ROOT/skills/delivery-pipeline-orca"',
            '"$CODEX_HOME_DIR/skills/delivery-pipeline-orca"',
            '"$CLAUDE_HOME_DIR/skills/delivery-pipeline-orca"',
            '"$PI_HOME_DIR/agent/skills/delivery-pipeline-orca"',
            'rm -rf "$PI_HOME_DIR/agent/skills/delivery-pipeline-pi"',
            "Symlinks establish discovery only",
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
    if text.count('link_skill "$ROOT/skills/delivery-pipeline-alma"') != 1 or (
        '"$CLAUDE_HOME_DIR/skills/delivery-pipeline-alma"' not in text
    ):
        record("Alma shell must be installed exactly once into the Claude skills home")
    if text.count('link_skill "$ROOT/skills/delivery-pipeline-orca"') != 3:
        record("Orca entrypoint must be installed into exactly three agent homes")
    if text.count('link_skill "$ROOT/skills/delivery-pipeline-herdr"') != 3:
        record("Herdr shell must be installed into exactly three CLI homes")
    if text.count('link_skill "$ROOT/skills/delivery-pipeline-t3code"') != 3:
        record("T3Code shell must be installed into exactly three CLI homes")
    subprocess.run(["bash", "-n", str(install_path)], check=True)


def check_context_and_docs() -> None:
    require(
        ROOT / "GLOSSARY.md",
        (
            "Configured Planning Lane",
            "Review Evidence Bundle",
            "Reviewers consume the same bundle with read/search access",
            "Worker Task Configuration",
            "model-config-schema.md",
            "current calling session is the coordinator",
            "current calling session is the coordinator",
            "Coordinator Pane",
            "new workspace requires explicit user request",
            "map isolation belongs to Map Integration Worktrees and Execution Worktrees",
            "skills/delivery-pipeline-codex-app",
            "Orca Entrypoint",
            "skills/delivery-pipeline-orca",
            "dispatch unavailable",
            "There are no built-in agent/model/effort defaults",
            "repository file overlap is an Integration risk",
            "all lane types share the same worker-tab capacity pool",
        ),
    )
    require(
        ROOT / "AGENTS.md",
        (
            "Canonical 核心链路",
            "delivery-pipeline-codex-app",
            "delivery-pipeline-herdr",
            "Canonical 核心链路保持 runtime-neutral",
            "`codex-thread` 只存在于 delivery-pipeline-codex-app 树",
        ),
    )
    for readme in (ROOT / "README.md", ROOT / "README.zh-CN.md"):
        require(
            readme,
            (
                "delivery-pipeline-setup",
                "delivery-pipeline-codex-app",
                "delivery-pipeline-orca",
                "delivery-pipeline-herdr",
                "model-roles.json",
                "orca-cli",
                "orchestration",
                "skills installed --json",
                "caller-declared",
                "authority: false",
                "host",
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
        ROOT / "docs" / "adr" / "0009-orca-runtime-entrypoint.md",
        (
            "Status:** Accepted",
            "skills/delivery-pipeline-orca",
            "version-matched",
            "dispatch unavailable",
            "preflight-ready",
            "authority: false",
            "target + runtimeId",
            "不 fallback 到 Herdr/Codex App",
            "#121–#128",
        ),
    )
    require(
        ROOT / "docs" / "adr" / "0008-unified-task-type-config-schema.md",
        (
            "Status:** Accepted",
            "model-config-schema.md",
            "codex-app",
            "model_config.py migrate",
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
    roots = (CORE, APP, ORCA, HERDR, SETUP, TICKET_SIZING)
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
    require(
        ORCA / "agents" / "openai.yaml",
        (
            'display_name: "Delivery Pipeline (Orca)"',
            "$delivery-pipeline-orca",
            "allow_implicit_invocation: false",
        ),
    )
    # pi-lens-ignore: unchecked-throwing-call-python
    if not is_executable(ROOT / "scripts" / "validate.py"):
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
    for path in (
        helper,
        probe,
        continuation,
        continuation_probe,
        pi_adapter,
        pi_adapter_probe,
        codex_adapter,
        codex_adapter_probe,
    ):
        if not path.exists():
            record(f"missing checkpoint helper: {path.relative_to(ROOT)}")
    if helper.exists():
        result = subprocess.run(
            [sys.executable, str(helper), "self-test"], text=True, capture_output=True
        )
        if result.returncode != 0:
            record(
                f"checkpoint helper self-test failed: {result.stdout}{result.stderr}"
            )
    if probe.exists():
        result = subprocess.run(
            [sys.executable, str(probe)],
            text=True,
            capture_output=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        if result.returncode != 0:
            record(f"checkpoint isolation check failed: {result.stdout}{result.stderr}")
    if continuation_probe.exists():
        result = subprocess.run(
            [sys.executable, str(continuation_probe)],
            text=True,
            capture_output=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        if result.returncode != 0:
            record(
                f"continuation isolation check failed: {result.stdout}{result.stderr}"
            )
    if pi_adapter.exists():
        result = subprocess.run(
            [sys.executable, str(pi_adapter), "self-test"],
            text=True,
            capture_output=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        if result.returncode != 0:
            record(f"Pi adapter self-test failed: {result.stdout}{result.stderr}")
    if pi_adapter_probe.exists():
        result = subprocess.run(
            [sys.executable, str(pi_adapter_probe)],
            text=True,
            capture_output=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        if result.returncode != 0:
            record(f"Pi adapter isolation check failed: {result.stdout}{result.stderr}")
    if codex_adapter_probe.exists():
        result = subprocess.run(
            [sys.executable, str(codex_adapter_probe)],
            text=True,
            capture_output=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        if result.returncode != 0:
            record(f"Codex CLI adapter check failed: {result.stdout}{result.stderr}")
    require(
        HERDR / "assets" / "HERDR_ROLE_DISPATCH_PACKET.md",
        (
            "Prewalk Checkpoint / Continuation Overlay",
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


def check_lane_graph() -> None:
    script = CORE / "scripts" / "lane_graph.py"
    require(
        script,
        (
            "--registry-root",
            "--self-test",
            "--no-tracker",
            "--edges-json",
            "Blocked by",
            "lane-graph.html",
            "superseded",
            "渲染是派生物，不是状态",
            "--format",
            "--map",
        ),
    )
    if not is_executable(script):
        record("lane graph renderer must exist and remain executable")
    else:
        result = subprocess.run(
            [sys.executable, str(script), "--self-test"],
            text=True,
            capture_output=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        if result.returncode != 0:
            record(
                f"lane graph self-test failed: {result.stdout}{result.stderr}"
            )


def check_recovery_record() -> None:
    script = CORE / "scripts" / "recovery_record.py"
    if not is_executable(script):
        record("coordinator recovery helper must exist and remain executable: recovery_record.py")
        return
    require(script, ("show", "set", "check", "--self-test", "## Coordinator Recovery"))
    result = subprocess.run(
        [sys.executable, str(script), "--self-test"],
        text=True,
        capture_output=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    if result.returncode != 0:
        record(f"recovery_record self-test failed: {result.stdout}{result.stderr}")


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
            record(
                f"Claude dispatch caller check failed: {result.stdout}{result.stderr}"
            )
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
    check_handoff_contract()
    check_context_loading()
    check_lane_wakeup()
    check_app_shell()
    check_orca_contract()
    check_t3code_contract()
    check_alma_shell()
    check_tree_ownership()
    check_installer()
    check_context_and_docs()
    check_pruned_policy()
    check_metadata_and_helpers()
    check_checkpoint_contract()
    check_lane_graph()
    check_recovery_record()
    check_claude_adapter_contract()

    if ERRORS:
        fail(
            f"{len(ERRORS)} violation(s):\n"
            + "\n".join(f"  - {item}" for item in ERRORS)
        )
    print("bundle: pass")


if __name__ == "__main__":
    main()
