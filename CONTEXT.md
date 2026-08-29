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
The running Herdr session containing the Coordinator Pane. New lanes remain in this session; an explicit request for a new workspace still creates it inside this session.

**Herdr Workspace**
The terminal workspace containing the Coordinator Pane is the default target for new Herdr lanes. Multiple maps may share it; a new workspace requires explicit user request, while map isolation belongs to Map Integration Worktrees and Execution Worktrees.

**Coordinator Pane**
The current Herdr pane where `delivery-pipeline` was invoked. It remains the control plane: worker agents run in separate panes rooted at isolated worktrees, so dispatch does not switch the Coordinator Pane's cwd or checked-out branch.

**Trusted Execution Bootstrap**
A narrow authority granted with the user's Herdr/Claude transport approval. It lets the coordinator confirm Claude workspace trust for the exact verified Execution Worktree and allow imports whose realpaths are mechanically bounded to the resolved worker skill, its direct references, or applicable ancestor repo instructions. The worker reads those bodies; the coordinator does not preload them. This authority does not grant unrelated prompts or final publication.

**Map Run Authority**
The durable authority created when the user starts or resumes one named map. It covers that map's canonical tracker transitions: claim and registry checkpoints, child resolution and close, map Decisions/Out of scope gist, dependency blocker maintenance, owner-required follow-up decision tickets, and dispatch of the next ready frontier. It does not cover unrelated issues, ambiguous or destructive tracker rewrites, push, main, PR/MR, merge, or final publication closeout.

**Tracker Transaction**
One bounded tracker snapshot, the minimum dependency-ordered write layers, and one aggregate readback per layer. Independent writes share a layer. It preserves exact expected/actual verification without serial per-field reads or progress narration; unrelated document repair stays outside its critical path.

**Dispatch Handoff**
Dispatch Handoff is batch-scoped. It is the control-plane terminal after every item in the selected maximal safe batch is accounted for: each successful user-visible lane has verified coordinates and isolation, accepted its packet, entered `working`, and persisted the runtime state; each failed setup is durably isolated as `setup_blocked`. The coordinator reports the batch coordinates and ends its turn only after the whole batch, then resumes on a user completion signal, a real terminal event, or an explicit monitor request; repository file overlap is an Integration risk handled by isolated Execution Worktrees and serial fan-in, not a dispatch blocker.

**Lane Terminal Signal**
The worker-emitted single-line `LANE_DONE <lane_id>` marker required by the dispatch packet at both completed and blocked terminal states. The coordinator-side lane watcher (`scripts/lane-watch.sh`) polls the worker pane output for the marker and prompts the Coordinator Pane; pane-vanished and two-hour timeout also wake the coordinator. `herdr agent wait --until done` is not a valid terminal signal: CLI agents settle back to idle without emitting a `done` event, so a `done` listener blocks forever. HITL lanes still wake on the user completion signal; the watcher is only a terminal backstop.

**HITL Handoff**
The Herdr specialization of Dispatch Handoff. A configured pi, Codex CLI, or Claude CLI pane has accepted its packet and entered `working`; its lane persists `awaiting_human`. The user completes the live discussion in Herdr, then returns to the current coordinator session to trigger terminal fan-in from durable evidence.

**Task Coordinate Title**
A stable, human-facing Codex App task title that identifies the owning map, lane role, and work item. It is used only by the `delivery-pipeline-codex-app` shell; the lane registry remains recovery truth.

**Codex Task Archive**
The post-Integration transport state of a `codex-thread` lane owned by the Codex App shell. Archive readback closes the lane; `close_pending` retains recoverable coordinates without blocking ready tickets, while unsuccessful Integration keeps the task visible.

**Configured Planning Lane**
A Herdr worker handling one AFK discovery/research item or one spec/tickets gate. Its agent, model, and effort come from the `planning` role in the version 3 worker configuration; it uses the same registry, packet, Dispatch Handoff, and fan-in contract as other configured lanes.

**Review Evidence Bundle**
A repo-external, single-snapshot evidence set produced by the parent worker before `code-review` fans out to read-only Standards/Spec reviewers. It contains the resolved fixed point and HEAD, exact patch, commits, complete changed-path inventory, fixed-point additions, worktree/staged state, and producing commands. An implementation lane uses its Execution Worktree base commit as fixed point; the whole-change review lane uses the Map Integration Worktree creation base persisted in the map registry. Reviewers consume the same bundle with read/search access instead of requesting Git authority from the supervisor.

**Worker Role Configuration**
The user-level file `~/.config/delivery-pipeline/model-roles.json`. Version 3 defines exactly six worker roles—`planning`, `design`, `frontend`, `backend`, `testing`, `review`—and requires a non-empty `agent`, `model`, and `effort` for each. Pi frontend/backend roles may additionally declare one bootstrap model/effort; the ordinary role model remains their Target Model. It contains no coordinator entry: the current calling session is the coordinator. Skills contain no default model routing; missing or invalid configuration blocks dispatch and runs `delivery-pipeline-setup`.

