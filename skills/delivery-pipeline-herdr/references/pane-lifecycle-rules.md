# Pane 生命周期规则

派发机制归 `scripts/dispatch.py`；其行为由 `scripts/dispatch_check.py` 锁定。本文件只记录
helper 之外仍需 coordinator 判断的规则。

## 拓扑

- Coordinator Pane 所在 tab 只调度；worker lane 落在容量管理的 worker tab `X`、`X-2`…，
  每个 worker tab 最多 4 pane（取代 ADR-0005 的一 lane 一 tab）。HITL lane 共用同一容量。
- pane label 是 work item 标题；agent name 由 lane_id 派生（lowercase alphanumeric + hyphens）。

## Terminal Signal 与 Watcher

worker 终态输出单行 `LANE_DONE <lane_id>`；dispatch 挂的 `scripts/lane-watch.sh` 探测后唤醒
Coordinator Pane，pane 消失或两小时超时也唤醒。不用 `herdr agent wait --until done`：CLI agent
回到 idle 不触发 `done` 事件，listener 会永久阻塞。watcher 按标记数量增量去重，陈旧标记不唤醒；
回归检查是 `scripts/lane_watch_check.py`。WAKE 只负责唤醒，完成证据在 Git、tracker 与 registry。
HITL lane 以用户完成信号为准。

手工重挂 watcher：

```bash
nohup "$SKILL_ROOT/scripts/lane-watch.sh" "$pane_id" "$coordinator_pane_id" "$lane_id" "$lane_label" \
  >/tmp/lane-watch-"$lane_id".log 2>&1 &
```

## 收尾

关闭本 lane pane；空 worker tab 保留供复用；保留 Coordinator Pane 与 Workspace。
