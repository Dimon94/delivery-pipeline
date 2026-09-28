# ADR-0012: 验收失败的诊断-修复-复验回路（acceptance circuit）

**Status:** Accepted
**Date:** 2026-09-28
**Decider:** User (Dimon)

## Context

仓里现有熔断只有 transport 层：Orca 原生三次连续 dispatch 失败 circuit-break
（`delivery-pipeline-orca/references/orca-recovery.md`），数的是派发失败。验收层
（checks/verdict/prereq check 不过）只有 `blocked`、`integration_checks_failed` 等
状态，失败之后怎么走——先诊断还是直接重跑、同 lane 还是新 lane、几轮上限、超限
上浮给谁——没有 canonical 定义。GitHub Issue #1588 是既有占位规格，尚未验证。

外部一个月的运行证据给出参考形态：诊断 → 修 → 同一套机器证据复验，最多三轮，
三轮不过带全部诊断结果上浮 orchestrator 裁定；与 dispatch 熔断是两回事。关键纪律是
「先搞清楚为什么失败，而不是原地重跑」——失败证据是花钱买来的，重跑等于扔掉。

## Decision

1. **两个熔断分层。** dispatch circuit-break 数派发失败（维持现状，transport 壳自有）；
   acceptance circuit 数「诊断 → 修 → 同证据复验」的轮次，归核心链路定义。两者计数
   互不影响，都不许用新 Run/Task 绕过。
2. **轮次纪律。** 每轮必须先产出诊断 artifact，明确归因类别：实现 / 环境 / 判据 /
   前置（ADR-0011 prereq check）。无诊断 artifact 不得发起下一轮；复验必须使用与首次
   失败同一套机器证据，不许换更宽松的判据。
3. **上限与上浮。** 三轮不过即停，三轮诊断 bundle 一起交 coordinator 裁定：实现问题回
   实现、判据错改判据、证据指向上游前提才动图（ADR-0011 supersede / ADR-0013 补票）。
   coordinator 裁不了的才上浮用户。
4. 本 ADR 为 #1588 提供决策框架；lane registry 状态与 packet 字段的具体设计归 #1588
   及其 implementation tickets。

## Consequences

- 验收失败从「状态停在那」变成有协议的可恢复流程，且每轮都沉淀诊断证据。
- 「原地重跑」被协议禁止；改图只能由指向上游的证据触发，不靠重试撞运气。
