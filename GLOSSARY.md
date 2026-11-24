# Wayfinder Implement Orchestrator — Domain Model

## Core Concepts

**Epic**
一个 MMF 容纳不下的交付目标，由多个独立验收、合入及上线的 MMF 组成。Epic Issue 记录该目标、MMF 索引和跨 MMF 依赖。`to-epic` 切分 MMF，用户确认一次；每个 MMF 跑在自己的 map 上，start blockers 清空后由 Epic 级 **Driver** 打开。Map 不是 Epic。

**MMF**
Minimal Marketable Feature. The unit of acceptance, merge, and release: one Spec, one MR, and zero or more tickets. One map delivers one MMF. Boundary test: a cut that lets each half ship alone, and that someone would use alone, is multiple MMFs. Spec-gate action: `skills/delivery-pipeline/references/gate-state-machine.md` §tickets 前链路.

**Source Worktree**
The user's primary working directory, typically checked out to `main` branch. This worktree remains stable during orchestration — the user can continue working here while maps run in parallel. Never modified by orchestrator automation.

**Map Integration Worktree**
A dedicated Git worktree created for one Wayfinder map's entire lifecycle (discovery → spec → tickets → implementation → integration). Lives at `<source-parent>/worktrees/<repo-name>-map-<issue-number>/` on branch `feature/map-<issue-number>`. It carries that map's one **MMF** and is the single summary-MR branch. Tickets are execution units inside this branch; they integrate here by cherry-pick and do not merge to main alone. In the default mode, automatically created when a map is launched from source worktree. Deleted after successful merge to main.

**Execution Worktree**
A dedicated Git worktree created for one implementation ticket's work. In the default mode it is based on the Map Integration Worktree branch, not main, and contains one ticket's changes. Codex App native Dispatch lets Codex App own the worktree path and initial checkout; Herdr Dispatch uses `<source-parent>/worktrees/<repo-name>-map-<map-issue>-issue-<ticket-number>/`; T3Code Dispatch uses `~/.t3/worktrees/<two-segments>/` via `delegate_task(isolation:"worktree")`; Lody Dispatch uses the Lody-managed worktree from `lody_session_create(workContext: {worktree: true})`. The worker creates or verifies `codex/issue-<ticket-number>` (Codex App/Codex CLI), `claude/issue-<ticket-number>` (Claude Code), or `pi/issue-<ticket-number>` (pi) before writing. After Integration the Driver can close the worktree.

**Integration**
The default-mode process of collecting completed execution worktree commits into the map integration worktree. Legacy lanes use `git cherry-pick`. For frozen briefs, the Driver merges each verified branch in full and runs the ticket scenario on the integration HEAD. Happens incrementally as tickets complete. Distinct from merging to main and from **Ticket Release Mode**. See **Map Integration Worktree**.

**Merge to Main**
The final step that lands the one **MMF** from **Map Integration Worktree**: rebase that branch onto main and push. Only happens after that MMF's tickets complete, whole-change checks pass, and the user confirms the test strategy.

**Ticket Release Mode（独立票模式）**
Exception mode. The trigger lives only in `skills/delivery-pipeline/references/integration-worktree-management.md` §独立票模式. When that section has written `delivery_mode: ticket_release`, each Execution Worktree starts from the freshly fetched remote default branch instead of the Map Integration Worktree, each ticket ships through its own MR, and the ticket closes only after `release_stage` reaches `deployed`. No Integration, cherry-pick, or summary MR.

**Test Decision Point**
完成 whole-change testing/review 后核对测试策略的 gate。策略在 **Plan Review** 定下；范围与风险
未变时沿用、不停，变化时触发 **Halt**。策略与证据要求见
`skills/delivery-pipeline/references/test-decision-and-rebase.md`；测试选择不等于远程发布授权。

**Concurrent Maps**
多个 Wayfinder map 各自拥有 Integration Worktree 与 Execution Worktree，并行推进。Epic 调度只覆盖其已确认的 MMF。

**Worktree Lifecycle**
Creation → work → integration/merge → deletion. Execution worktrees: created at dispatch, deleted after cherry-pick in the default mode. Integration worktrees: created at map start, deleted after push to main. Empty setup-failed worktrees are deleted after the bounded retry; active, awaiting-human, or recoverable blocked lanes retain their worktrees.

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

