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
ORCA = ROOT / "skills" / "delivery-pipeline-orca"
HERDR = ROOT / "skills" / "delivery-pipeline-herdr"
T3CODE = ROOT / "skills" / "delivery-pipeline-t3code"
LODY = ROOT / "skills" / "delivery-pipeline-lody"
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
OUTPUT_MODES = {"commit", "artifact", "checks", "verdict", "integration", "none"}
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




def is_executable(path: Path) -> bool:
    try:
        return path.is_file() and os.access(path, os.X_OK)
    except OSError:
        return False


def check_skill_links(path: Path) -> None:
    """指针按所在文件或所属壳根解析，二者都不存在才算断链。"""
    shell = next((p for p in path.parents if p.parent.name == "skills"), path.parent)
    for token in re.findall(r"`([^`]+\.md)`", path.read_text()):
        if token.startswith(("references/", "assets/", "../")):
            if not any((base / token).resolve().exists() for base in (path.parent, shell)):
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
        "lody": "skills/delivery-pipeline-lody/SKILL.md",
        "setup": "skills/delivery-pipeline-setup/SKILL.md",
    }:
        record("v2 entrypoints mismatch")
    if manifest.get("install") != {
        "sharedSkillDirectory": "skills/delivery-pipeline",
        "herdrSkillDirectory": "skills/delivery-pipeline-herdr",
        "codexAppSkillDirectory": "skills/delivery-pipeline-codex-app",
        "orcaSkillDirectory": "skills/delivery-pipeline-orca",
        "t3codeSkillDirectory": "skills/delivery-pipeline-t3code",
        "lodySkillDirectory": "skills/delivery-pipeline-lody",
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
        (LODY / "SKILL.md", "delivery-pipeline-lody"),
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


SHELLS = (CORE, HERDR, APP, ORCA, T3CODE, LODY, SETUP)


def check_skill_trees() -> None:
    """SKILL 保持克制；每个壳的 references/assets 都能从本壳 SKILL 沿指针到达，指针目标都存在。"""
    body = (CORE / "SKILL.md").read_text().split("---", 2)[-1].strip().splitlines()
    if len(body) > 50:
        record(f"core SKILL.md body exceeds 50 lines: {len(body)}")
    core_refs = {p.name: p for p in (CORE / "references").glob("*.md")}
    for shell in SHELLS:
        docs = {p for d in ("references", "assets") for p in (shell / d).glob("*.md")}
        local = {p.name: p for p in docs}
        seen, queue = set(), [shell / "SKILL.md"]
        while queue:
            path = queue.pop()
            check_skill_links(path)
            for name in re.findall(r"([\w.-]+\.md)", path.read_text()):
                for target in (local.get(name), core_refs.get(name)):
                    if target and target not in seen:
                        seen.add(target)
                        queue.append(target)
        for orphan in sorted(docs - seen):
            record(f"{shell.name} doc unreachable from its SKILL.md: {orphan.name}")


def check_core_contract() -> None:
    check_skill_trees()
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
    registry = CORE / "references" / "lane-registry.md"
    registry_text = registry.read_text()
    schema_block = re.search(r"## Base Schema\n.*?```yaml\n(.*?)\n```", registry_text, re.S)
    lane_keys = re.findall(r"^(\w+):", schema_block[1], re.M) if schema_block else []
    if not lane_keys or len(lane_keys) > 15:
        record(f"lane row schema must stay within 15 fields: {len(lane_keys)}")
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


def check_prompt_branches() -> None:
    # 提示合同静态回归；不冒充真实 runtime 执行验收。
    gates = CORE / "references" / "gate-state-machine.md"
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
    schema = extract_schema_example(schema_doc)
    if schema.get("version") != 5:
        record("model config schema version must be 5")
    if not {"work", "modes", "review"} <= set(schema):
        record("model config schema example must define work/modes/review")
    routing = CORE / "references" / "model-role-routing.md"
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
    bundle = re.search(r"^## Review Evidence Bundle\n(.*?)(?=^## )",
                       (CORE / "references" / "code-review-evidence-preflight.md").read_text(), re.M | re.S)
    files = tuple(re.findall(r"^- `([^`]+)`", bundle[1], re.M)) if bundle else ()
    if files != ("fixed-point.txt", "diff.patch", "changed-paths.txt"):
        record(f"Review Evidence Bundle must be exactly three files: {files}")


def check_handoff_contract() -> None:
    registry = CORE / "references" / "lane-registry.md"
    content = registry.read_text()
    for title, expected in (
        ("派发模板", ("Lane ID", "Work item", "执行", "Owner", "Registry", "现场", "范围", "验收", "输入", "Worker 合同")),
        ("恢复模板", ("Map/Spec", "Registry", "Gate/状态", "现场", "证据", "下一步")),
    ):
        section = re.search(r"^### " + title + r"\n(.*?)(?=^### |^## |\Z)", content, re.M | re.S)
        block = re.search(r"```text\n(.*?)\n```", section[1], re.S) if section else None
        actual = tuple(line.split("：", 1)[0] for line in block[1].splitlines() if "：" in line) if block else ()
        if actual != expected:
            record(f"fixed handoff fields mismatch: {title}: {actual}")
    terminal = re.search(r"^### 终态行\n.*?```text\n(.*?)\n```", content, re.M | re.S)
    if not terminal or terminal[1].splitlines() != [
        "LANE_DONE <lane_id> <交付坐标>", "LANE_DONE <lane_id> BLOCKED <一句原因；失败工件绝对路径>"]:
        record("lane-registry §终态行 must be the two LANE_DONE lines")
    for shell, filename, expected in (
        (HERDR, "HERDR_ROLE_DISPATCH_PACKET.md", ("Coordinator pane", "Worker pane")),
        (APP, "APP_ROLE_DISPATCH_PACKET.md", ("Coordinator task", "Coordinator host", "Terminal 回传合同")),
        (ORCA, "ORCA_ROLE_DISPATCH_PACKET.md", ("Orca runtime/host/terminal", "Coordinator terminal")),
    ):
        path = shell / "assets" / filename
        blocks = re.findall(r"```text\n(.*?)\n```", path.read_text(), re.S)
        actual = tuple(line.split("：", 1)[0] for line in blocks[0].splitlines()) if len(blocks) == 1 else ()
        if actual != expected:
            record(f"fixed transport fields mismatch: {filename}: {actual}")
        check_skill_links(path)


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
        for required in ("Owner SKILL.md", "HEAD 包含 base", "to-spec", "send_message_to_thread", "Unknown", "phase: executing"):
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
    if "worker 完整读这些当前入口" in (APP / "references" / "development-mode.md").read_text():
        record("App worker 仍被要求整读所有调度入口")


def check_lane_wakeup() -> None:
    lifecycle = HERDR / "references" / "pane-lifecycle-rules.md"
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
    for banned in ("w26:p1", "xcodebuild", "feature/map-", "pagugu"):
        if banned in watcher_text:
            record(f"lane-watch.sh carries session-specific hardcode: {banned}")
    subprocess.run(["bash", "-n", str(watcher)], check=True)
    subprocess.run(
        [sys.executable, str(HERDR / "scripts" / "lane_watch_check.py")], check=True
    )
    subprocess.run(
        [sys.executable, str(HERDR / "scripts" / "dispatch_check.py")], check=True
    )


def check_app_shell() -> None:
    if not is_executable(APP / "scripts" / "prewalk.py"):
        record("App prewalk helper must be executable")
    subprocess.run(
        [sys.executable, str(APP / "scripts" / "check_prewalk.py")], check=True
    )
    # App 请求值与运行证据分离；这只是提示合同检查。
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
    for path in (APP / "SKILL.md", APP / "references" / "codex-app-dispatch.md"):
        check_skill_links(path)


def check_orca_contract() -> None:
    preflight = ORCA / "scripts" / "preflight.py"
    overlay = ORCA / "scripts" / "registry_overlay.py"
    audit_script = ORCA / "scripts" / "lane_cleanup_audit.py"
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
    t3_only = re.compile(
        r"delegate_task|task_status|t3_thread_|t3_worktree_|t3_pending_request|"
        r"orchestrator_capabilities"
    )
    for root in (CORE, SETUP, HERDR, APP, ORCA, LODY):
        for path in sorted(root.rglob("*.md")):
            for lineno, line in enumerate(path.read_text().splitlines(), 1):
                if t3_only.search(line):
                    record(
                        f"T3Code transport leaked outside its shell: {path.relative_to(ROOT)}:{lineno}"
                    )



def check_lody_contract() -> None:
    for path in (
        LODY / "SKILL.md",
        LODY / "references" / "lody-dispatch.md",
        LODY / "references" / "lody-lifecycle.md",
        LODY / "assets" / "LODY_ROLE_DISPATCH_PACKET.md",
    ):
        check_skill_links(path)
    lody_only = re.compile(r"\blody_(?:session|operation|agent_config)_")
    for root in (CORE, SETUP, HERDR, APP, ORCA, T3CODE):
        for path in sorted(root.rglob("*.md")):
            for lineno, line in enumerate(path.read_text().splitlines(), 1):
                if lody_only.search(line):
                    record(
                        f"Lody transport leaked outside its shell: {path.relative_to(ROOT)}:{lineno}"
                    )


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
        CORE / "scripts" / "dispatch.py",
    ):
        if path.exists():
            record(
                f"Herdr-owned file leaked into canonical core: {path.relative_to(ROOT)}"
            )


