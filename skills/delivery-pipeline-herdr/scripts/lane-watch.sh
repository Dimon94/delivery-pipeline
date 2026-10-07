#!/bin/bash
# Lane watcher:CLI/Herdr lane 的 canonical 完成信号探测。
# 轮询 worker pane 输出，见到 packet 合同要求的 `LANE_DONE <lane_id>` 单行标记后
# prompt Coordinator Pane 唤醒 fan-in；pane 异常消失或超时也会唤醒。
# 不用 `herdr agent wait --until done`:CLI agent 完成回合回到 idle 不会触发
# `done` 事件,listener 会永久阻塞。
# Usage: lane-watch.sh <worker_pane_id> <coordinator_pane_id> <lane_id> <lane_label> [timeout_hours=2]
set -u
PANE="$1"; COORD="$2"; LANE_ID="$3"; LABEL="$4"; TIMEOUT_H="${5:-2}"
export HERDR_ENV=1
DEADLINE=$(( $(date +%s) + TIMEOUT_H*3600 ))
SEEN_PREWALK=''
PENDING_PREWALK=''

while [ "$(date +%s)" -lt "$DEADLINE" ]; do
  # jsonl 主通道（map#765 实证：屏扫只取可视区，LANE_DONE 滚出后 100% 错过；session jsonl 是 ground truth）
  JSONL=$(herdr pane get "$PANE" 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin).get("result",{}).get("pane",{}).get("agent_session",{}).get("value",""))' 2>/dev/null || true)
  # map#1262 实证修复：jsonl 通道必须只数 assistant 输出的真实 marker；packet 投递回显的
  # toolResult 含 LANE_DONE 字样（指令原文）曾致两次 false-positive WAKE。
  # map#1262 codex lane 实证：rollout jsonl 是 response_item/message/output_text 结构，
  # pi 格式解析全漏（4 条 lane PREWALK/LANE_DONE 未捕获）；这里同时支持两种格式，
  # 输出匹配到的完整 marker 行（每行一条），由 shell 统一走去重与唤醒。
  MARKERS=$(
  if [ -n "$JSONL" ] && [ -f "$JSONL" ]; then python3 -c '
import json,sys
lane=sys.argv[2]
for line in open(sys.argv[1]):
    try: d=json.loads(line)
    except Exception: continue
    texts=[]
    if d.get("type")=="message" and d.get("message",{}).get("role")=="assistant":
        for p in d["message"].get("content",[]):
            if isinstance(p,dict) and p.get("text"): texts.append(p["text"])
    elif d.get("type")=="response_item":
        it=d.get("payload",{})
        if it.get("type")=="message" and it.get("role")=="assistant":
            for c in it.get("content",[]):
                if isinstance(c,dict) and c.get("type")=="output_text" and c.get("text"):
                    texts.append(c["text"])
    for t in texts:
        for ln in t.splitlines():
            ln=ln.strip()
            if ln=="LANE_DONE "+lane or ln.startswith("PREWALK_READY "+lane+" /"):
                print(ln)
' "$JSONL" "$LANE_ID" 2>/dev/null; fi)
  DONE_FIRED="/tmp/lane-watch-fired-${LANE_ID}-done"
  if printf '%s\n' "$MARKERS" | grep -qxF "LANE_DONE $LANE_ID" && [ ! -f "$DONE_FIRED" ]; then
    touch "$DONE_FIRED"
    herdr agent prompt "$COORD" "WAKE: $LABEL 已完成(session jsonl 实证 LANE_DONE $LANE_ID)。请按 delivery-pipeline terminal fan-in:从 registry 与 Git 验证 lane $LANE_ID 的持久证据 → 按 output_mode 执行 Integration 或写 consumed → cleanup → 重算 ready frontier 并派发下一批 lane。WAKE 只负责唤醒,证据以 Git、tracker、artifact 与 registry 为准。" >/dev/null 2>&1
    exit 0
  fi
  # --source visible 只取当前屏幕，避免匹配到已滚动走的历史回显（packet 指令文本本身含 LANE_DONE 字样，曾致两次误报）
  OUT=$(herdr pane read "$PANE" --source visible 2>/dev/null || true)
  # 按完整行和字面 lane ID 匹配；路径保留空格，artifact 内容由 coordinator 核验。
  while IFS= read -r LINE; do
    # 去掉 TUI 行首缩进；保留 marker/path 内容，供精确匹配与去重。
    LINE="${LINE#"${LINE%%[![:space:]]*}"}"
    case "$LINE" in
      "PREWALK_READY $LANE_ID /"*)
        if ! printf '%s\n' "$SEEN_PREWALK" | grep -qxF -- "$LINE" &&
           ! printf '%s\n' "$PENDING_PREWALK" | grep -qxF -- "$LINE"; then
          PENDING_PREWALK="${PENDING_PREWALK}${LINE}
"
        fi
        ;;
    esac
  done <<< "$OUT"
  # jsonl 通道检出的 PREWALK（含 codex rollout）同样走去重队列
  while IFS= read -r LINE; do
    case "$LINE" in
      "PREWALK_READY $LANE_ID /"*)
        if ! printf '%s\n' "$SEEN_PREWALK" | grep -qxF -- "$LINE" &&
           ! printf '%s\n' "$PENDING_PREWALK" | grep -qxF -- "$LINE"; then
          PENDING_PREWALK="${PENDING_PREWALK}${LINE}
"
        fi
        ;;
    esac
  done <<< "$MARKERS"
  while IFS= read -r LINE; do
    [ -n "$LINE" ] || continue
    # 持久去重（2026-09-27）：watcher 超时重挂后重扫 jsonl 会重报历史 PREWALK；
    # 以 lane+标记行哈希建档，跨进程只报一次。LANE_DONE 不在此列（进程见到即退出）。
    LINE_KEY=$(printf '%s' "$LINE" | shasum | cut -c1-16)
    FIRED="/tmp/lane-watch-fired-${LANE_ID}-${LINE_KEY}"
    if [ ! -f "$FIRED" ] && ! printf '%s\n' "$SEEN_PREWALK" | grep -qxF -- "$LINE" &&
       herdr agent prompt "$COORD" "WAKE: $LABEL 的 pane $PANE 输出阶段标记：${LINE}。请仅核验 checkpoint 与原 runtime 停止证据；此信号不证明已停止或完成，不授权接续、fan-in、Integration 或 cleanup。watcher 继续监听 LANE_DONE。" >/dev/null 2>&1; then
      touch "$FIRED"
      SEEN_PREWALK="${SEEN_PREWALK}${LINE}
"
    fi
  done <<< "$PENDING_PREWALK"
  # 行首锚定匹配单行标记，防止 worker 计划/回显文本中的子串误报（曾致 false-positive WAKE）
  if printf '%s\n' "$OUT" | grep -qE "^[[:space:]]*LANE_DONE ${LANE_ID}([[:space:]]|$)"; then
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
herdr agent prompt "$COORD" "WAKE: $LABEL watcher 超时(${TIMEOUT_H}h 未见 LANE_DONE $LANE_ID)。请人工检查 pane $PANE 与 registry 中 lane $LANE_ID 的状态。" >/dev/null 2>&1
exit 1
