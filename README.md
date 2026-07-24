# Wayfinder Implementation Dispatcher

[中文说明](README.zh-CN.md)

A personal Codex/Claude skill bundle that dispatches existing implementation
tickets to isolated Codex workers.

Given tracker issue URLs or numbers, it reads their current dependency and
write-footprint metadata, computes a maximal safe batch, launches one fresh
Codex worker in an independent Git worktree per selected ticket, verifies
placement and cwd, and reports every input as either `dispatched` or `deferred`.

The skill ends when dispatch is verified. Ticket authoring, execution
monitoring, result collection, integration, tracker mutation, and remote
publication belong to the caller or another skill.

## Install

Install Matt Pocock's `implement` skill first, then run:

```bash
./scripts/install.sh
```

Install the Claude/Herdr variant with:

```bash
./scripts/install.sh --target claude
```

Install both variants with:

```bash
./scripts/install.sh --target all
```

All targets are symlinked to this checkout.

## Use

Codex:

```text
Use $wayfinder-implement-orchestrator with <issue-url> <issue-url> ...
```

Claude inside Herdr:

```text
Use /wayfinder-implement-orchestrator <issue-url> <issue-url> ...
```

## Verify

```bash
python3 scripts/validate.py
```
