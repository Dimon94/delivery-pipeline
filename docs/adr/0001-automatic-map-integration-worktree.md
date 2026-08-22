# ADR-0001: Automatic Map Integration Worktree Management

**Status:** Accepted  
**Date:** 2026-08-01  
**Deciders:** User (Dimon), Kiro

> ADR-0002 supersedes the fixed Herdr workspace/pane and fixed Execution Worktree path clauses.
> The two-tier worktree isolation and Integration decisions remain accepted.

## Context

Orchestrator currently requires users to manually manage Git worktrees and branches for Wayfinder maps. This creates friction in high-frequency concurrent development scenarios where 5+ maps run simultaneously. The user is not proficient with Git operations (branch creation, merging, worktree management) and wants AI-assisted automation.

### Current pain points

1. **Branch conflicts**: Switching branches in source worktree blocks concurrent map work
2. **Manual worktree setup**: Users must create worktrees, branches, and coordinate paths manually
3. **Merge complexity**: Rebasing to main, resolving conflicts, and cleaning up requires Git expertise
4. **Lost isolation**: Without worktrees, concurrent maps interfere with each other
5. **Cleanup debt**: Failed worktrees and orphaned branches accumulate

### User's actual workflow needs

- Start maps from main worktree (stays on main, never switches branches)
- 5+ maps running concurrently, each isolated
- Automatic worktree creation, branch management, and cleanup
- Automatic rebase to main with conflict resolution assistance
- Optional testing in integration worktree or after merge to main
- Zero manual Git commands required

## Decision

Orchestrator will **automatically manage a two-tier worktree hierarchy** for each map:

### Tier 1: Map Integration Worktree

When user launches a map from source worktree (main):
1. Auto-detect if integration worktree already exists (recovery scenario)
2. If not, create: `<source-parent>/worktrees/<repo-name>-map-<issue-number>/`
3. Create branch `feature/map-<issue-number>` based on current main HEAD
4. Create/rename Herdr workspace to `map-<issue-number>`
5. Run discovery/spec/tickets in this integration worktree

### Tier 2: Execution Worktrees

For each ready implementation ticket:
1. Create: `<source-parent>/worktrees/<repo-name>-map-<map-issue>-issue-<ticket-number>/`
2. Create branch `codex/issue-<ticket-number>` based on integration worktree's branch
3. Launch Codex pane via `/herdr` in map's workspace
4. After completion, cherry-pick commit to integration worktree
5. Delete execution worktree and branch immediately

### Merge to Main Flow

After all tickets integrated and whole-change checks pass:
1. **Pause at test decision point**, offer user three options:
   - Test in integration worktree (stays isolated)
   - Rebase to main first, then test there (blocks others)
   - Skip manual test, push immediately
2. Rebase `feature/map-<map-number>` to latest main
3. If main has advanced (another map merged), auto-rebase first
4. If conflicts arise, invoke `/mattpocock-skills:resolving-merge-conflicts`
5. Push to main (not via PR/MR unless user explicitly requests)
6. Delete all worktrees and branches
7. Close map issue with completion comment
8. Preserve Herdr workspace (close panes, keep workspace)

### Concurrent Maps Isolation

Each orchestrator session manages only its own map:
- No global resource coordination
- No cross-map scheduling
- Each map independently creates worktrees
- Multiple maps can rebase to main sequentially (first-come-first-served, with auto-rebase for later ones)

## Consequences

### Positive

**User experience**
- Zero manual Git commands required
- Can run 5+ maps concurrently without conflicts
- Source worktree stays clean on main
- Automatic cleanup prevents worktree/branch pollution

**Isolation**
- Each map has dedicated workspace
- Execution worktrees prevent ticket interference
- Testing can happen in isolation before affecting main

**Recovery**
- Auto-detect existing worktrees on session restart
- Restore running execution worktrees from registry
- Idempotent operations (safe to re-run)

**Automation**
- Automatic rebase with conflict detection
- Automatic cleanup on success
- Automatic workspace management via `/herdr`

### Negative

**Disk space**
- 5 concurrent maps × 3-5 tickets each = 15-25 worktrees
- Each worktree is a full checkout (~repo size)
- Mitigated by: immediate cleanup after integration, sparse checkouts if needed

**Complexity**
- Two-tier worktree hierarchy adds orchestrator logic
- Rebase conflicts require `/mattpocock-skills:resolving-merge-conflicts` delegation
- Failed worktree cleanup must be robust

**Git expertise required (for orchestrator)**
- Must handle: worktree creation, branch management, cherry-pick, rebase, conflict detection
- Must verify: worktree paths, branch validity, clean state
- Must clean up: on success, on failure, on user abort

**No PR/MR by default**
- Bypasses GitHub/GitLab review process
- CI/CD runs after push, not before (unless checks run in integration worktree)
- Acceptable tradeoff for user's automation goal

### Risks and Mitigations

**Risk: Concurrent rebase conflicts**  
If map-A and map-B both finish simultaneously, both try to rebase to main.  
**Mitigation:** Second map auto-detects main advanced, rebases first. If conflict, stops and asks for help.

**Risk: User loses work in worktrees**  
If orchestrator deletes worktrees prematurely or user makes untracked changes.  
**Mitigation:** Always check `git status --short` before deletion. Preserve dirty worktrees with warning.

**Risk: Orphaned worktrees from crashes**  
If orchestrator crashes mid-creation or user kills process.  
**Mitigation:** Recovery logic detects existing worktrees by path and branch. User can manually clean via `git worktree prune`.

**Risk: Integration worktree out of sync with main**  
Long-running maps may diverge significantly from main.  
**Mitigation:** Periodic rebase prompts? Or accept divergence until final merge. Not addressed in this ADR.

## Implementation Notes

Must delegate to `/herdr` skill for:
- Workspace creation/renaming
- Pane placement and lifecycle
- All Herdr CLI operations

Must handle Git operations directly:
- `git worktree add -b <branch> <path> <base>`
- `git cherry-pick <commit>`
- `git rebase <branch>`
- `git worktree remove <path>`
- `git branch -D <branch>`

Must verify before operations:
- Path doesn't exist or is valid worktree
- Branch doesn't exist or is safe to reuse
- Working tree is clean before deletion
- Common dir matches source repo

Must update `lane-registry.md` schema to include:
- `integration_worktree_path`
- `integration_branch`
- `execution_worktree_path` (per ticket)

## Alternatives Considered

**Alternative 1: Manual worktrees (status quo)**  
Rejected: Doesn't meet automation goal, user not proficient with Git.

**Alternative 2: Single integration worktree, no execution worktrees**  
Rejected: Tickets would interfere with each other during concurrent implementation.

**Alternative 3: Use submodules or sparse checkouts**  
Rejected: More complex than worktrees, doesn't solve branch isolation problem.

**Alternative 4: Always create PR/MR instead of direct push**  
Rejected: User wants rebase-based flow, PR/MR adds friction for high-frequency changes.

**Alternative 5: Global scheduler coordinating all maps**  
Rejected: Adds complexity, violates "each session owns one map" principle.