**派发合同（brief）**
技术负责人交给执行者的一份工作说明，写明本次要交付的结果、允许改动的范围和验收方式。一张 ticket 可以对应一份或多份派发合同。

**Dispatch Handoff**
Dispatch Handoff is batch-scoped. It is the control-plane terminal after every item in the selected maximal safe batch is accounted for: each successful user-visible lane has verified coordinates and isolation, accepted its packet, entered `working`, and persisted the runtime state; each failed setup is durably isolated as `setup_blocked`. The coordinator reports the batch coordinates and ends its turn only after the whole batch, then resumes on a user completion signal, a real terminal event, or an explicit monitor request; repository file overlap is an Integration risk handled by isolated Execution Worktrees and serial fan-in, not a dispatch blocker.

**Coordinator Recovery**

一个 map 的最新恢复记录，连接当前 gate、全部 active writers、未决约束与原始证据。
它是可重建的导航快照，不是新的状态权威或授权；恢复后的动作仍由 tracker、Git、lane registry
与运行证据判定。它与宿主自动生成的聊天压缩摘要不同。

**Lane Terminal Signal**
The worker's whole terminal output: one line `LANE_DONE <lane_id> <delivery coordinate>` (commit SHA, artifact URL, result or verdict path, Integration HEAD), or `LANE_DONE <lane_id> BLOCKED <reason; artifact path>`. Everything else the coordinator needs it reads from Git, tracker, and registry. The coordinator-side lane watcher (`skills/delivery-pipeline-herdr/scripts/lane-watch.sh`) polls the worker pane output for the marker and prompts the Coordinator Pane; pane-vanished and two-hour timeout also wake the coordinator. `herdr agent wait --until done` is not a valid terminal signal: CLI agents settle back to idle without emitting a `done` event, so a `done` listener blocks forever. HITL lanes still wake on the user completion signal; the watcher is only a terminal backstop.

**HITL Handoff**
The Herdr specialization of Dispatch Handoff. A configured pi, Codex CLI, or Claude CLI pane has accepted its packet and entered `working`; its lane persists `awaiting_human`. The user completes the live discussion in Herdr, then returns to the current coordinator session to trigger terminal fan-in from durable evidence.

**Task Coordinate Title**
A stable, human-facing Codex App task title that identifies the owning map, lane role, and work item. It is used only by the `delivery-pipeline-codex-app` shell; the lane registry remains recovery truth.

**Codex Task Archive**
The post-Integration transport state of a `codex-thread` lane owned by the Codex App shell. Archive readback closes the lane; `close_pending` retains recoverable coordinates without blocking ready tickets, while unsuccessful Integration keeps the task visible.

**Orca Entrypoint**
The independent `delivery-pipeline-orca` skill bound to the current Orca runtime. Before any operation it fixes one executable and reads that binary's version-matched guides with exact native command provenance, runtime/target-host/terminal identity, exact skill discovery, shared worker policy, and operation-scoped capability evidence. Missing or Unknown evidence returns `blocked` / `dispatch unavailable`; it never falls back to Herdr or Codex App. #120 owns only this entry/preflight boundary; Orca lane lifecycle coordinates belong to later implementation tickets.

**Configured Planning Lane**
A Herdr worker handling one AFK discovery/research item or one spec/tickets gate. Its agent, model, and effort come from the `planning` task type in the Worker Task Configuration; it uses the same registry, packet, Dispatch Handoff, and fan-in contract as other configured lanes.

**Review Evidence Bundle**
A repo-external, single-snapshot evidence set produced by the parent worker before `code-review` fans out to read-only Standards/Spec reviewers: `fixed-point.txt` (fixed point, HEAD, diff relation), `diff.patch`, and `changed-paths.txt` with per-path patch offsets. The whole-change review lane uses the Map Integration Worktree creation base persisted in the map registry as fixed point; a shell that still runs per-ticket review uses the Execution base. Reviewers find any other fact themselves with read/search.

