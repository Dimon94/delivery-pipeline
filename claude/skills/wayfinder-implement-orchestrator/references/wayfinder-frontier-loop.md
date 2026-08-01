# Wayfinder Frontier Loop

当 discovery gate 使用 wayfinder map issue 时读取本文件。

## 循环

1. 读取 map issue 的低分辨率 index：Destination、Notes、Decisions-so-far、
   Not yet specified、Out of scope，并读取本 repo 的 Wayfinding operations。
2. 查询 `open`、未被 native blocking 阻塞、且没有 assignee 的 child issues；
   不要从 map 正文推断 open tickets。
   同时查询 open 但仍被 blocking 阻塞或已 assigned 的 in-scope child issues，用来判断
   discovery 是否真的完成。
3. 从 ready frontier 选择没有 tracker-write 或 artifact-write 冲突的 maximal safe batch。
   自动派发 AFK `Research` 和只为 decision 清障的 `Task`，使用 `Agent` tool 与
   `WAYFINDER_TICKET_DISPATCH_PACKET.md` 作为 prompt；不需要用户先开启并发。
   `Research` subagent 必须走 `research` owner 路线并返回 `research/<name>` branch +
   Markdown context pointer；不得统一改走 `/wayfinder`。已 assigned 的 research ticket 不在
   frontier 内，先读回 owner 坐标，不重复派发。
   `Prototype`、`Grilling` 和 HITL `Task` 必须有真人参与；没有可参与的用户 pane 时，
   生成对应 prompt/worker 坐标并停止为 `ask-user`。
4. 派发后 subagent 在后台运行（`run_in_background: true`）；lead 进入
   `child-monitoring.md` 等待 Agent tool 完成通知；不读取 routine progress。
5. 每个 subagent 完成通知只读一次 final report，更新对应 ticket/artifact，然后重读 map 与
   frontier query；不等待同批全部 subagents。
6. 立即派发下一 maximal safe batch，直到 frontier 清空或只剩真正 blocked/HITL work。

## 停止

出现以下情况时停止 frontier loop：

- map issue 没有任何 open in-scope Wayfinder child issues，且没有阻塞交付的
  in-scope Not yet specified fog；停止后回到 lead 并进入 `spec` gate；
- frontier query 为 0，但仍有 open blocked child issues；这不是 route 条件，停在
  discovery 的 blocked/waiting 状态，列出阻塞票和前置票；
- 下一个 frontier child issue 是 `wayfinder:prototype`、`wayfinder:grilling`、
  HITL `wayfinder:task`，或需要实时用户判断；加载
  `assets/WAYFINDER_GRILLING_DISPATCH_PACKET.md`，输出一个用于完整 HITL 会话的
  已填写 prompt，然后等待 returned handoff 再继续。不要每个问题创建一个 prompt；
- worker 报告 `ask-user`、`blocked` 或 `Unknown` 时只暂停对应 item；若其他 ready work 存在则继续；
- 两个 worker panes 编辑了同一个 child issue，或留下冲突 tracker state。

对非判断类 tickets，copy-paste worker prompts 只是 `Agent` tool 不可用时的 fallback。
`Agent` tool 可用时通过后台 subagent 执行。

Lead 负责派发 subagents。worker subagent 可以建议后续 frontier，但不能自己派发
descendant subagents，也不能建议进入 `/to-spec`、`/to-tickets` 或 `/implement`。
