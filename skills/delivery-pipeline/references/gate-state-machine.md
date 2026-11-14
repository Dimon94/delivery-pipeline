# 可恢复交付链

启动、恢复或推进 gate 时读取。本文件是 gate 顺序、owner 与通过证据的唯一定义点；
tracker relationships、Git、lane registry 和 PR/MR 是状态，聊天不是状态。

## 从任意 Issue 重建

先运行 `python3 scripts/lane_graph.py --registry-root <lanes 目录> --format text --map <map 编号>`
取得该 map 全部 lane 的 issue/state/tracker 状态/依赖一览（每 lane 一行），只对其中未闭合或状态
矛盾的 issue 做以下逐票读取。

1. 读取给定 issue 的 labels、body、comments、native parent/children、blocking links。
2. 识别 artifact：
   - Wayfinder map：含 map label 或 Destination / Decisions-so-far / Not yet specified。
   - Spec：含 spec label/模板，并链接 source map。
   - Implementation ticket：含 implementation label，并通过 native parent 或 `Parent`
     字段链接 spec。
3. 向上追踪 parent 直到 map/spec 根坐标，向下读取当前已链接的 spec 与 tickets。旧 map
   已有多份 spec 时读这份现状，不据此再发布 Spec。按 issue ID 去重。closed items 也必须读取，
   它们是已完成 gate 的证据。
4. 选择最早未完成的 gate并继续。用户不需要说明当前阶段。

## Gates

| Gate | 持久输入 | 通过证据 |
| --- | --- | --- |
| `discovery` | map 与 decision child issues | 所有 in-scope child issues closed；resolution 与 artifacts 可读回 |
| `spec` | published spec issue | to-spec owner 执行产物、owner 要求的用户确认、spec URL/ID、source map link 和 body 可读回 |
| `tickets` | published implementation tickets | to-tickets owner 执行产物、用户对拆分与依赖的批准、ticket ID、spec `Parent` 回链和 dependency edges 可读回 |
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

独立票模式（`integration-worktree-management.md` §独立票模式）下每票单独走
`dispatch -> execute -> collect -> MR -> merged -> deployed -> closed`，跳过 `integrate`、
whole-map `testing/review`、`test-decision`、`rebase` 与 summary MR。

输入已位于后续 gate 时，用持久证据跳过已经完成的前置 gate。例如：

- 给 map：继续未完成 discovery；完成后进入 spec。
- 给 spec：读取 source map 作为上下文，从 tickets 继续。
- 给任意 implementation ticket：向上找到 spec，向下重建 sibling dependency graph，从
  dispatch/collect/integrate 的实际状态继续。

## Stage Ownership

- `wayfinder owner` 负责 map 与 decision tickets。松散想法的建图留在当前交互会话；
  decision work 按 `wayfinder-frontier-loop.md` 进入 configured lanes。
- 链路没有已批准 spec 时，由 `to-spec owner` 按 §tickets 前链路 负责判定、内容与发布。
- 没有通过 tickets gate 的 linked implementation tickets 时，先走 §tickets 前链路，再由 `to-tickets owner` 发布已选定的票、依赖和回链。
- `implement owner` 负责单张 ticket 的实现、验证、review 和 commit。
- `code-review owner` 负责 whole-change verdict；testing lane 负责 whole-change checks。
- 以上 delegated work 的 role/output mode 由 `frontier-lanes.md` 的 Role Binding 唯一定义。
  orchestrator 只验证持久坐标与状态转换，然后自动分配下一 ready batch。

如果 linked implementation tickets 已存在且前置 gate 证据齐全，直接复用。只有精确 parent/backlink 关系算 linked；
宽关键词或相似标题不算。无票或缺 owner/确认执行证据时回到 §tickets 前链路；已有票坐标则复用，发布后重新 readback。
不得因 ticket 大小、拆分方式、描述详细度、验收内容或主观”合理性”阻止 dispatch。
拆分信号的使用边界见 resolved `ticket-sizing` 的绝对 SKILL.md 路径。

## tickets 前链路

discovery 收口后、发布实施票之前只按本节。一张 map 交付一个 MMF：验收、合入、上线的单位，一份 Spec、一张 summary MR、零到多张 ticket。
切分测试：存在一种切法，使每半都能单独上线且单独有人用，就是多个 MMF。

