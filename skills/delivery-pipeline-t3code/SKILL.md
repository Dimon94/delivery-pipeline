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

Epic 输入按 `../delivery-pipeline/references/epic-scheduling.md` 从 Issue 恢复各 MMF，使用本壳派发和等待终态。

## 覆盖

0. **Driver run（ADR-0026）。** map 有 driver.json 时，每次唤醒先调一次
   `../delivery-pipeline/scripts/driver.py run <map 目录>`；fan-in、consume、closeout 与审核页渲染已由程序完成。
   交回的普通 `dispatch` 由本壳 `work_dispatch.py` 执行，Driver 直接读本 lane Registry。`prepare_map` 等其他 Action 的回执经 `driver.py record` 交回。
   票带 `briefs` 时 run 自己执行蜂巢执行片（`../delivery-pipeline/references/brief-dispatch.md`），执行片是本机
   `claude -p` 进程，不是 T3 task；run 可能运行很久，用后台命令执行并等待退出；
   worker 终态先按本壳生命周期核验，再用 `driver.py signal` 交回并 run，输出 `wait` 即结束本轮。无 driver.json 的旧 map
   按下列旧合同推进，直到下一次 Plan Review。
1. 当前 T3 线程就是 coordinator，记录 `coordinator_runtime: t3code`、`dispatch_runtime: t3code`，
   宿主 provider 记入 `t3code` overlay。coordinator 留在 Source Worktree。新建 lane 前加载
   `references/t3code-dispatch.md`。
2. 普通新 worker（含委派 planning）使用 `references/t3code-dispatch.md` §新 work lane 的入口。
   本壳从 setup 的 CLI 实例解析并验证 worker 身份，再使用 T3 隔离子任务执行。
3. 新 lane 使用本壳 `assets/T3CODE_ROLE_DISPATCH_PACKET.md`；worker 先把 T3 给的 worktree 对齐到
   packet 的 `base_sha`。完成唤醒、HITL、fan-in、恢复与 Cleanup 按 `references/t3code-lifecycle.md`。
4. map 的目标仓库（Spec 或票面 `Repo:`）与 coordinator checkout 不在同一 Git 仓库时，不在本线程派发：
   按 `references/t3code-dispatch.md` §跨仓路由 在目标仓库开 coordinator 线程后结束本轮。
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
