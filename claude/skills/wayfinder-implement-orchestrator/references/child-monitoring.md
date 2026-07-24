# Terminal Fan-in 与 Listener Recovery

任何 Herdr child pane 创建前读取本文件。回传主通道是 lead-owned terminal listener；child
正文或自发 `WAKE` 不能作为唯一通道。

## Startup

1. 验证 pane 出现在 `herdr agent list`，且 workspace/tab、work item、cwd、branch 与
   dispatch packet 一致。
2. 按 `lane-registry.md` 写入 `created` 并 readback，再投递完整 packet。
3. 确认 agent 进入 `working` 后写入 `running`。
4. 为每个 pane 启动一个后台 listener；`lead-pane-id` 取当前 lead 的
   `HERDR_PANE_ID`，不得让 child 猜测：

   ```bash
   (
     if herdr agent wait <child-pane-id> \
          --until idle \
          --until done \
          --until blocked \
          --timeout 7200000; then
       herdr agent prompt <lead-pane-id> \
         'WAKE: <work-item> terminal <child-pane-id>'
     else
       herdr agent prompt <lead-pane-id> \
         'WAKE: <work-item> listener-timeout <child-pane-id>'
     fi
   ) &
   ```

5. listener 启动后把 `waiter_owner`、`waiter_attached_at` 和
   `waiter_state: attached` 写入 registry 并 readback。完成标准：每个 `running` child 都有
   pane ID、durable registry 和本 lead 挂载的 listener。

listener 的 WAKE 只负责唤醒。Herdr lifecycle、完整 final report、tracker 和 Git 才是证据。

## Terminal Readback

收到 WAKE，或 registry 恢复发现 pane 已 `done`/`blocked` 时：

1. 把 `waiter_state` 更新为 `terminal`。
2. 等待完整 report marker，避免 lifecycle 与终端输出的竞态：

   ```bash
   herdr pane wait-output \
     --match 'FINAL_REPORT_END' \
     --source recent-unwrapped \
     --lines 300 \
     --timeout 15000 \
     <child-pane-id>
   ```

3. 成功后只读取一次：

   ```bash
   herdr agent read <child-pane-id> \
     --source recent-unwrapped \
     --lines 300 \
     --format text
   ```

4. 只接受同一输出中的 `FINAL_REPORT_BEGIN` 到 `FINAL_REPORT_END`；验证 work item、状态、
   output coordinates、commit/checks、dirty state 和 blocker。
5. marker 等待超时时写入 `terminal_report_pending`，保留 pane；下次外部 wake 或新会话重新
   执行 Terminal Readback，不猜测结果、不重新实现。
6. report 验证成功后写入 `terminal`。implementation completed 进入集成；其他 gate/decision
   child 在持久 artifact readback 后写入 `consumed`。

## Integration Fan-in

- implementation completed：按 dependency topology 集成已验证 commit并运行 focused checks；
  成功后执行 `herdr-dispatch.md` 的“集成后关闭”。
- blocked：写入 `blocked`，只暂停对应 work item。
- gate/decision child consumed：关闭 pane并确认消失后写入 `closed`。
- 每次 terminal fan-in 后立即重算当前 frontier，不等待同批其他 children。

## Listener Recovery

- listener timeout 后查询一次 agent lifecycle。仍 `working` 时重新挂相同 listener并更新
  `waiter_attached_at`；已 terminal 时进入 Terminal Readback。
- 新会话对所有 `created`、`running`、`terminal_report_pending` registries 验证 pane/Git。
  running pane 无条件挂到新 lead listener，不相信旧 `waiter_state`。
- pane 消失但 Git/artifact 已存在时从持久证据继续 fan-in；坐标冲突时标 stale，确认没有
  active writer 后才能 replacement。
- ignored/replaced pane 的 WAKE 直接丢弃。
