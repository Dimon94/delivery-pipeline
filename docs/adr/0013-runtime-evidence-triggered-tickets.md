# ADR-0013: 运行中证据触发的补票与依赖重连

**Status:** Accepted
**Date:** 2026-09-28
**Decider:** User (Dimon)

## Context

现行 tickets gate 要求拆票全量完成且用户逐批批准后才 dispatch（gate-state-machine 的
实施前置检查）；Map Run Authority 只覆盖 discovery 的 follow-up decision ticket，
orchestrator 在 dispatch/execute/collect 阶段无权新增 implementation ticket 或改依赖。

外部一个月的运行证据表明「开工前全量拆对」在复杂需求上系统性不成立：41 张票分布在
33 个创建时间点，开工时只有 2 张；orchestrator 拿着真机证据自行补了一张 P0「后端服务
实现」并重连依赖，备注写明是哪次验收暴露了假前提。图是长出来的，不是画出来的。

但「拆票批准权归用户」是本仓刻意的权衡，不应默默放弃——需要一条只被机器证据触发、
全程留痕、范围受限的加急通道，而不是把拆票权整体下放。

## Decision

1. **触发条件（穷尽）。** 只有三类机器证据可触发运行中补票：ADR-0011 prereq check
   失败、ADR-0012 acceptance circuit 三轮耗尽且诊断指向上游、spec 禁止项命中。无证据
   的「顺手补一张」不许走本通道。
2. **通道形态。** 补票仍经 to-tickets owner 创建（不绕过既有 owner 结构），标 P0，
   body 必须引用触发证据坐标；依赖重连只许发生在受影响子图内，不许借机调整无关边。
3. **确认降级为批量追认。** 本通道的票用户确认从「逐票事前批准」降为「下一次
   Dispatch Handoff 报告时批量追认」；追认前补票可派发（它本身就是 P0 阻塞解除条件），
   用户拒绝则按 ADR-0011 supersede 处理并保留现场。其余 feature 票的 tickets gate
   不变。
4. **边界。** 本通道不扩大 scope（只在当前 spec 的既有验收目标内补前提缺口）、不授予
   remote publication authority、不覆盖 unrelated issue。所有创建与重连写 lane registry
   与 tracker，事后可审计「这张图在运行中长了什么、凭哪条证据」。

## Consequences

- 「以为就绪、其实不是」类的假前提可以在运行中被补票修复，而不是整单推倒重来。
- 用户保留否决权（批量追认 + supersede），但不再成为 P0 解阻的关键路径。
- 触发条件穷尽枚举，防止加急通道被稀释成绕开 tickets gate 的通用后门。
