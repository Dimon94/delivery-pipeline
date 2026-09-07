---
name: ticket-sizing
description: 拆分 implementation tickets 或审查现有拆票粒度时使用。
---

# Ticket Sizing

按独立验收与依赖边界确定粒度。本 skill 只提供粒度判据；拆票流程的 owner 是 `to-tickets`。

## 判据

每张 ticket 应有一个可检查的交付目标，能在单个 Execution Worktree 内实现、验证与交回；
所需前置产物明确为 dependency，不把跨票协同留成隐含条件。普通文件路径重叠本身不是拆票理由。

- **拆分：** 包含可独立验收的多个目标，或读取、实现和验证所需的同时在场上下文无法可靠承载时，
  沿交付物或依赖边界拆分，保留明确的验收与集成顺序。
- **合并：** 相邻细票没有独立验收价值、反复加载同一上下文且能在同一 Execution Worktree
  验证时合并；保留真实 dependency，已派发或被 claim 的票不由本 skill 自动重写。
- **Token 证据：** 有当前模型与相近任务的实际运行记录时，用作辅助校准；没有时记 Unknown。
  累计消耗不等于同时占用的上下文，不据此直接计算票数或套用统一前后端系数。

完成标准：每张票均有独立验收目标、显式前置依赖与单个 Execution Worktree 的交付边界；
无法满足的票明确标出待拆分、合并或补充证据的原因，交由 `to-tickets` owner 处理。
