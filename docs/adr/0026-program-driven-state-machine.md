# ADR-0026: 程序驱动状态机，LLM 只做执行器和判断函数

**Status:** Accepted
**Date:** 2026-11-17
**Decider:** User (Dimon)

## Context

`scripts/orchestration_metrics.py` 对最近 30 天 25 个 coordinator 会话的基线：上下文峰值中位数约
48 万 token、P90 约 94 万；轮询/监控类调用占全部工具调用 11.6%；25 个会话里 19 个出现
coordinator 亲手改业务仓文件、cherry-pick 或自己 fan-in，共 777 次。gate 推导、frontier 选择、
收口和清理都由 LLM 读 reference 后自行推理，ADR-0019 把 fan-in 移给 merger lane 后，亲手改代码
仍反复出现；每个 gate 都停下来等用户，map 推进依赖人一直在场。

2026-11-17 grilling 与用户逐条确定：把状态机交给程序（Driver），LLM 只执行程序给出的 Action
并回答判断；用户只在计划前和合入前各审一次，其余停点收敛成封闭的 Halt 清单。

## Decision

1. **Driver 两层。** core 层是纯函数 `decide(state) → Action`，位于
   `skills/delivery-pipeline/scripts/driver.py`：冻结输入、带 self-test、无副作用。每个 transport
   壳带一个 `run` 循环：反复调用 decide，程序能执行的 Action（Herdr `dispatch.py`、cherry-pick、
   focused checks、`closeout.py`、`orca` 命令）直接执行；需要宿主工具、判断（judge）、等待
   （wait）或停下（halt）时只交回一行。各壳共用的执行器（cherry-pick、closeout）放在 core；
   core 不引用任何壳文件。
2. **Action 协议。** 一行 JSON `{"action","id","args"}`。coordinator 执行宿主工具后用
   `driver record <id> <回执JSON>` 交回；Driver 校验后写 registry。registry 只由 Driver 写；
   回执按 id 幂等，重复交回同一 id 不重复生效。
3. **judge 分轻重。** 轻判断由 coordinator 当场回答并附证据坐标；重判断（ADR-0012 验收诊断、
   review 修复）派成 lane。reference 只在 judge 时读取。
4. **唤醒。** Herdr `lane-watch.sh` 与 Orca worker nudge 先跑 `run`：结果是 wait 或已由程序执行完时
   不唤醒 LLM。T3、Codex App、Lody 每次唤醒由 coordinator 调一次 `run`。不引入常驻 daemon。
5. **收口。** 正常 fan-in 由 Driver 自己完成（cherry-pick + focused checks）；只有冲突或 focused
   checks 失败时才派 merger lane。**修订 ADR-0019 决策 2。**
6. **两个审核点。** Plan Review 在 to-tickets 草稿过脚本检查之后、发布之前；Merge Review 在开 PR
   之前。两份 HTML 由 Driver 用同一模板确定性渲染：Plan Review 只渲染计划；Merge Review 叠加
   实际交付和自动处理过的偏差。用户回复"通过"后 Driver 写入授权：Plan Review 授予
   Autonomy Grant 并写入 map registry；Merge Review 授权 push、建 PR、等 CI，并按仓库分支合同
   合入、收尾。CI 红或评审阻塞时 halt。
7. **Test Decision Point 并入 Plan Review。** 范围与风险未变时沿用已定策略、不停；有变化按
   Halt 第 1 类处理。
8. **Halt 是封闭清单。** 只有：(1) 计划的 T/R、范围或验收要改；(2) 补票超出已批准波次，或改动
   合同票；(3) `REVIEW_EXHAUSTED`；(4) 重拆后仍失败；(5) 需要远程权限、不可逆操作或授权外的
   决定；外加 CI 红与评审阻塞。清单外的偏差自动处理并在 Merge Review 报告。halt 把原因、证据
   坐标和可选项写入 map registry；用户回复后 coordinator 用 `driver record halt <决定>` 交回。
9. **Epic 级 Driver。** 只读 Epic 候选表和各 map 终态，为开工阻塞已解除的 MMF 开 map 并自动启动
   该 MMF 的 to-spec。map 之间不共享 worktree 与 lane。
10. **wayfinder HITL。** 当前 frontier 上的 HITL 问题合成一个停点一次问完；AFK 票照常推进。
11. **Orca 授权。** 在 Autonomy Grant 范围内，Driver 的 readback 校验通过即构成授权；版本匹配的
    guides 与 capability 证据是前置条件，缺失时 halt，不回落到其他 transport。**修订
    `skills/delivery-pipeline-orca/SKILL.md` 中"结构成功仅 `preflight-ready`、`authority: false`，
    coordinator 必须核验原生 source provenance 后才授权"一款**（自治 map 内由 Driver readback
    取代 coordinator 手工核验；无 Autonomy Grant 的 map 维持原条款）。
12. **迁移。** Driver 直接读现有 registry。无 Autonomy Grant 的 map 继续按旧流程逐个 gate 推进，
    直到下一次 Plan Review。不写迁移脚本。

## Consequences

- coordinator 上下文只承载一行 Action 和回执；状态推导、收口与清理的正确性由 `driver.py`
  self-test 锁定，回归指标由 `scripts/orchestration_metrics.py` 复测。
- 用户停点从每个 gate 收敛为 Plan Review、Merge Review 与封闭 Halt；清单外偏差不再打断。
- ADR-0019 决策 2 改为"仅冲突或 focused checks 失败时派 merger"；merger lane 与 `integration`
  output_mode 保留。
- 壳只声明 Action 由程序还是 coordinator 执行，不再写推进逻辑；未接入 Driver 的壳在接入前
  沿旧合同运行。
