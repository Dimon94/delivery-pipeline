# ADR-0008: Unified Task-type Model Config Schema (version 4)

**Status:** Accepted
**Date:** 2026-09-11
**Decider:** User (Dimon)

## Context

ADR-0004 的 version 2/3 schema 把两个不同维度缝进一份配置：`roles`（六角色 ×
`{agent, model, effort}`）回答"这类活谁来做"，`execution`（每 agent 的
starting/execution/direct + default_mode）回答"这条 lane 怎么跑"。对 implementation 角色，
model/effort 同时存在两份权威，文档被迫引入 ticket → map → user-config 的补丁式解析与
output_mode 门控来掩盖维度错位。

同时 Codex App 壳的 `models.json` 已独立演化成另一套格式：九个 work 项（含 research、
integration、ticket-sizing 等 CLI 六角色之外的工作）、命名 mode 预设（kind + phase_plan）、
review 双轴矩阵。两套配置格式并存，同一策略在两边词汇不同。

## Decision

1. 配置 schema 只有一份，version 4，定义于
   `skills/delivery-pipeline/references/model-config-schema.md`；CLI 实例
   （`~/.config/delivery-pipeline/model-roles.json`）与 App 实例
   （`skills/delivery-pipeline-codex-app/config/models.json`）共用。调度逻辑保持两套。
2. 配置按**任务类型**组织，废除"角色"命名。已知任务类型 12 个：coordinator、research、
   prototype、planning、design、frontend、backend、testing、integration、assistance、
   second-opinion、ticket-sizing。每项为 `{agent, model, effort}`；agent 属于
   `pi|codex|claude|codex-app`，agent 值决定 transport。每个 transport 声明必需子集：
   缺必需项阻塞该 transport，未消费的定义项不阻塞，未知 key 拒绝。
3. 起步续接收敛为**命名 mode 预设**：`modes.<name>` = `kind`（staged/direct）+
   `agents.<agent>` 的 starting/execution/direct 三组计划。mode 名是两个 transport 共享的
   词汇，agents 层解决同一策略在不同 CLI 上的模型名翻译。implementation lane 按
   本票 → map → 配置 `default_mode` 解析 mode 名；旧票据遗留的 `staged`/`direct` 字面值
   阻塞，不做别名映射。
4. 正式 review 统一为 `review.<implementation|whole-change>.<standards|spec>` 四格矩阵；
   CLI 的单一 review 角色废除，review lane 用 standards 轴启动 pane 并携带两轴配置给 owner。
5. 旧配置机械迁移：`model_config.py migrate` 处理 CLI v2/v3 与 App v1，写回并 readback。
   同 agent 冲突或混合 default_mode 时迁移 fail-closed，重跑 setup。已有 lane 沿 registry
   恢复，不受配置版本影响；registry/checkpoint 的持久化字段名（`role`、`development_mode` 等）
   保持不变。
6. 全局唯一 `default_mode`，不按任务类型拆分默认；将来确有证据时再加 per-task-type 覆盖。

## Consequences

- implementation lane 的模型选择只有单一来源（mode 预设），v2/v3 的双权威与
  legacy-config 分支消除。
- 同一 agent 上的多个非实现任务类型各自保有独立 model/effort（work 项），未损失粒度；
  失去的是"同 agent 不同角色不同模型"对 implementation 的影响——那现在由命名 mode 表达。
- CLI 配置可以预定义 research/integration 等当前未消费的任务类型，调度逻辑演进时无需改
  schema。
- 本 ADR 取代 ADR-0004 的 version 2/3 schema 段（决策 3、5 与 2026-09-08 重开段）；
  ADR-0004 的 runtime-neutral 主干、coordinator 不入配置、App 壳边界与 lane 恢复语义不变。
