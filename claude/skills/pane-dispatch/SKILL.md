---
name: pane-dispatch
description: Dispatch work to verified Herdr panes (Claude or Codex) with placement validation, capacity management, and lifecycle pairing
---

# Pane Dispatch

接收已填好的 dispatch packet，创建或定位目标 Herdr pane，投递 packet，验证落点，挂载 listener，回报坐标。服务 Claude 和 Codex 两种 agent kind。

## 职责边界

**这个 skill 做的事**：
- 解析/创建目标 workspace（按 map key 匹配）
- 解析/创建目标 tab（按类型字母 + 容量 <4）
- 创建 pane（复用默认 pane 或 split 既有 pane）
- 启动 agent（`--kind claude` 或 `--kind codex`）
- 投递 packet（写文件 + 单行引用 + working 确认）
- Rename pane + 同步 tab label（lifecycle 配对）
- 验证落点（`herdr pane get` 确认 workspace/tab 匹配）
- 挂载 listener（`herdr agent wait` 后台进程）
- 回报坐标（workspace/tab/pane IDs）

**这个 skill 不做的事**：
- Maximal safe batch 计算（归编排层）
- Worktree 创建（归编排层）
- Terminal readback、final report 解析、集成（归编排层）
- Tracker URL 拼接（调用方在 packet 里提供完整 URL）

**完成标准**：pane 已创建、坐标已验证、packet 已投递、agent 已 working、listener 已挂载。`agent_status=done` 的解释权归编排层；本 skill 只负责机械落地。

## 调用形式

```bash
/pane-dispatch \
  --kind <claude|codex> \
  --tab-type <G|X|P|R|D> \
  --workspace-key <map-key> \
  --packet-file <path-to-filled-packet> \
  --cwd <worktree-path> \
  --pane-label <label> \
  [--lead-pane-id <id>]
```

参数说明：
- `--kind`：agent 引擎（claude | codex）
- `--tab-type`：tab 类型字母（G=grilling/规划、X=execution、P=prototype、R=review、D=debug）
- `--workspace-key`：map 标识（如 `#86`），用于匹配或创建 workspace
- `--packet-file`：已填好的 dispatch packet 文件路径
- `--cwd`：pane 工作目录（通常是 worktree 路径）
- `--pane-label`：pane 名称（如 `#957 ImageLightbox组件`）
- `--lead-pane-id`：可选，lead pane ID，用于 Claude pane 的回信地址块

参考 `references/pane-placement-rules.md` 了解 workspace/tab/pane 三层模型、tab 容量规则和 lifecycle 配对机制。

## Agent Kind 绑定

`--kind` 参数必须显式提供，且必须与 tab-type 兼容：

| Tab Type | 允许的 Kind |
|---|---|
| G（grilling/规划） | claude only |
| P（prototype） | claude only |
| R（review） | claude only |
| D（debug） | claude only |
| X（execution） | claude or codex |

**Fail-closed 原则**：
- `--kind` 缺失 → 拒绝派发并报错
- Tab-kind 组合非法 → 拒绝派发并报错

## 生命周期规则

投递机制、agent 启动命令、落点验证、listener 挂载和 lifecycle 配对见 `references/pane-lifecycle-rules.md`。
本 skill 不再内联这些命令块；修改生命周期规则只动该 reference。

## Workspace 解析

1. 运行 `herdr workspace list`，查找 label 包含 map key 的 workspace
2. 命中 → 使用该 workspace ID
3. 无命中 → 创建新 workspace：
   ```bash
   herdr workspace create --label "<map-label>" --cwd <repo-root> --no-focus
   ```
4. 记录返回的 `workspace_id` 和默认 pane ID（需复用）

## Tab 容量管理

每个 tab 最多 **4 个并发 pane**。优先填充现有 tab，满员后创建新 tab。

**解析目标 tab**：
1. `herdr tab list --workspace <workspace_id>`，找 label 以 `<字母>-` 开头的 tabs
2. 对每个候选 tab，`herdr pane list --tab <tab_id>` 统计 pane 数量
3. 找到第一个 pane 数 < 4 的 tab → 使用该 tab
4. 无候选或全部满员 → 创建新 tab：
   ```bash
   herdr tab create --workspace <workspace_id> --no-focus
   ```
5. 新 tab 会产生一个默认空 pane，**必须复用为第一个 worker**（见下节）

**Tab label 格式**：
- Design tabs：`<字母>-#<issue1>·#<issue2>·...`（如 `G-#42·#43`）
- Execution tabs：`X-#<issue1>·#<issue2>·...`（如 `X-#957·#958`）

## 复用默认 Pane

`herdr workspace create` 和 `herdr tab create` 会产生默认空 shell pane。**必须复用为第一个 worker**，不要闲置。

