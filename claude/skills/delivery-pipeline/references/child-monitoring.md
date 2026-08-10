# Terminal Fan-in 与 Listener Recovery

任何 child 派发前读取本文件。child panes 的创建、投递、等待和关闭通过
`/pane-dispatch` skill 执行。child subagents 的派发通过 `Agent` tool 执行（`run_in_background: true`）。
本文件规定两种 runtime 的 terminal fan-in 和恢复规则。

## Startup — Subagent (runtime: subagent)

1. 填写 `WAYFINDER_TICKET_DISPATCH_PACKET.md` 模板作为 prompt。
2. 调用 `Agent` tool：`description` = ticket title、`prompt` = 填写后的 packet、
   `run_in_background: true`、`name` = `research-<ticket-number>` 或 `task-<ticket-number>`。
3. 按 `lane-registry.md` 写入 `created` → `running` 状态转换并 readback。

完成标准：registry 已写入 `running`，`agent_name` 已记录。

无需 listener 挂载——`Agent` tool 完成时系统自动推送通知给 lead 会话。

## Startup — Pane (runtime: herdr-*)

1. 通过 `/pane-dispatch` skill 创建 pane 并启动 agent，传入 worktree cwd、issue 标识和 packet。
2. `/pane-dispatch` skill 会落地 pane/tab、启动 agent、投递 packet、重命名并验证 startup probe。
3. 按 `lane-registry.md` 写入 `created` → `running` 状态转换并 readback。
4. 通过 `/pane-dispatch` skill 为每个 running child pane 挂 lead-owned listener（`agent wait`）。

完成标准：每个 running child 都有 pane ID、durable registry 和本 lead 挂载的 listener。

listener 的 WAKE 只负责唤醒。final report、tracker 和 Git 才是证据。

## Terminal Readback — Subagent

收到 `Agent` tool 完成通知时：

1. 把 registry `state` 更新为 `terminal`。
2. 从 Agent tool 返回的 result 中提取 final report（`FINAL_REPORT_BEGIN` …
   `FINAL_REPORT_END` markers）。
3. 验证 work item、状态、output coordinates、commit/checks 和 blocker。
4. report 验证成功后写入 `terminal`。decision child 在持久 artifact readback 后写入
   `consumed` → `closed`。

subagent 无需关闭 pane；`consumed` 后直接写 `closed`。

## Terminal Readback — Pane

收到 WAKE，或 registry 恢复发现 pane 已 `done`/`blocked` 时：

1. 把 `waiter_state` 更新为 `terminal`。
2. 通过 `/pane-dispatch` skill 等待 marker 并读取 final report。
3. 只接受同一输出中的 `FINAL_REPORT_BEGIN` 到 `FINAL_REPORT_END`；验证 work item、状态、
   output coordinates、commit/checks、dirty state 和 blocker。
4. marker 等待超时时写入 `terminal_report_pending`，保留 pane；下次外部 wake 或新会话重新
   执行 Terminal Readback，不猜测结果、不重新实现。
5. report 验证成功后写入 `terminal`。implementation completed 进入集成；其他 gate/decision
   child 在持久 artifact readback 后写入 `consumed`。

## Integration Fan-in

- implementation completed：按 dependency topology 集成已验证 commit并运行 focused checks；
  成功后通过 `/pane-dispatch` skill 关闭对应 pane。
- blocked：写入 `blocked`，只暂停对应 work item。
- gate/decision child consumed（pane runtime）：通过 `/pane-dispatch` skill 关闭 pane并确认消失后写入 `closed`。
- gate/decision child consumed（subagent runtime）：直接写入 `closed`。
- 每次 terminal fan-in 后立即重算当前 frontier，不等待同批其他 children。

## Listener Recovery — Pane only

- listener timeout 后查询一次 agent lifecycle。仍 `working` 时通过 `/pane-dispatch` skill 重新挂
  相同 listener并更新 `waiter_attached_at`；已 terminal 时进入 Terminal Readback。
- 新会话对所有 `created`、`running`、`terminal_report_pending` registries 验证 pane/Git。
  running pane 无条件通过 `/pane-dispatch` skill 挂到新 lead listener，不相信旧 `waiter_state`。
- pane 消失但 Git/artifact 已存在时从持久证据继续 fan-in；坐标冲突时标 stale，确认没有
  active writer 后才能 replacement。
- ignored/replaced pane 的 WAKE 直接丢弃。

Subagent lanes 不需要 listener recovery——完成通知绑定当前 lead 会话。跨会话恢复见
`lane-registry.md` Fresh-session Recovery § subagent。