1. `to-spec` 按 **MMF** 的切分测试判定。多个 MMF：停在 spec gate，向用户报告，并请其在编排器外跑 `to-epic`。每个 MMF 另开一张 map。不在本 map 再发布 Spec。切不开且这一整体有人用：发布这一份 Spec。整体没人用：不足一个 MMF，是某个 MMF 里的 ticket，不在本 map 发布 Spec。
2. `vertical-slicing` 接着判定。一个上下文装得下：不拆票，交 `to-tickets` 发布单票。本节到此结束。
3. 装不下：`vertical-slicing` 切候选票，并调用 `ticket-sizing` 给出逐票拆分信号、票数、拆分信号合计与推荐。估算口径只在 resolved `ticket-sizing` 的绝对 SKILL.md 路径。
4. 向用户报告合计与推荐。用户三选一：照此执行；回 `to-epic` 重切，落点同第 1 步；确认切不开则转入 Ticket Release Mode。启用条件只按 `integration-worktree-management.md` §独立票模式。
5. 照此执行且单票超过拆分线：先经 `ticket-split-100k`，再由 `to-tickets` 发布。先估算，后发布。

## 实施前置检查

每次选 frontier、发布实施票、创建或接续 implementation lane 前，先重建最早未完成 gate。
`to-spec → to-tickets → dispatch` 是实施证据要求；`spec` 与 `ticket` 两段执行证据缺一不可。证据怎么产生只按 §tickets 前链路。
已有且仍适用的执行证据可以复用；只读过 skill、存在票或补齐字段不算已执行。
Map Run Authority 的 follow-up decision ticket 只扩展 discovery；原型报告里的实施建议是
规划输入，不是 Spec、获批拆票或实施授权。coordinator 将输入交给对应 owner：

- 缺 Spec：调用 resolved `to-spec`，按 §tickets 前链路 做 MMF 判定；通过后核验测试切入点等用户确认，并发布这一份 Spec。
- Spec 已通过但缺获批拆票：按 §tickets 前链路 完成估算与用户选定，再调用 resolved `to-tickets` 发布。
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
      "owner_run": "<to-tickets 执行产物坐标>",
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

terminal/user completion signal 只负责唤醒。读取所属壳的 monitoring 合同与
`execution-worktree-integration.md`，按 output mode 验证持久交付：仅 commit 进入 cherry-pick（独立票模式改走本票 MR）；
artifact/checks/verdict 验证成功写 `consumed`。完成 cleanup 后自动重算 ready frontier。
Testing 或 review 失败时保留现场与精确失败，进入验收失败修复；原验收通过后再进入后续 gate。

通过 testing/review 后读取 `test-decision-and-rebase.md`，执行测试选择、rebase 与授权收尾。
无 remote authority 时以可恢复的本地 Integration 坐标交回，不宣称远程完成。

## Resume State

每次派发或 terminal event 后更新 `lane-registry.md` 定义的 child checkpoint，并可报告一行
摘要：

```text
输入 issue；map/spec 坐标；当前 gate；completed/running/blocked/ready 数量；下一动作
```

摘要只用于报告；在同次持久化中按 `fresh-session-boundaries.md` §Coordinator Recovery 更新六项
恢复记录。新会话从 tracker relationships、lane registries、Git 和 PR/MR 重建。

## 验收失败修复（ADR-0012）

验收层失败（checks/verdict/prereq check 不过）由核心链路负责诊断、修复与复验；transport 层
dispatch circuit-break 只数派发失败，验收失败不占用其计数。诊断用 `toc-thinking-processes.md`
的 Abductive ECE（先写 kill probe）。

1. 每轮先产出诊断 artifact，归因一类：实现 / 环境 / 判据 / 前置（ADR-0011 prereq check）。
   无诊断 artifact 不得发起下一轮，不原地重跑。
2. 复验使用与首次失败同一套机器证据，不换更宽松的判据。
3. checks 与 prereq check 失败的实现问题由 implementation owner 修复，按原判据复验。轮次按该
   work item 的诊断 artifact 计；两轮修复后原验收仍不过，停止修复：原票置 `superseded`，经
   §证据触发的运行中补票 重拆。Review finding 不走本回路，按 §Review 预算处理。
   环境或判据问题交对应 owner 修复；证据指向上游前提才动图（ADR-0011 supersede / ADR-0013 补票）。
