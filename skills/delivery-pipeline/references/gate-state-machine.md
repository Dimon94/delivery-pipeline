# 可恢复交付链

每次新会话先读取本文件。tracker relationships、Git 和 PR/MR 是状态；聊天不是状态。

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
|---|---|---|
| `discovery` | map 与 decision child issues | 所有 in-scope child issues closed；resolution 与 artifacts 可读回 |
| `spec` | published spec issue | spec URL/ID、source map link 和 body 可读回 |
| `tickets` | published implementation tickets | 至少一张 ticket 的 ID、spec `Parent` 回链和 dependency edges 可读回 |
| `dispatch` | ticket dependency graph | ready frontier 已派给独立 Codex worktree tasks；冲突/blocked tickets 有原因 |
| `execute` | worker packets、worktrees | 每个 terminal worker 有 commit/checks/dirty-state report |
| `collect` | terminal reports | completed commits 已验证；blocked 只影响对应 ticket |
| `integrate` | verified commits | commits 按 dependency order 集成；每次集成后 focused checks 通过 |
| `remote-review` | summary PR/MR | CI/CD 通过且 remote review Agent 明确 can pass |

线性推进：

```text
discovery -> spec -> tickets -> (dispatch -> execute -> collect -> integrate)*
  -> remote-review
```

输入已位于后续 gate 时，用持久证据跳过已经完成的前置 gate。例如：

- 给 map：继续未完成 discovery；完成后进入 spec。
- 给 spec：读取 source map 作为上下文，从 tickets 继续。
- 给任意 implementation ticket：向上找到 spec，向下重建 sibling dependency graph，从
  dispatch/collect/integrate 的实际状态继续。

## Stage Ownership

- `$wayfinder` 负责 map 与 decision tickets。
- `$to-spec` 负责 spec 内容与发布。
- `$to-tickets` 负责 implementation tickets 内容、依赖和发布。
- `$implement` 负责单张 ticket 的实现、验证、review 和 commit。
- orchestrator 只验证持久坐标与状态转换，然后自动分配下一 ready batch。

如果 linked implementation tickets 已存在，直接复用。只有精确 parent/backlink 关系算 linked；
宽关键词或相似标题不算。没有 linked tickets 时才调用 `$to-tickets`，发布后重新 readback。
不得因 ticket 大小、拆分方式、描述详细度、验收内容或主观”合理性”阻止 dispatch；
这些都属于 `$to-tickets` 的产物所有权。

## Resume State

每次派发或 terminal event 后更新 `lane-registry.md` 定义的 child checkpoint，并可报告一行
摘要：

```text
输入 issue；map/spec 坐标；当前 gate；completed/running/blocked/ready 数量；下一动作
```

摘要只用于报告；新会话从 tracker relationships、lane registries、Git 和 PR/MR 重建。
