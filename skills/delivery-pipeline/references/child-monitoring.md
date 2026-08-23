# Terminal Fan-in 与 Subagent Recovery

任何 discovery child subagent 派发前读取本文件。discovery AFK tickets（research、task）通过
`Agent` tool 以后台 subagent 派发（`run_in_background: true`）。

Implementation lanes 的 fan-in 规则见 `frontier-lanes.md` § Terminal Fan-in。

## Herdr HITL Handoff

Herdr HITL pane 由 `dispatch-runtime-routing.md` 完成 bootstrap。首个范围内业务问题证明 packet 已
消费；coordinator 用 packet、registry 和现有输出核对坐标，scrollback 缺失字段记为 `Unknown`，
不补发 readback。registry 写 `state: awaiting_human` 后，coordinator 立即 yield 并向用户回报
session/workspace/tab/pane 坐标。运行期由用户在 Herdr 直接回答 worker；此状态不创建 listener，
不调用 `herdr agent wait`，不读取 routine progress。

用户回到 Codex App 报告完成后，coordinator 读取 pane final report 一次，验证 tracker/artifact/Git，
再写 `terminal` → `consumed` 并重算 frontier。用户尚未返回时，`awaiting_human` 是正常终点，
不是 blocker 或 setup failure。

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
