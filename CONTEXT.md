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
Creation → work → integration/merge → deletion. Execution worktrees: created at dispatch, deleted after cherry-pick. Integration worktrees: created at map start, deleted after push to main. Empty setup-failed worktrees are deleted after the bounded retry; active, awaiting-human, or recoverable blocked lanes retain their worktrees.

**Herdr Session Target**
The running, user-visible Herdr session selected by the Codex App Herdr Bridge. The bridge targets it explicitly with `herdr --session <name>` and stores `herdr_session_name`; `default` wins when it is running. Map isolation belongs to Herdr Workspace, so HITL dispatch does not create a second hidden session.

**Herdr Workspace**
A Herdr terminal multiplexer workspace corresponding to one map when Herdr Dispatch is selected. Label matches `map-<issue-number>`. Created lazily inside the selected Herdr session before the first Herdr lane. HITL panes (grilling, prototype) and execution panes land in this workspace. Preserved (not deleted) after map completes, for history access. Codex App native Dispatch does not create a Herdr Workspace.

**Trusted Execution Bootstrap**
A narrow authority granted with the user's Herdr/Claude transport approval. It lets the coordinator confirm Claude workspace trust for the exact verified Execution Worktree and allow imports whose realpaths are mechanically bounded to the resolved worker skill, its direct references, or applicable ancestor repo instructions. The worker reads those bodies; the coordinator does not preload them. This authority does not grant unrelated prompts or final publication.

**Map Run Authority**
The durable authority created when the user starts or resumes one named map. It covers that map's canonical tracker transitions: claim and registry checkpoints, child resolution and close, map Decisions/Out of scope gist, dependency blocker maintenance, owner-required follow-up decision tickets, and dispatch of the next ready frontier. It does not cover unrelated issues, ambiguous or destructive tracker rewrites, push, main, PR/MR, merge, or final publication closeout.

**Tracker Transaction**
One bounded tracker snapshot, the minimum dependency-ordered write layers, and one aggregate readback per layer. Independent writes share a layer. It preserves exact expected/actual verification without serial per-field reads or progress narration; unrelated document repair stays outside its critical path.

**Dispatch Handoff**
The control-plane terminal after one user-visible lane has verified coordinates and isolation, accepted its packet, entered `working`, and persisted the runtime state. The coordinator reports the coordinates and ends its turn. It resumes only on a user completion signal, a real terminal event, or an explicit monitor request.

**HITL Handoff**
The Herdr specialization of Dispatch Handoff. A fully permissioned Claude pane has accepted its packet and moved from `idle` to `working`; its lane persists `awaiting_human`. The user completes the live discussion in Herdr, then returns to Codex App to trigger terminal fan-in from durable evidence.

**Task Coordinate Title**
A stable, human-facing Codex App task title that identifies the owning map, lane role, and work item. It is a navigation coordinate; Codex App task lifecycle carries dynamic state, while the lane registry remains the recovery truth.

**Codex Task Archive**
The post-Integration transport state of a `codex-thread` lane, reached after its terminal commit is cherry-picked and focused checks pass. Archive readback closes the lane; `close_pending` retains recoverable coordinates without blocking ready tickets, while unsuccessful Integration keeps the task visible.

**Subagent (Discovery)**
A background `Agent` tool subagent that handles one AFK discovery ticket (research or automatic task). Runs autonomously — no Herdr pane created, no pane resources consumed. Reports results via Agent tool completion notification. Results committed to `research/<ticket-name>` branch and written as ticket resolution comment.

**Coordinator Runtime**
The environment hosting the delivery coordinator: `codex-app`, `codex-cli`, or `claude-cli`. It is distinct from the worker kind. Codex App exposes native task/thread orchestration; Codex CLI and Claude CLI use Herdr Dispatch.

**Dispatch Model**
- Coordinator Runtime 先决定调度 transport：`codex-app` 默认 Codex App 原生 Dispatch，`codex-cli` 与 `claude-cli` 使用 Herdr Dispatch；Codex App 用户可在 capability probe 通过后显式覆盖为 Herdr。
- Codex App 原生 Dispatch = Codex App task + App-managed Execution Worktree，lane runtime 为 `codex-thread`。
- Herdr Dispatch = map Herdr Workspace 中的 Codex CLI 或 Claude CLI pane；lane runtime 为 `herdr-codex-pane` 或 `herdr-claude-pane`。显式 worker kind 优先，否则 frontend/design → Claude，backend/other → Codex。
- Codex App coordinator 不在 Herdr pane 时，通过 Codex App Herdr Bridge 显式控制 Herdr Session Target；用户批准后由原 coordinator 完成 Trusted Execution Bootstrap。
- Herdr HITL lane 到达 HITL Handoff 后由用户直接参与；Codex App coordinator 不占用运行期 monitoring token。
- 所有 user-visible lanes 到达 Dispatch Handoff 后都是 coordinator 本轮 terminal；长任务由用户或真实 terminal event 重新唤醒。
- Map Run Authority 覆盖 named map 的 canonical tracker transitions 和下一 ready frontier 派发；最终 publication 仍是独立门禁。
- 每条 lane 在 registry 持久化自己的 runtime；恢复时以 lane runtime 为准。Coordinator Runtime 与 worker kind 是两条独立轴。
- Codex CLI 是否具备与 Codex App 相同的原生 thread 能力是 Unknown；本模型不依赖该能力。
- Subagents = autonomous background work that reports results (research, AFK task). Research and AFK tasks do not occupy Codex App tasks or Herdr tabs.
- Ready frontier、单写者、Execution Worktree 隔离、Integration 和 terminal fan-in 不随调度运行时变化。

## Relationships

- One running Herdr session → many map workspaces
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
The skill that materializes a filled dispatch packet into a verified Herdr pane. Claude-only, kind-generic (claude | codex). Receives a packet file path, resolves workspace/tab, creates the pane, starts the agent, delivers the packet, verifies placement, and reports coordinates. A listener is attached only under an explicit monitor request; normal user-visible lanes end at Dispatch Handoff. It does not compute maximal safe batch, manage worktrees, or parse terminal reports — those stay in the orchestrator. Replaces the retired `dispatch-to-codex` skill.
