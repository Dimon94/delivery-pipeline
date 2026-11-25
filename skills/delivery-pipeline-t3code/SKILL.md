---
name: delivery-pipeline-t3code
description: 通过 T3 Code 启动或恢复交付编排。
disable-model-invocation: true
---

# Delivery Pipeline（T3Code 壳）

当前 T3 线程是 coordinator，留在 Source Worktree。新建 map 时记录
`coordinator_runtime: t3code`、`dispatch_runtime: t3code` 和 T3 overlay 的宿主 provider。

## 按唤醒原因进入

- **已有 map**：运行 `../delivery-pipeline/scripts/driver.py run <map 目录>`。收到 `wait` 或 `done` 即结束本轮。
- **子任务唤醒**：按 [生命周期 §唤醒](references/t3code-lifecycle.md) 核验该 lane。有效终态用
  `driver.py signal <map 目录> "<LANE_DONE 行>"` 交回，再 run。HITL 按同文件 §HITL 处理。
- **接手或压缩恢复**：按 [生命周期 §恢复](references/t3code-lifecycle.md) 从六项记录核验 Git、T3 与 active writers，再 run。交接时更新这六项。
- **Epic**：按 [Epic 调度](../delivery-pipeline/references/epic-scheduling.md) 恢复各 MMF。
- **新 map、旧 map**：按 [核心入口](../delivery-pipeline/SKILL.md) 初始化 Driver 或推进旧 gate。

run 可能在本机执行蜂巢整批合同。长命令交给命令完成事件，收到退出结果后处理 Action；失败现场见
[蜂巢执行片 §执行](../delivery-pipeline/references/brief-dispatch.md)。

## 按 Action 查合同

- **dispatch**：按 [派发 §新 work lane 的入口](references/t3code-dispatch.md) 调用 `work_dispatch.py`，使用
  [T3 packet](assets/T3CODE_ROLE_DISPATCH_PACKET.md)。目标仓与 Source 不同时先走 §跨仓路由。
- **ask_human（审核页）**：Merge Review 与旧 map 的 Plan Review 按 [审核页呈现](../delivery-pipeline/references/review-presentation.md) 准备 HTML，先用 `html_preview` 校验高度与明暗可读性，再用 `html_render` 内联展示，不贴裸文件路径；HITL 一次问完。原文作回执。
- **judge、invoke_owner、handoff_epic、prepare_map、prepare_contract、remote、halt**：读 [核心 §Run 循环](../delivery-pipeline/SKILL.md)
  的对应分支，按 Action id 交回回执。
- **人工收口、取消或 replacement**：只读 [生命周期](references/t3code-lifecycle.md) 的相应章节。

现有 lane 按 Registry 里的 runtime 恢复。用户明确改用其他 transport 时，使用对应入口。
