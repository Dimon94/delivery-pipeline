---
name: delivery-pipeline-lody
description: 通过 Lody 原生 session 与 Lody-managed worktree 启动或恢复交付编排的 transport 壳。
disable-model-invocation: true
---

# Delivery Pipeline（Lody 壳）

本 skill 是 `../delivery-pipeline/SKILL.md` 核心链路的 transport 壳，供运行在 Lody session 里的
pi、Codex 与 Claude coordinator 使用。先完整读取 canonical 主干；本文件覆盖 dispatch transport、
Lody session 生命周期与 Lody packet，其他 gate、owner、worktree、Integration、权限和收尾不变量不变。
委派、阻塞与恢复时执行 canonical「调度职责」；以 context pointers 填写本壳 packet，
后台 Lody session 与 Operation 结果投递沿本壳生命周期合同。

Epic 输入按 `../delivery-pipeline/references/epic-scheduling.md` 从 Issue 恢复各 MMF，使用本壳派发和等待终态。

## 覆盖

0. **Driver run（ADR-0026）。** map 有 driver.json 时，每次唤醒先调一次
   `../delivery-pipeline/scripts/driver.py run <map 目录>`；fan-in、consume、closeout 与审核页渲染已由程序完成。
   交回的 `dispatch` / `prepare_map` 由 coordinator 用Lody session 工具按下列合同执行，回执经 `driver.py record` 交回；
   worker 终态先用 `driver.py signal` 交回再 run，输出 `wait` 即结束本轮。第 4 项的亲自 Integration 只适用于旧 map；无 driver.json 的旧 map
   按下列旧合同推进，直到下一次 Plan Review。
1. 当前 Lody session 就是 coordinator，记录 `coordinator_runtime: lody`、`dispatch_runtime: lody`，
   宿主 agent 记入 `lody` overlay。coordinator 留在 Source Worktree。新建 lane 前加载
   `references/lody-dispatch.md`。
2. 所有新 worker 是 `lody_session_create(workContext: {kind: "local", worktree: true})` 子 session，
   runtime 为 `lody-session`。worker kind、model 与 effort 来自 version 5 CLI 配置实例，按 dispatch
   合同映射到 Lody agent config，并以 `lody_session_create_options` 的 runConfig 实时核对。
3. 新 lane 使用本壳 `assets/LODY_ROLE_DISPATCH_PACKET.md`；worker 先把 Lody 给的 worktree 对齐到
   packet 的 `base_sha`。结果投递、HITL、fan-in、恢复与 Cleanup 按 `references/lody-lifecycle.md`。
4. Integration 由 coordinator 在 Map Integration Worktree 亲自执行；testing 与 whole-change review
   各为一条 Lody lane。whole-change review 必须沿 `references/lody-dispatch.md` §M3
   冻结 ReviewPlan/owner_calls，通过现有 native host 协议调用 native_review.py；不走 work fallback。
5. 当前会话明确选择 Herdr、T3Code、Codex App 或 Orca 时退出本壳，改用对应入口；同一 map 不静默
   混合新 lane transport。existing lane 始终按 registry runtime 恢复。

完成标准：每个 delegated gate 都有明确 Lody session transport 与 output mode；Lody session、Execution
Worktree、registry 与 Integration branch 一致，其余完成标准沿用 canonical 主干。

## Coordinator 恢复

沿 canonical `../delivery-pipeline/references/fresh-session-boundaries.md` §Coordinator Recovery
在原 map registry 保存六项短记录；恢复按 `references/lody-lifecycle.md` §恢复 核验 Lody session、Git、
active writers 与当前 gate 证据。

## References

- `references/lody-dispatch.md`：Preflight、target 映射、registry overlay、派发关键路径、startup readback。
- `references/lody-lifecycle.md`：结果投递、HITL、fan-in、恢复、Cleanup、取消与 replacement。
- `assets/LODY_ROLE_DISPATCH_PACKET.md`：worker packet 模板。
