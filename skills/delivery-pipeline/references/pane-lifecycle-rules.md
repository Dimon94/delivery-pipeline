# Pane 生命周期规则

投递机制、落点验证、lifecycle 配对和 listener 挂载前提的唯一定义点。
dispatch-runtime-routing 的 Herdr 章节引用本文件，不再内联命令块。

## 投递机制

Packet 已由调用方写入文件，只投单行引用指令，经 agent 面原子提交：

```bash
herdr agent prompt "$agent_name" "完整读取 $packet_file 并严格按其中全部指令执行。" --wait --until working --timeout 15000
```

`agent prompt` 原子提交 text + Enter 并遵守 pane 的 bracketed-paste；`--wait --until working` 兼作 startup 验证——返回成功即 agent 确认 working。

投递失败处理（`agent_blocked` / `agent_prompt_stalled` / timeout）：
1. `herdr agent get` + `herdr agent read` 查 pane 状态；首启设置页或权限 UI 用 `herdr agent send-keys <agent-name> esc` 清掉
2. 重试一次上面的 prompt
3. 仍失败 → 标记 `setup_blocked`，继续其他 lanes

不要用裸 `pane send-text` + `pane send-keys Enter` 投递：多行文本静默丢失，且首个 Enter 经常只聚焦不提交（文本滞留 composer，链路停摆）。

## Agent 启动命令

按 kind 分支：

**Claude pane**：
```bash
herdr agent start <agent-name> \
  --kind claude \
  --pane <pane-id> \
  --cwd <worktree-path> \
  --no-focus \
  -- --dangerously-skip-permissions
```

注：Claude pane 一律使用默认模型。

**Codex pane**：
```bash
herdr agent start <agent-name> \
  --kind codex \
  --pane <pane-id> \
  --cwd <worktree-path> \
  --no-focus \
  -- -s danger-full-access -a never
```

Agent 名字必须 lowercase alphanumeric + hyphens，格式如 `codex-957` 或 `grilling-42`。

## 落点验证

创建后立即验证：
```bash
pane_info=$(herdr pane get "$pane_id")
actual_ws=$(echo "$pane_info" | jq -r '.result.pane.workspace_id')
actual_tab=$(echo "$pane_info" | jq -r '.result.pane.tab_id')
```

断言：
- `actual_ws` == 目标 `workspace_id`
- `actual_tab` == 目标 `tab_id`

**落点不符时**：
1. `herdr pane close "$pane_id"` — 不留孤儿 pane
2. 用显式 `--workspace`/`--tab` 重试一次
3. 第二次仍失败 → 标记为 `setup_blocked`，log 坐标和 Herdr state，继续其他 lanes

**为什么验证**：裸 `herdr agent start` 或 `herdr pane split` 不带显式坐标时会落在用户聚焦的 pane（可能是别的 space）。显式坐标 + 验证防止静默错放。

## Listener 挂载

Claude pane 和 Codex pane 都挂 lead-side listener：

```bash
(
  herdr agent wait "$pane_id" --until done --timeout 7200000
  if [ -n "$lead_pane_id" ]; then
    herdr agent prompt "$lead_pane_id" "WAKE: $pane_label done"
  fi
) &
listener_pid=$!
```

**为什么后台**：Codex sandbox 可能拦 socket 访问，Codex pane 无法主动 `herdr agent prompt` 回 lead。Lead-side polling 是可靠的 terminal signal。

**挂载前提**：agent 已确认 `working`（投递步骤已保证）。idle 态挂 `agent wait --until done` 会立即返回假 WAKE。

**Timeout**：默认 2 小时（7200000ms）。

**WAKE 语义**：WAKE 只是唤醒信号，不承载完成证据。Lead 收到 WAKE 后读 pane 内的 final report 和真相源（Git、tracker），不认 WAKE 正文。

## Lifecycle 配对

Tab label 必须永远只反映**存活中**的 issue/lane。与 create+prompt 原子对同级强制：

**派发时**：
- 创建 pane → 投递 packet → rename pane → **sync tab label（追加 issue）**

**收尾时**（由编排层调用）：
- `herdr pane close <pane_id>` → **sync tab label（剔除 issue）** → 最后一个 pane 关闭时 tab 会自动消失，**不需要**手动 `herdr tab close`

**异常对账**：startup probe、terminal fan-in 或 watchdog 触发时，用 `herdr pane list` / `herdr pane get` 核对；不建立固定轮询。
