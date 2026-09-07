# 可恢复交付链

启动、恢复或推进 gate 时读取。本文件是 gate 顺序、owner 与通过证据的唯一定义点；
tracker relationships、Git、lane registry 和 PR/MR 是状态，聊天不是状态。

## 从任意 Issue 重建

1. 读取给定 issue 的 labels、body、comments、native parent/children、blocking links。
2. 识别 artifact：
   - Wayfinder map：含 map label 或 Destination / Decisions-so-far / Not yet specified。
   - Spec：含 spec label/模板，并链接 source map。
   - Implementation ticket：含 implementation label，并通过 native parent 或 `Parent`
     字段链接 spec。
3. 向上追踪 parent 直到 map/spec 根坐标，向下读取所有 linked spec/tickets；按 issue ID
   去重。closed items 也必须读取，它们是已完成 gate 的证据。
4. 选择最早未完成的 gate并继续。用户不需要说明当前阶段。

## Gates

| Gate | 持久输入 | 通过证据 |
| --- | --- | --- |
| `discovery` | map 与 decision child issues | 所有 in-scope child issues closed；resolution 与 artifacts 可读回 |
| `spec` | published spec issue | spec URL/ID、source map link 和 body 可读回 |
| `tickets` | published implementation tickets | 至少一张 ticket 的 ID、spec `Parent` 回链和 dependency edges 可读回 |
| `dispatch` | ticket dependency graph | ready frontier 已派给独立 worktree tasks（kind 按绑定规则）；冲突/blocked tickets 有原因 |
| `execute` | worker packets、worktrees | 每个 terminal worker 有与 output mode 对应的交付与 dirty-state report |
| `collect` | terminal reports | 持久交付证据已验证；blocked 只影响对应 item |
| `integrate` | verified commits | commits 按 dependency order 集成；每次集成后 focused checks 通过 |
| `testing` | execution graph 为空 | configured testing lane 的 whole-change checks 通过，证据已 consumed |
| `review` | whole-change checks 通过 | configured review lane 的 verdict 允许通过，证据已 consumed |
| `test-decision` | testing/review 通过 | map registry 有仍适用的用户测试选择，额外手测的执行时点已确定 |
| `rebase` | clean Integration branch 与测试选择 | rebase 到最新 main，所选额外测试与必要的测试/review 通过 |
| `remote-review` | remote authority 与 push/summary PR/MR | CI/CD、remote review verdict 与最终 closeout 通过 |

线性推进：

```text
discovery -> spec -> tickets -> (dispatch -> execute -> collect -> integrate)*
  -> testing -> review -> test-decision -> rebase -> remote-review
```

输入已位于后续 gate 时，用持久证据跳过已经完成的前置 gate。例如：

- 给 map：继续未完成 discovery；完成后进入 spec。
- 给 spec：读取 source map 作为上下文，从 tickets 继续。
- 给任意 implementation ticket：向上找到 spec，向下重建 sibling dependency graph，从
  dispatch/collect/integrate 的实际状态继续。

## Stage Ownership

- `wayfinder owner` 负责 map 与 decision tickets。松散想法的建图留在当前交互会话；
  decision work 按 `wayfinder-frontier-loop.md` 进入 configured lanes。
- 链路没有已批准 spec 时，由 `to-spec owner` 负责 spec 内容与发布。
- 没有 linked implementation tickets 时，由 `to-tickets owner` 负责内容、依赖和发布。
- `implement owner` 负责单张 ticket 的实现、验证、review 和 commit。
- `code-review owner` 负责 whole-change verdict；testing lane 负责 whole-change checks。
- 以上 delegated work 的 role/output mode 由 `frontier-lanes.md` 的 Role Binding 唯一定义。
  orchestrator 只验证持久坐标与状态转换，然后自动分配下一 ready batch。

如果 linked implementation tickets 已存在，直接复用。只有精确 parent/backlink 关系算 linked；
宽关键词或相似标题不算。没有 linked tickets 时才调用 `to-tickets owner`，发布后重新 readback。
不得因 ticket 大小、拆分方式、描述详细度、验收内容或主观”合理性”阻止 dispatch；
这些都属于 `to-tickets owner` 的产物所有权。

## Role-aware Fan-in / Integration

terminal/user completion signal 只负责唤醒。读取 `child-monitoring.md` 与
`execution-worktree-integration.md`，按 output mode 验证持久交付：仅 commit 进入 cherry-pick；
artifact/checks/verdict 验证成功写 `consumed`。完成 cleanup 后自动重算 ready frontier。
Testing 或 review 失败时保留现场，报告精确失败，不进入后续 gate。

通过 testing/review 后读取 `test-decision-and-rebase.md`，执行测试选择、rebase 与授权收尾。
无 remote authority 时以可恢复的本地 Integration 坐标交回，不宣称远程完成。

## Resume State

每次派发或 terminal event 后更新 `lane-registry.md` 定义的 child checkpoint，并可报告一行
摘要：

```text
输入 issue；map/spec 坐标；当前 gate；completed/running/blocked/ready 数量；下一动作
```

摘要只用于报告；新会话从 tracker relationships、lane registries、Git 和 PR/MR 重建。