**Review Budget**
The hard limit on review rounds. CLI runs no per-ticket review: one whole-change review on the integration branch gets at most 3 rounds, and every FIX round's findings go to one implementer lane. A shell that still runs per-ticket review gives each ticket its own 3 rounds. `scripts/review_gate.py` derives each outcome from P0/P1 counts and enforces the limit through a ledger. `REVIEW_BLOCKED` terminates a formal review round with known reviewer execution mismatch (DD-508 R17), retaining findings and forbidding automatic rerun; Unknown alone does not block. `REVIEW_EXHAUSTED` is its budget terminal state: the work stays unmerged and a retro of the implementation chain runs.

**Worker Task Configuration**
One canonical config schema (CLI version 7 with version 6 compatibility, App version 5) with two file instances: the CLI instance at user-level `~/.config/delivery-pipeline/model-roles.json` and the App instance at `skills/delivery-pipeline-codex-app/config/models.json`. The schema defines task types (`coordinator`, `research`, `prototype`, `planning`, `design`, `frontend`, `backend`, `testing`, `integration`, `assistance`, `second-opinion`), each bound to a non-empty `agent`, `model`, and `effort`; agent is one of `pi`, `codex`, `claude`, `antigravity`, or `codex-app` and selects the transport (`antigravity` runs via T3Code `delegate_task`, not Herdr pane). CLI lanes run each work entry's `{agent, model, effort}` directly in one pass (ADR-0018). Named `modes` presets carry `kind` (`staged`/`direct`) plus per-agent `starting`/`execution`/`direct` pairs; CLI modes must be `direct` and are consumed only when a ticket or map explicitly names one (its `direct` group overrides), while App lanes resolve them in ticket → map → `default_mode` order (`default_mode` is App-only). Formal review uses the `review.<implementation|whole-change>.<standards|spec>` matrix. The single schema authority is `skills/delivery-pipeline/references/model-config-schema.md`; each transport declares its required task-type subset. Canonical CLI skills contain no default model routing; missing, unknown, or invalid configuration blocks dispatch and runs `delivery-pipeline-setup`. Older config versions migrate mechanically via `model_config.py migrate`. Existing lanes recover from registry and are not migrated by a configuration change.

**出自哪家（厂商）**

整体交付检查有候选时，用于优先选择与所有写代码模型都不同厂商的检查模型。
默认按内置模型前缀对照表判断（剥离路由与上下文后缀），精确 agent/native model 的
`model_families` 手动声明可覆盖；未命中为 Unknown。厂商判断不代表能力核对或外部认证。
预计结果按设计、前端、后端主模型计算，运行时按实际执行身份计算；两者共用选择函数。
没有另一家或存在认不出的模型时按可运行池的用户顺序回退；实施检查不使用该规则。

**Coordinator Runtime**
The current session hosting the coordinator: `codex-cli`, `claude-cli`, or `pi-cli` entering through the `delivery-pipeline-herdr` shell; `t3code` when running in a T3 Code thread via the `delivery-pipeline-t3code` shell; `lody` when running in a Lody session via the `delivery-pipeline-lody` shell; `codex-app` only when the `delivery-pipeline-codex-app` shell is invoked; the current Orca terminal only when the `delivery-pipeline-orca` entrypoint is invoked. The current calling session is the coordinator; its model is chosen before skill invocation and is not part of Worker Task Configuration; a `coordinator` work entry only records recommendation observations.

**Dispatch Model**

