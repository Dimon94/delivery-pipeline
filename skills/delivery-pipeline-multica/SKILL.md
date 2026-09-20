---
name: delivery-pipeline-multica
description: Multica 本机交付编排合同核心；frontier 计算、依赖声明、单写者纪律、四类保留事项、HITL 等待与恢复。CLI/Herdr/其他 transport 交付仍用 delivery-pipeline 及其壳，本 skill 只覆盖 Multica 会话内编排。
disable-model-invocation: true
---

# Delivery Pipeline Multica（编排合同核心）

当前调用会话就是 coordinator，Multica 会话即调度现场。本 skill 是编排合同的
**唯一住所**：frontier 计算、依赖声明、每 Issue 单活跃写入 run、四类永远留给人类的事项、
HITL 等待与恢复。宿主（Multica 后端 + Daemon）只提供通用原语；不另起调度服务、不建核心
状态机、不激活 `issue_dependency` 表、不做插件事件桥（决策 02/03/07 已定量否决，勿重开）。

load-on-demand：

| 时机 | 必读 reference |
| --- | --- |
| 计算 frontier 或准备派发 | `references/dispatch-frontier.md` |
| 需要人参与（提问/等待/恢复/授权） | `references/hitl-waiting-recovery.md` |
| 验收、失败回投、授权判定 | `references/acceptance-recovery.md` |
| 执行 C1 演练 | `references/c1-drill.md` |

## 权责模型（决策 02 所有权表，勿双写）

每类事实恰好一个所有者；coordinator 是唯一编排写者。

| 事实 | 所有者 | 存取方式 |
| --- | --- | --- |
| 交付范围/契约/依赖声明 | Issue 正文（只存一份） | Issue 读取/更新接口 |
| 等待与授权指针 | Issue metadata | `PUT/DELETE /api/issues/{id}/metadata/{key}`（单键原子写，值仅 primitive；复合指针写为 JSON 字符串） |
| 对话/提问/回答 | Chat 消息 | 对应会话的消息输入框 |
| 队列/运行 | `agent_task_queue` + TaskService | 宿主派发与 claim 链路 |
| 现场 | Git + Daemon 读回 | worktree/branch/SHA 读回，不信 worker 汇报 |
| lane registry | 可重建缓存 | 崩溃后从 Issue 正文 + queue 血缘 + Git 重建 |

## 依赖声明格式（权威载体 = Issue 正文）

依赖权威在 skill 层的 Issue 正文，`agent_task_queue` 只存运行引用；**不激活
`issue_dependency` 表**（决策 03 Q1，已否决，勿重开）。

- Issue 正文新增一节，标题固定为 `## Orchestration`，内含一个 fenced code block（```json）：

```json
{
  "blocked_by": ["MUL-12", "MUL-34"],
  "work_class": "write",
  "acceptance": ["产物 x 存在于 artifacts/<lane>/", "pnpm typecheck 绿"]
}
```

- `blocked_by`：票标识数组（human-readable identifier，如 `MUL-12`）；缺省或空数组 = 无前置依赖。
- `work_class`：`"read"`（纯读：讨论/研究/只读审查）或 `"write"`（默认）。缺省按 write 处理。
- `acceptance`：本票在全局默认验收判据之外的追加判据（见 09 票验收合同）；可省略。
- 除 fenced block 外正文其余部分照旧是给人看的契约；解析失败一律记 Unknown 并按
  blocked 处理，不猜测。

## Frontier 计算

`frontier` = 依赖全满足的待派票集合。每次准备派发、以及每次收到 worker 终态回流后重算；
缓存只在单次会话内有效，跨恢复必须重算。详细算法与派发流程见
`references/dispatch-frontier.md`。判定输入（全部来自所有者的持久证据，不信内存）：

1. Issue 状态（未 closed/cancelled）；
2. 该 Issue 的 Orchestration 块 `blocked_by` 各票当前是否已验收通过；
3. 该 Issue 当前是否有活跃写入 run（由宿主在派发事务内再校验，skill 侧只做预筛）；
4. 四类保留事项是否挡住自动推进。

## 每 Issue 单活跃写入 run 纪律

- coordinator 对同一 Issue 同一时刻**只派发一个写入类 run**；这是派发不变量
  （决策 04 Q3），由 skill 预筛 + 宿主事务内强制双层保证。
- 宿主保证（票 01/02 已交付，只读引用）：派发走
  `TaskService.DispatchOrchestratedIssueTask`（单事务 lock→check→enqueue→stamp，
  append-only 归属引用落 `agent_task_queue.orchestration_ref`）；claim 前置校验走
  `TaskService.CheckOrchestrationWriteSlot`；无归属引用的非编排派发不受影响。
- 被拒绝时**不重试覆盖**：读取拒绝原因（同 Issue 已有活跃写入 run），把该票留在
  blocked，等既有 run 终态回流后重算 frontier。
- 归属引用格式建议 `<map-run-id>/<lane-id>`；一次派发一个值，写入后不可改
  （SQL `WHERE orchestration_ref IS NULL` 保证，0 行影响 = 已有归属，不是覆盖）。

## 四类永远留给人类的事项

以下四类**永远升级 HITL**，不得由 agent 代答、不得自动推进（决策 05 Q4）：

1. **不可逆/破坏性操作**：删除数据、关闭不可恢复的实体、force-push、销毁环境。
2. **动钱**：支付、计费、定价变更、任何产生费用的外部动作。
3. **范围与拆分变更**：改票的范围、拆票/合票、改验收判据本身。
4. **授权失效后重答**：已给授权因 (question_key, applies_to) 不再一致而失效，
   必须重新提问（授权复用规则见 `references/hitl-waiting-recovery.md`）。

其余一切默认自动化：准备、执行、结果回传、验收判据核对、依赖解锁推进。

## HITL 等待与恢复（概要）

等待 = deferred 任务 + Issue metadata 指针 + chat 提问卡，零新状态机（决策 03 Q3）；
有效回答 = 指针之后第一条 member/user 消息，只恢复对应工作。写读链路、UI 提示消费、
授权 (question_key, applies_to) 复用、失败签名升级，全部见
`references/hitl-waiting-recovery.md`。

## 已否定方案（勿重开）

插件事件桥、独立调度器/外部调度组件、激活 `issue_dependency` 表、review verdict 新表
（首版落 Issue 正文/metadata 投影）、「待我参与」聚合页、`chat_message` 新列、
staged 换模、完整 Prewalk 产品化。

DRY record:
- scope: Multica 编排合同核心（frontier/依赖/单写者/四类保留/HITL 概要）
- searched: delivery-pipeline SKILL.md + references/（gate/frontier/terminal 合同已存在且面向
  tracker 通用模型）；multica spec.md 与 map 七票 Answer；票 01–07 交付代码
- reused: delivery-pipeline 的 gate 顺序/registry/terminal fan-in 概念不复制——本 skill 只写
  Multica 宿主差异（queue 即 registry 证据、chat 即唤醒通道）；宿主字段/函数逐一按已交付
  代码核对（见 artifacts/lane-08/cross-check.md）
- remaining duplication: frontier 概念在两 skill 各有一份语义（tracker-claim 模型 vs
  Multica 依赖正文模型），属边界 duplication，合并会泄漏宿主 internals
