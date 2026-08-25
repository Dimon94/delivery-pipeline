# Pane 生命周期规则

投递机制、落点验证、Working 确认、lifecycle 配对与 listener 前提的唯一定义点。
Agent/Model/Effort 启动参数由 `model-role-routing.md` 的 adapter 提供。

## 批级并发序列

1. **批级前置（唯一串行段）**：从 Coordinator Pane caller context 解析并 readback Herdr
   session/workspace/tab/pane；只有用户显式要求时才把新 Workspace 作为目标。
2. **并发段 A**：每条新 lane 默认在目标 Workspace 新建 tab，使用
   `--cwd <Execution Worktree>` 并保持 `--no-focus`，随后验证返回的 root pane 落点。
3. **并发段 B**：按配置并发 agent start + packet 投递；投递不阻塞。
4. **记账段**：rename pane + sync tab label，与 agent 冷启动重叠。
5. **聚合 Working 确认**：并行等待各 agent working；单项失败独立隔离。
6. **Listener + 聚合 readback**：确认 working 后挂 listener，聚合 registry readback，到达
   Dispatch Handoff。

## 投递

Packet 已写入文件，只投递单行绝对路径引用：

```bash
herdr agent prompt "$agent_name" "完整读取 $packet_file 并严格按其中全部指令执行。"
```

不带 `--wait`。失败时 get/read 一次、重试一次；仍失败写 `setup_blocked`。不用裸
`pane send-text` + Enter 投递多行文本。

## Agent 启动

从 registry readback 的 agent/model/effort 构造命令；不得用 skill 内默认值：

```bash
# pi
herdr agent start "$agent_name" --kind pi --pane "$pane_id" -- \
  --approve --model "$model" --thinking "$effort"

# Codex CLI
herdr agent start "$agent_name" --kind codex --pane "$pane_id" -- \
  --model "$model" -c "model_reasoning_effort=\"$effort\"" \
  -s danger-full-access -a never

# Claude CLI
herdr agent start "$agent_name" --kind claude --pane "$pane_id" -- \
  --model "$model" --effort "$effort" --dangerously-skip-permissions
```

`agent start` 不支持 `--cwd`；cwd 在 pane split/create 时绑定。shell 未就绪时先等待
`agent_status` 非 unknown。Agent name 使用 lowercase alphanumeric + hyphens。

## 落点验证

默认拓扑是一 lane一 tab：

```bash
herdr tab create --workspace "$workspace_id" --cwd "$execution_worktree" \
  --label "$lane_label" --no-focus
```

从返回值读取真实 tab/pane ID，再执行 `herdr pane get "$pane_id"`；断言 workspace_id、tab_id 与
目标一致，且 coordinator pane 不作为 worker pane。用户显式要求新 Workspace 时，创建响应的
root pane可承载首条 lane，其余 lane仍新建 tab。落点错误时关闭本 lane tab/pane并用显式
workspace/tab重试一次；第二次失败写 `setup_blocked`，继续 siblings。

## Working 确认

记账段完成后聚合执行：

```bash
herdr agent wait "$agent_name" --until working --timeout 15000
```

失败时 get/read 一次、重投 packet 一次、再确认一次；仍失败执行 close + label 对账并写
`setup_blocked`。确认前不挂 listener。

## Listener

```bash
(
  herdr agent wait "$pane_id" --until done --timeout 7200000
  if [ -n "$lead_pane_id" ]; then
    herdr agent prompt "$lead_pane_id" "WAKE: $pane_label done"
  fi
) &
```

WAKE 只负责唤醒；Git、tracker、artifact 与 registry 承载完成证据。默认 timeout 两小时；
不建立固定轮询。

## Lifecycle 配对

派发：tab/pane create → placement verify → start → non-blocking prompt → rename/label → aggregate
working → listener。收尾：关闭本 lane pane/tab；保留 Coordinator Pane与承载 Workspace。
startup/fan-in/watchdog 只做一次 bounded pane 对账。
