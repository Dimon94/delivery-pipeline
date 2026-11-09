# ADR-0022: 按原因重试，两次后重拆

**Status:** Accepted
**Date:** 2026-11-08
**Decider:** User (Dimon)
**Supersedes:** ADR-0012 §3「不设修复轮次上限」；Herdr replacement「沿原 lane runtime/model/effort」
**Amends:** ADR-0013 §1 触发条件

## Context

两层重试都缺一半。验收层（ADR-0012）按实现 / 环境 / 判据 / 前置归因，但 2026-10-09 起不设
轮次上限。worker 层的 replacement 不归因，一律沿原配置原样重派，也没有次数上限：上下文耗尽的
lane 会以同样范围再派一次。

来源：pstack `playbooks/orchestrate.md`（cursor/plugins@6b03002）Supervision 节：按原因重试，
上下文到顶缩小范围，断线用同一 kickoff，工具报错换模型；两次后放弃该单元、绕开它重新规划；
重试不上浮用户。用户 2026-11-08 决定全部按 pstack 执行，不保留此前的不设上限决定。
证据边界：复盘记录中未见同一 work item 反复 replacement 的实例，本决定属推断性预防。

## Decision

1. **worker 层按原因 replacement。** 连接中断或原因 Unknown：同一 packet、原配置。工具或模型
   报错：按配置 `work` 的 key 顺序取第一个 model 与原 lane 不同的项，经实时可用性验证后派发，
   不上浮用户。上下文耗尽：不原样重派，经运行中补票拆小。
2. **replacement 留痕。** 原 lane 写 `blocked` 并记原因；replacement 用新 `lane_id`、同一
   `work_item`。次数从 registry 数出，不新增计数字段。
3. **两次后重拆。** 同一 work item 两次 replacement 仍中断，或验收修复两轮后原验收仍不过：
   停止重试，原票置 `superseded`，经运行中补票重拆。轮次按该 work item 的诊断 artifact 计。
4. **上浮用户。** 只在当前授权内无法解除的阻塞，或重拆后仍走不通时。
5. **ADR-0013 触发条件**增一类：上下文耗尽，或同一 work item 两次重试仍失败。

## Consequences

- 原样重派只用于原因已自行消失的情况；失败代价不再无上限重复。
- 真 bug 两轮未修好会转为重拆，而不是继续在原票上修；这是对 ADR-0012 用户修订的有意回退。
- 换模型不再等用户选择，所选模型必须已在配置中并通过实时验证。
- 运行中补票的使用频率上升；用户仍在下一次 Dispatch Handoff 批量追认。