- `skills/delivery-pipeline` is the single canonical core installed unchanged for pi, Codex CLI, Claude CLI, T3 Code, and Lody; current host never rewrites configured worker routing.
- CLI Dispatch (Herdr, T3Code, or Lody) resolves work item → task type → configured agent/model/effort. Agent selects lane runtime: Herdr uses pi → `herdr-pi-pane`, codex → `herdr-codex-pane`, claude → `herdr-claude-pane` (rejects `antigravity`); T3Code uses pi/codex/claude/antigravity → `t3-task` via `delegate_task`; Lody uses pi/codex/claude → `lody-session` via `lody_session_create`.
- Herdr: pi starts with `--approve --model <model> --thinking <effort>`; Codex CLI with `--model <model>` plus `model_reasoning_effort`; Claude CLI with `--model <model> --effort <effort>`. Kind-specific permissions belong to Trusted Execution Bootstrap.
- T3Code: coordinator calls `orchestrator_capabilities` to verify model/effort, then `delegate_task(target: {providerInstanceId, model, options}, isolation:"worktree", mode:"async")`. Worker kind maps pi→`pi`, codex→`codex`, claude→`claudeAgent`, antigravity→`antigravity` (`thought_level`).
- Lody: coordinator verifies model/effort against the matching agent config's `runConfig`, then calls `lody_session_create(agentConfigId, modelId, reasoningEffort, workContext: {kind: local, worktree: true})`; the worker's final reply is delivered back as the Operation result.
- Model/effort bind only at lane launch; after dispatch, the user may change the model in the worker pane/thread and the lane's delivery stands. The coordinator performs no mid-run or fan-in model reconciliation: model drift from the registry never rebuilds a lane or rewrites the config. Work lane delivery is unchanged; formal whole-change review separately blocks round release on known per-axis executed mismatch (DD-508 R17), without rerun or candidate replacement.
- `skills/delivery-pipeline-codex-app` remains the Codex App transport shell. Its instance of the Worker Task Configuration binds task types to `agent: codex-app` and maps delegated work to Codex App tasks + App-managed Execution Worktrees (`codex-thread`); its packet, registry overlay, task-aware fan-in, and task references are co-located inside that shell. App 模型值统一读取 `skills/delivery-pipeline-codex-app/config/models.json`；`references/development-mode.md` 定义查询与执行合同。新 lane 冻结计划与来源，恢复沿持久值；App execution readback remains separate from requests.
- `skills/delivery-pipeline-orca` is a separate Orca-bound entrypoint. It reuses the current CLI schema and owner contract, but resolves one Orca executable and requires version-matched guides, exact native discovery, current terminal identity, shared agent/model/effort readback, and operation-scoped capabilities. It owns no fallback, override config, static compatibility matrix, second installer, or dispatcher.
- New CLI lanes run the task type's work entry directly; a ticket or map may explicitly name a `modes` preset whose `direct` group overrides it. App implementation lanes keep resolving a named mode in ticket → map → `default_mode` order. Plans freeze mode name (none on the default path), source, and phase model/effort in the packet and registry. Existing lanes recover from their registry and are never migrated by a config change.
- `delivery-pipeline-setup` probes pi (`pi --list-models`), Codex (`codex debug models --bundled`；直连 OpenAI 使用内置清单，网关路由取 catalog 与网关清单交集，均不提供 ultra/persistent), Claude 官方模型清单（Claude Code 当前账号与地址，route=official，只读不推理）, and Antigravity（只读 `~/.t3/caches/antigravity.json` 与 `~/.t3/userdata/settings.json` 启用态，route=t3code，提取带 `thought_level` 档位的模型，不读取凭据）, then requires explicit choices for all CLI-required task types and the review matrix. There are no built-in agent/model/effort defaults. Claude 地址依次取进程环境、settings.env、Anthropic 默认地址；凭据依次取 ANTHROPIC_API_KEY（进程环境优先于 settings.env）、ANTHROPIC_AUTH_TOKEN（同上）、OAuth（macOS 只读 Claude Code-credentials 钥匙串项，其他平台只读 ~/.claude/.credentials.json）。不刷新过期 OAuth，不执行 apiKeyHelper；本机网关和 apiKeyHelper 暂不支持核对。只保留官方明确支持的档位与完整模型 id；凭据不进入证据或异常文本。首次钥匙串授权框未确认、额度与实际调用均为 Unknown。
- Same-batch lanes complete startup readback before Dispatch Handoff; long tasks wake the current coordinator only on user completion, Lane Terminal Signal, or explicit monitor request.
- Each lane persists task type, output mode (`commit | artifact | checks | verdict`), agent, model, effort, evidence, runtime, permissions, worktree, and transport coordinates. Only commit mode cherry-picks; artifact/checks/verdict modes verify durable evidence then become `consumed`. Existing lanes recover by registry rather than new configuration.
- Map Run Authority covers named-map canonical tracker transitions and next ready frontier; final publication remains an independent gate.
- Ready frontier, one writer, Execution Worktree isolation, Integration, and terminal fan-in do not change with agent kind.

