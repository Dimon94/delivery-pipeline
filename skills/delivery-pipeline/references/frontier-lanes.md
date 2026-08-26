# Frontier、Configured Role Lane 与 Terminal Fan-in

任一 gate dispatch、implementation dispatch 或 worker terminal 后读取。

## Ready Frontier

`ready frontier` 是当前真相源中所有 open、未被 dependency 阻塞且未被 claim 的 work items。
每次派发和 terminal event 都从 tracker/Git 重算；ready 计算只使用 tracker state、dependencies 与 claim。

按 tracker priority、dependency order、issue ID 选 maximal safe batch。无前序依赖的 ready items
同批并发派发；只有 active writer、无法由 Execution Worktree 隔离的 external mutable resource，
或用户明确要求串行时排除。普通 repo 文件路径重叠只进入 Integration 冲突检测，不构成
Dispatch blocker。

## Role Binding

| 工作 | Role | Output mode |
|---|---|---|
| AFK discovery/research、spec、tickets gate worker | `planning` | `artifact` |
| grilling/prototype HITL | `design` | `artifact` |
| design implementation | `design` | `commit` |
| frontend implementation | `frontend` | `commit` |
| backend/other implementation | `backend` | `commit` |
| whole-change tests | `testing` | `checks` |
| code review | `review` | `verdict` |

role 只选择 config entry，不暗含 agent。agent/model/effort 只从
`model-role-routing.md` 的 version 2 配置读取。

## Execution Lanes

- 每个 work item 一个 fresh Herdr lane、一个 Execution Worktree、一个 active writer。
- pi → `herdr-pi-pane`；codex → `herdr-codex-pane`；claude → `herdr-claude-pane`。
- 所有 kind 使用 `HERDR_ROLE_DISPATCH_PACKET.md`；packet 持久化 role + output_mode，owner path 是绝对路径。
- worker 只处理 packet 的 work item，不领取 sibling/dependent item或进入下一 gate。
- blocked 只暂停对应 item；其余 ready work继续。

## Dispatch Handoff

每条 lane 的 pane、Execution Worktree、packet、owner/work item、role config 与 registry 已互相验证，
worker 进入 `working`，registry readback 为 `running` 或 `awaiting_human`，即完成该 lane startup。
整批成功 lanes 完成 startup、失败项隔离为 `setup_blocked` 后，统一报告全部坐标并立即 yield；
不等待 routine progress、首个问题或最终结果。

## Terminal Fan-in

- normal path 只消费 completed/blocked terminal event（由 `pane-lifecycle-rules.md` 的
  LANE_DONE watcher 合同产生）；HITL 由用户完成信号唤醒。
- final report 是 transport cache；Git、tracker 与 artifact 是持久证据。
- 用户返回后对 pane 做一次 bounded read；final marker 缺字段记 Unknown，不要求 worker 重显。
- coordinator 用 registry、worktree base/head/diff/dirty state、tracker 与 artifacts 验证，按 dependency
  order串行 Integration。
- Integration 后完成 canonical tracker transitions，自动重算下一 ready frontier，不等待“继续”。
- watchdog 只处理 startup failure、terminal signal 丢失或工具 timeout；不固定轮询。

## Authority

local execution authority 覆盖 worktree、文件修改与本地 commit；Map Run Authority 覆盖 named map
canonical tracker transitions；remote publication authority 只在 push/main/PR/MR/merge/final closeout
前检查。
