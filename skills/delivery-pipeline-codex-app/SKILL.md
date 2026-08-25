---
name: delivery-pipeline-codex-app
description: Codex App native shell for delivery-pipeline—use App tasks and App-managed Execution Worktrees for every delegated role while preserving canonical gates, Integration, and closeout.
disable-model-invocation: true
---

# Delivery Pipeline（Codex App 壳）

本 skill 是 `../delivery-pipeline/SKILL.md` 的薄 delta。先完整读取 canonical 主干；本文件
覆盖 transport、配置 gate 与 delegated-role execution，其他 gate、owner、worktree、Integration、
权限和收尾不变量不变。

## 覆盖

1. 当前 Codex App 会话就是 coordinator，记录 `coordinator_runtime: codex-app`、
   `dispatch_runtime: codex-app`。
2. 跳过 canonical CLI 主干的 model-role 配置 gate。App task 的模型由 App 会话/任务环境拥有，
   registry 写 `agent: codex-app`、`model/effort/model_evidence: app-owned`。
3. canonical 的六个 delegated roles 全部使用 `runtime: codex-thread` + App-managed Execution
   Worktree，不创建 Herdr pane：
   - planning → `output_mode: artifact`
   - design/frontend/backend implementation → `output_mode: commit`
   - design HITL → `output_mode: artifact`
   - testing → `output_mode: checks`
   - review → `output_mode: verdict`
   map creation与用户 gate 判断仍留在当前 App coordinator。
4. 所有 delegated roles 使用本壳 `assets/APP_ROLE_DISPATCH_PACKET.md`；创建、恢复、startup
   readback、role-aware fan-in、archive 与 cleanup 加载 `references/codex-app-dispatch.md`。
5. 当前 App 明确选择 Herdr 时退出本壳，改用 canonical `delivery-pipeline`；同一 map 不静默
   混合新 lane transport。existing lane 始终按 registry runtime 恢复。

完成标准：每个 delegated gate 都有明确 App task transport与 output mode；App task、App-managed
Execution Worktree、App registry overlay 与 Integration branch一致，其余完成标准沿用 canonical。
