# ADR-0018: CLI lane 只单轮直跑

**Status:** Accepted
**Date:** 2026-11-07
**Decider:** User (Dimon)

## Context

ADR-0010 让 CLI implementation work 项可选 `execution`，设了即 staged：起步 → checkpoint →
同 session 续接。复盘最近 30 次编排会话：staged 路径需要 checkpoint、continuation overlay、
send lease、三个 agent adapter（pi/codex/claude）与 PREWALK watcher，占 lane registry 与 packet
的大量字段和 coordinator 往返；当前模型能力下首改暂停换模带来的质量收益无证据（Unknown），
而 token 与恢复复杂度是确定成本。用户决定极致精简编排 token。

## Decision

1. CLI lane（Herdr、T3Code、Lody、Orca 共享 CLI 配置实例）只单轮直跑：用任务类型 work 项的
   `{agent, model, effort}`；ticket/map 显式点名 `modes` 预设时用其 `direct` 组覆盖。
   CLI 配置的 work 项不再允许 `execution`，CLI mode 的 `kind` 必须为 `direct`。
2. 删除 canonical continuation helper 与 pi/codex/claude staged adapter；lane registry 删除
   starting/execution/checkpoint/continuation 字段；Herdr watcher 只匹配 `LANE_DONE`；Orca
   recovery 删除 `staged` operation，question 绑定 lane 的 orca 坐标而非 checkpoint。
3. 迁移：CLI v3/v4 的 staged 计划 execution 与 starting 不同时 `migrate` 报错，相同时按 direct
   迁移；v5 配置带 `execution` 则 `validate` 失败。两者都重跑 setup。已有 staged lane 不迁移，按 registry 证据人工收口。
4. Codex App 的 staged/Prewalk 路径（checkpoint、prewalk、implementation gate）不变。
5. 本 ADR 取代 ADR-0010 决策 1 中 CLI `execution` 与 staged 部分；ADR-0010 的 per-task-type
   权威与 App-only `default_mode` 保留。

## Consequences

- registry、packet、watcher 与 setup 的字段和步骤减少；CLI 换模只能通过换 work 项或点名 mode。
- 需要首改后换模的场景改为拆票：小 ticket 用不同任务类型/mode 分别派发。
