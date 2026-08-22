# 调度运行时路由

创建、恢复或替换任何 worker lane 前读取本文件。本文件是 Codex entrypoint 的 Coordinator
Runtime adapter：区分 `codex-app` 与 `codex-cli`。Coordinator Runtime 只决定 transport；
worker kind 是第二条轴。ready frontier、单写者、Execution Worktree、Integration 和 terminal
fan-in 保持不变。

**Herdr Control Route** 是本文件唯一的 pane lifecycle owner：coordinator 已在 Herdr pane
（`HERDR_ENV=1`）时解析并调用 `$herdr`；Codex App coordinator 不在 Herdr pane 时走
**Codex App Herdr Bridge**，所有 CLI 调用显式携带 map 的 named session。下游文件提到
Herdr Control Route 时都回到本节，不自行选择 default/focused session。

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
5. 用户批准后由当前 coordinator 在同一 turn 继续派发；批准只改变 transport，当前 Codex App
   task 立即进入 Bridge 启动步骤。

把 `coordinator_runtime`、`dispatch_runtime` 与 bridge 使用的 `herdr_session_name` 写入 map
registry。每条 existing lane 仍按自己的
`runtime` 恢复；本次选择只约束新 lane。存在 active writer 时先完成恢复与去重，再创建
replacement 或切换新 lane 的 transport。

选择 `dispatch_runtime: codex-app` 后加载 `task-coordinate-title.md`。map key 可用时先把当前
coordinator task 设为 `LEAD` 坐标并 readback；创建、替换、重命名或恢复每条 user-visible
Codex App task 时沿用同一命名契约。

## Codex App 原生调度

### 创建

1. 用 `list_projects` 按 `fresh-session-boundaries.md` 解析 Source owner projectId，并确认项目是
   当前 repo。
2. 按 `task-coordinate-title.md` 生成 Task Coordinate Title，并与完整 packet 一起传给
   `create_thread`；显式设置 `title`。target 使用该 project，environment 使用 worktree，
   `startingState` 的 branchName 必须是当前 Integration branch。Codex App 拥有 Execution
   Worktree 的创建与路径；不要预创建同票手工 worktree。
3. `create_thread` 返回 `threadId` 时记录其 `hostId`。只返回 `clientThreadId` 表示 worktree 仍在
   setup；`clientThreadId` 不能作为 `thread_id`，用 `list_threads` 按 Task Coordinate Title、
   project 和 lane 标识找到 ready task。
4. 用 `list_threads`、`read_thread`、`git worktree list --porcelain` 和 Git state readback：
   title 与预期 Task Coordinate Title 精确相等，task 属于 owner project，worktree 的 common dir
   属于 source repo，base commit 是 dispatch 时 Integration HEAD，cwd 不在 Source Worktree 或
   Map Integration Worktree。
5. worker 在首次写入前创建或验证 `codex/issue-<ticket>` branch。把 `project_id`、`host_id`、
   `thread_id`、`thread_archived: false`、实际 worktree、branch 和 base commit 写入 lane registry，
   并精确 readback。

完成标准：`runtime: codex-thread` lane 的 Task Coordinate Title、task、App-managed Execution
Worktree 和 registry 互相一致，startup probe 已读回 owner skill name/path 与 work item。

### 监控与恢复

- 对同批 1–8 个 running tasks 用一次 `wait_threads`；后续等待携带每个 task 的最新 cursor。
  routine commentary 不触发 fan-in，只在 completed 或 needs-attention 时读取。
- terminal 后用 `read_thread` 读取一次 final report，随后以 Git commit、checks、dirty state 和
  touched files 为准进入 Integration。
- worker 需要范围内的收口指令或回答时才调用 `send_message_to_thread`；常规进度用
  `wait_threads`，不反复发送催促。
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

`codex-app` 且 `HERDR_ENV!=1` 时，从 repo 与 map/root work-item key 生成只含 ASCII 字母、数字、
`.`、`_`、`-` 的稳定 `herdr_session_name`，例如 `delivery-pagugu-map-1`。禁止使用 default session。

1. 用 `herdr session list --json` readback named session。server 未运行时，通过非阻塞 terminal
   启动 `herdr --session "$herdr_session_name" server`，读到 `api socket:` 后再继续。
2. 后续 workspace/tab/pane/agent/read/wait/cleanup 命令统一使用
   `herdr --session "$herdr_session_name" <group> ...`，每次从 JSON 读回真实 ID。
3. `agent start` 返回 `agent_not_ready` 且 `agent get` 为 `blocked` 时保留 lane；读取 UI，向用户
   请求精确确认，确认后用同一 named session 和 agent/pane 继续 startup probe。
4. bridge capability、session readiness 或 agent binary 缺失时输出完整 durable packet 并报告
   `dispatch unavailable`；已创建的空 Execution Worktree 按 cleanup contract 收口。

完成标准：Codex App coordinator 无需进入 Herdr pane即可读回 named session，且 user approval
之后创建的 Claude/Codex pane 到达 `idle`、`working` 或可恢复的 `blocked`。

### Lane 创建与生命周期

1. workspace 缺失时通过 Herdr Control Route 懒创建；已有 workspace 先 readback。
2. 从当前 Integration HEAD 手工创建 `codex/issue-<ticket>` 或 `claude/issue-<ticket>`
   Execution Worktree。
3. Codex CLI 填写 `assets/HERDR_CODEX_IMPLEMENT_DISPATCH_PACKET.md`；Claude Code 填写
   `assets/HERDR_CLAUDE_IMPLEMENT_DISPATCH_PACKET.md`。以 Execution Worktree 为 cwd 启动 pane，
   并验证 placement、owner skill 和 work item。
4. registry 写入 `runtime: herdr-codex-pane` 或 `runtime: herdr-claude-pane`，以及
   `herdr_session_name`、workspace/tab/pane、worktree、branch 与 base commit。
5. terminal、recovery 和 pane cleanup 通过 Herdr Control Route 完成；该 lane 不调用 Codex App
   thread tools。

完成标准：每条 Herdr lane 都有唯一 kind-matched pane、唯一 Execution Worktree 和可读回 registry。

## 模式切换

- active `codex-thread` 继续由 thread tools fan-in；active `herdr-codex-pane` 和
  `herdr-claude-pane` 继续由 registry 指定的 Herdr Control Route fan-in。切换不会迁移或复制
  running lane。
- replacement 沿原 lane runtime，除非用户明确改变该票且已证实原 active writer 不存在。
- cleanup 按每条 lane 的 runtime 执行；只在 map 曾创建 Herdr workspace 时关闭其 panes并保留
  workspace。Codex App Herdr Bridge 在 panes 收口后执行
  `herdr session stop "$herdr_session_name" --json`，保留 named session 供历史恢复。
