# Wayfinder Implement Orchestrator — Domain Model

## Core Concepts

**Source Worktree**
The user's primary working directory, typically checked out to `main` branch. This worktree remains stable during orchestration — the user can continue working here while maps run in parallel. Never modified by orchestrator automation.

**Map Integration Worktree**
A dedicated Git worktree created for one Wayfinder map's entire lifecycle (discovery → spec → tickets → implementation → integration). Lives at `<source-parent>/worktrees/<repo-name>-map-<issue-number>/` on branch `feature/map-<issue-number>`. Serves as the integration point for all implementation tickets belonging to that map. Automatically created when a map is launched from source worktree. Deleted after successful merge to main.

**Execution Worktree**
A dedicated Git worktree created for one implementation ticket's work. It is based on the Map Integration Worktree branch, not main, and contains one ticket's changes. Codex App native Dispatch lets Codex App own the worktree path and initial checkout; Herdr Dispatch uses `<source-parent>/worktrees/<repo-name>-map-<map-issue>-issue-<ticket-number>/`. The worker creates or verifies `codex/issue-<ticket-number>` (Codex App/Codex CLI), `claude/issue-<ticket-number>` (Claude Code), or `pi/issue-<ticket-number>` (pi) before writing. The terminal commit is cherry-picked to the Map Integration Worktree, then the worktree is deleted.

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
Dispatch Handoff is batch-scoped. It is the control-plane terminal after every item in the selected maximal safe batch is accounted for: each successful user-visible lane has verified coordinates and isolation, accepted its packet, entered `working`, and persisted the runtime state; each failed setup is durably isolated as `setup_blocked`. The coordinator reports the batch coordinates and ends its turn only after the whole batch, then resumes on a user completion signal, a real terminal event, or an explicit monitor request; repository file overlap is an Integration risk handled by isolated Execution Worktrees and serial fan-in, not a dispatch blocker.

**HITL Handoff**
The Herdr specialization of Dispatch Handoff. A configured pi, Codex CLI, or Claude CLI pane has accepted its packet and entered `working`; its lane persists `awaiting_human`. The user completes the live discussion in Herdr, then returns to the current coordinator session to trigger terminal fan-in from durable evidence.

**Task Coordinate Title**
A stable, human-facing Codex App task title that identifies the owning map, lane role, and work item. It is used only by the `delivery-pipeline-codex-app` shell; the lane registry remains recovery truth.

**Codex Task Archive**
The post-Integration transport state of a `codex-thread` lane owned by the Codex App shell. Archive readback closes the lane; `close_pending` retains recoverable coordinates without blocking ready tickets, while unsuccessful Integration keeps the task visible.

**Configured Planning Lane**
A Herdr worker handling one AFK discovery/research item or one spec/tickets gate. Its agent, model, and effort come from the `planning` role in the version 2 worker configuration; it uses the same registry, packet, Dispatch Handoff, and fan-in contract as other configured lanes.

**Worker Role Configuration**
The user-level file `~/.config/delivery-pipeline/model-roles.json`. Version 2 defines exactly six worker roles—`planning`, `design`, `frontend`, `backend`, `testing`, `review`—and requires a non-empty `agent`, `model`, and `effort` for each. It contains no coordinator entry: the current calling session is the coordinator. Skills contain no default model routing; missing or invalid configuration blocks dispatch and runs `delivery-pipeline-setup`.

**Coordinator Runtime**
The current session hosting the coordinator: `codex-cli`, `claude-cli`, or `pi-cli` for canonical CLI/Herdr orchestration; `codex-app` only when the `delivery-pipeline-codex-app` shell is invoked. Coordinator model is chosen before skill invocation and is not part of Worker Role Configuration.

**Dispatch Model**
- `skills/delivery-pipeline` is the single canonical CLI/Herdr core installed unchanged for pi, Codex CLI, and Claude CLI; current host never rewrites configured worker routing.
- Canonical CLI Dispatch resolves work item → one of six roles → configured agent/model/effort. Agent selects lane runtime: pi → `herdr-pi-pane`, codex → `herdr-codex-pane`, claude → `herdr-claude-pane`.
- pi starts with `--approve --model <model> --thinking <effort>`; Codex CLI with `--model <model>` plus `model_reasoning_effort`; Claude CLI with `--model <model> --effort <effort>`. Kind-specific permissions belong to Trusted Execution Bootstrap.
- `skills/delivery-pipeline-codex-app` is the only transport shell. It skips Worker Role Configuration and maps all six delegated roles to Codex App tasks + App-managed Execution Worktrees (`codex-thread`); its packet, registry overlay, role-aware fan-in, and task references are co-located inside that shell.
- `delivery-pipeline-setup` probes pi (`pi --list-models`), Codex (`codex debug models`), and Claude `settings.json.env`, then requires explicit choices for all six roles. There are no built-in agent/model/effort defaults.
- Same-batch lanes complete startup readback before Dispatch Handoff; long tasks wake the current coordinator only on user completion, real terminal event, or explicit monitor request.
- Each lane persists role, output mode (`commit | artifact | checks | verdict`), agent, model, effort, evidence, runtime, permissions, worktree, and transport coordinates. Only commit mode cherry-picks; artifact/checks/verdict modes verify durable evidence then become `consumed`. Existing lanes recover by registry rather than new configuration.
- Map Run Authority covers named-map canonical tracker transitions and next ready frontier; final publication remains an independent gate.
- Ready frontier, one writer, Execution Worktree isolation, Integration, and terminal fan-in do not change with agent kind.

## Relationships

- One running Herdr session → many map workspaces
- One map → one integration worktree → zero or one Herdr workspace
- One map → many implementation tickets → many execution worktrees → many runtime-owned lanes
- One map → many discovery tickets → configured planning/design lanes → many Herdr panes
- One execution worktree → one Codex App task or one Herdr-hosted Codex CLI/Claude Code/pi pane
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

**Pane Dispatch Compatibility Helper**
The Claude-only `pane-dispatch` skill retained for compatibility. It is not the canonical dispatch owner: `delivery-pipeline` now owns runtime-neutral Herdr lifecycle and configured pi/Codex/Claude worker startup. The helper may materialize a caller-supplied packet, but it does not own role configuration, maximal safe batch, worktrees, Integration, or fan-in.
