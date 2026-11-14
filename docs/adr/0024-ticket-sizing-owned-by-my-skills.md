# ADR-0024: ticket-sizing 所有权转移到 my-skills

**Status:** Accepted
**Date:** 2026-11-13
**Decider:** User (Dimon)
**Related:** ADR-0008（只更新 Skill 来源，工作类型不变）；my-skills ADR-0017

## Context

5ecd9ce 已将 `ticket-sizing` 移出交付链路，`dispatch.py` 的 `OFF_CHAIN_OWNERS` 保留该边界。
主要调用方在 my-skills。继续随本 bundle 安装会使切票依赖交付编排仓，并可能覆盖新 owner 的链接。

## Decision

1. `ticket-sizing` 由 my-skills 唯一拥有；本仓删除原目录、安装链接与目录校验。调用方与其他外部 Skill 一样，
   按运行时名称解析其绝对 SKILL.md 路径，不假定本仓相对位置；bundle 清单登记其外部来源为 `dimon94-skills`。
2. `OFF_CHAIN_OWNERS` 和配置中的 `ticket-sizing` 工作类型保留。ADR-0008 仅补来源说明，不改 schema。
3. legacy 清理不再处理 `ticket-sizing`：本仓安装器只管理自己的 Skill，避免触碰新 owner 的链接。
4. 回滚时先撤销本仓的迁移提交，再撤销 my-skills 的配套提交；重跑原 owner 安装器，读回运行时真实路径。
   Magpie 的来源配置单独同步；两仓成对回滚，避免双 owner 或缺失 owner。

## Consequences

my-skills 可独立提供切票规则；本仓不再校验外部 Skill 内容。现有用户需安装 my-skills 并重建链接。
Magpie 若仍登记旧来源，可能覆盖运行时链接；本次不修改其配置。Skill 行为与派发 gate 保持不变。
