#!/bin/bash
# Lane watcher:CLI/Herdr lane 的 canonical 完成信号探测。
# 轮询 worker pane 输出，见到 packet 合同要求的 `LANE_DONE <lane_id>` 单行标记后
# prompt Coordinator Pane 唤醒 fan-in；pane 异常消失或超时也会唤醒。
# 不用 `herdr agent wait --until done`:CLI agent 完成回合回到 idle 不会触发
# `done` 事件,listener 会永久阻塞。
# Usage: lane-watch.sh <worker_pane_id> <coordinator_pane_id> <lane_id> <lane_label>
set -u
PANE="$1"; COORD="$2"; LANE_ID="$3"; LABEL="$4"
export HERDR_ENV=1
DEADLINE=$(( $(date +%s) + 7200 ))

while [ "$(date +%s)" -lt "$DEADLINE" ]; do
  OUT=$(herdr pane read "$PANE" 2>/dev/null || true)
  if printf '%s' "$OUT" | grep -qF "LANE_DONE $LANE_ID"; then
    herdr agent prompt "$COORD" "WAKE: $LABEL 已完成(pane $PANE 输出出现 LANE_DONE $LANE_ID 标记)。请按 delivery-pipeline terminal fan-in:从 registry 与 Git 验证 lane $LANE_ID 的持久证据 → 按 output_mode 执行 Integration 或写 consumed → cleanup → 重算 ready frontier 并派发下一批 lane(每条新 lane 复用 scripts/lane-watch.sh 挂 watcher)。WAKE 只负责唤醒,证据以 Git、tracker、artifact 与 registry 为准。" >/dev/null 2>&1
    exit 0
  fi
  # pane 消失(异常关闭)也唤醒 coordinator 处理
  if ! herdr pane get "$PANE" >/dev/null 2>&1; then
    herdr agent prompt "$COORD" "WAKE: $LABEL 的 pane $PANE 已消失(异常)。请检查 registry 中 lane $LANE_ID 的 worktree/commit/dirty 证据并按 fan-in 或 blocked 处理。" >/dev/null 2>&1
    exit 0
  fi
  sleep 20
done
# timeout: wake coordinator to check manually
herdr agent prompt "$COORD" "WAKE: $LABEL watcher 超时(2h 未见 LANE_DONE $LANE_ID)。请人工检查 pane $PANE 与 registry 中 lane $LANE_ID 的状态。" >/dev/null 2>&1
exit 1
