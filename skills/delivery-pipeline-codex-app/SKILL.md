---
name: delivery-pipeline-codex-app
description: 通过 Codex App 原生任务与 App-managed Execution Worktrees 启动或恢复交付编排。
disable-model-invocation: true
---

# Delivery Pipeline（Codex App 壳）

本 skill 是 `../delivery-pipeline/SKILL.md` 的 coordinator 薄 delta。coordinator 先读取 canonical
主干入口，按当前 gate 加载引用；worker 从 `assets/APP_ROLE_DISPATCH_PACKET.md` §按分支加载进入。本文件
覆盖 transport、配置 gate 与 delegated-task execution，其他 gate、owner、worktree、Integration、
权限和收尾不变量不变。
委派、阻塞与恢复时执行 canonical「调度职责」；以 context pointers 组织外层 packet 与内部
subagent prompt，后台任务回传与验收沿本壳合同。

## 覆盖

1. 当前 Codex App 会话就是 coordinator，记录 `coordinator_runtime: codex-app`、
   `dispatch_runtime: codex-app`。启动时读取 `references/development-mode.md` 的工作分工、执行入口
   与参数与证据；
   通过 `scripts/prewalk.py models` 读取本 skill 的 `config/models.json`，查询 coordinator 推荐值。用户明确选择可覆盖所有阶段的模型与档位。
   核对新任务的模型请求，按本次操作完成“每次调用的执行核验”；worker 按 packet 选择当前章节，
   内部委派必须经过 subagent 入口的模型、权限与并发核验。
2. 本壳使用 `config/models.json` 这个 App 配置实例：它与 CLI 实例共用
   `../delivery-pipeline/references/model-config-schema.md` 的 version 5 schema，所有任务类型绑定
   `agent: codex-app`。不加载 Herdr 的 pane lifecycle 合同；新 lane 入口用本壳的 dispatch
   reference。本壳记录明确的 model/effort 请求与独立运行 readback，缺失证据记 Unknown。
3. canonical 任务类型与 output mode 保持不变。planning、design、frontend、backend 使用
   `runtime: codex-thread` + App-managed Execution Worktree，不创建 Herdr pane：
   - planning → `output_mode: artifact`
   - design/frontend/backend implementation → `output_mode: commit`
   - design HITL → `output_mode: artifact`
   - testing → `output_mode: checks`，由 coordinator 串行委派配置中 testing 模型的只读 subagent
   - review → `output_mode: verdict`，由 coordinator 调用双轴 owner subagents
   map creation与地图沟通按开发模式合同查询配置后交给 planning artifact lane；用户直接在该任务沟通。
   coordinator 核验确认与持久产物后判断 gate，不能以 task completed 代替用户确认。
   Testing 与 Review 不另建 App task/worktree；结果仍持久化到对应 canonical gate。逐票
   Integration 由 coordinator 单独串行委派配置中 integration 模型的可写 subagent，并由 coordinator 回读 Git。
4. 外层 task lane 使用本壳 `assets/APP_ROLE_DISPATCH_PACKET.md`；创建、恢复、startup
   readback、terminal 回传、fan-in、archive 与 cleanup 读取
   `references/codex-app-dispatch.md` 的对应操作章节；worker 最终回复前按 packet 的回传合同通知 coordinator。commit 与
   verdict lane 还传递 canonical `../delivery-pipeline/references/code-review-evidence-preflight.md` 的
   绝对路径：commit 使用 Execution Base commit，verdict 使用 map registry base commit，沿同一
   Review Evidence Bundle 合同运行只读子审查。内部 Testing、Review 与 Integration 每次先走
   `references/development-mode.md` 的 subagent 入口。
   正式 Review 由 coordinator 按
   `review_scope: implementation | whole-change` 调用 resolved code-review owner；App 壳从配置传递
   两轴 model/effort，resolved owner 保持不变。实施 worker 的自评不能放行。候选 commit 在 Integration 前必须通过
   `references/codex-app-dispatch.md` 的“独立 Review 放行”和 `scripts/prewalk.py review`。
   新 Prewalk checkpoint 由 `scripts/prewalk.py checkpoint` 复用 canonical helper 原子写入并读回；
   legacy checkpoint 仅恢复已持久 lane。
5. 当前 App 明确选择 Herdr 时退出本壳，改用 `delivery-pipeline-herdr`；同一 map 不静默
   混合新 lane transport。existing lane 始终按 registry runtime 恢复。

coordinator 在 gate/批级交接时更新 canonical `../delivery-pipeline/references/fresh-session-boundaries.md`
§Coordinator Recovery；恢复先读原 map registry 的短记录，再执行当前操作的宿主与证据核验。

完成标准：每个 delegated gate 都有明确 App task transport与 output mode；App task、App-managed
Execution Worktree、App registry overlay 与 Integration branch一致，其余完成标准沿用 canonical。
