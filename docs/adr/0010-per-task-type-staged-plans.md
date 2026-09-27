# ADR-0010: Per-task-type Staged Plans（version 5）

**Status:** Accepted
**Date:** 2026-09-26
**Decider:** User (Dimon)

## Context

ADR-0008 的 version 4 schema 把 implementation lane 的阶段计划收敛为命名 mode 预设，
`agents` 层按 CLI agent 给出 starting/execution/direct 三段。后果：`design`/`frontend`/
`backend` 只要 agent 相同就被迫共享同一份 starting/execution triple——work 项自己的
`{model, effort}` 对 `output_mode: commit` 的 lane 成为死字段。用户的产品判断是前端实施
与后端实施的 starting 应该可以不同，且 starting 与 execution 一致时「第一处修改后
checkpoint 暂停」纯属仪式，应直接跑完。

## Decision

1. CLI 的 implementation work 项（`design`/`frontend`/`backend`）收回默认 commit lane 的
   计划权威：`{model, effort}` 是 starting；可选 `execution` 设了则 staged（起步 →
   checkpoint → execution 续接），未设则 direct 单轮直跑，无 checkpoint 暂停。
   `execution` 只允许出现在这三个任务类型上。
2. `modes` 收窄为 ticket/map **显式点名**时的整体覆盖预设（选中时行为同 version 4）；
   CLI 的 `modes` 允许为空对象。`default_mode` 成为 App-only 顶层 key：App 没有
   implementation work 项，阶段计划仍按 本票 → map → `default_mode` 来自 mode，
   App 语义不变。
3. Schema version 5。机械迁移：CLI v4→v5 对照 `default_mode` 的 per-agent 计划，
   starting（或 direct）与 work 项不一致时报错重跑 setup（fail-closed）；`execution` 与
   starting 不同才携带（相同则按新语义成为直跑）。CLI v2/v3 直接迁移到 v5（per-task
   权威消除了 v3 的同 agent 冲突与混合 default_mode 冲突）。App v4→v5 仅版本号升位。
4. 本 ADR 修订 ADR-0008 决策 3 中「agents 层是 implementation lane 默认计划权威」的部分
   与决策 6（全局唯一 `default_mode`）的 CLI 侧；ADR-0008 的单一 schema、任务类型组织、
   review 矩阵、迁移 fail-closed 与 lane 恢复语义不变。

## Consequences

- 同 agent 的 design/frontend/backend 可以各自设置 starting 与 execution；work 项不再是
  commit 路径的死字段，双权威消除。
- starting 与 execution 一致不再强制 checkpoint 暂停；staged 成为显式选择（设置不同的
  execution）。
- CLI 解析顺序由「票 → map → `default_mode`」变为「票 → map → work 项」；App 不变。
- 已有 lane 沿 registry 恢复，不受配置版本影响；迁移不迁移 lane。
