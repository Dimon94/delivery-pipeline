# ADR-0014: 用既有 registry 数据做静态 lane 图渲染

**Status:** Accepted（2026-09-28 修订：产物从 per-map 渲染改为单一全局静态页）
**Date:** 2026-09-28
**Decider:** User (Dimon)

> 2026-09-28 用户修订：不做 per-map 出图，改为**一个全局自包含静态页**，项目 → 地图 → lane
> 三级选择，只保存一个 URL。实现为 `skills/delivery-pipeline/scripts/lane_graph.py`：扫描
> registry root 下全部 `registry-*.md`，依赖边取 tracker `Blocked by`（每仓一次 gh 调用，
> 不可用标 Unknown），输出 `<registry-root>/lane-graph.html`（默认）；无外部资源，file://
> 直接打开。coordinator 在 Dispatch Handoff 与 terminal fan-in 后重跑该脚本，实现「自动新建
> 与刷新」；重新生成覆盖同一路径，收藏的 URL 不变。

## Context

外部实践用 `orca-viz` 渲染实时任务图（四态：完成/在跑/就绪/未轮到）并用创建时间戳
证明图在增长，对调试与复盘都有价值。用户明确两条约束：

1. 数据可读性不能只覆盖 Orca——Herdr/CLI、Codex App 各 transport 的 lane 都要能渲染；
> **修订（同日，凭据注）**：GitLab 访问的 host/IP、keychain 服务名、CA 路径等内部坐标**不入库、不进脚本**。脚本只从私有 config（默认 `~/.config/lane-graph/gitlab.json`，可用 `--gitlab-config` 指向他处）读取；该文件由 .gitignore 规则保护。脚本内所有 host/项目/账号字面量只允许出现于虚构的 self-test fixture 中。

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
