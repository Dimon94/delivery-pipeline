---
name: delivery-pipeline-herdr
description: 通过 Herdr 启动或恢复交付编排的 CLI transport 壳。
disable-model-invocation: true
---

# Delivery Pipeline（Herdr 壳）

本 skill 是 `../delivery-pipeline/SKILL.md` 核心链路的 transport 壳，供 pi、Codex CLI 与
Claude CLI 使用。先完整读取 canonical 主干；本文件覆盖 dispatch transport、pane/monitoring
生命周期与 Herdr packet，其他 gate、owner、worktree、Integration、权限和收尾不变量不变。

## 覆盖

1. 当前调用会话就是 coordinator，记录 `coordinator_runtime: pi-cli | codex-cli | claude-cli`、
   `dispatch_runtime: herdr`。新建 lane 前加载 `references/dispatch-runtime-routing.md`，
   验证当前 Herdr session/workspace/tab/pane；只有用户显式要求新 Workspace 才创建。
2. 所有新 worker 通过 Herdr Pane 承载，worker kind 由 version 4 work config 的 `agent`
   决定：pi → `herdr-pi-pane`，codex → `herdr-codex-pane`，claude → `herdr-claude-pane`。
   启动参数与 kind-specific permission 按 `references/dispatch-runtime-routing.md` 与
   `references/pane-lifecycle-rules.md`。
3. 新 lane 使用本壳 `assets/HERDR_ROLE_DISPATCH_PACKET.md`；落点拓扑、容量与 lane watcher
   按 `references/pane-lifecycle-rules.md`；terminal event、用户完成信号与显式 monitor 的
   fan-in 按 `references/child-monitoring.md`。
4. staged continuation、replacement 与 checkpoint 核验按
   `references/dispatch-runtime-routing.md` 的「恢复与切换」。
5. 当前会话明确选择 Codex App 或 Orca 时退出本壳，改用对应入口；同一 map 不静默混合新 lane
   transport。existing lane 始终按 registry runtime 恢复。

完成标准：每个 delegated gate 都有明确 Herdr transport 与 output mode；Herdr pane、Execution
Worktree、registry 与 Integration branch 一致，其余完成标准沿用 canonical 主干。

## References

- `references/dispatch-runtime-routing.md`：新 lane 选择顺序、Herdr session/workspace 解析、
  packet 投递、replacement 与 staged continuation。
- `references/pane-lifecycle-rules.md`：落点拓扑与容量、lane watcher、pane 命名。
- `references/child-monitoring.md`：终态信号、role-aware outcomes、fan-in。
- `assets/HERDR_ROLE_DISPATCH_PACKET.md`：worker packet 模板。
