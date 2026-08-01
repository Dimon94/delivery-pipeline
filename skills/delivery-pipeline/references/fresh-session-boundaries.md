# Fresh Session 与 Ownership

每次新会话从用户给出的任意 issue 重建 map → spec → tickets → execution 链。读取
`gate-state-machine.md` 的持久关系和 `lane-registry.md` 的执行坐标。

## Stage Owners

- coordinator：链路重建、当前 gate、用户问题、ready frontier、integration、remote closeout。
- discovery worker：一个 Wayfinder decision ticket。
- spec worker：一次 `/to-spec` 调用及其持久 spec。
- ticket worker：一次 `/to-tickets` 调用及其已发布 ticket graph。
- execution worker：一张 implementation ticket、一个 worktree、一个 commit/report。

每个 owner 的输出必须写入 tracker、artifact、Git 或 PR/MR，下一会话才能 readback。
每个 dispatched child 的 registry 保存 role、thread ID、projectId、worktree/branch、commit
和 lifecycle state。

## Codex Project Targeting

派发前用 `list_projects` 找到源码 repo 的 `Source owner projectId`。按以下顺序解析：

1. source path 与 project path 精确匹配；
2. source path 位于某个 project 内时取最长匹配；
3. Git worktree 通过 `git rev-parse --path-format=absolute --git-common-dir` 与候选 project
   匹配。

同一 repo 的所有首次创建、replacement 和 worktree-to-local fallback 使用相同 projectId。
不存在 owner project 时停止派发并请用户先把 repo 加为 Codex project。

每个 child startup probe 同时核对：

- dispatch packet 已收到；
- child `cwd` 等于 owner project path，或位于该 project 创建的独立 Codex worktree；
- work item 与 tracker URL 一致。

归属错误的 child 标记 ignored，用相同 projectId 重建一次。

## Execution Isolation

- 每张 implementation ticket 一个 fresh child 与独立 worktree/branch。
- source worktree 保持当前 branch。
- worker 只处理 packet 指定的 ticket；dependency graph 与下一批由 coordinator 持有。
- remote authority 缺失不阻塞本地实现与 integration。

thread tools 不可用时，输出完整 durable packets；不要由 coordinator 代替 execution workers。
