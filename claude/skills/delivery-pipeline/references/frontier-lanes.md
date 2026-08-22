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
  subagent（`run_in_background: true`）；不创建 Herdr pane。
- HITL prototype、grilling 和 task：各自独立，用户判断只阻塞该 ticket。
  通过 `/pane-dispatch` skill 创建 pane（G/P tab），**必须使用 `--kind claude`**。
  使用 `WAYFINDER_GRILLING_DISPATCH_PACKET.md` 模板（已内置 `--kind claude`）。
- lead 拥有 map frontier、用户问题和 fan-in；subagent 只拥有自己的 decision ticket。

## Execution Lanes

- maximal safe batch 中每张 implementation ticket 创建一个 fresh execution pane。
- 每张票先创建并验证独立 worktree（Git），再以该 worktree 作为 pane cwd。
- 通过 `/pane-dispatch` skill 创建 X tab pane；`--kind` 与 packet 模板按下方
  「Agent Kind 绑定规则」分流。
- Execution pane 只运行该 ticket 的 `/mattpocock-skills:implement`、focused checks、review 和 commit。
- worker 不领取 sibling 或 dependent ticket。terminal 后由 lead 重算下一 batch。
- 某 lane blocked 只暂停对应 ticket；其余 ready work 继续。

## Agent Kind 绑定规则

**Packet 模板选择**（用户显式 worker kind 优先，否则按 ticket label 与 domain 查表）：
- `wayfinder:grilling`、`wayfinder:prototype` → `WAYFINDER_GRILLING_DISPATCH_PACKET.md`（内置 `--kind claude`）
- implementation tickets 按 domain 分流：
  - 前端与设计（UI 页面、组件、样式、交互）→ `CLAUDE_PANE_DISPATCH_PACKET.md`（内置 `--kind claude`）
  - 后端及其余 → `CODEX_PANE_DISPATCH_PACKET.md`（内置 `--kind codex`）

**Tab-Kind 交叉验证**：
- G tab（grilling/规划）、P tab（prototype）、R tab（research）→ 必须 `--kind claude`
- X tab（execution）→ 可以 `--kind claude` 或 `--kind codex`
- D tab（data/debug）→ 待定，暂不强制

**Fail-closed 原则**：
- Packet 缺少 `--kind` 参数时，拒绝派发并报错
- Tab-kind 组合不符合规则时，拒绝派发并报错

## Terminal Fan-in

- normal path 只消费 terminal event，不读取 routine progress。
- final report、Git 和 tracker 是证据；lifecycle notification 只负责唤醒。
- lead 对每个 terminal lane 读取一次 final report，验证 commit、checks、dirty state 和
  touched files，按 dependency order 集成，然后立即重算 ready frontier。
- watchdog 只处理启动失败、terminal signal 丢失或工具 timeout；每次异常只做一次状态检查。

## Authority

- local execution authority 覆盖 worktree、文件修改和本地 commit。
- remote publication authority 只在 push、PR/MR 或 remote comment 前检查，不阻塞本地 lanes。
