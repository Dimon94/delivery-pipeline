# Herdr 落点与布局：Space / Tab / Pane

只有在需要创建、补建或替换 Herdr worker panes 时才读取本文件。

## 术语与坐标

- Herdr UI 侧边栏的 "space" 就是 CLI 的 `workspace`；本文统一说 space。
- 每个 space 顶部可开多个 tab；pane 属于某个 tab。
- lead 自身坐标来自环境变量：`HERDR_WORKSPACE_ID`、`HERDR_TAB_ID`、`HERDR_PANE_ID`。

## 三层模型

| 层 | 对应什么 | 命名 |
|---|---|---|
| space | 一个 map/交付任务及其 integration target；lane worktree 由 pane cwd 隔离 | 地图主要内容 + 地图 issue 编号，如 `派发通道确认 #86` |
| tab | 一类会话的并发容器 | `LEAD` 或 `类型字母-编号·编号·…` |
| pane | design worker 或 execution lane | design：`#编号 极短摘要`；execution：`#编号 极短摘要` |

### 五类会话 tab

| 字母 | 类型 | 覆盖 |
|---|---|---|
| G | 拷问/规划 | grilling、spec 拷问、规划类 |
| X | 执行 | 实现票（claude 或 codex pane） |
| P | 原型 | prototype |
| R | 评审 | 集成评审、PR review |
| D | 诊断/调研 | debugging、research、证据收集 |

- 每个 space 的第一个 tab 固定命名 `LEAD`，由主编排者独占；lead 进场后先
  `herdr tab rename $HERDR_TAB_ID LEAD`。
- design tab label 格式：`D-#142·#143`；execution tab label 格式：`X-#957·#958`。label 只列存活
  issue 或 lane ID。
  超长被 UI 截断无妨；不加序号后缀，编号列表本身唯一。
- 每个类型 tab 最多 **4 个并发 pane**。第 5 个同类 work item 到来时新建同字母
  tab，不往满员 tab 里挤。
- 不做低水位合并：tab 各自然消亡，不用 `pane move` 把残留 pane 并回旧 tab。
- 阶段迁移：同一 issue 同时只允许一个 writer lane。read-only review 可并发，但必须用
  R pane 且不得写 lane worktree。

## 硬规则：落点必须显式

裸 `herdr pane split` 和裸 `herdr agent start`（不带 `--workspace`/`--tab`/`--pane`/
`--current`）的落点是**用户当前聚焦的 pane/space**，不是 lead 所在的 space，也不是
map 对应的 space。用户随时在切换视图，裸命令等于把 worker 派进随机位置。因此：

- 每条创建命令必须显式定位（`--workspace <id>` + `--tab <id>`，或 `--pane <id>`/`--current`）。
- 每条创建命令必须带 `--no-focus`，批量派发不许抢用户焦点。

## 解析目标 space

1. 确定 map key：优先 tracker 号形态，例如 `#608`。
2. 运行 `herdr workspace list`，在 labels 里找包含 map key 的 space。命中即用。
3. 无命中时：若 lead 自己 `HERDR_WORKSPACE_ID` 的 label 与当前 map 明确一致（且
   工作区/分支正确），直接用；否则创建
   `herdr workspace create --label "<map-label>" --cwd <repo-root> --no-focus`
   并记录返回的 `workspace_id`。
4. lead 正运行在哪个 space、用户正看着哪个 space，都不是派发依据；map key 匹配才是。
5. 所有 lanes 使用同一个 map space；每个 execution pane 的 `--cwd` 指向该 lane 的独立
   worktree。不要为了 lane 隔离另建 space，隔离边界是 pane cwd + worktree/branch。

## 解析目标 tab

1. 按 work item 类型确定字母（G/X/P/R/D）。
2. `herdr tab list --workspace <workspace_id>`，找 label 以该字母 + `-` 开头且存活 ID 数
   < 4 的 tab；命中即为目标 tab。
3. 无命中时创建：design 用 `<字母>-#<编号>`；execution 用 `X-#<编号>`。
   新 tab 自带一个默认空 pane，必须复用为第一个 worker（同下文"复用默认 pane"）。
4. 编号计数以 tab label 为准；label 与实际 pane 不符时先对账修正（见"生命周期配对"）。

## 生命周期配对（每次派发/收尾的强制动作）

