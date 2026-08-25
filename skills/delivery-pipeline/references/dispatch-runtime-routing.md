# 调度运行时路由

创建、恢复或替换任何 worker lane 前读取本文件。本文件是 Codex entrypoint 的 Coordinator
Runtime adapter：区分 `codex-app` 与 `codex-cli`。Coordinator Runtime 只决定 transport；
worker kind 是第二条轴。ready frontier、单写者、Execution Worktree、Integration 和 terminal
fan-in 保持不变。

**Herdr Control Route** 是本文件唯一的 pane lifecycle owner：coordinator 已在 Herdr pane
（`HERDR_ENV=1`）时解析并调用 `$herdr`；Codex App coordinator 不在 Herdr pane 时走
**Codex App Herdr Bridge**，所有 CLI 调用显式携带已读回的 visible Herdr session。下游文件提到
Herdr Control Route 时都回到本节，不依赖 focused pane。Bridge 是 `delivery-pipeline` 自有 adapter，
直接调用 Herdr CLI，不调用、不修改 `$herdr` skill。

## 选择顺序

1. **识别 Coordinator Runtime。** 检查 `list_projects`、`create_thread`、`list_threads`、
   `read_thread`、`wait_threads`、`send_message_to_thread`、`set_thread_title`、
   `set_thread_archived` 和 `list_archived_threads` 是否全部可用。全部可用时记录
   `coordinator_runtime: codex-app`；否则本 Codex entrypoint 记录
   `coordinator_runtime: codex-cli`。推断：完整原生 task tool set 表示 Codex App。Codex CLI
   原生 thread 能力是 Unknown，本模型不尝试调用它。
2. **探测 Herdr capability。** 可能需要 Claude/Herdr 的分支先检查 `herdr` 与目标 agent binary。
   `HERDR_ENV=1` 时验证当前 `$herdr` session 可读；`codex-app` 且 `HERDR_ENV!=1` 时验证
   `command -v herdr`、`command -v <claude|codex>`、`herdr session list --json`，并确认
   `herdr --help` 暴露 `--session` 与 `server`。先完成 capability probe，再向用户呈现 Herdr/Claude
   选择。probe 失败时直接报告 `dispatch unavailable` 和 durable packet。
3. **显式指令优先。** `codex-app` 用户明确要求本次使用 Herdr 时选择
   `dispatch_runtime: herdr`；否则选择 `dispatch_runtime: codex-app`，新 lane 使用
   `runtime: codex-thread`。`codex-cli` 固定选择 `dispatch_runtime: herdr`。
4. **选择 Herdr worker kind。** 用户指定 Codex CLI 或 Claude CLI 时固定对应 pane；否则按
   `frontier-lanes.md` 的 domain binding。
5. 用户明确选择 Herdr，或回答“授权/批准/可以”后，由当前 coordinator 在同一 turn 继续派发；
   同一次 approval 写为 `bootstrap_authority: trusted_execution_bootstrap`，覆盖本文件定义的安全
   Claude bootstrap，不覆盖 remote publication。

把 `coordinator_runtime`、`dispatch_runtime`、`bootstrap_authority`、`herdr_session_name` 与
`herdr_session_owned` 写入 map registry。每条 existing lane 仍按自己的
`runtime` 恢复；本次选择只约束新 lane。存在 active writer 时先完成恢复与去重，再创建
replacement 或切换新 lane 的 transport。

选择 `dispatch_runtime: codex-app` 后加载 `task-coordinate-title.md`。map key 可用时先把当前
coordinator task 设为 `LEAD` 坐标并 readback；创建、替换、重命名或恢复每条 user-visible
Codex App task 时沿用同一命名契约。

## Dispatch critical path

每个 maximal safe batch 只做一次并行 preflight snapshot：同时读取 target ticket/claim/registry、
Integration HEAD/clean state、worktree path/branch collision 和已选 transport capability。snapshot 中
相互独立的 checks 并行；写入导致某个字段失效时只刷新该字段，不重读整个 map、合同或 owner body。
preflight 通过后一次准备本批全部 packet/registry；同批 lane 并发创建和启动。Herdr lanes 的
workspace 解析是批级唯一串行前置，readback 后同批 pane 的 create/split、agent start 与投递
并发发出，批末一次聚合 working 确认（并行等待各 pane），确认后挂 listener，聚合 readback 后到达
Dispatch Handoff——串行单位是批级前置，不是 pane。单条 lane 到达
`working` 不提前 yield，直到整批均完成 startup readback 或已隔离为 `setup_blocked`；单 pane
失败独立隔离为 `setup_blocked`，sibling pane 不受影响。

