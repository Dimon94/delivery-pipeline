#!/usr/bin/env python3
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODEX_ROOT = ROOT / "skills" / "wayfinder-implement-orchestrator"
CLAUDE_ROOT = ROOT / "claude" / "skills" / "wayfinder-implement-orchestrator"
CODEX_SKILL = CODEX_ROOT / "SKILL.md"
CLAUDE_SKILL = CLAUDE_ROOT / "SKILL.md"


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text()
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
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


def check_scope() -> None:
    active = [
        ROOT / "README.md",
        ROOT / "README.zh-CN.md",
        CODEX_SKILL,
        CLAUDE_SKILL,
        CLAUDE_ROOT / "references" / "herdr-dispatch.md",
    ]
    forbidden = (
        re.compile(r"拆票"),
        re.compile(r"估时"),
        re.compile(r"估档"),
        re.compile(r"不拆理由"),
        re.compile(r"\bS/M/L/XL\b"),
        re.compile(r"\bXL\s*票"),
        re.compile(r"estimate-log", re.IGNORECASE),
        re.compile(r"ticket-split", re.IGNORECASE),
        re.compile(r"split proposal", re.IGNORECASE),
        re.compile(r"/to-spec"),
        re.compile(r"/to-tickets"),
        re.compile(r"route classifier", re.IGNORECASE),
    )
    hits = []
    for path in active:
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if any(pattern.search(line) for pattern in forbidden):
                hits.append(f"{path.relative_to(ROOT)}:{lineno}:{line}")
    if hits:
        fail("non-dispatch policy remains:\n" + "\n".join(hits))

    allowed_codex = {
        CODEX_ROOT / "SKILL.md",
        CODEX_ROOT / "agents" / "openai.yaml",
    }
    actual_codex = {path for path in CODEX_ROOT.rglob("*") if path.is_file()}
    if actual_codex != allowed_codex:
        unexpected = sorted(str(path.relative_to(ROOT)) for path in actual_codex - allowed_codex)
        fail("unexpected Codex skill files: " + ", ".join(unexpected))

    allowed_claude = {
        CLAUDE_ROOT / "SKILL.md",
        CLAUDE_ROOT / "references" / "herdr-dispatch.md",
    }
    actual_claude = {path for path in CLAUDE_ROOT.rglob("*") if path.is_file()}
    if actual_claude != allowed_claude:
        unexpected = sorted(
            str(path.relative_to(ROOT)) for path in actual_claude - allowed_claude
        )
        fail("unexpected Claude skill files: " + ", ".join(unexpected))


def main() -> None:
    manifest = json.loads((ROOT / "skill-bundle.json").read_text())
    if manifest != {
        "format": "codex-claude-skill-bundle/v1",
        "name": "wayfinder-implement-orchestrator",
        "entrypoints": {
            "codex": "skills/wayfinder-implement-orchestrator/SKILL.md",
            "claude": "claude/skills/wayfinder-implement-orchestrator/SKILL.md",
        },
        "install": {
            "codexSkillDirectory": "skills/wayfinder-implement-orchestrator",
            "claudeSkillDirectory": "claude/skills/wayfinder-implement-orchestrator",
        },
        "requires": [
            {
                "name": "implement",
                "source": "mattpocock-skills",
                "reason": (
                    "Issue-level implementation directive sent to each dispatched "
                    "Codex worker."
                ),
            }
        ],
    }:
        fail("bundle manifest mismatch")

    codex_fm = frontmatter(CODEX_SKILL)
    claude_fm = frontmatter(CLAUDE_SKILL)
    if codex_fm.get("name") != "wayfinder-implement-orchestrator":
        fail("Codex skill name mismatch")
    if codex_fm.get("disable-model-invocation") != "true":
        fail("Codex skill must remain user-invoked")
    if "Dispatch existing implementation tickets" not in codex_fm.get("description", ""):
        fail("Codex description is not dispatch-led")
    if claude_fm.get("name") != "wayfinder-implement-orchestrator":
        fail("Claude skill name mismatch")
    if "Dispatch existing implementation tickets" not in claude_fm.get("description", ""):
        fail("Claude description is not dispatch-led")

    common = (
        "maximal safe batch",
        "dispatched",
        "deferred",
        "$implement",
        "每张输入票必须恰好出现一次",
        "派发完成即结束",
    )
    require(CODEX_SKILL, common + ("create_thread", "Source owner projectId"))
    require(
        CLAUDE_SKILL,
        common + ("HERDR_ENV=1", "references/herdr-dispatch.md"),
    )
    require(
        CLAUDE_ROOT / "references" / "herdr-dispatch.md",
        (
            "herdr workspace list",
            "git worktree add -b",
            "git-common-dir",
            "--no-focus",
            "herdr agent start",
            "--cwd <lane-path>",
            "codex -s danger-full-access -a never",
            "herdr pane send-text",
            "herdr pane send-keys",
            "herdr pane rename",
            "herdr tab rename",
            "herdr pane get",
            "herdr pane close",
            "不启动 wait",
        ),
    )
    check_references(CODEX_SKILL)
    check_references(CLAUDE_SKILL)
    check_scope()

    metadata = (CODEX_ROOT / "agents" / "openai.yaml").read_text()
    require(
        CODEX_ROOT / "agents" / "openai.yaml",
        (
            'display_name: "Wayfinder Implementation Dispatcher"',
            'short_description: "Dispatch tickets to isolated Codex tasks"',
            "$wayfinder-implement-orchestrator",
            "allow_implicit_invocation: false",
        ),
    )
    if "through implementation" in metadata:
        fail("stale Codex metadata")

    install = (ROOT / "scripts" / "install.sh").read_text()
    for stale in ("to-spec", "to-tickets", "wayfinder-frontier", "helper agents"):
        if stale in install:
            fail(f"stale install behavior: {stale}")
    if "for dep in implement" not in install:
        fail("installer must check only the implement dependency")

    subprocess.run(
        ["bash", "-n", str(ROOT / "scripts" / "install.sh")],
        check=True,
    )
    print("bundle: pass")


if __name__ == "__main__":
    main()