def check_installer() -> None:
    install_path = ROOT / "scripts" / "install.sh"
    text = install_path.read_text()
    if text.count('link_skill "$ROOT/skills/delivery-pipeline"') != 3:
        record(
            "canonical core must be installed from one source into exactly three CLI homes"
        )
    if text.count('link_skill "$ROOT/skills/delivery-pipeline-setup"') != 3:
        record("setup skill must be installed into exactly three CLI homes")
    if text.count('link_skill "$ROOT/skills/delivery-pipeline-codex-app"') != 1:
        record("Codex App shell must be installed exactly once")
    if text.count('link_skill "$ROOT/skills/delivery-pipeline-orca"') != 3:
        record("Orca entrypoint must be installed into exactly three agent homes")
    if text.count('link_skill "$ROOT/skills/delivery-pipeline-herdr"') != 3:
        record("Herdr shell must be installed into exactly three CLI homes")
    if text.count('link_skill "$ROOT/skills/delivery-pipeline-t3code"') != 3:
        record("T3Code shell must be installed into exactly three CLI homes")
    if text.count('link_skill "$ROOT/skills/delivery-pipeline-lody"') != 3:
        record("Lody shell must be installed into exactly three CLI homes")
    if re.search(r'^\s+"\$CODEX_HOME_DIR/skills/', text, re.M):
        record("Codex skills install into $AGENTS_HOME_DIR/skills, never $CODEX_HOME_DIR/skills")
    subprocess.run(["bash", "-n", str(install_path)], check=True)


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
    # pi-lens-ignore: unchecked-throwing-call-python
    if not is_executable(ROOT / "scripts" / "validate.py"):
        record("validator must remain executable")