安全不变量保持不变：一个 active writer、registry 先于 worker、Execution Worktree 隔离、真实路径与
base commit readback、未知/dirty/conflict fail closed。routine success 不逐步播报；一次开始状态与一次
Dispatch Handoff 足够。

## Codex App 原生调度

### 创建

1. map registry 没有已验证的 Source owner projectId 时，才用 `list_projects` 按
   `fresh-session-boundaries.md` 解析并持久化；后续 lanes 复用，project/path 变化时才刷新。
2. 按 `task-coordinate-title.md` 为本批生成 Task Coordinate Title 和完整 packet；同批 `codex-thread`
   并行调用 `create_thread`，每次显式设置 `title`。target 使用该 project，environment 使用 worktree，
   `startingState` 的 branchName 必须是当前 Integration branch。Codex App 拥有 Execution
   Worktree 的创建与路径；不要预创建同票手工 worktree。
3. `create_thread` 返回 `threadId` 时记录其 `hostId`。只返回 `clientThreadId` 表示 worktree 仍在
   setup；`clientThreadId` 不能作为 `thread_id`，用 `list_threads` 按 Task Coordinate Title、
   project 和 lane 标识找到 ready task。
4. 用一次聚合 readback 并行调用 `list_threads` / `read_thread` 与 Git state：
   title 与预期 Task Coordinate Title 精确相等，task 属于 owner project，worktree 的 common dir
   属于 source repo，base commit 是 dispatch 时 Integration HEAD，cwd 不在 Source Worktree 或
   Map Integration Worktree。
5. worker 在首次写入前创建或验证 `codex/issue-<ticket>` branch。把 `project_id`、`host_id`、
   `thread_id`、`thread_archived: false`、实际 worktree、branch 和 base commit 写入 lane registry，
   并精确 readback；task 已接受 prompt 且出现首次真实 progress 后写 `state: running`。

完成标准：本批每条 `runtime: codex-thread` lane 的 Task Coordinate Title、task、App-managed
Execution Worktree 和 registry 互相一致，packet 带 resolved owner/work item，task 已运行；失败项已
隔离为 `setup_blocked`。完成整批 registry 聚合 readback 后才 yield；Dispatch Handoff 是 coordinator
本轮 terminal。

### 监控与恢复

- 默认不等待 running task。只有用户明确要求 monitor/wait，或用户返回并给出完成信号时，才对同批
  1–8 个 tasks 用一次带 cursor 的 `wait_threads` snapshot；routine commentary 不触发 fan-in。
- terminal 后用 `read_thread` 读取一次 final report，随后以 Git commit、checks、dirty state 和
  touched files 为准进入 Integration。
- worker 需要范围内的收口指令或回答时才调用 `send_message_to_thread`；显式 monitor 使用
  `wait_threads` snapshot，不反复发送催促。
- 新会话对 `running` / `terminal` lane 用 registry 的 `thread_id` + `host_id` 调用
  `list_threads` / `read_thread`；对 `integrated` / `close_pending` / `closed` lane 调用
  `list_archived_threads` 验证 archive，`close_pending` 按 `execution-worktree-integration.md` 重试。
  推断：archived task 不出现在 active task 列表是预期状态。task 不可见但 commit 存在时从持久
  Git 证据继续；task 和 commit 都不存在且已排除 active writer 后才创建 replacement。

## Herdr 调度

此分支由用户明确选择，或在 Codex App thread tools 不完整而 Herdr Control Route 可用时选择。
在 Map Integration Worktree 对应 workspace 中创建 Codex CLI 或 Claude Code pane。
显式 worker kind 优先；否则按 `frontier-lanes.md` 的 Herdr binding：前端/设计用 Claude Code，
后端及其余用 Codex CLI。

### Codex App Herdr Bridge

`codex-app` 且 `HERDR_ENV!=1` 时，用 `herdr session list --json` 选择 visible Herdr session：运行中的
`default` 优先；没有 `default` 且恰有一个 running session 时使用该 session；其余情况在创建 lane
前请用户选择或启动 Herdr。记录 `herdr_session_owned: false`。Map 隔离由 workspace 承担。此分支
直接执行下列 Herdr CLI，不解析 `$herdr`，因此不要求 `HERDR_ENV=1`。

1. 后续 workspace/tab/pane/agent/read/cleanup 命令统一使用
   `herdr --session "$herdr_session_name" <group> ...`，每次从 JSON 读回真实 ID。
2. workspace label 使用 map 标题，HITL tab 使用 `G-#<ticket>`，pane label 使用 ticket title；创建后
   readback 三层坐标，确保 lane 直接出现在用户的 Herdr UI。
