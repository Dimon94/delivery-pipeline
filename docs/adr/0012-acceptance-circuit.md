# ADR-0012: 验收失败的诊断-修复-复验回路

**Status:** Accepted
**Date:** 2026-09-28
**Decider:** User (Dimon)

> 2026-10-09 用户修订：取消验收修复轮次上限，有 bug 就持续修复并按原判据复验直到通过。

## Context

仓里现有熔断只有 transport 层：Orca 原生三次连续 dispatch 失败 circuit-break
（`delivery-pipeline-orca/references/orca-recovery.md`），数的是派发失败。验收层
（checks/verdict/prereq check 不过）只有 `blocked`、`integration_checks_failed` 等
状态，失败后的诊断、修复与复验没有 canonical 定义。GitHub Issue #1588 是既有占位
规格，尚未验证。

外部运行证据给出参考形态：诊断 → 修复 → 同一套机器证据复验。固定轮次后停止会让
尚未修复的 bug 被提前转交，用户要求持续修复直到验收通过。关键纪律仍是先诊断再修复，
保留失败证据，不原地重跑。

## Decision

1. **职责分层。** dispatch circuit-break 数派发失败（维持现状，transport 壳自有）；
   验收失败修复归核心链路定义，不占用派发失败计数；派发熔断仍不许用新 Run/Task 绕过。
2. **轮次纪律。** 每轮必须先产出诊断 artifact，明确归因类别：实现 / 环境 / 判据 /
   前置（ADR-0011 prereq check）。无诊断 artifact 不得发起下一轮；复验必须使用与首次
   失败同一套机器证据，不许换更宽松的判据。
3. **持续修复。** 实现问题由 implementation owner 持续修复，直到原验收通过；不设修复
   轮次上限，不因历史失败次数暂停。环境或判据问题交对应 owner 修复；证据指向上游前提
   才动图（ADR-0011 supersede / ADR-0013 补票）。只有当前授权内无法解除的权限、外部依赖
   或用户决策阻塞才上浮用户，附失败证据与恢复条件。
4. 本 ADR 为 #1588 提供决策框架；lane registry 状态与 packet 字段的具体设计归 #1588
   及其 implementation tickets。

## Consequences

- 验收失败从「状态停在那」变成有协议的可恢复流程，且每轮都沉淀诊断证据。
- 「原地重跑」被协议禁止；改图只能由指向上游的证据触发，不靠重试撞运气。
