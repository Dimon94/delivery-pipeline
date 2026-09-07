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
| `spec` | published spec issue | to-spec owner 执行产物、owner 要求的用户确认、spec URL/ID、source map link 和 body 可读回 |
| `tickets` | published implementation tickets | to-tickets owner 与 ticket-sizing 执行产物、用户对拆分与依赖的批准、ticket ID、spec `Parent` 回链和 dependency edges 可读回 |
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
- 没有通过 tickets gate 的 linked implementation tickets 时，由 `to-tickets owner` 负责内容、依赖和发布，必读并执行本 bundle 的 `ticket-sizing`。
- `implement owner` 负责单张 ticket 的实现、验证、review 和 commit。
- `code-review owner` 负责 whole-change verdict；testing lane 负责 whole-change checks。
- 以上 delegated work 的 role/output mode 由 `frontier-lanes.md` 的 Role Binding 唯一定义。
  orchestrator 只验证持久坐标与状态转换，然后自动分配下一 ready batch。

如果 linked implementation tickets 已存在且前置 gate 证据齐全，直接复用。只有精确 parent/backlink 关系算 linked；
宽关键词或相似标题不算。无票或缺 owner/粒度/确认执行证据时调用 `to-tickets owner`，复用既有票坐标，发布后重新 readback。
不得因 ticket 大小、拆分方式、描述详细度、验收内容或主观”合理性”阻止 dispatch；
这些都属于 `to-tickets owner` 的产物所有权。

## 实施前置检查

每次选 frontier、发布实施票、创建或接续 implementation lane 前，先重建最早未完成 gate。
`to-spec → to-tickets（含 ticket-sizing）→ dispatch` 是必经流程；三个 skill 都须有执行证据。
已有且仍适用的执行证据可以复用；只读过 skill、存在票或补齐字段不算已执行。
Map Run Authority 的 follow-up decision ticket 只扩展 discovery；原型报告里的实施建议是
规划输入，不是 Spec、获批拆票或实施授权。coordinator 将输入交给对应 owner：

- 缺 Spec：调用 resolved `to-spec`，按 owner 核验测试切入点等用户确认并发布 Spec。
- Spec 已通过但缺获批拆票：调用 resolved `to-tickets`，packet 同时传递本 bundle 的
  `ticket-sizing` name、绝对 SKILL.md path、runtime-specific invocation label；owner 完整读取并逐票
  判定独立验收目标、前置依赖与单 worktree 边界；可按 ticket-sizing 委派评估，由 owner 核验并保存判定结果，再展示拆分与依赖，用户批准后发布。
- 既有票缺上述证据：保留票与 worktree，阻塞实施，回到最早缺失 gate；不靠补标签或只补 Parent 放行。
- discovery 原型需要尚未实现的生产功能：保留 blocked 和缺口，回到 decision owner 收窄为可独立验证的
  原型，或由用户明确调整 discovery 验收范围并记录延期事项；满足 discovery 后才进入 Spec。
  不直接创建实施 blocker 来绕过链路，也不把 blocked 当作 closed。

实施新建、replacement 或继续写代码前，将刚回读的证据交给 canonical
`scripts/implementation_gate.py`（JSON stdin，非零退出即阻塞）。输入：

```json
{
  "work_item": "<ticket URL>",
  "map": "<map URL；无 map 的独立 Spec 省略此字段>",
  "gate_evidence": {
    "readback": "<tracker 读取来源与时间>",
    "discovery": "<map 的 resolution、产物与用户确认来源>",
    "spec": {
      "url": "<Spec URL>", "source_map": "<map URL>", "body": "<回读正文>",
      "owner_run": "<to-spec 执行产物坐标>", "confirmation": "<owner 所需确认的来源与内容>"
    },
    "ticket": {
      "url": "<ticket URL>", "parent": "<Spec URL>", "body": "<回读正文>",
      "owner_run": "<to-tickets 执行产物坐标>", "sizing": "<ticket-sizing 逐票判定产物坐标>",
      "confirmation": "<拆分与依赖获批的来源与内容>",
      "dependencies": []
    }
  }
}
```

dependencies 是回读的 blocking 坐标列表，空列表仅表示确认无依赖。证据保存到既有 repo 外
lane registry 旁并在 packet 引用；App 的 resolve/prepare 直接校验同一输入。
helper 只验证必填证据与精确回链，不访问 tracker，不判断正文质量，也不证明确认真实。
coordinator 必须核对内容、范围与确认有效性；Unknown、任务 completed、ready label 或仅模型选择
均不能替代证据。用户已确认且仍适用时复用，不增加内容复审 gate。
恢复坐标、读现场、暂停与 cleanup 不受此检查阻塞；恢复不等于授权继续写代码或 Integration。

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
