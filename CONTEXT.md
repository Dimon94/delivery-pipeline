# Wayfinder Implement Orchestrator — Domain Model

## Core Concepts

**Source Worktree**  
The user's primary working directory, typically checked out to `main` branch. This worktree remains stable during orchestration — the user can continue working here while maps run in parallel. Never modified by orchestrator automation.

**Map Integration Worktree**  
A dedicated Git worktree created for one Wayfinder map's entire lifecycle (discovery → spec → tickets → implementation → integration). Lives at `<source-parent>/worktrees/<repo-name>-map-<issue-number>/` on branch `feature/map-<issue-number>`. Serves as the integration point for all implementation tickets belonging to that map. Automatically created when a map is launched from source worktree. Deleted after successful merge to main.

**Execution Worktree**  
A dedicated Git worktree created for one implementation ticket's work. Lives at `<source-parent>/worktrees/<repo-name>-map-<map-issue>-issue-<ticket-number>/` on branch `codex/issue-<ticket-number>`. Based on the map's integration worktree branch, not main. Contains a single ticket's changes. Cherry-picked to map integration worktree upon completion, then deleted.

**Integration**  
The process of collecting completed execution worktree commits into the map integration worktree via `git cherry-pick`. Happens incrementally as tickets complete. Distinct from merging to main.

**Merge to Main**  
The final step where a map integration worktree's branch is rebased onto main and pushed. Only happens after all tickets complete, whole-change checks pass, and user confirms test strategy.

**Test Decision Point**  
The moment when orchestrator pauses after integration completes and asks user to choose:
1. Test in integration worktree first
2. Rebase to main then test there
3. Skip manual test, push immediately

Only main-branch tests block other developers; integration worktree tests are isolated.

**Concurrent Maps**  
Multiple Wayfinder maps running simultaneously, each with its own integration worktree and execution worktrees. Each orchestrator session owns one map and ignores others. No global resource coordination — each map independently creates worktrees and panes.

**Worktree Lifecycle**  
Creation → work → integration/merge → deletion. Execution worktrees: created at dispatch, deleted after cherry-pick. Integration worktrees: created at map start, deleted after push to main. Failed/blocked worktrees: deleted immediately to avoid pollution.

**Herdr Workspace**  
A Herdr terminal multiplexer workspace corresponding to one map. Label matches `map-<issue-number>`. Created/renamed automatically when map integration worktree is created. Only HITL panes (grilling, prototype) and execution Codex panes land in this workspace. Preserved (not deleted) after map completes, for history access.

**Subagent (Discovery)**  
A background `Agent` tool subagent that handles one AFK discovery ticket (research or automatic task). Runs autonomously — no Herdr pane created, no pane resources consumed. Reports results via Agent tool completion notification. Results committed to `research/<ticket-name>` branch and written as ticket resolution comment.

**Dispatch Model**  
- Panes = interactive work requiring user feedback loop (grilling, prototype, HITL task) + Codex execution panes.
- Subagents = autonomous background work that reports results (research, AFK task).
- Research and AFK tasks do not occupy Herdr tabs — they run as parallel subagents and report back to the lead session.

## Relationships

- One map → one integration worktree → one Herdr workspace
- One map → many implementation tickets → many execution worktrees → many Codex panes
- One map → many discovery tickets → many subagents (no panes)
- One execution worktree → one Codex pane (in map's Herdr workspace)
- Execution worktrees branch from integration worktree, not from main
- Integration worktree eventually rebases to main (not merge)
- Multiple maps run concurrently, isolated by separate integration worktrees

## Non-goals

**Not a global scheduler**  
Orchestrator does not coordinate across multiple concurrent maps. Each session manages only its own map's worktrees.

**Not branch-free**  
Git worktrees fundamentally require branches. "No branches" is impossible — the design uses disciplined branch management instead.

**Not merge-based**  
Uses rebase to main, not merge commits. Keeps linear history per map.
