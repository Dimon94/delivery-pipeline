---
name: delivery-pipeline-herdr
description: 通过 Herdr 启动或恢复交付编排的 CLI transport 壳。
disable-model-invocation: true
---

# Delivery Pipeline（Herdr 壳）

本 skill 是 `../delivery-pipeline/SKILL.md` 核心链路的 transport 壳，供 pi、Codex CLI 与
Claude CLI 使用。先完整读取 canonical 主干；本文件覆盖 dispatch transport、pane/monitoring
生命周期与 Herdr packet，其他 gate、owner、worktree、Integration、权限和收尾不变量不变。
委派、阻塞与恢复时执行 canonical「调度职责」；以 context pointers 填写本壳 packet，
后台 pane 与终态唤醒沿本壳生命周期合同。

## 覆盖

1. 当前调用会话就是 coordinator，记录 `coordinator_runtime: pi-cli | codex-cli | claude-cli`、
   `dispatch_runtime: herdr`。新建 lane 前加载 `references/dispatch-runtime-routing.md`，
   验证当前 Herdr session/workspace/tab/pane；只有用户显式要求新 Workspace 才创建。
2. 所有新 worker 通过 Herdr Pane 承载，worker kind 由 version 5 work config 的 `agent`
   决定：pi → `herdr-pi-pane`，codex → `herdr-codex-pane`，claude → `herdr-claude-pane`。
   落位、启动、投递、watcher 与 registry 由 `scripts/dispatch.py` 一次完成，见
   `references/dispatch-runtime-routing.md`。
3. 新 lane 使用本壳 `assets/HERDR_ROLE_DISPATCH_PACKET.md`；terminal event、用户完成信号与显式 monitor 的
   fan-in 按 `references/child-monitoring.md`。
4. replacement 按
   `references/dispatch-runtime-routing.md` 的「恢复与切换」。
5. 当前会话明确选择 Codex App 或 Orca 时退出本壳，改用对应入口；同一 map 不静默混合新 lane
   transport。existing lane 始终按 registry runtime 恢复。

完成标准：每个 delegated gate 都有明确 Herdr transport 与 output mode；Herdr pane、Execution
Worktree、registry 与 Integration branch 一致，其余完成标准沿用 canonical 主干。

## Coordinator 恢复

沿 canonical `../delivery-pipeline/references/fresh-session-boundaries.md` §Coordinator Recovery
在原 map registry 保存六项短记录；恢复再核验真实 pane、Git、active writers 与当前 gate 证据。
Pi coordinator 需要可控压缩且本机版本支持 `/compact [instructions]` 时，先完成该记录的
持久 readback，再将记录正文、未决约束和原证据指针交给 `/compact`；压缩后核对摘要。
自动压缩和其他宿主的能力以实际接口为准。

## References

- `references/dispatch-runtime-routing.md`：新 lane 经 `scripts/dispatch.py` 派发、恢复与 replacement。
- `references/pane-lifecycle-rules.md`：worker tab 拓扑、terminal signal 与 watcher。
- `references/child-monitoring.md`：终态信号、role-aware outcomes、fan-in。
- `assets/HERDR_ROLE_DISPATCH_PACKET.md`：worker packet 模板。
