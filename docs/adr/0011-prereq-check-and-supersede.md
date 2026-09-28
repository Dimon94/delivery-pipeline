# ADR-0011: 前提即事实的 prereq check 与 supersede 语义

**Status:** Accepted
**Date:** 2026-09-28
**Decider:** User (Dimon)

## Context

外部运行证据（Orca 编排一个月、570 任务的复盘）里最贵的一次失败：计划写「后端/Runner
已就绪」，没有任何节点负责验它，真机验收一撞才发现是假前提，下游 010/011 全挂在空气上。
本仓现状有两个对应缺口：

1. `scripts/implementation_gate.py` 只验证依赖坐标存在且回链精确，显式「不证明确认真实」；
   一张票声明「依赖 #x 提供的能力」时，没有任何环节验证该能力真的可运行。
2. lane 状态机与 tracker 都没有「因上游前提被推翻而作废」的语义，只有 blocked/stale/closed；
   整段作废时不留原因，事后无法审计一串票为什么一起没了。

## Decision

1. **Prereq check。** implementation ticket 可声明可执行前提检查（命令/探测脚本 + 期望证据）。
   collect/fan-in 验证交付时先跑 prereq check：不过则被依赖票不派发，记 blocked 并附失败
   证据；过了才进入既有三类证据验证。prereq check 的声明与结果都写入 lane registry，
   聊天不是状态。
2. **Supersede 语义。** lane registry 增加 `superseded` 终态；tracker 约定
   `Superseded by: #x` 文字链接（与 `Blocked by` 同一约定层）。上游前提被证据推翻时，
   coordinator 将受影响下游子图整体置 superseded，必须写原因 comment（哪条证据推翻了
   哪个前提）；superseded lane 保留 worktree 与坐标、不 fan-in、不计入失败，也不许
   原地复活——需要同类工作时按 ADR-0013 或正常 tickets gate 起新票。
3. 本 ADR 只定义语义与状态；gate-state-machine、lane-registry、implementation_gate.py
   的具体改动归后续 implementation ticket。

## Consequences

- 「计划里写了它在」不再是任何下游任务的放行依据；前提必须有跑过的证据。
- 一次推翻带走一串任务时，registry 与 tracker 都能回答「为什么一起没的」。
- prereq check 是可选声明；不声明的票行为不变，不强制回填存量票。
