# Frontier、Execution Lane 与 Terminal Fan-in

design 派发、implementation dispatch 或任一 worker terminal 后读取本文件。

## Ready Frontier

`ready frontier` 是当前真相源中所有 open、未被 dependency 阻塞且未被 claim 的 work items。
每次派发和 terminal event 都从 tracker/Git 重算。
ready 计算不读取 ticket 长度、工期判断、拆分建议、描述详细度或验收文本质量。

从 ready frontier 按 tracker priority、dependency order、issue ID 选择
`maximal safe batch`。以下 items 串行：

- blockers 尚未 completed；
- 显式文件、migration、lock 或 external mutable resource 重叠；
- 写集合无法证明相互独立；
- 同一 tracker item 需要并发写入。

其余 items 并发。

## Design Fan-out

- AFK research、evidence 和自动 task：每个 decision ticket 通过 `Agent` tool 派发为后台
  subagent（`run_in_background: true`）；不创建 pane。
- HITL prototype、grilling 和 task：各自独立，用户判断只阻塞该 ticket。
  `codex-thread` 使用 user-visible Codex App task；Herdr 使用 `herdr-claude-pane`。
  两者都使用 `WAYFINDER_GRILLING_DISPATCH_PACKET.md` 填充 owner 与 decision 上下文。Herdr lane
  startup 后进入 `awaiting_human`，由用户返回 Codex App 触发 terminal fan-in。
- coordinator 拥有 map frontier、用户问题和 fan-in；subagent 只拥有自己的 decision ticket。

## Dispatch Handoff

user-visible lane 的 task/pane、Execution Worktree、packet、owner/work item 与 registry 已互相验证，
worker 已进入真实 `working`，registry 已 readback 为 `running` 或 `awaiting_human`，即完成 Dispatch
Handoff。这是 coordinator 本轮 terminal：向用户报告坐标后立即 yield，不等待 worker 的 routine
progress、首个问题或最终结果。用户完成信号、真实 terminal event 或显式 monitor 请求才重新进入 fan-in。

## Execution Lanes

- maximal safe batch 中每张 implementation ticket 按 `dispatch-runtime-routing.md` 已选的
  调度运行时创建一个 fresh lane。
- 每条 lane 都有一个独立 worktree（canonical term: Execution Worktree）和一个 active writer。
- `codex-thread` 使用 `ISSUE_IMPLEMENT_DISPATCH_PACKET.md`，由 Codex App 创建 task 与独立
  App-managed Execution Worktree。
- Herdr 显式 kind 优先；否则前端/设计使用 `herdr-claude-pane` +
  `HERDR_CLAUDE_IMPLEMENT_DISPATCH_PACKET.md`，后端/其余使用 `herdr-codex-pane` +
  `HERDR_CODEX_IMPLEMENT_DISPATCH_PACKET.md`。两者都由 Herdr Control Route 创建 pane，并以手工创建的
  独立 Execution Worktree 为 cwd。ticket domain 不改写调度运行时，只决定 Herdr worker kind。
- 只运行该 ticket 的 `$implement`、focused checks、review 和 commit。
- worker 不领取 sibling 或 dependent ticket。terminal 后由 coordinator 重算下一 batch。
- 某 lane blocked 只暂停对应 ticket；其余 ready work 继续。
- 每条 user-visible execution lane 到达 Dispatch Handoff 后停止调度 turn；长任务不占用 coordinator。

## 调度运行时绑定

| Lane runtime | Worker | Packet | Lifecycle owner |
| --- | --- | --- | --- |
| `codex-thread` | Codex App task | `ISSUE_IMPLEMENT_DISPATCH_PACKET.md` | native thread tools |
| `herdr-codex-pane` | Codex CLI pane | `HERDR_CODEX_IMPLEMENT_DISPATCH_PACKET.md` | Herdr Control Route |
| `herdr-claude-pane` | Claude pane | `HERDR_CLAUDE_IMPLEMENT_DISPATCH_PACKET.md` | Herdr Control Route |

registry runtime、packet、worker 与 Execution Worktree transport 必须同一行匹配；不匹配时将
lane 标记为 `setup_blocked`，完成清理后再重算 frontier。

## Terminal Fan-in

- normal path 只消费 `completed` / `blocked` terminal event；Herdr HITL 以用户完成信号唤醒。两者都不读取 routine progress。
- final report 是可丢失的 transport cache；Git、tracker 与 artifact 是持久证据，notification 只负责唤醒。
- `codex-thread` 对同批最多 8 个 tasks 使用带 cursor 的 `wait_threads`；terminal 后
  `read_thread` 一次。Herdr pane 在用户返回后最多做一次 bounded read；final marker 缺失字段记为 `Unknown`，
  不要求 worker 重显、补发或继续输出。
- coordinator 用 registry、Execution Worktree 的 base/head/diff/dirty state、tracker 与 artifacts 验证
  terminal 结果；证据足够时即使 final report 不完整也按 dependency order 集成。
- Integration 后调用 `wayfinder-frontier-loop.md` 完成 canonical tracker transitions，随后
  自动重算并派发下一 ready frontier，不等待用户回复“继续”。
- watchdog 只处理启动失败、terminal signal 丢失或工具 timeout；每次异常只做一次状态检查。

## Authority

- local execution authority 覆盖 worktree、文件修改和本地 commit。
- Map Run Authority 覆盖 named map 的 canonical tracker transitions；remote publication authority
  只在 push、main、PR/MR、merge 和最终 publication closeout 前检查，不阻塞本地 lanes。
