---
name: delivery-pipeline
description: 交付编排核心链路；CLI/Herdr 交付调用 delivery-pipeline-herdr。
disable-model-invocation: true
---

# Delivery Pipeline（核心链路）

本 skill 是 canonical 核心链路，由平级 transport 壳读取（`delivery-pipeline-herdr`、`delivery-pipeline-codex-app`、
`delivery-pipeline-orca`、`delivery-pipeline-t3code`、`delivery-pipeline-lody`）；直接调用时改用对应壳，
CLI 交付用 `delivery-pipeline-herdr`。当前调用会话就是 coordinator：调度归壳，产物质量归 owner，
Integration 不变量归本链路。

目标是一张 map 交付一个 MMF 到一条 **Integration** branch。判定与拆票链见 `references/gate-state-machine.md`。
tickets 是带阻塞关系的任务图，始终有一个 ready **frontier**。

## 调度职责

- coordinator 只推进最早未完成 gate、派发 frontier、读终态行；coordinator 不亲自实现或 fan-in。
- 沟通走 **context pointers**：绝对路径或 tracker URL 加章节或 commit 定点，不复制 spec、ticket 与日志正文。
- 失败交对应 owner 修复并按原判据复验，保留失败证据；证据缺失写 Unknown 并停在所属 gate。
- 用户明确要求定时工作时才用 runtime 原生调度；日常等待按所属壳的真实唤醒合同。

## Steps

1. **识别 gate。** 读 repo instructions、tracker 与输入（想法、map、spec 或 ticket；裸编号须唯一解析），
   按 `references/gate-state-machine.md` 从持久证据选最早未完成 gate；discovery 走
   `references/wayfinder-frontier-loop.md`。
2. **恢复坐标。** 新会话或压缩后按 `references/fresh-session-boundaries.md` §Coordinator Recovery，
   只读恢复记录的合同入口所指章节并枚举 active writers。恢复既有 lane 不依赖当前 worker 配置，按 registry
   runtime 续跑。按 `references/integration-worktree-management.md` 复用或创建 Map Integration Worktree；
   Git 操作都指向隔离 worktree，不切换 coordinator 当前目录的 branch。
3. **校验配置。** 新建 lane 前从 setup skill realpath 运行 `scripts/model_config.py validate <config>`
   （version 5，见 `references/model-config-schema.md`）并验证本机 evidence；旧版本先 `migrate`；
   缺失或非法时执行 `../delivery-pipeline-setup/SKILL.md`，不静默回落。
4. **派发 frontier。** 每张 ready ticket 一个 lane、一个 owner（name + 绝对 SKILL.md path + invocation
   label）、一个 Execution Worktree（默认从 Integration HEAD 建，例外见 `references/integration-worktree-management.md`）。lane 单轮直跑任务类型的 `{agent, model, effort}`
   （ticket/map 点名 mode 时用其 `direct` 组），冻结进 packet 与 registry。按 `references/frontier-lanes.md`、
   `references/owner-skill-resolution.md`、`references/model-role-routing.md` 与所属壳 dispatch 合同落位；
   registry 先于 worker，packet 用 `references/lane-registry.md` §轻量交接。本批启动后到达 Dispatch Handoff；
   本 map 尚无 lane `closed` 时本批只有一项。
5. **收口。** 终态行到达后派 integration lane（merger）按 `references/execution-worktree-integration.md`
   收口到 `closed`；merger 终态后重算 frontier，回到第 4 步。
6. **Testing 与 Review。** frontier 清空后派 testing lane，再派一个 review lane：输入给出
   fixed point（map registry base）与 `references/code-review-evidence-preflight.md`，worker 先生成
   Review Evidence Bundle。轮次与 FIX 按 gate-state-machine §Review 预算，finding 交给同一个 implementer lane。
7. **收尾。** 按 `references/test-decision-and-rebase.md` 处理测试选择、rebase 与 remote gate。

## 边界

- 本地 worktree、修改与 commit 用 local execution authority；named-map tracker 迁移用 Map Run Authority；
  push、PR/MR、merge 与 publication 需要 remote publication authority。
- 面向用户、worker、tracker 与 PR/MR 的自然语言用中文；skill/tool/status/path/hash 保持原样。

完成标准：map/spec/tickets 与各 lane 交付可追溯，execution graph 为空，whole-change testing/review 通过；
远程获授权时 CI/CD 与 closeout 通过，否则报告唯一剩余 remote gate。
