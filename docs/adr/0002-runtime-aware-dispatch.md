# ADR-0002: Runtime-aware Dispatch

**Status:** Accepted
**Date:** 2026-08-22
**Decider:** User (Dimon)

## Context

ADR-0001 established two-tier worktree isolation but bound every Execution Worktree to a Herdr pane.
Three observed Codex App delivery chains used a different working transport successfully:

- `01a02741-8013-7f20-87a8-4be443184eb0` created and monitored multiple implementation tasks.
- `01a027a7-c629-7c63-9900-f4226595373d` created an isolated closeout review task.
- `01a027a9-737a-77e2-bacb-737396f4f6f9` recovered an older task without creating a duplicate writer.

The runs used Codex App thread tools for task creation, App-managed worktrees, startup readback,
bounded waiting, follow-up, and recovery. Requiring Herdr in this environment adds a second scheduler
without changing the delivery invariants.

## Decision

Dispatch is selected by Coordinator Runtime before any new lane is created:

1. `codex-app` uses Codex App native Dispatch by default; an explicit Herdr instruction overrides it.
2. `codex-cli` uses Herdr Dispatch.
3. `claude-cli` uses Herdr Dispatch.
4. Herdr may host a Codex CLI or Claude CLI worker. Explicit worker kind wins; otherwise the binding
   table selects Claude for frontend/design and Codex for backend/other work.
5. Codex CLI native thread capability parity with Codex App is Unknown; the model does not depend on it.
6. Existing lanes always recover through the `runtime` stored in their registry. A runtime switch
   affects only new lanes after active writers have been accounted for.

Codex App native Dispatch uses one user-visible task and one App-managed Execution Worktree per lane.
Herdr Dispatch uses one manually managed Execution Worktree and one Herdr-hosted Codex CLI or Claude
Code pane per lane. The user may select the kind explicitly; otherwise the Herdr binding table selects
Claude for frontend/design and Codex CLI for backend/other tickets. Both transports retain
the ADR-0001 invariants: branch from the Map Integration Worktree, one writer per ticket, terminal
commit fan-in through Integration, focused checks, and cleanup after successful Integration.

This ADR supersedes ADR-0001 only where ADR-0001 requires a Herdr Workspace, fixed Execution Worktree
path, or Codex pane for every lane. The two-tier isolation and Integration decisions remain accepted.

## Consequences

- Codex App is self-hosting for dispatch and no longer requires Herdr for its default path.
- Herdr remains available for both Codex CLI and Claude Code panes.
- Registry recovery becomes runtime-aware; task and pane coordinates cannot be treated as interchangeable.
- Codex App-created worktree paths are discovered and persisted after creation rather than predicted.