**Bootstrap Handoff**
An optional model Shift inside one eligible pi frontend/backend Implementation Lane. The lane starts on its configured bootstrap model and continues on its ordinary role model after the Bootstrap Checkpoint passes; it does not replace fresh Review.

**Bootstrap Checkpoint**
The Delivery Pipeline Trigger satisfied when one focused command has been observed failing, a declared canonical-owner path has changed after that failure and still has the verified edit/write digest after the exact command passes, and the Source Model attests meaningful remaining work. Red/green exits and owner mutation are adapter-verified; remaining work is agent-attested.

**Bootstrap Gearshift Policy**
The version 3 configuration decision `off | opt_in | all_eligible`. Opt-in requires the configured ticket label; all-eligible applies mechanically to pi frontend/backend roles with a bootstrap entry and does not ask an LLM to classify risk.

**Gearshift Projection**
The bounded, coordinator-owned lane-registry projection of one Pi Gearshift Shift Record: policy, deterministic eligibility evidence, JSON-quoted opt-in label, profile, Shift ID, Source/Target Model, Adapter, state, and evidence reference. Pi session entries remain the running Shift state owner. Coordinator independently validates the machine-readable Shift Record before updating the Projection; the worker final report is only a later cross-check and never owns Projection state.

**Coordinator Runtime**
The current session hosting the coordinator: `codex-cli`, `claude-cli`, or `pi-cli` for canonical CLI/Herdr orchestration; `codex-app` only when the `delivery-pipeline-codex-app` shell is invoked. Coordinator model is chosen before skill invocation and is not part of Worker Role Configuration.

**Dispatch Model**
- `skills/delivery-pipeline` is the single canonical CLI/Herdr core installed unchanged for pi, Codex CLI, and Claude CLI; current host never rewrites configured worker routing.
- Canonical CLI Dispatch resolves work item → one of six roles → configured agent/ordinary model/effort plus optional Bootstrap Gearshift Policy. Agent selects lane runtime: pi → `herdr-pi-pane`, codex → `herdr-codex-pane`, claude → `herdr-claude-pane`.
- Ordinary pi lanes start with `--approve --model <model> --thinking <effort>`. Eligible pi frontend/backend lanes instead start on their configured bootstrap Source Model, load the Delivery Pipeline Adapter, and arm Pi Gearshift toward the ordinary Target Model. Codex CLI uses `--model <model>` plus `model_reasoning_effort`; Claude CLI uses `--model <model> --effort <effort>`. Kind-specific permissions belong to Trusted Execution Bootstrap.
- Routes bind only at lane launch; after dispatch, the user may change the model in the worker pane and the lane's delivery stands. The coordinator performs no pane-model reconciliation and model drift never rebuilds a lane, but final evidence records actual model history and only a matching Shift Record proves Bootstrap Handoff.
- `skills/delivery-pipeline-codex-app` is the only transport shell. It skips Worker Role Configuration and maps all six delegated roles to Codex App tasks + App-managed Execution Worktrees (`codex-thread`); its packet, registry overlay, role-aware fan-in, and task references are co-located inside that shell.
- `delivery-pipeline-setup` probes pi (`pi --list-models`), Codex (`codex debug models`), Claude `settings.json.env`, and Pi Gearshift Core flags, then requires explicit ordinary routes, optional eligible bootstrap routes, and one Gearshift policy. There are no built-in agent/model/effort defaults.
- Same-batch lanes complete startup readback before Dispatch Handoff; long tasks wake the current coordinator only on user completion, Lane Terminal Signal, or explicit monitor request.
- Each lane persists role, output mode (`commit | artifact | checks | verdict`), agent, ordinary/bootstrap route, Gearshift Projection, evidence, runtime, permissions, worktree, and transport coordinates. Only commit mode cherry-picks; artifact/checks/verdict modes verify durable evidence then become `consumed`. Existing lanes recover by registry rather than new configuration.
- Map Run Authority covers named-map canonical tracker transitions and next ready frontier; final publication remains an independent gate.
- Ready frontier, one writer, Execution Worktree isolation, Integration, and terminal fan-in do not change with agent kind.

## Relationships

- One running Herdr session → many Herdr workspaces
- One Herdr workspace → many coordinator and worker panes across maps
- One Coordinator Pane → one current Herdr workspace → new lanes default to capacity-managed worker tabs in that workspace (max 4 panes per tab, four-corner splits, overflow tabs `X-2`/`X-3`; all lane types share the same worker-tab capacity pool)
- One map → one integration worktree → many execution worktrees and runtime-owned lanes
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