**Entrypoint Layering**
The rule that arranges the entry skills. `skills/delivery-pipeline` is the Core Chain: the single home of shared semantics (gate state machine, lane registry, Worker Task Configuration schema, owner resolution) and of the pi/Codex CLI/Claude CLI coordinator adapters. `skills/delivery-pipeline-herdr`, `skills/delivery-pipeline-codex-app`, `skills/delivery-pipeline-orca`, `skills/delivery-pipeline-t3code`, and `skills/delivery-pipeline-lody` are peer Transport Shells: each owns its channel-specific dispatch, monitoring, and lifecycle material, and reads the Core Chain. Dependencies point only from shell to core; the core may name shells and enumerate their runtime markers in shared state (the lane registry must parse lanes written by any runtime), but never references files inside a shell. Channel-specific content lives in its shell; shared content settles in the core; no fourth shared location exists.

## Autonomy

**Driver**
所有 transport 共用的唯一 gate 判定程序：读取持久状态，自行执行能执行的 **Action**，
遇到须宿主工具、判断或等待时只交回一条。壳只声明各类 Action 由程序还是 coordinator 执行，
不写推进逻辑。分两级：map 级推进一个 MMF；Epic 级只决定哪个就绪 MMF 该开 map。
_Avoid_: Scheduler、调度器

**Action**
Driver 每一步输出的单条指令：执行一次派发、fan-in 或清理，请求一次判断，停在 **Halt**，或结束本轮等待唤醒。
交给 coordinator 的 Action 带 id；执行结果以同 id 的回执交回 Driver，registry 只由 Driver 写。

**Coordinator**
宿主会话里的 LLM：执行 Driver 交给它的 Action，当场回答轻判断，把重判断派成 lane。它不推导 gate。

**Plan Review**
每个 MMF 的 to-tickets 草稿通过脚本核对后、发布前，用户审阅一份 show-me HTML 页面，页面包含 Spec、切片表、波次、关键路径和测试选择默认值。
新 map 的同一阶段由 Driver 自动检查和冻结计划，并生成计划快照；旧人工审核 map 回复通过后授予 **Autonomy Grant**。

**Autonomy Grant**
计划冻结后写入 map registry 的授权：在已确定计划内自动推进到 Merge Review，
只在 Halt 时停下。不含远程发布授权。

**Halt**
自治运行中唯一的人工停点。只有命中封闭的异常清单才触发：计划的 T/R、范围或验收要改；补票超出已批准波次或改动合同票；
`REVIEW_EXHAUSTED`；重拆后仍失败；需要远程权限、不可逆操作或授权外的决定。
清单外的偏差自动处理，并在 Merge Review 时报告。

**Merge Review**
一个 MMF 开 PR 或合入 main 之前，用户审阅一份 show-me HTML 页面，对比计划与实际交付，包括自动处理过的偏差。
通过即授权 push、建 PR、等 CI、按仓库分支合同合入并收尾；CI 红或阻塞评审意见触发 **Halt**。

## Relationships

- One running Herdr session → many Herdr workspaces
- One Herdr workspace → many coordinator and worker panes across maps
- One Coordinator Pane → one current Herdr workspace → new lanes default to capacity-managed worker tabs in that workspace (max 4 panes per tab, four-corner splits, overflow tabs `X-2`/`X-3`; all lane types share the same worker-tab capacity pool)
- One map → one MMF → one integration worktree → many execution worktrees and runtime-owned lanes
- One map → many discovery tickets → configured planning/design lanes → many Herdr panes
- One execution worktree → one Codex App task or one Herdr-hosted Codex CLI/Claude Code/pi pane; future Orca Task/Dispatch ownership is not introduced by the #120 preflight entrypoint
- One Orca entry invocation → one fixed executable + one current terminal identity + one operation-scoped capability verdict
- Default mode: execution worktrees branch from the integration worktree, not from main. **Ticket Release Mode** is the exception.
- Integration worktree eventually rebases to main (not merge)
- Multiple maps run concurrently, isolated by separate integration worktrees

## Non-goals

**Not a global scheduler**
Epic coordinator 只协调同一 Epic 下的 Map。独立 Map 和其他 Epic 分别调度。

**Not a cross-map resource coordinator**
Maps share no worktrees, lanes, or capacity budget. The Epic-level Driver only decides which ready MMF opens a map; each map then manages only its own worktrees.

**Not branch-free**
Git worktrees fundamentally require branches. "No branches" is impossible — the design uses disciplined branch management instead.

**Not merge-based**
Uses rebase to main, not merge commits. Keeps linear history per map.
