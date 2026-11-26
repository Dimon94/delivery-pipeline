---
name: delivery-pipeline
description: 交付编排核心链路；CLI/Herdr 交付调用 delivery-pipeline-herdr。
disable-model-invocation: true
---

# Delivery Pipeline（核心链路）

本 skill 是 canonical 核心链路，由平级 transport 壳（herdr、codex-app、orca、t3code、lody）读取；直接调用时改用
对应壳。目标是一张 map 交付一个 MMF 到一条 **Integration** branch。状态机归程序（**Driver**，ADR-0026）：
`scripts/driver.py` 推导 gate、frontier、收口、清理与停点；当前会话是 coordinator，只执行 Action 并回答判断。

## Run 循环

1. **run。** 每次唤醒调所属壳的 run 入口（壳未提供时 `scripts/driver.py run <map 目录>`）。程序能执行的
   Action（fan-in、consume、closeout、审核页渲染、蜂巢执行片 `references/brief-dispatch.md`、壳的派发
   helper）已在 run 内完成；只交回一行 JSON `{"action","id","args"}`。
2. **执行 Action。** 按 `action` 分支：
   - `invoke_owner`：按 `references/owner-skill-resolution.md` 调用 owner（name + 绝对 SKILL.md path + invocation label），
     传入 Action 的 `planning_mode`。按 [计划 owner 回执](references/owner-skill-resolution.md) 交回 NEXT、工件、计划改动和脚本结果。
   - `handoff_epic`：按 [Epic 调度](references/epic-scheduling.md) 接管 `args.epic`，使用原 Epic 认领入口。回执附 Epic 恢复坐标 `artifact`，结束原单 MMF map。
   - `prepare_contract` 与带合同的 `dispatch`、“合同违约”的 `judge`：按 `references/brief-dispatch.md` §单票合同。
   - `dispatch` / `prepare_map`：按所属壳 dispatch 合同落位；packet 用 `references/lane-registry.md` §轻量交接。
   - `ask_human`：Merge Review 与旧 map 的 Plan Review 按 `references/review-presentation.md` 呈现 `args.html`；HITL 把全部问题一次问完。原文作回执。
   - `judge`：轻判断当场从 `options` 选一项并附证据坐标；重判断（验收诊断、重拆、review 修复）派成 lane。
     只在 judge 时按 `args.kind` 读取 `references/execution-worktree-integration.md`、`references/frontier-lanes.md`
     或 `references/gate-state-machine.md` 对应章节。自动重拆回执附 `decision`，格式同计划 owner。
   - `remote`：按 `references/test-decision-and-rebase.md` §Remote Gate 执行 Merge Review 已授权的一步。
   - `halt`：把 `args` 的原因、证据坐标与可选项原样交给用户；回复后 `driver.py record <map 目录> halt <决定>`。
   - `wait` / `done`：结束本轮；`legacy`：无 Driver 的旧 map，按 `references/gate-state-machine.md` 推进。
3. **record。** `scripts/driver.py record <map 目录> <id> <回执JSON>`；worker 终态行用
   `driver.py signal <map 目录> "<LANE_DONE 行>"`。registry 只由 Driver 写，回执按 id 幂等。回到第 1 步。

## 停点
新 map 用 `driver.py init` 进入自动规划。to-tickets 脚本检查和蜂巢预检通过后，Driver 自动冻结计划与测试策略，
写入 Autonomy Grant 和计划快照。测试入口、票粒度和未开工 MMF 的划分由 owner 在原范围内调整，理由和证据留给最终验收。
需要改变业务预期、追加权限或命中 Halt 时请求裁决。Merge Review 核对计划与交付，用户通过后才授权 push、PR、CI 与合入收尾。

## 恢复与配置

- Epic 启动、恢复或 lane 唤醒走 `references/epic-scheduling.md`，从 Issue 恢复各 MMF 后逐 map 调 run。
- 新会话或压缩后按 `references/fresh-session-boundaries.md` §Coordinator Recovery 恢复，再调 run；既有 lane
  按 registry runtime 续跑。Map Integration Worktree 见 `references/integration-worktree-management.md`。
- 新建 lane 前从 setup skill realpath 运行 `scripts/model_config.py validate <config>`（见
  `references/model-config-schema.md`、`references/model-role-routing.md`）；缺失或非法时执行
  `../delivery-pipeline-setup/SKILL.md`，不静默回落。
- discovery 见 `references/wayfinder-frontier-loop.md`；review 证据见 `references/code-review-evidence-preflight.md`。

## 边界

- coordinator 不亲自实现、cherry-pick 或 fan-in，冲突交回 `run` 派 merger；集成分支出现不是 Driver 留下的提交时 `run` 以 `halt` 停下。沟通走 context pointers，不复制 spec、ticket 与日志正文。
- 本地 worktree、修改与 commit 用 local execution authority；push、PR/MR、merge 与 publication 只在 Merge Review
  授权后由 Driver 下发。证据缺失写 Unknown。面向用户与 tracker 的自然语言用中文。

完成标准：Driver 输出 `done`；map/spec/tickets 与各 lane 交付可追溯，whole-change testing/review 通过，
Merge Review 授权范围内的 remote 步骤与 closeout 完成。
