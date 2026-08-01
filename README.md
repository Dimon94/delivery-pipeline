# Wayfinder Implement Orchestrator

[中文说明](README.zh-CN.md)

A resumable Codex/Claude skill bundle for one durable delivery chain:

```text
idea/map -> discovery -> spec -> implementation tickets
  -> automatic Codex worktree dispatch -> integration -> summary PR/MR
```

Start a fresh session with any issue from the chain. The skill follows tracker
relationships upward and downward, reconstructs map/spec/ticket state, and
continues from the earliest incomplete gate.

Stage-owning skills remain authoritative: `wayfinder` owns discovery,
`to-spec` owns the spec, `to-tickets` owns ticket publication, and `implement`
owns one ticket. The orchestrator verifies durable links and state transitions;
it does not add a second ticket-shaping policy.

Implementation dispatch is automatic. Every ready ticket gets one isolated
Codex worker and one Git worktree. Dependencies and mutable-resource conflicts
serialize only the affected tickets.
Each dispatched child persists its pane/thread ID, worktree, branch, commit, and
lifecycle state. Fresh sessions recover children and reattach terminal listeners
first. Claude closes the matching Codex pane after integration and focused checks
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
Use $wayfinder-implement-orchestrator with <any-map-spec-or-ticket-issue>.
```

Claude（通过 `/herdr` skill 管理 panes）：

```text
Use /wayfinder-implement-orchestrator <any-map-spec-or-ticket-issue>.
```

## Verify

```bash
python3 scripts/validate.py
```
