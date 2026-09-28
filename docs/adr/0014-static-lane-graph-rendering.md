# ADR-0014: 用既有 registry 数据做静态 lane 图渲染

**Status:** Accepted
**Date:** 2026-09-28
**Decider:** User (Dimon)

## Context

外部实践用 `orca-viz` 渲染实时任务图（四态：完成/在跑/就绪/未轮到）并用创建时间戳
证明图在增长，对调试与复盘都有价值。用户明确两条约束：

1. 数据可读性不能只覆盖 Orca——Herdr/CLI、Codex App 各 transport 的 lane 都要能渲染；
2. 不做 agent 在环的「绘图」，直接用当前持久数据静态渲染即可，不为可视化额外烧 token。

## Decision

1. **数据源唯一：核心链路的 lane registry + tracker 依赖边。** lane registry
   （`skills/delivery-pipeline/references/lane-registry.md`）本就是 transport-neutral
   的持久状态，三个壳都写它；渲染脚本只读 registry 与 tracker `Blocked by` 边，不读
   Orca DB、不依赖任何单一 runtime 的私有格式。
2. **静态渲染，按需生成。** 一个只读脚本把当前 registry 快照渲染成静态产物（Mermaid
   或自包含 HTML/SVG），由 coordinator 或用户显式调用时生成；不进 CI、不持续轮询、
   产物不提交（落 `.scratch/` 或临时路径）。
3. **渲染是派生物，不是状态。** 图只用于人读与报告，任何状态判断仍以 registry 与
   tracker 为准；渲染失败或数据不全时标注 Unknown，不从图反推状态。

## Consequences

- 任何 transport 的 map 都能出同一张图，排查「图长到哪了、哪段被拦」不再靠翻 registry
  原文。
- 零常驻成本：没有 watcher、没有定时任务， token 只花在显式调用的那一刻。
