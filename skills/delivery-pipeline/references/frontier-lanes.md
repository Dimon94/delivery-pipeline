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
  两者都使用 `WAYFINDER_GRILLING_DISPATCH_PACKET.md` 填充 owner 与 decision 上下文。
- coordinator 拥有 map frontier、用户问题和 fan-in；subagent 只拥有自己的 decision ticket。

## Execution Lanes

- maximal safe batch 中每张 implementation ticket 按 `dispatch-runtime-routing.md` 已选的
  调度运行时创建一个 fresh lane。
- 每条 lane 都有一个独立 worktree（canonical term: Execution Worktree）和一个 active writer。
- `codex-thread` 使用 `ISSUE_IMPLEMENT_DISPATCH_PACKET.md`，由 Codex App 创建 task 与独立
  App-managed Execution Worktree。
- Herdr 显式 kind 优先；否则前端/设计使用 `herdr-claude-pane` +
  `HERDR_CLAUDE_IMPLEMENT_DISPATCH_PACKET.md`，后端/其余使用 `herdr-codex-pane` +
  `HERDR_CODEX_IMPLEMENT_DISPATCH_PACKET.md`。两者都由 `$herdr` 创建 pane，并以手工创建的
  独立 Execution Worktree 为 cwd。ticket domain 不改写调度运行时，只决定 Herdr worker kind。
- 只运行该 ticket 的 `$implement`、focused checks、review 和 commit。
- worker 不领取 sibling 或 dependent ticket。terminal 后由 coordinator 重算下一 batch。
- 某 lane blocked 只暂停对应 ticket；其余 ready work 继续。

## 调度运行时绑定

| Lane runtime | Worker | Packet | Lifecycle owner |
| --- | --- | --- | --- |
| `codex-thread` | Codex App task | `ISSUE_IMPLEMENT_DISPATCH_PACKET.md` | native thread tools |
| `herdr-codex-pane` | Codex CLI pane | `HERDR_CODEX_IMPLEMENT_DISPATCH_PACKET.md` | `$herdr` |
| `herdr-claude-pane` | Claude pane | `HERDR_CLAUDE_IMPLEMENT_DISPATCH_PACKET.md` | `$herdr` |

registry runtime、packet、worker 与 Execution Worktree transport 必须同一行匹配；不匹配时将
lane 标记为 `setup_blocked`，完成清理后再重算 frontier。

## Terminal Fan-in

- normal path 只消费 `completed` / `blocked` terminal event，不读取 routine progress。
- final report、Git 和 tracker 是证据；notification 只负责唤醒。
- `codex-thread` 对同批最多 8 个 tasks 使用带 cursor 的 `wait_threads`；terminal 后
  `read_thread` 一次。两种 Herdr pane 都通过 `$herdr` 读取完整 final markers。
- coordinator 对每个 terminal lane 读取一次 final report，验证 commit、checks、dirty state
  和 touched files，按 dependency order 集成，然后立即重算 ready frontier。
- watchdog 只处理启动失败、terminal signal 丢失或工具 timeout；每次异常只做一次状态检查。

## Authority

- local execution authority 覆盖 worktree、文件修改和本地 commit。
- remote publication authority 只在 push、PR/MR 或 remote comment 前检查，不阻塞本地 lanes。
