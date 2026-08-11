# Delivery Pipeline

[中文说明](README.zh-CN.md)

A resumable Codex/Claude skill bundle for one durable delivery chain:

```text
idea/map -> discovery -> spec -> implementation tickets
  -> automatic worktree dispatch -> integration -> summary PR/MR
```

Start a fresh session with any issue from the chain. The skill follows tracker
relationships upward and downward, reconstructs map/spec/ticket state, and
continues from the earliest incomplete gate.

Stage-owning skills remain authoritative: `wayfinder` owns discovery,
`to-spec` owns the spec, `to-tickets` owns ticket publication, and `implement`
owns one ticket. The orchestrator verifies durable links and state transitions;
it does not add a second ticket-shaping policy.

Implementation dispatch is automatic. Every ready ticket gets one isolated
worker and one Git worktree — Claude Code for frontend/design tickets, Codex
for backend. Dependencies and mutable-resource conflicts
serialize only the affected tickets.
Each dispatched child persists its pane/thread ID, worktree, branch, commit, and
lifecycle state. Fresh sessions recover children and reattach terminal listeners
first. Claude closes the matching worker pane after integration and focused checks
succeed.
Delegated children receive the owner skill's resolved `SKILL.md` path, so
user-invoked stage owners do not depend on the child task's active skill catalog.

## Install

Install the dependencies listed in `skill-bundle.json`, then:

```bash
./scripts/install.sh --target all
```

Both installations are symlinked to this checkout.

## Use

Codex:

```text
Use $delivery-pipeline with <any-map-spec-or-ticket-issue>.
```

Claude（通过 `/herdr` skill 管理 panes）：

```text
Use /delivery-pipeline <any-map-spec-or-ticket-issue>.
```

## Verify

```bash
python3 scripts/validate.py
```

`scripts/install.sh` also installs `scripts/hooks/pre-commit`, which runs the
validator against the staged tree and refuses a red commit. Pass `--no-hooks` to
skip, or commit with `--no-verify` to override deliberately. The same validator
runs in CI (`.github/workflows/validate.yml`) as a backstop for fresh clones.

Skill references are runtime-specific and enforced: the Codex tree (`skills/`)
uses `$name`, the Claude tree (`claude/skills/`) uses `/mattpocock-skills:name`.
Claude plugin locators are rejected inside the Codex tree, where they cannot
resolve.
