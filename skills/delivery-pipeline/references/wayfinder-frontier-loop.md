# Wayfinder Frontier Loop

当 discovery gate 使用 wayfinder map issue 时读取本文件。

## 循环

1. 用户启动或恢复 named map 时，在 map registry 持久化
   `map_run_authority: canonical_tracker_transitions`。读取 map issue 的低分辨率 index：Destination、Notes、Decisions-so-far、
   Not yet specified、Out of scope，并读取本 repo 的 Wayfinding operations。
2. 查询 `open`、未被 native blocking 阻塞、且没有 assignee 的 child issues；
   不要从 map 正文推断 open tickets。
   同时查询 open 但仍被 blocking 阻塞或已 assigned 的 in-scope child issues，用来判断
   discovery 是否真的完成。
3. AFK discovery 的 `Research` 和可自动执行且只为 decision 清障的 `Task` 进入 ready
   frontier；按 `frontier-lanes.md` 选择 maximal safe batch，用
   `WAYFINDER_TICKET_DISPATCH_PACKET.md` 通过 `Agent` tool 自动创建并行 subagents。
   `Research` subagent 必须走 `research` owner 路线并返回 `research/<name>` branch +
   Markdown context pointer；不得统一改走 `$wayfinder`。已 assigned 的 research ticket 不在
   frontier 内，先读回 owner 坐标，不重复派发。
   `Prototype`、`Grilling` 和 HITL `Task` 必须有真人参与；按当前调度运行时创建 user-visible
   Codex App task 或 Claude pane。没有可参与的用户 task/pane 时，生成对应 prompt/worker
   坐标并停止为 `ask-user`。
4. AFK workers 由系统 terminal signal 唤醒；Herdr HITL lane 写 `awaiting_human` 后 coordinator
   立即 yield，由用户完成会话并回到 Codex App 报告，不读 routine progress。
5. 任一 worker terminal 或用户完成信号到达后，按 `frontier-lanes.md` 消费持久证据，再用 Map Run
   Authority 执行一个 tracker transaction：先取一次 affected issues snapshot；同一 dependency layer 的
   独立 writes 并行，只有新 issue ID、resolution-before-close 等真实依赖才进入下一层；每个 dependency
   layer 一次聚合 readback，统一核对 expected/actual。事务覆盖 resolution comment、关闭 child、
   Decisions-so-far / Out of scope gist、dependency blocker 和 owner contract 明确要求的 follow-up
   decision ticket。Map Run Authority 随 packet 进入 worker，不把 canonical tracker scope 降级为 read-only；
   coordinator 聚合核验并幂等补齐缺口。同一 turn 不重复 Nowledge 或 contract lookup，不逐项播报 routine success；并发改写或
   越界 scope 写 `Unknown` 并 fail closed。不把文档漂移修复放在发布/派发 critical path；记录 follow-up
   后继续 canonical transaction。
6. 重读 map issue 的 Destination、Decisions-so-far、Not yet specified、Out of scope 和 frontier query，
   自动派发新 ready work，不等待用户回复“继续”。
7. 只要还有新的 open、未阻塞且 unassigned 的 discovery child issues，就从第 1 步重复。

## 停止

出现以下情况时停止 frontier loop：

- map issue 没有任何 open in-scope Wayfinder child issues，且没有阻塞交付的
  in-scope Not yet specified fog；停止后回到 coordinator 并进入 `spec` gate；
- frontier query 为 0，但仍有 open blocked child issues；这不是 route 条件，停在
  discovery 的 blocked/waiting 状态，列出阻塞票和前置票；
- child 报告 `ask-user`、`blocked` 或 `Unknown`；
- Herdr HITL lane 已 `awaiting_human`；这是成功 handoff，用户返回后从第 5 步继续；
- 两个 tasks 编辑了同一个 child issue，或留下冲突 tracker state。

对非判断类 tickets，`Agent` tool 可用时自动并发派发为后台 subagents；不可用时输出所有
ready work 的 durable briefs，coordinator 不亲自执行任何 work item。

coordinator 负责 frontier、fan-in 和下一 gate；subagents 不进入 `$to-spec`、
`$to-tickets` 或 `$implement`。
