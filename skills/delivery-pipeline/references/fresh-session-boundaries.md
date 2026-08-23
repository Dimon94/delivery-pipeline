# Fresh Session 与 Ownership

每次新会话从用户给出的任意 issue 重建 map → spec → tickets → execution 链。读取
`gate-state-machine.md` 的持久关系、`lane-registry.md` 的执行坐标和
`dispatch-runtime-routing.md` 的调度运行时选择。

Codex entrypoint 中，完整 App thread tool set 表示 `coordinator_runtime: codex-app`；否则是
`coordinator_runtime: codex-cli` 并走 Herdr。Claude entrypoint 的 coordinator runtime 由其自身
routing reference 记录为 `claude-cli`。

## Stage Owners

- coordinator：链路重建、当前 gate、用户问题、ready frontier、integration、remote closeout。
- discovery worker：一个 Wayfinder decision ticket。
- spec worker：一次 `$to-spec` 调用及其持久 spec。
- ticket worker：一次 `$to-tickets` 调用及其已发布 ticket graph。
- execution worker：一张 implementation ticket、一个 worktree、一个 commit/report。

每个 owner 的输出必须写入 tracker、artifact、Git 或 PR/MR，下一会话才能 readback。
每个 dispatched child 的 registry 保存 role、runtime、task 或 pane 坐标、worktree/branch、
commit 和 lifecycle state。

## Context reuse

- fresh coordinator task 从持久证据重建一次；同一 task 的后续 lane 复用已解析的 map、runtime、
  projectId、owner realpath 和共享合同。
- 只有对应文件/realpath 改变、registry/Git 与缓存矛盾或 action 需要此前未加载的 branch reference 时，
  才重读精确文件。compaction、下一 lane 或 routine tracker write 本身不触发全量重读。
- continuation/prior-decision 需要 Nowledge 时，每个 user turn 一次 targeted lookup 足够；后续动作复用
  结果，除非出现矛盾证据。

## Codex Project Targeting (`runtime: codex-thread`)

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
- Codex App 原生调度让 `create_thread` 创建 App-managed worktree；Herdr 调度手工创建
  固定路径 worktree。两者都从当前 Integration branch HEAD 开始。

thread tools 不可用时按 `codex-cli` 使用 Herdr；Herdr 也不可用时输出完整 durable packets，
不要由 coordinator 代替 execution workers。
