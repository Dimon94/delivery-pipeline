---
name: delivery-pipeline-alma
description: 通过 Alma Task tool 启动或恢复交付编排的 UI transport 壳。
disable-model-invocation: true
---

# Delivery Pipeline（Alma 壳）

本 skill 是 `../delivery-pipeline/SKILL.md` 的 coordinator 薄 delta。coordinator 先读取 canonical
主干入口，按当前 gate 加载引用；worker 从 `assets/ALMA_ROLE_DISPATCH_PACKET.md` §按分支加载进入。本文件
覆盖 dispatch transport、配置 gate 与 delegated-task execution，其他 gate、owner、worktree、Integration、
权限和收尾不变量不变。
委派、阻塞与恢复时执行 canonical「调度职责」；以 context pointers 组织 packet，Task 回传与验收沿本壳合同。

## 覆盖

1. 当前 Alma UI 会话就是 coordinator，记录 `coordinator_runtime: alma-ui`、
   `dispatch_runtime: alma-task`。新建 lane 前加载 `references/alma-dispatch.md`，
   验证当前 Alma thread/workspace/project；只有用户显式要求新 thread 才创建。
2. 本壳使用 `config/models.json` 这个 Alma 配置实例：它与 CLI 实例共用
   `../delivery-pipeline/references/model-config-schema.md` 的 version 5 schema，所有任务类型绑定
   `agent: alma`。不加载 Herdr 的 pane lifecycle 合同；新 lane 入口用本壳的 dispatch
   reference。本壳记录明确的 model 请求与独立运行 readback，**effort 只记录请求值**（ADR-0015）；
   缺失证据记 Unknown。
3. canonical 任务类型与 output mode 保持不变。planning、design、frontend、backend 使用
   `runtime: alma-task`，**不创建 Herdr pane**：
   - planning → `output_mode: artifact`
   - design/frontend/backend implementation → `output_mode: commit`（**只支持 kind: direct**，ADR-0015）
   - design HITL → `output_mode: artifact`
   - testing → `output_mode: checks`，由 coordinator 串行委派配置中 testing 模型的只读 Task
   - review → `output_mode: verdict`，由 coordinator 调用双轴 owner Tasks

   map creation 与地图沟通按配置查询后交给 planning artifact lane；用户直接在该 Task 沟通。
   coordinator 核验确认与持久产物后判断 gate，不能以 Task completed 代替用户确认。
   Testing 与 Review 不另建独立 Task registry 记录；结果仍持久化到对应 canonical gate。逐票
   Integration 由 coordinator 单独串行委派配置中 integration 模型的可写 Task，并由 coordinator 回读 Git。
4. 外层 Task lane 使用本壳 `assets/ALMA_ROLE_DISPATCH_PACKET.md`；创建、恢复、startup
   readback、terminal 回传、fan-in 与 cleanup 读取
   `references/alma-dispatch.md` 的对应操作章节；worker 最终回复前按 packet 的回传合同输出 `LANE_DONE` 标记。commit 与
   verdict lane 还传递 canonical `../delivery-pipeline/references/code-review-evidence-preflight.md` 的
   绝对路径：commit 使用 Execution Base commit，verdict 使用 map registry base commit，沿同一
   Review Evidence Bundle 合同运行只读子审查。内部 Testing、Review 与 Integration 每次先走本壳
   config 查询入口。
   正式 Review 由 coordinator 按
   `review_scope: implementation | whole-change` 调用 resolved code-review owner；Alma 壳从配置传递
   两轴 model，resolved owner 保持不变。实施 worker 的自评不能放行。候选 commit 在 Integration 前必须通过
   `references/alma-dispatch.md` 的"独立 Review 放行"和 `scripts/alma_gate.py review`。
5. 当前 UI 明确选择 Herdr 时退出本壳，改用 `delivery-pipeline-herdr`；同一 map 不静默
   混合新 lane transport。existing lane 始终按 registry runtime 恢复。

coordinator 在 gate/批级交接时更新 canonical `../delivery-pipeline/references/fresh-session-boundaries.md`
§Coordinator Recovery；恢复先读原 map registry 的短记录，再执行当前操作的宿主与证据核验。

完成标准：每个 delegated gate 都有明确 Alma Task transport 与 output mode；Alma Task、coordinator-created
Execution Worktree、Alma registry overlay 与 Integration branch 一致，其余完成标准沿用 canonical。
