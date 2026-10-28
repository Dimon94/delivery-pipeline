---
name: delivery-pipeline-t3code
description: 通过 T3 Code 原生 delegate_task 启动或恢复交付编排的 transport 壳。
disable-model-invocation: true
---

# Delivery Pipeline（T3Code 壳）

本 skill 是 `../delivery-pipeline/SKILL.md` 核心链路的 transport 壳，供运行在 T3 Code 线程里的
pi、Codex 与 Claude coordinator 使用。先完整读取 canonical 主干；本文件覆盖 dispatch transport、
T3 task 生命周期与 T3Code packet，其他 gate、owner、worktree、Integration、权限和收尾不变量不变。
委派、阻塞与恢复时执行 canonical「调度职责」；以 context pointers 填写本壳 packet，
后台 T3 task 与完成唤醒沿本壳生命周期合同。

## 覆盖

1. 当前 T3 线程就是 coordinator，记录 `coordinator_runtime: t3code`、`dispatch_runtime: t3code`，
   宿主 provider 记入 `t3code` overlay。coordinator 留在 Source Worktree。新建 lane 前加载
   `references/t3code-dispatch.md`。
2. 所有新 worker 是 `delegate_task(mode:"async", isolation:"worktree")` 子任务，runtime 为 `t3-task`。
   worker kind、model 与 effort 来自 version 5 CLI 配置实例，按 dispatch 合同映射到 T3 target 并以
   `orchestrator_capabilities` 实时核对。
3. 新 lane 使用本壳 `assets/T3CODE_ROLE_DISPATCH_PACKET.md`；worker 先把 T3 给的 worktree 对齐到
   packet 的 `base_sha`。完成唤醒、HITL、fan-in、恢复与 Cleanup 按 `references/t3code-lifecycle.md`。
4. v1 只承载 direct 计划；staged 计划保持 `blocked`，直到 T3 staged adapter 落地。
5. 当前会话明确选择 Herdr、Codex App 或 Orca 时退出本壳，改用对应入口；同一 map 不静默混合
   新 lane transport。existing lane 始终按 registry runtime 恢复。

完成标准：每个 delegated gate 都有明确 T3 task transport 与 output mode；T3 task、Execution
Worktree、registry 与 Integration branch 一致，其余完成标准沿用 canonical 主干。

## Coordinator 恢复

沿 canonical `../delivery-pipeline/references/fresh-session-boundaries.md` §Coordinator Recovery
在原 map registry 保存六项短记录；恢复按 `references/t3code-lifecycle.md` §恢复 核验 T3 线程、Git、
active writers 与当前 gate 证据。

## References

- `references/t3code-dispatch.md`：Preflight、target 映射、registry overlay、派发关键路径、startup readback。
- `references/t3code-lifecycle.md`：完成唤醒、HITL、fan-in、恢复、Cleanup、取消与 replacement。
- `assets/T3CODE_ROLE_DISPATCH_PACKET.md`：worker packet 模板。