**新建 workspace 时**：
```bash
create_result=$(herdr workspace create --label "$map_label" --cwd "$repo_root" --no-focus)
workspace_id=$(echo "$create_result" | jq -r '.result.workspace.workspace_id')
default_pane=$(echo "$create_result" | jq -r '.result.root_pane.pane_id')
# 把 default_pane 用作第一个 worker，启动 agent
```

**新建 tab 时**：
```bash
create_result=$(herdr tab create --workspace "$workspace_id" --no-focus)
tab_id=$(echo "$create_result" | jq -r '.result.tab.tab_id')
default_pane=$(echo "$create_result" | jq -r '.result.root_pane.pane_id')
# 把 default_pane 用作第一个 worker
```

**添加到现有 tab**（pane 数 < 4）：
```bash
existing_pane=$(herdr pane list --tab "$tab_id" | jq -r '.result.panes[0].pane_id')
split_result=$(herdr pane split --pane "$existing_pane" --direction right --ratio 0.5 --no-focus)
new_pane=$(echo "$split_result" | jq -r '.result.pane.pane_id')
```

Split 方向：宽 pane 用 `right`，窄或高 pane 用 `down`。避免重复同方向 split。

## 原子派发序列

每个 pane 必须走完这个序列才能开始下一个：

1. **解析或创建 target tab**（见上节"Tab 容量管理"）
2. **获取可用 pane**（复用默认 pane 或 split）
3. **启动 agent**（见 `references/pane-lifecycle-rules.md`"Agent 启动命令"）
4. **投递 packet**（见 `references/pane-lifecycle-rules.md`"投递机制"）
5. **Rename pane**：
   ```bash
   herdr pane rename "$pane_id" "$pane_label"
   ```
6. **同步 tab label**（追加 issue 编号）：
   ```bash
   current_label=$(herdr tab get "$tab_id" | jq -r '.result.tab.label // ""')
   if [[ -z "$current_label" || "$current_label" == "null" ]]; then
     new_label="<字母>-#<issue>"
   else
     new_label="${current_label}·#<issue>"
   fi
   herdr tab rename "$tab_id" "$new_label"
   ```
7. **验证落点**（见 `references/pane-lifecycle-rules.md`"落点验证"）
8. **挂载 listener**（见 `references/pane-lifecycle-rules.md`"Listener 挂载"）
9. **回报坐标**

**失败隔离**：某个 pane 的原子序列失败（即使重试后），标记为 skipped，继续其他 panes。

## 输出格式

派发成功时回报：
```json
{
  "status": "dispatched",
  "workspace_id": "w48",
  "workspace_label": "派发通道确认 #86",
  "tab_id": "w48:t3",
  "tab_label": "G-#42",
  "pane_id": "w48:p8",
  "pane_label": "#42 极短摘要",
  "agent_name": "grilling-42",
  "listener_pid": 12345
}
```

派发失败时回报：
```json
{
  "status": "setup_blocked",
  "issue": "#42",
  "reason": "placement verification failed twice",
  "last_coords": {"workspace": "w48", "tab": "w48:t3", "pane": "w48:p9"}
}
```

## 错误处理

- **No workspace matches map key**：创建新 workspace（不 fail）
- **All tabs full**：创建新 tab（不 fail）
- **Placement verification failed twice**：标记 `setup_blocked`，log 详细坐标，继续其他 panes
- **Agent startup timeout**：标记 `setup_blocked`，关闭 pane，继续其他 panes
- **JSON parse error**：写到文件后用 Python 解析，fallback 到 jq

**Partial success is valid**：batch 中 3/5 panes 成功派发，2/5 skipped，仍然算成功，回报两份清单。

## 防御性模式

**JSON 解析**：
```bash
result=$(herdr ... 2>&1)
if echo "$result" | jq -e '.error' > /dev/null 2>&1; then
  error_msg=$(echo "$result" | jq -r '.error.message')
  echo "ERROR: $error_msg"
  exit 1
fi
pane_id=$(echo "$result" | jq -r '.result.pane.pane_id // ""')
if [ -z "$pane_id" ]; then
  echo "ERROR: pane_id not found"
  exit 1
fi
```

**Agent 命名**：lowercase letters/digits/hyphens only，如 `codex-957`，不用 `L1(#957)` 或 `Codex-L1`。

**Tab label 初始化**：handle numeric-only initial labels（herdr 默认）：
```bash
if [[ -z "$current_label" || "$current_label" == "null" || "$current_label" =~ ^[0-9]+$ ]]; then
  new_label="<字母>-#${issue}"
else
  new_label="${current_label}·#${issue}"
fi
```

## 参考

- `references/pane-placement-rules.md` — Space/tab/pane 三层模型、tab 字母、容量规则
- `references/pane-lifecycle-rules.md` — 投递机制、落点验证、lifecycle 配对、listener 挂载前提
