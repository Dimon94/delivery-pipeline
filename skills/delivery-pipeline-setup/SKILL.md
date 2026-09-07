---
name: delivery-pipeline-setup
description: 初始化或重配 delivery-pipeline 的六角色 worker 配置。
disable-model-invocation: true
---

# Delivery Pipeline Setup

在当前会话交互执行，不派发 lane。读取 `../delivery-pipeline/references/model-role-routing.md`：
它是 version 2 schema、角色、agent adapter 与 evidence 的唯一文档定义点。
本 skill 负责选择与写入 `~/.config/delivery-pipeline/model-roles.json`。

## 流程

1. **验证现状与探测。** 从本 SKILL.md realpath 运行 `scripts/model_config.py validate <config>`，
   并按 routing reference 的 Agent Adapter 并行探测本机 evidence。配置结构与实时 evidence
   都通过、且用户未要求重配时，报告当前表并结束。缺失字段、binary 或候选记 Unknown；
   非法配置进入初始化，合法配置仅在用户明确要求重配时覆盖。
2. **选择角色。** 按 reference 的角色表展示工作范围、当前选择与候选来源；用户明确选择全部六角色
   的 agent/model/effort，可一次确认整表或保留现有有效项，不强制逐字段问答。不提供内置默认。
   每个选择须命中对应 binary 与实时 model/effort evidence；失败只重问该角色，保留稳定选择。
3. **写入并 readback。** 六角色选择均验证通过后创建父目录，只写目标 config。再次运行
   `scripts/model_config.py validate <config>` 并验证实时 evidence，读回与用户选择逐项一致后
   报告最终表。验证失败时报告失败项，不宣称配置可用于派发。

完成标准：六角色都由用户明确选择，结构校验、实时 evidence 与配置 readback 全部通过。