def check_checkpoint_contract() -> None:
    """App Prewalk 仍用 canonical checkpoint；CLI 已无 staged 续接（ADR-0018）。"""
    helper = CORE / "scripts" / "checkpoint.py"
    probe = CORE / "scripts" / "checkpoint_check.py"
    for path in (helper, probe):
        if not path.exists():
            record(f"missing checkpoint helper: {path.relative_to(ROOT)}")
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    for args, label in (([str(helper), "self-test"], "self-test"), ([str(probe)], "isolation check")):
        if not Path(args[0]).exists():
            continue
        result = subprocess.run([sys.executable, *args], text=True, capture_output=True, env=env)
        if result.returncode != 0:
            record(f"checkpoint {label} failed: {result.stdout}{result.stderr}")
    for removed in ("continuation.py", "pi_adapter.py", "codex_cli_adapter.py", "claude_adapter.py"):
        if (CORE / "scripts" / removed).exists():
            record(f"CLI staged helper resurrected: {removed}")
    lane_watch = (HERDR / "scripts" / "lane-watch.sh").read_text()
    if "PREWALK" in lane_watch:
        record("Herdr watcher still handles PREWALK (CLI is direct-only)")


def check_lane_graph() -> None:
    script = CORE / "scripts" / "lane_graph.py"
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
    result = subprocess.run(
        [sys.executable, str(script), "--self-test"],
        text=True,
        capture_output=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    if result.returncode != 0:
        record(f"recovery_record self-test failed: {result.stdout}{result.stderr}")


def check_review_gate() -> None:
    script = CORE / "scripts" / "review_gate.py"
    if not is_executable(script):
        record("review gate must exist and remain executable: review_gate.py")
        return
    result = subprocess.run(
        [sys.executable, str(script), "--self-test"],
        text=True,
        capture_output=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    if result.returncode != 0:
        record(f"review_gate self-test failed: {result.stdout}{result.stderr}")


def check_artifact_gc() -> None:
    script = CORE / "scripts" / "artifact_gc.py"
    if not is_executable(script):
        record("artifact GC must exist and remain executable: artifact_gc.py")
        return
    result = subprocess.run(
        [sys.executable, str(script), "self-test"],
        text=True,
        capture_output=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    if result.returncode != 0:
        record(f"artifact_gc self-test failed: {result.stdout}{result.stderr}")


def check_closeout() -> None:
    script = CORE / "scripts" / "closeout.py"
    if not is_executable(script):
        record("closeout helper must exist and remain executable: closeout.py")
        return
    result = subprocess.run(
        [sys.executable, str(script), "self-test"],
        text=True,
        capture_output=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    if result.returncode != 0:
        record(f"closeout self-test failed: {result.stdout}{result.stderr}")
    for shell_doc in (
        CORE / "references" / "execution-worktree-integration.md",
        CORE / "references" / "test-decision-and-rebase.md",
        T3CODE / "references" / "t3code-lifecycle.md",
        LODY / "references" / "lody-lifecycle.md",
        APP / "references" / "codex-app-dispatch.md",
    ):
        text = shell_doc.read_text()
        if "closeout.py" not in text and "§Cleanup" not in text:
            record(f"cleanup must route through closeout.py: {shell_doc.relative_to(ROOT)}")


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
    check_lody_contract()
    check_tree_ownership()
    check_installer()
    check_pruned_policy()
    check_metadata_and_helpers()
    check_checkpoint_contract()
    check_lane_graph()
    check_recovery_record()
    check_review_gate()
    check_artifact_gc()
    check_closeout()

    if ERRORS:
        fail(
            f"{len(ERRORS)} violation(s):\n"
            + "\n".join(f"  - {item}" for item in ERRORS)
        )
    print("bundle: pass")


if __name__ == "__main__":
    main()
