# Orca 本地 worker dispatch packet

派发、终态与恢复使用 `../../delivery-pipeline/references/lane-registry.md` §轻量交接的固定模板。
仅展开当前分支，输入省略不适用项；本壳只追加两个 transport 字段：

```text
Orca runtime/host/terminal：<native readback>
Coordinator terminal：<coordinator_terminal_handle>
```

coordinator 的 startup、settlement 与 cleanup 读取 `../references/orca-dispatch.md`，
Worker 合同只描述本 lane；冻结配置与完整 overlay 留在原 registry。

## Worker 执行

从本节进入；公共合同只读 lane-registry 的 Worker 共同行为与终态行，完整 owner 另读。
commit 加载 gate-state-machine 的实施前置检查；原生 preamble 的能力与授权核验始终保留。

1. 执行公共模板的 Worker 共同行为。Task/Dispatch、心跳、ask、queued follow-up 与恰好一次的
   worker_done --outcome 按 native preamble 执行；报告正文使用 lane-registry §终态行。
2. 每次 orchestration send 后向 Coordinator terminal 发 `<lane_id> <信号类型>，请结算`
   的 terminal send --enter nudge；消息与 registry 是事实，nudge 失败保留发送结果并注明。
   question/escalation 绑定本 lane、Task/Dispatch 与 work item；ask timeout 沿
   原 message ID resume。共享 overlay 的 startup、settlement 与 cleanup 归 coordinator。
3. 取消、retry、response lost 或 restart 前读取 `../references/orca-recovery.md`；
   原生身份与停止状态 Unknown 时保留现场。

## Whole-change verdict

只消费 `DP_REVIEW_PLAN` 中冻结的 `review_plan` 与 `owner_calls`；不重新读取配置选模型。
standards lane 启动身份不能替代双轴 executed；spec-only 只执行 spec。
每轴 requested 与 executed/applied effort 独立保存，无原生读回写 Unknown。
沿 `scripts/review_dispatch.py execution` 进入 canonical Review Budget/mismatch gate，
保留完整 findings；known 冲突阻断，无自动下一候选。同轮先 recover 原 Registry/
intent/receipt/已有轴结果，已完成轴不重跑；取消不换模型、不重复派发。
