---
name: delivery-pipeline-codex-app
description: 通过 Codex App 原生任务与 App-managed Execution Worktrees 启动或恢复交付编排。
disable-model-invocation: true
---

# Delivery Pipeline（Codex App 壳）

本 skill 是 `../delivery-pipeline/SKILL.md` 的薄 delta。先完整读取 canonical 主干；本文件
覆盖 transport、配置 gate 与 delegated-role execution，其他 gate、owner、worktree、Integration、
权限和收尾不变量不变。

## 覆盖

1. 当前 Codex App 会话就是 coordinator，记录 `coordinator_runtime: codex-app`、
   `dispatch_runtime: codex-app`。启动时读取 `references/development-mode.md`，按工作分工核对
   当前 coordinator 与新任务的模型请求，并完成其中“每次调用的执行核验”；worker 从 packet
   读取同一合同，内部委派必须经过 subagent 入口的模型、权限与并发核验。
2. 跳过 canonical CLI 主干的 model-role 配置 gate；新 lane 入口用本壳的 dispatch reference，
   不加载 Herdr 的 model-role/runtime/pane lifecycle 合同。App 拥有执行配置；本壳记录明确的
   model/effort 请求与独立运行 readback，缺失证据记 Unknown。
3. canonical 的六个 delegated roles 全部使用 `runtime: codex-thread` + App-managed Execution
   Worktree，不创建 Herdr pane：
   - planning → `output_mode: artifact`
   - design/frontend/backend implementation → `output_mode: commit`
   - design HITL → `output_mode: artifact`
   - testing → `output_mode: checks`
   - review → `output_mode: verdict`
   map creation与地图沟通按开发模式合同交给 Astra artifact lane；用户直接在该任务沟通。
   coordinator 核验确认与持久产物后判断 gate，不能以 task completed 代替用户确认。
4. 所有 delegated roles 使用本壳 `assets/APP_ROLE_DISPATCH_PACKET.md`；创建、恢复、startup
   readback、terminal 回传、role-aware fan-in、archive 与 cleanup 必读
   `references/codex-app-dispatch.md`；worker 最终回复前按 packet 的回传合同通知 coordinator。commit 与
   review roles 还传递 canonical `../delivery-pipeline/references/code-review-evidence-preflight.md` 的
   绝对路径：commit 使用 Execution Base commit，verdict 使用 map registry base commit，沿同一
   Review Evidence Bundle 合同运行只读子审查。
5. 当前 App 明确选择 Herdr 时退出本壳，改用 canonical `delivery-pipeline`；同一 map 不静默
   混合新 lane transport。existing lane 始终按 registry runtime 恢复。

完成标准：每个 delegated gate 都有明确 App task transport与 output mode；App task、App-managed
Execution Worktree、App registry overlay 与 Integration branch一致，其余完成标准沿用 canonical。
