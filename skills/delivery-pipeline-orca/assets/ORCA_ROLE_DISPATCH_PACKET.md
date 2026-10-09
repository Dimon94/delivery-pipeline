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

1. 执行公共模板的 Worker 共同行为。Task/Dispatch、心跳、ask、queued follow-up 与恰好一次的
   worker_done --outcome 按 native preamble 执行；报告正文使用公共终态模板。
2. 每次 orchestration send 后向 Coordinator terminal 发 `<lane_id> <信号类型>，请结算`
   的 terminal send --enter nudge；消息与 registry 是事实，nudge 失败保留发送结果并注明。
   question/escalation 绑定本 lane、Task/Dispatch、checkpoint 与 work item；ask timeout 沿
   原 message ID resume。共享 overlay 的 startup、settlement 与 cleanup 归 coordinator。
3. starting、取消、retry、response lost 或 restart 前读取 `../references/orca-recovery.md`；
   原生身份与停止状态 Unknown 时保留现场。中间 PREWALK_READY / WORKER_STOPPED 后结束本轮，
   不发最终 worker_done，不进入 terminal fan-in。
