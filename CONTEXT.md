# Wayfinder Implement Orchestrator — Domain Model

## Core Concepts

**Source Worktree**
The user's primary working directory, typically checked out to `main` branch. This worktree remains stable during orchestration — the user can continue working here while maps run in parallel. Never modified by orchestrator automation.

**Map Integration Worktree**
A dedicated Git worktree created for one Wayfinder map's entire lifecycle (discovery → spec → tickets → implementation → integration). Lives at `<source-parent>/worktrees/<repo-name>-map-<issue-number>/` on branch `feature/map-<issue-number>`. Serves as the integration point for all implementation tickets belonging to that map. Automatically created when a map is launched from source worktree. Deleted after successful merge to main.

**Execution Worktree**
A dedicated Git worktree created for one implementation ticket's work. It is based on the Map Integration Worktree branch, not main, and contains one ticket's changes. Codex App native Dispatch lets Codex App own the worktree path and initial checkout; Herdr Dispatch uses `<source-parent>/worktrees/<repo-name>-map-<map-issue>-issue-<ticket-number>/`. The worker creates or verifies `codex/issue-<ticket-number>` (Codex App/Codex CLI) or `claude/issue-<ticket-number>` (Claude Code) before writing. The terminal commit is cherry-picked to the Map Integration Worktree, then the worktree is deleted.

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
A Herdr terminal multiplexer workspace corresponding to one map when Herdr Dispatch is selected. Label matches `map-<issue-number>`. Created lazily before the first Herdr lane. HITL panes (grilling, prototype) and execution panes land in this workspace. Preserved (not deleted) after map completes, for history access. Codex App native Dispatch does not create a Herdr Workspace.

**Subagent (Discovery)**
A background `Agent` tool subagent that handles one AFK discovery ticket (research or automatic task). Runs autonomously — no Herdr pane created, no pane resources consumed. Reports results via Agent tool completion notification. Results committed to `research/<ticket-name>` branch and written as ticket resolution comment.

**Coordinator Runtime**
The environment hosting the delivery coordinator: `codex-app`, `codex-cli`, or `claude-cli`. It is distinct from the worker kind. Codex App exposes native task/thread orchestration; Codex CLI and Claude CLI use Herdr Dispatch.

**Dispatch Model**
- Coordinator Runtime 先决定调度 transport：`codex-app` 默认 Codex App 原生 Dispatch，`codex-cli` 与 `claude-cli` 使用 Herdr Dispatch；Codex App 用户可显式覆盖为 Herdr。
- Codex App 原生 Dispatch = Codex App task + App-managed Execution Worktree，lane runtime 为 `codex-thread`。
- Herdr Dispatch = map Herdr Workspace 中的 Codex CLI 或 Claude CLI pane；lane runtime 为 `herdr-codex-pane` 或 `herdr-claude-pane`。显式 worker kind 优先，否则 frontend/design → Claude，backend/other → Codex。
- 每条 lane 在 registry 持久化自己的 runtime；恢复时以 lane runtime 为准。Coordinator Runtime 与 worker kind 是两条独立轴。
- Codex CLI 是否具备与 Codex App 相同的原生 thread 能力是 Unknown；本模型不依赖该能力。
- Subagents = autonomous background work that reports results (research, AFK task). Research and AFK tasks do not occupy Codex App tasks or Herdr tabs.
- Ready frontier、单写者、Execution Worktree 隔离、Integration 和 terminal fan-in 不随调度运行时变化。

## Relationships

- One map → one integration worktree → zero or one Herdr workspace
- One map → many implementation tickets → many execution worktrees → many runtime-owned lanes
- One map → many discovery tickets → many subagents (no panes)
- One execution worktree → one Codex App task or one Herdr-hosted Codex CLI/Claude Code pane
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

**Pane Dispatch**
The skill that materializes a filled dispatch packet into a verified Herdr pane with an attached listener. Claude-only, kind-generic (claude | codex). Receives a packet file path, resolves workspace/tab, creates the pane, starts the agent, delivers the packet, verifies placement, mounts the listener, and reports coordinates. Does not compute maximal safe batch, manage worktrees, or parse terminal reports — those stay in the orchestrator. Replaces the retired `dispatch-to-codex` skill.