4. 只有当前授权内无法解除的权限、外部依赖或用户决策阻塞，或重拆后仍走不通，才上浮用户，
   附失败证据与恢复条件。

## Review 预算（ADR-0017）

CLI 不做逐票 review：commit lane 交付即收口，Review 只在 Map Integration（或独立票 PR）上做一次
whole-change，最多 3 轮，不能续。所属壳仍启用逐票 review 时，每票另有独立的 3 轮预算。
一轮是一次审查派发，命中的专项 Review 与主审同轮，只在 R1 运行。

| 轮次 | 触发条件 | 范围 |
| --- | --- | --- |
| R1 | 候选 head 已同步目标分支，本地检查与验收对账完成 | 完整 diff |
| R2 | R1 有 P0/P1 且已修复 | 修复 diff 及其影响到的行为；只重跑报过 P0/P1 的轴，修复改了公开 Interface 或依赖时两轴都跑 |
| R3 | R2 有 P0/P1 且已修复 | 同 R2 |

每轮 fan-in 运行 `scripts/review_gate.py --ledger <artifacts_root>/review-budget/<scope>-<work_item>.json`。
输入与账本合同见脚本头部。verdict 只由 P0/P1 计数决定；中断、超时或缺 verdict 的审查不进账本，由派发熔断兜底。

按 gate 输出处置：

- `PASS`：进入下一 gate。验证缺口写入报告，由 testing/closeout gate 判定，不改变 Review verdict。
- `FIX`：写诊断 artifact，给出根因和归因类别；whole-change 的全部 finding 交给同一个 implementer
  lane 修复并排查同类位置，merger 收口后再开下一轮。
- `REVIEW_EXHAUSTED`：lane 写 `blocked`，不合并，不开第 4 轮。对实现链路运行 `retro`，输入三轮 finding、
  诊断 artifact 与 packet，产出漏在哪一环及环境改法。用户随后决定重开新票（新预算）或放弃，原票不再加轮。

归因类别：合同未兑现、时序或身份代次、入口或调用方遗漏、持久或升级恢复、测试或夹具、越界或权限、环境。

其他规则：

- P2 查重后登记 Issue，P3 留在报告里。两者都不开修复 lane，也不触发新一轮。
- whole-change 阶段的修复 lane 和同步主干不跑内嵌 Review，由下一轮 whole-change 复核。
- 只有 `FIX` 能续轮；`PASS` 与 `REVIEW_EXHAUSTED` 是账本终态，gate 拒绝之后的写入。终态后的冲突解决、
  恢复修复等改动靠测试验证并在 PR 注明，沿用原账本路径。FIX 与下一轮之间的 merge 并入下一轮范围。
- base 与 head 相同的 Review 结果直接复用，不重跑。
- packet 不得抬高阻断线或预算。用户明确破例时，packet 引用用户原话与来源坐标。

完成标准：每轮都有账本记录，输出由 gate 给出；每条 P2 有 Issue 坐标；`REVIEW_EXHAUSTED` 有 retro 交付物。

## Supersede（ADR-0011）

上游前提被证据推翻时，coordinator 将受影响下游子图整体置 `superseded`：lane registry 写该终态，
tracker 写 `Superseded by: #x` 链接（与 `Blocked by` 同约定层），必须附原因 comment（哪条证据推翻
哪个前提）。superseded lane 保留 worktree 与坐标、不 fan-in、不计入失败、不原地复活；
同类工作按 ADR-0013 或正常 tickets gate 起新票。

## 证据触发的运行中补票（ADR-0013）

tickets gate 之外唯一的运行中增票/改依赖通道，触发条件穷尽：

- ADR-0011 prereq check 失败；
- ADR-0012 验收修复诊断证明当前 spec 的上游前提缺失或错误；
- spec 禁止项命中；
- worker 因上下文耗尽中断，或同一 work item 两次重试仍失败（验收修复两轮未过、两次
  replacement 仍中断）。

补票仍经 to-tickets owner 创建，标 P0，body 引用触发证据坐标；依赖重连只发生在受影响子图内。
用户确认从逐票事前批准降为下一次 Dispatch Handoff 报告时批量追认；追认前可派发，拒绝则按
supersede 处理并保留现场。本通道不扩大 scope、不授予 remote authority、不覆盖 unrelated issue，
全部创建与重连写 registry 与 tracker。
