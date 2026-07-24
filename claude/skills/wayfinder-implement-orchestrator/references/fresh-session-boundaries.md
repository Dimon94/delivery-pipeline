# Fresh Session 与 Ownership

每次新会话从用户给出的任意 issue 重建 map → spec → tickets → execution 链。读取
`gate-state-machine.md` 的持久关系和 `lane-registry.md` 的执行坐标。

## Stage Owners

- lead：链路重建、当前 gate、用户问题、ready frontier、integration、remote closeout。
- discovery pane：一个 Wayfinder decision ticket。
- spec pane：一次 `/to-spec` 调用及其持久 spec。
- ticket pane：一次 `/to-tickets` 调用及其已发布 ticket graph。
- execution pane：一张 implementation ticket、一个 Codex process、一个 worktree 和一个
  commit/report。

每个 owner 的输出必须写入 tracker、artifact、Git 或 PR/MR，下一会话才能 readback。
每个 dispatched child 的 registry 保存 role、pane ID、workspace/tab、worktree/branch、
commit、listener owner 和 lifecycle state。

## Herdr Boundaries

- design worker 可以按 ticket 类型使用相应 Claude workflow；implementation ticket 固定派给
  Codex pane。
- 每张 implementation ticket 先创建并验证独立 Git worktree，再把该路径作为
  `herdr tab create --cwd` 或 `herdr pane split --cwd` 的 pane cwd。
- source worktree 保持当前 branch。
- pane 只处理 packet 指定的 ticket；dependency graph 与下一批由 lead 持有。
- workspace/tab/pane 落点按 `herdr-dispatch.md` 显式解析和验证。
- 每个 child pane 都按 `child-monitoring.md` 挂 lead-owned listener；新会话从 registry
  重挂。
- remote authority 缺失不阻塞本地实现与 integration。

Herdr 不可用时，输出完整 durable packets；不要由 lead 代替 execution panes。
