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

## 正式 review 同轮恢复

`dispatch.py --recover-review --registry <原 Registry> --lane <原 lane> --request-id <原 request>`
只读原 plan、Herdr startup intent/receipt；可加 `--review-ledger <原 Review Budget>` 读取已记录
轴结果、findings 与终态。无需 config/catalog/当前能力文件，不调用 Herdr、不投递 prompt。
`inspect_original` 表示原响应 Unknown，只能沿原坐标对账；`recover_original` 表示恢复已有
请求，仍不得重发；`stop` 表示取消、失败或已有终态；`fan_in_recorded` 只返回原 FIX 结果，
本票不创建下一轮计划。原生取消由 coordinator 在原 session 执行，保留结果文件、草稿与
findings；取消尝试不计完成轮次。已完成轴只恢复原结果，禁止为补并行再启动同一轴。
resolved owner 必须在原结果文件保留每个已完成轴；尚未 fan-in 的结果由该 owner 读取，
不能把文件缺失推断为“未执行”。外部 owner 接口能力不足时报告 Root，不能盲目重跑。

公开检查：`python3 skills/delivery-pipeline-herdr/scripts/check_review_dispatch.py --case same-round-recovery`。
known agent/model/applied effort mismatch 复用 DD510 规则阻断放行，保留 finding；Unknown
不单独阻断。启动后失败不进入 work replacement，配置变化不改变原计划。