3. Claude pane 按 `pane-lifecycle-rules.md` 的启动命令以完全授权模式启动。

4. `bootstrap_authority: trusted_execution_bootstrap` 只自动处理两个已知 UI：
   - **workspace trust**：UI 路径必须完全等于 registry 的 Execution Worktree，且 Git common dir、
     branch 与 base commit 已通过 startup probe；
   - **external imports**：列出的每个文件必须属于 packet 的 resolved owner skill realpath、机械解析出的
     direct reference paths，或同时适用于 Source Worktree 与 Execution Worktree 的共同祖先 repo
     instructions；worker 自己完整读取，coordinator 不预加载 owner body。

   每次匹配后调用 `herdr --session "$herdr_session_name" agent send-keys "$agent_name" enter`，再读
   `agent get` / `agent read`。授权状态按 `blocked -> idle -> working` 推进；其他 question/approval UI
   保留为 `blocked` 并交给用户。
5. Claude 到达 `idle` 后，按 `pane-lifecycle-rules.md` 的投递机制投递 packet 的单行绝对路径引用（投递不阻塞），再按该文件的
   Working 确认观察到 `idle -> working` 即 startup terminal（前置：`agent prompt` accepted；packet 与 registry 已
   持久化 owner、ticket 和坐标。HITL lane 跳过 `running` checkpoint，直接执行
   `created -> awaiting_human` 并写 `state: awaiting_human` 后精确 readback；非 HITL lane 写
   `state: running` 并 readback。
   单条 lane 的 registry readback 后继续本批其余 lanes；整批 readback 后才 yield，Dispatch Handoff 是
   coordinator 本轮 terminal。不等待首个业务问题，
   不读取 routine terminal、可见屏幕或进程信息，也不启动 `agent wait` 或 listener。用户在 Herdr
   直接回答；用户回到 Codex App 报告完成后，按 `frontier-lanes.md` 做 terminal fan-in。
6. bridge capability、session readiness 或 agent binary 缺失时输出完整 durable packet 并报告
   `dispatch unavailable`；已创建的空 Execution Worktree 按 cleanup contract 收口。

完成标准：Claude pane 在 visible Herdr session 中可见，以 `--dangerously-skip-permissions` 运行，
`agent prompt` 已 accepted 且 agent 为 `working`；registry 为 `running` 或 `awaiting_human`，Codex App
已结束本轮，不监控 worker。

### Lane 创建与生命周期

1. workspace 缺失时通过 Herdr Control Route 懒创建；已有 workspace 先 readback。workspace 是本批
   唯一串行前置，readback 后同批 Herdr lanes 并行创建。
2. 从同一个当前 Integration HEAD 并行创建各票的 `codex/issue-<ticket>` 或
   `claude/issue-<ticket>` Execution Worktree。
3. Codex CLI 填写 `assets/HERDR_CODEX_IMPLEMENT_DISPATCH_PACKET.md`；Claude Code 填写
   `assets/HERDR_CLAUDE_IMPLEMENT_DISPATCH_PACKET.md`。以 Execution Worktree 为 cwd 启动 pane，
   并验证 placement、owner skill 和 work item。
4. registry 先以 `state: created` 写入 `runtime: herdr-codex-pane` 或 `runtime: herdr-claude-pane`，以及
   `herdr_session_name`、`herdr_session_owned`、`bootstrap_authority`、`agent_permission_mode`、
   workspace/tab/pane、worktree、branch 与 base commit。
5. agent 启动并接受 packet 后，HITL 直接写 `awaiting_human`，其他 lanes 写 `running`；terminal、
   recovery 和 pane cleanup 通过 Herdr Control Route 完成；该 lane 不调用 Codex App
   thread tools。批末一次聚合 working 确认（并行等待各 pane），确认后挂 listener；整批聚合
   readback 后统一 Dispatch Handoff。

完成标准：每条 Herdr lane 都有唯一 kind-matched pane、唯一 Execution Worktree 和可读回 registry。

## 模式切换

- active `codex-thread` 继续由 thread tools fan-in；active `herdr-codex-pane` 和
  `herdr-claude-pane` 继续由 registry 指定的 Herdr Control Route fan-in。切换不会迁移或复制
  running lane。
- replacement 沿原 lane runtime，除非用户明确改变该票且已证实原 active writer 不存在。
- cleanup 按每条 lane 的 runtime 执行；只关闭本 lane 创建的 panes 并保留 map workspace。
  `herdr_session_owned: false` 的 user-visible session 始终保留运行。
