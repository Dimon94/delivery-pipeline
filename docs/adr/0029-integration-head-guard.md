# ADR-0029: 票实施阶段集成 HEAD 只认 Driver 留下的，外来提交停机

**Status:** Accepted（ADR-0026 的 Halt 清单不变，复用第 5 类）
**Date:** 2026-11-25
**Decider:** User (Dimon)

## Context

“coordinator 不亲自实现、cherry-pick 或 fan-in”只写在 SKILL.md 里，没有东西强制它。
回看 2026-11-19 至 2026-11-25 的 15 个 coordinator 会话，10 个出现过亲手操作，共 66 次。
按命令文本重分类（推断）：约 30 次是真违规，其中集成树手工 cherry-pick 16 次、手改产品代码、测试或迁移 9 次、
候选树手工 merge 约 5 次，基本都发生在 fan-in 冲突之后。其余是已授权的合回本地 main 和度量误报。

Driver 每次启动直接读集成树当前 HEAD 当基线，不比对，所以手工提交会被后续 fan-in、场景验收和评审照单全收。

## Decision

1. Driver 在 `driver.json` 记 `integration_seen`：它自己执行完一条程序 Action 后集成树的 HEAD。
2. 下一次 `run` 发现集成 HEAD 不等于 `integration_seen` 时按 Halt 第 5 类停下，列出外来提交，
   选项是认可、回退到 Driver 留下的提交、放弃。halt id 带当前 HEAD，同一个 HEAD 只问一次。
3. 两种情况不拦，因为别的 lane 会合法地移动集成 HEAD：
   - 有 merger（`role: integration`）在途或待消费；
   - 已进入整体测试、评审阶段（出现 `testing` 或 `review` lane），之后还有同步主干和 remote closeout。
4. 不检查集成树是否有未提交改动：未跟踪的依赖目录会误报，未提交的改动也进不了交付提交。

## Consequences

- 冲突后手工 cherry-pick、手改迁移号这类操作在下一次 `run` 就会被看见，由用户决定认不认。
- merger 在途期间分不清 HEAD 是 merger 还是 coordinator 动的；整体测试开始后不再拦。这两段靠 Merge Review 兜底。
- 目标仓若约定每张票都在集成树提交进度文档，会每票停一次。应改成收尾时写一次；这是目标仓的约定，不在本仓改。
- 没有 `integration_seen` 的旧 map 在 Driver 第一次执行程序 Action 后才开始受保护。

## Verification

`driver.py self-test`：Driver 自己 fan-in 后不停机并记下 HEAD；集成树出现手工提交后停机并列出提交；
用户认可后继续；merger 在途和整体测试阶段不停机。
