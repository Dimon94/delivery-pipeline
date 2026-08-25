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

- **派发**：创建 pane → 验证落点 → 启动 agent → 投递 packet（投递不阻塞，机制见 pane-lifecycle-rules.md"投递机制"）→ 按 design/execute 格式 rename →
  `herdr tab rename` 同步存活 issue/lane IDs → 确认 working（见 pane-lifecycle-rules.md"Working 确认"）→ 挂载 listener。
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

# 2. 验证落点（见 pane-lifecycle-rules.md"落点验证"；只依赖 pane 存在）

# 3. 把默认 pane 变成第一个 worker（agent start 与投递命令见 pane-lifecycle-rules.md）
#    启动 agent → 投递 packet（不阻塞）

# 4. pane rename + tab rename 同步 label（与冷启动重叠），然后确认 working
herdr pane rename "$default_pane" '<design #编号 | execution #编号> <极短摘要>'
```

## 标准创建命令（批级并发派发）

workspace 解析是批级唯一串行前置：space 与 tab 解析每批只做一次并 readback；readback 后同批
pane 的 create/split、agent start、packet 投递并发发出，批末一次聚合 working 确认，挂 listener
后做一次聚合 readback。不要批量建完再统一发 prompt 以外的串行化——pane 之间不互为前置。

```bash
# 批级前置（唯一串行段）：解析/创建 space 与各 item 的目标 tab，readback 坐标

# 1. 各 pane create/split 并发发出（新 workspace/tab 复用默认 pane；既有 tab split 既有 pane）
#    每个 pane 创建后立即验证落点（见 pane-lifecycle-rules.md"落点验证"，只依赖 pane 存在）

# 2. 各 pane 的 agent start 与 packet 投递并发发出（见 pane-lifecycle-rules.md；投递不阻塞）

# 3. rename pane + 同步 tab label（追加编号；在 agent 冷启动期间完成）
herdr tab rename <tab_id> '<字母>-<存活 issue 或 lane ID 列表>'

# 4. 批末聚合 working 确认：并行等待各 pane（见 pane-lifecycle-rules.md"Working 确认"）

# 5. 逐 pane 挂 listener（前提：该 pane 已确认 working），整批聚合 readback 坐标
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

1. 按 pane-lifecycle-rules.md"落点验证"核对 `workspace_id` 和 `tab_id`。
2. 落点不符时按该节流程 close、重试；连续两次落点错误则停下问用户。
3. 把 space label、`workspace_id`、tab label、`tab_id`、pane label、`pane_id` 写进
   worker 坐标记录，并要求 worker readback 原样回报。
