# Terminal Fan-in 与 Subagent Recovery

任何 discovery child subagent 派发前读取本文件。discovery AFK tickets（research、task）通过
`Agent` tool 以后台 subagent 派发（`run_in_background: true`）。

Implementation lanes 的 fan-in 规则见 `frontier-lanes.md` § Terminal Fan-in。

## Herdr HITL Handoff

Herdr HITL startup terminal 与 yield 只由 `dispatch-runtime-routing.md` 定义；用户完成信号后的证据
消费、Integration 和自动续派只由 `frontier-lanes.md` 定义。本文件不复制这两个状态机。

## Startup

1. 填写 `WAYFINDER_TICKET_DISPATCH_PACKET.md` 模板作为 prompt。
2. 调用 `Agent` tool：`description` = ticket title、`prompt` = 填写后的 packet、
   `run_in_background: true`、`name` = `research-<ticket-number>` 或 `task-<ticket-number>`。
3. 写入 `created` → `running` registry 并 readback。

完成标准：每个 running child 都有 durable registry 和 `agent_name`。

无需 listener 挂载——`Agent` tool 完成时系统自动推送通知给 lead 会话。

## Terminal Fan-in

- `Agent` tool 完成通知到达后，从返回 result 读取 final report 一次；
  验证 `FINAL_REPORT_BEGIN` … `FINAL_REPORT_END` markers。
- 验证 status、commit、branch、artifact 和 blocker。
- completed 写入 `terminal` → `consumed` → `closed`。
- blocked 只暂停自身。
- fan-in 后立即重算 frontier，不等待同批其他 children。

## Recovery

- subagent 完成状态无法跨会话恢复。新会话读取所有 `running` registries 时：
  检查 branch/artifact 是否存在；存在则从持久证据继续 fan-in；不存在则标 `blocked`
  并由 lead 决定是否重新派发。
- 全部 lanes terminal 且 frontier 为空后 durable registry 保留。
