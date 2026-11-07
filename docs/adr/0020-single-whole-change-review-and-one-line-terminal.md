# ADR-0020: 单次 whole-change review 与单行终态

**Status:** Accepted
**Date:** 2026-11-07
**Decider:** User (Dimon)
**Supersedes:** ADR-0017 中 CLI 的逐票 implementation review

## Context

编排会话复盘显示，每张票的 commit lane 内嵌双轴 review、七文件 bundle 与八字段 FINAL_REPORT
是 worker 与 coordinator 的主要 token 来源；这些信息 Agent 可从 Git、tracker 与 registry 自取，
而真正挡住缺陷的是 Integration 上的 whole-change review。

## Decision

1. CLI 壳（Herdr、T3 Code、Lody、Orca）的 commit lane 不跑 review，交付 commit 即由 merger 收口。
2. Review 只在 Map Integration（独立票为本票 PR）做一次 whole-change，最多 3 轮；每轮 `FIX` 的全部
   finding 交给同一个 implementer lane 修复，merger 收口后开下一轮。
3. Review Evidence Bundle 只含 `fixed-point.txt`、`diff.patch`、`changed-paths.txt`。
4. worker 终态只输出 `lane-registry.md` §终态行：`LANE_DONE <lane_id> <交付坐标>`，阻塞时
   `LANE_DONE <lane_id> BLOCKED <原因；工件路径>`。
5. Codex App 壳保留逐票 review 与 App 终态模板（FINAL_REPORT），模板只存于 App 树。

## Consequences

- 每票省去一次双轴 review 与长终态报告；缺陷暴露推迟到 whole-change，修复集中到单 implementer。
- 每张票的 Review 预算账本只在 App 使用；CLI 只有 whole-change 账本。