tab label 必须永远只反映**存活中**的 issue/lane。与 create+prompt 原子对同级强制：

- **派发**：创建 pane → `agent prompt` 投递 → 按 design/execute 格式 rename →
  `herdr tab rename` 同步存活 issue/lane IDs。
- **收尾**：terminal fan-in 完成后 `pane close` → `tab rename`（剔除该 ID）→ 最后一个 pane 关闭时
  tab 会自动消失，**不需要**手动 `herdr tab close <tab_id>`。
- **异常对账**：只在 startup probe、terminal fan-in 或 watchdog 触发时，用 pane list/get 核对；
  不为布局建立固定轮询。
- space 内 panes 全部关闭、批次收尾后，`herdr workspace close <id>` 关闭空 space
  （lead 自己所在 space 除外）。

## 复用默认 pane（新建 workspace / tab 时必做）

`herdr workspace create` 和 `herdr tab create` 都会产生一个默认空 shell pane。
**必须把它复用为第一个 worker**，不要闲置——否则出现空 shell 白占 slot 且视觉混乱。

```bash
# 1. 取得默认 pane id（workspace 级同理；tab 级用 pane get 核对 tab_id）
default_pane=$(herdr pane list --workspace <workspace_id> | python3 -c "
import json,sys; panes=json.load(sys.stdin)['result']['panes']
print(panes[-1]['pane_id'])
")

# 2. 把默认 pane 变成第一个 worker
herdr pane rename "$default_pane" '<design #编号 | execution #编号> <极短摘要>'
herdr agent start '<agent-name>' --kind <kind> --pane "$default_pane" --cwd <path> --no-focus -- <args>
herdr agent prompt '<agent-name>' '<packet-reference-command>' --wait --until working --timeout 15000

# 3. tab rename + 验证落点（见下节）
```

## 标准创建命令（原子对：创建 + 投递 + 改名）

每个 worker 必须走完下面步骤再开始下一个 worker，不要批量建完再统一发 prompt。

```bash
# 1. 在目标 space + tab 创建 pane 并启动 worker agent
# (如果是新 workspace/tab，复用默认 pane；如果是既有 tab，split 既有 pane)

# 2. 投递 dispatch packet（写文件 + 单行引用 + working 确认；机制见 pane-dispatch SKILL.md"投递机制"）
herdr agent prompt <agent-name> "完整读取 <packet-file-path> 并严格按其中全部指令执行。" --wait --until working --timeout 15000

# 3. 同步 tab label（追加编号）
herdr tab rename <tab_id> '<字母>-<存活 issue 或 lane ID 列表>'

# 4. 验证落点（见下节）
```

## 回信地址与 WAKE 信号

worker pane 与 lead 共享同一个 Herdr server socket，可以反向发消息。派发 claude pane
时，每个 filled dispatch packet 末尾必须附加一个"回信地址"块，lead pane id 取自 lead
自己的 `$HERDR_PANE_ID`：

```text
回信地址（lead pane）：<lead 的 HERDR_PANE_ID>
求助规则：进入 blocked 或 completed 时，先在本 pane 输出完整 final report 或
blocked 问题，然后运行一条单行 WAKE 通知：
  herdr agent prompt <lead-pane-id> 'WAKE: <#issue> blocked|done <一句原因>'
WAKE 只是唤醒信号；lead 只认 pane 内的 final report 和真相源，不认 WAKE 正文。
```

- WAKE 只适用于 claude pane。codex pane 的 sandbox 可能拦截 socket 访问，其
  `working`/`done`/`blocked` 状态由 Herdr codex integration 上报，完成提醒由 lead
  侧后台 `herdr agent wait` 兜底。packet 不附回信地址块。
- lead 收到 WAKE 后按 `child-monitoring.md` 的 terminal fan-in 处理。

## 创建后验证（每个 pane 必做）

1. `herdr pane get <pane_id>`，确认 `workspace_id` 和 `tab_id` 都等于目标。
2. 落点不符时 `herdr pane close <pane_id>`，重新解析目标后用显式参数重建；
   连续两次落点错误则停下问用户。
3. 把 space label、`workspace_id`、tab label、`tab_id`、pane label、`pane_id` 写进
   worker 坐标记录，并要求 worker readback 原样回报。
