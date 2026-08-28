# Pane 生命周期规则

投递机制、落点验证、Working 确认、lifecycle 配对与 watcher 前提的唯一定义点。
Agent/Model/Effort 启动参数由 `model-role-routing.md` 的 adapter 提供。

## 批级并发序列

1. **批级前置（唯一串行段）**：从 Coordinator Pane caller context 解析并 readback Herdr
   session/workspace/tab/pane；只有用户显式要求时才把新 Workspace 作为目标。
2. **并发段 A**:按下方“拓扑与命名”的容量管理规则放置 lane pane:worker tab 内用
   `pane split`(`--cwd <Execution Worktree>`、`--no-focus`)落到未占用角落;新 worker tab
   用 `tab create` 并由 root pane 承载首条 lane;随后验证落点。
3. **并发段 B**：按配置并发 agent start + packet 投递；投递不阻塞。
4. **记账段**:rename pane 为 work item 标题 + 把编号并入 tab label,与 agent 冷启动重叠。
5. **聚合 Working 确认**：并行等待各 agent working；单项失败独立隔离。
6. **Watcher + 聚合 readback**：确认 working 后挂 lane watcher，聚合 registry readback，到达
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

Model/effort 只在该启动命令中绑定一次。之后不做 pane model 对账：运行中或 fan-in 发现 pane
实际 model 与 registry 不符（通常是用户改的），不构成 setup 失败，不重建 lane，不阻塞交付。

## 拓扑与命名

默认拓扑是容量管理的 worker tab,不是一 lane 一 tab(本规则取代 ADR-0005 的“每条 lane
独立 tab/pane”条款;current-workspace-first 前提不变):

- Coordinator Pane 所在 tab 不放 worker lane,它只承担调度。
- Worker tab 命名为 `X`,溢出依次 `X-2`、`X-3`;每个 worker tab 最多 4 pane。tab label
  跟踪活跃 work item 编号:`X-#391·#392`。
- HITL lane 与其他 lane 共用 X tab 容量；交互属性只决定 handoff state,不改变落点拓扑。
- pane label 使用 work item 标题;agent name 仍为 lowercase alphanumeric + hyphens。
- tab 内落点按 herdr 几何规则分布四角:先读 `herdr pane layout --pane "$anchor_pane_id"`,
  宽 pane 向右 split、窄或高 pane 向下 split,依次占满未占用角落;同 tab 第 5 条 lane 不再
  split,改开下一个 worker tab。

## 落点验证

tab 内新增 pane:

```bash
herdr pane split --pane "$anchor_pane_id" --direction "$direction" \
  --cwd "$execution_worktree" --no-focus
```

新 worker tab 的首条 lane:

```bash
herdr tab create --workspace "$workspace_id" --cwd "$execution_worktree" \
  --label "$tab_label" --no-focus
```

从返回值读取真实 tab/pane ID,再执行 `herdr pane get "$pane_id"`;断言 workspace_id、tab_id 与
目标一致,且 coordinator pane 不作为 worker pane。用户显式要求新 Workspace 时,创建响应的
root pane可承载首条 lane,其余 lane仍按容量规则放入 worker tab。落点错误时关闭本 lane
pane(新空 tab 一并关闭)并用显式 workspace/tab重试一次;第二次失败写 `setup_blocked`,
继续 siblings。

## Working 确认

记账段完成后聚合执行：

```bash
herdr agent wait "$agent_name" --until working --timeout 15000
```

失败时 get/read 一次、重投 packet 一次、再确认一次；仍失败执行 close + label 对账并写
`setup_blocked`。确认前不挂 watcher。

## Terminal Signal 与 Watcher

Terminal signal 的唯一 canonical 合同：worker 按 packet 要求在终态输出单行
`LANE_DONE <lane_id>` 标记，coordinator 侧 watcher 探测该标记后唤醒 Coordinator Pane。
不用 `herdr agent wait --until done`：CLI agent 完成回合回到 idle 不会触发 `done` 事件，
listener 会永久阻塞（pi lane 实测复现）。

聚合 working 确认后，为每条 lane 挂 watcher：

```bash
nohup "$SKILL_ROOT/scripts/lane-watch.sh" \
  "$pane_id" "$coordinator_pane_id" "$lane_id" "$lane_label" \
  >/tmp/lane-watch-"$lane_id".log 2>&1 &
```

watcher 每 20s 轮询 worker pane 输出，见到 `LANE_DONE <lane_id>` 立即 prompt Coordinator
Pane；pane 异常消失或两小时超时也会唤醒 coordinator 处理。HITL lane 的唤醒仍以用户完成
信号为准，watcher 只作 terminal 补充。WAKE 只负责唤醒；Git、tracker、artifact 与 registry
承载完成证据。

## Lifecycle 配对

派发:tab create/pane split → placement verify → start → non-blocking prompt → rename/label
→ aggregate working → watcher。收尾:关闭本 lane pane,从 X tab label 移除其编号;X tab 空后
label 还原为 `X`/`X-2` 并保留 tab 供后续 lane 复用;保留 Coordinator Pane与承载 Workspace。
startup/fan-in/watchdog 只做一次 bounded pane 对账。
