# 调度运行时路由

创建、恢复或替换任何 worker lane 前读取本文件。本文件是 Codex entrypoint 的 Coordinator
Runtime adapter：区分 `codex-app` 与 `codex-cli`。Coordinator Runtime 只决定 transport；
worker kind 是第二条轴。ready frontier、单写者、Execution Worktree、Integration 和 terminal
fan-in 保持不变。

## 选择顺序

1. **识别 Coordinator Runtime。** 检查 `list_projects`、`create_thread`、`list_threads`、
   `read_thread`、`wait_threads` 和 `send_message_to_thread` 是否全部可用。全部可用时记录
   `coordinator_runtime: codex-app`；否则本 Codex entrypoint 记录
   `coordinator_runtime: codex-cli`。推断：完整原生 task tool set 表示 Codex App。Codex CLI
   原生 thread 能力是 Unknown，本模型不尝试调用它。
2. **显式指令优先。** `codex-app` 用户明确要求本次使用 Herdr 时选择
   `dispatch_runtime: herdr`；否则选择 `dispatch_runtime: codex-app`，新 lane 使用
   `runtime: codex-thread`。`codex-cli` 固定选择 `dispatch_runtime: herdr`。
3. **选择 Herdr worker kind。** 用户指定 Codex CLI 或 Claude CLI 时固定对应 pane；否则按
   `frontier-lanes.md` 的 domain binding。
4. 已选择 Herdr 但 `$herdr` 不可用时，输出 ready lanes 的完整 durable packets，报告
   `dispatch unavailable`，不由 coordinator 代替 worker。

把 `coordinator_runtime` 与 `dispatch_runtime` 写入 map registry。每条 existing lane 仍按自己的
`runtime` 恢复；本次选择只约束新 lane。存在 active writer 时先完成恢复与去重，再创建
replacement 或切换新 lane 的 transport。

## Codex App 原生调度

### 创建

1. 用 `list_projects` 按 `fresh-session-boundaries.md` 解析 Source owner projectId，并确认项目是
   当前 repo。
2. 为 lane 生成稳定标题与完整 packet。调用 `create_thread`，target 使用该 project，environment
   使用 worktree，`startingState` 的 branchName 必须是当前 Integration branch。Codex App 拥有
   Execution Worktree 的创建与路径；不要预创建同票手工 worktree。
3. `create_thread` 返回 `threadId` 时记录其 `hostId`。只返回 `clientThreadId` 表示 worktree 仍在
   setup；`clientThreadId` 不能作为 `thread_id`，用 `list_threads` 按稳定标题、project 和 lane
   标识找到 ready task。
4. 用 `list_threads`、`read_thread`、`git worktree list --porcelain` 和 Git state readback：
   task 属于 owner project，worktree 的 common dir 属于 source repo，base commit 是 dispatch
   时 Integration HEAD，cwd 不在 Source Worktree 或 Map Integration Worktree。
5. worker 在首次写入前创建或验证 `codex/issue-<ticket>` branch。把 `project_id`、`host_id`、
   `thread_id`、实际 worktree、branch 和 base commit 写入 lane registry，并精确 readback。

完成标准：`runtime: codex-thread` lane 的 task、App-managed Execution Worktree 和 registry
互相一致，startup probe 已读回 owner skill name/path 与 work item。

### 监控与恢复

- 对同批 1–8 个 running tasks 用一次 `wait_threads`；后续等待携带每个 task 的最新 cursor。
  routine commentary 不触发 fan-in，只在 completed 或 needs-attention 时读取。
- terminal 后用 `read_thread` 读取一次 final report，随后以 Git commit、checks、dirty state 和
  touched files 为准进入 Integration。
- worker 需要范围内的收口指令或回答时才调用 `send_message_to_thread`；常规进度用
  `wait_threads`，不反复发送催促。
- 新会话先用 registry 的 `thread_id` + `host_id` 调用 `list_threads` / `read_thread`。task 不可见
  但 commit 存在时从持久 Git 证据继续；task 和 commit 都不存在且已排除 active writer 后才创建
  replacement。

## Herdr 调度

此分支由用户明确选择，或在 Codex App thread tools 不完整而 `$herdr` 可用时选择。解析并调用
`$herdr`，在 Map Integration Worktree 对应 workspace 中创建 Codex CLI 或 Claude Code pane。
显式 worker kind 优先；否则按 `frontier-lanes.md` 的 Herdr binding：前端/设计用 Claude Code，
后端及其余用 Codex CLI。

1. workspace 缺失时懒创建；已有 workspace 先 readback。
2. 从当前 Integration HEAD 手工创建 `codex/issue-<ticket>` 或 `claude/issue-<ticket>`
   Execution Worktree。
3. Codex CLI 填写 `assets/HERDR_CODEX_IMPLEMENT_DISPATCH_PACKET.md`；Claude Code 填写
   `assets/HERDR_CLAUDE_IMPLEMENT_DISPATCH_PACKET.md`。以 Execution Worktree 为 cwd 启动 pane，
   并验证 placement、owner skill 和 work item。
4. registry 写入 `runtime: herdr-codex-pane` 或 `runtime: herdr-claude-pane`，以及
   workspace/tab/pane、worktree、branch 与 base commit。
5. terminal、recovery 和 pane cleanup 通过 `$herdr` 完成；该 lane 不调用 Codex App thread tools。

完成标准：每条 Herdr lane 都有唯一 kind-matched pane、唯一 Execution Worktree 和可读回 registry。

## 模式切换

- active `codex-thread` 继续由 thread tools fan-in；active `herdr-codex-pane` 和
  `herdr-claude-pane` 继续由 `$herdr` fan-in。切换不会迁移或复制 running lane。
- replacement 沿原 lane runtime，除非用户明确改变该票且已证实原 active writer 不存在。
- cleanup 按每条 lane 的 runtime 执行；只在 map 曾创建 Herdr workspace 时关闭其 panes并保留
  workspace。
