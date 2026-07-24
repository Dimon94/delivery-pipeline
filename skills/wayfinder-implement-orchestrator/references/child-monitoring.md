# Terminal Fan-in 与 Listener Recovery

任何 child task 创建前读取本文件。回传主通道是 coordinator-owned `wait_threads`；child 的
`send_message_to_thread` 只提供低延迟唤醒。

## Startup

1. startup probe 验证 packet、work item、`Source owner projectId` 和独立 worktree。
2. `create_thread` 返回 `clientThreadId` 时先记录 pending coordinate；解析真实 thread ID 后
   写入 `created` registry 并 readback。
3. 确认 child 已收到 packet 后写入 `running`。
4. coordinator 对所有 running thread IDs 调用 `wait_threads`。保存返回 cursor；timeout 后用
   最新 cursor 继续 wait，不读取 routine progress。

完成标准：每个 running child 都有 durable thread ID、registry 和 coordinator-owned wait。

## Terminal Fan-in

- child final report 准备好后可发送
  `TERMINAL: <work-item> completed|blocked <一句原因>`；缺失此消息不影响 `wait_threads`
  检测 terminal。
- 任一通道唤醒后，用 `read_thread` 读取该 child 一次；final report、Git 和 tracker 才是
  证据。
- 验证 status、commit、checks、dirty state、touched files 和 blocker。
- completed 写入 `terminal`，按 dependency topology 集成并通过 focused checks 后写入
  `integrated`；blocked 只暂停自身。
- fan-in 后立即重算 frontier，不等待同批其他 children。

## Listener Recovery

- wait timeout 且 task 仍 running：保留 thread，用最新 cursor 继续 `wait_threads`。
- terminal signal 丢失：以 `wait_threads` terminal snapshot 为准进入 fan-in。
- pending setup、task 消失或工具 timeout：只检查目标 thread/Git 一次；证据存在时继续
  fan-in，否则按 startup replacement 规则处理。
- 新会话读取所有 `created`/`running` registries，验证 thread/Git 后重新调用
  `wait_threads`；确认没有 active writer 后才能 replacement。
- 全部 lanes terminal 且 frontier 为空后清除内存中的 cursors；durable registry 保留。
