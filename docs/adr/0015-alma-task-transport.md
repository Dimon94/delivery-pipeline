# ADR-0015: Alma Task transport 壳

**Status:** Accepted
**Date:** 2026-10-28
**Decider:** User (Dimon；2026-10-28 对话中确认 direct-only 与 effort 只记请求)

## Context

用户要求新增 Alma 版本：Alma UI 会话当 coordinator，worker 用 Alma 内置 Task 子代理。
2026-10-28 在 Alma 内实测 Task 能力（task id 见 Evidence），结论与 Codex App 的原生 task
能力差异较大，不能照搬 `delivery-pipeline-codex-app` 的 staged 与 App-managed worktree 合同。

## Evidence（2026-10-28 实测）

| 能力 | 结果 | 证据 |
| --- | --- | --- |
| 模型参数 | `model: "<providerId>:<provider model id>"` 生效；错误 ID 在启动前直接失败 | `4f552452…` 自报 `claude-sonnet-4-6`；`006cd397…` 失败并列出可用 ID |
| effort 参数 | Task 无此参数；模型元数据有 `reasoningLevels`，但无派发入口 | Task schema |
| resume 上下文 | 复用同一 taskId，但**不保留**前序对话 | `fc3c7da2…` 第三轮回答"不记得"第一轮内容与 pwd |
| resume 换模型 | 传新 `model` 后自报仍为原模型；未观察到切换 | `4f552452…` 第二轮 |
| 工作目录 | 无 cwd 参数；子代理继承 coordinator cwd | `fc3c7da2…` pwd 等于 coordinator 目录 |
| 后台完成 | `run_in_background` + `TaskOutput(block)` 可取终态与输出；自动唤醒未单独观察 | `91264645…` |
| 文本标记可靠性 | worker 可能在真实完成前输出完成字样 | `91264645…` 输出自述 |

模型自报只是弱证据；resume 不保留上下文是强证据（无法复述第一轮工具输出）。

## Decision

1. 新增 peer Transport Shell `skills/delivery-pipeline-alma`，`agent: alma`，
   `runtime: alma-task`，`coordinator_runtime: alma-ui`。core 只枚举该 agent 值与 runtime
   marker，不引用壳内文件。
2. **只支持 direct。** resume 既不保留上下文也未证明能换模型，staged（起步 → checkpoint →
   同 session 续接）在 Alma 下没有原生接续能力。Alma 实例的 mode 必须 `kind: direct`；
   出现 staged 即校验失败，不退化为"新 Task 冒充续接"。
3. **effort 只记请求。** 配置仍要求非空 effort（schema 不变），但 Alma 无派发入口：registry
   写 `requested_effort`，`effort` readback 恒为 Unknown，不声称已落实。
4. **Execution Worktree 由 coordinator 创建**（与 Herdr 相同），不是 App-managed。packet 给出
   绝对路径，worker 所有命令显式指向该路径；fan-in 时 coordinator 核验 Source/Integration
   Worktree 无意外改动，有则 fail closed。
5. **完成判据以宿主状态为准。** `TaskOutput.status == completed` + 持久证据（Git/artifact/
   registry）才进入 fan-in；`LANE_DONE` 文本只作辅助定位，单独不构成完成。
6. 模型 readback 记 `model_evidence: self-report`（弱）；不把请求或自报当成已验证。

## Consequences

- 需要改：`model-config-schema.md`、`setup/scripts/model_config.py`（新增 alma transport）、
  `scripts/validate.py`（manifest 与 schema 不变量）、`CONTEXT.md`（Transport Shell 计数与
  agent 枚举）、README。
- 已写的壳草稿中 staged/resume 续接、App-managed worktree、effort 注入相关段落需删改。
- 若 Alma 日后提供带上下文的 resume 与 effort 参数，另立 ADR 放开 staged。
