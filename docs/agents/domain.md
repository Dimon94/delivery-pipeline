# Domain Documentation

本文件说明开发任务如何使用领域文档。本仓为单上下文布局。

## 开始工作

先读:

- repo://CONTEXT.md(bundle 领域模型:三级 worktree、Herdr workspace、Dispatch Model)。
- 涉及当前区域的 accepted ADR(repo://docs/adr/)。
- 目标文件最近的 AGENTS.md。

文件缺失时按 Unknown 处理并继续,不凭空补齐;词表与 ADR 由 /domain-modeling 在概念真正落定后懒创建。

## 统一语言

issue 标题、测试名、类型名和文档使用 CONTEXT.md 的 canonical term,不漂移到同义词。新概念先确认不是现有概念的同义词,再更新词表。

## ADR 冲突

提案与 accepted ADR 冲突时,显式指出冲突、证据和重开理由,不静默覆盖。

## 文档边界

- CONTEXT.md 负责统一语言。
- ADR 负责难回退决定和取舍。
- AGENTS.md 负责修改规则和验证入口。
- 代码与 scripts/validate.py 负责可执行行为与门禁。

同一规范性陈述只保留一个 canonical owner,其他文档用 repo:// 指针引用。
