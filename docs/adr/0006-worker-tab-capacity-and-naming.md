# ADR-0006: Worker Tab 容量管理与命名规则

**Status:** Accepted
**Date:** 2026-08-27
**Decider:** User (Dimon)

Herdr lane 的默认落点是容量管理的 worker tab,而不是一 lane 一 tab:目标 Workspace 内 worker
tab 命名为 `X`(溢出依次 `X-2`、`X-3`),每个 worker tab 最多 4 pane,tab 内按 herdr 几何规则
split 分布四角;tab label 跟踪活跃 work item 编号(`X-#391·#392`),pane label 使用 work item
标题;HITL lane 用独立 tab `G-#<ticket>`。lane 收尾时关闭本 lane pane 并从 tab label 移除编号,
X tab 空后 label 还原并保留 tab 供复用,`G-#` tab 随 pane 一并关闭。

本 ADR 取代 ADR-0005 的“每条 lane 在目标 Workspace 的独立 tab/pane 中运行”条款;ADR-0005 的
current-workspace-first 前提(默认复用 Coordinator Pane 当前 Session/Workspace,只有用户显式要求
才新建 Workspace)不变。已有 active lane 仍按 registry 中的 session/workspace/tab/pane 坐标恢复,
行为变化仅影响后续新 lane 的默认落点。
