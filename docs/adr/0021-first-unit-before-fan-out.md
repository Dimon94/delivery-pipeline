# ADR-0021: 首单元合入后再扇出

**Status:** Accepted
**Date:** 2026-11-08
**Decider:** User (Dimon)
**Amends:** ADR-0001/0002/0003 列出的 maximal safe batch 不变量

## Context

第一批即派 maximal safe batch：ready frontier 中无前序依赖的 items 同批并发。startup 只核对
worktree、packet、owner、role config 与 registry，抓得到配置错误，抓不到跑到终态才暴露的缺陷：
packet 验收命令写错、owner Skill 规则有误、merger 收口步骤有坑。这类缺陷会在同批每条 lane 上
同时付出代价。

来源：pstack `playbooks/orchestrate.md`（cursor/plugins@6b03002）“Start with one unit”。
证据边界：本仓复盘记录中未见“多条 lane 同因失败”实例，本决定属推断性预防。

## Decision

1. 本 map 的 registry 中尚无 lane 到达 `closed` 时，本批只取 ready frontier 排序第一项。
2. 任一 lane 到达 `closed` 后，恢复 maximal safe batch。
3. 判定只读 registry 既有 state，不新增字段或标志位。

## Consequences

- packet 或流程缺陷在首单元暴露，只损失一条 lane；修正后再扇出。
- 首单元串行，map 墙钟时间增加约一张票的完整周期。
- 首单元 blocked 时，下一项仍单独派发，直到有 lane `closed`。
- map 中途修改 packet 模板或 owner Skill 不会重新触发首单元；需要时由用户要求串行。
- Dispatch Handoff 仍为 batch-scoped；一项的批同样适用。
