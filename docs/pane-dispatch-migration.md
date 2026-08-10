# Pane-Dispatch Migration from dispatch-to-codex

**迁移日期**：2026-08-01
**源路径**：`~/.claude/skills/dispatch-to-codex` (无版本控制)
**备份路径**：`~/.claude/skills/.backup-dispatch-to-codex-20260801-223746`
**新路径**：`claude/skills/pane-dispatch/` (本 repo，Claude-only 单树)

## 合并背景

`dispatch-to-codex` (673 行) 持有编排层完全没有的可执行派发机械（tab 容量、pane split、
落点校验、失败重试、agent 命名、lifecycle 配对），而编排层在用 `/herdr` 这个通用 CLI
driver 做派发——但 `/herdr` 的 contract 明确拒绝自动创建 workspace/tab ("unless the user
explicitly requests")。缺失层就在这里。

## 职责边界调整

**保留部分（进入 pane-dispatch）**：
- Workspace/tab 解析与创建
- Tab 容量管理（4-pane limit）
- Pane split / 默认 pane 复用
- Agent 启动（按 kind 分支）
- Packet 投递（写文件 + 单行引用）
- 落点验证（`herdr pane get` 断言）
- Listener 挂载（`herdr agent wait` 后台）
- Lifecycle 配对（tab label 同步）

**删除部分（归编排层或不需要）**：
- Maximal safe batch 计算（留 `frontier-lanes.md`，真相源是 tracker+Git，不是 issue 描述的文件清单）
- Background monitoring 与 terminal fan-in（留 `child-monitoring.md`，75 行那份已含 subagent+pane 两种 runtime）
- Tracker URL 拼接（由调用方在 packet 里提供，pane-dispatch 完全 tracker-agnostic）
- Issue fetch、conflict detection、lane ID allocation（编排层职责）
- `child-monitoring.md` 45 行旧版（本 repo 那份 75 行已更全面，直接丢弃不合并）

## 禁词替换（6 处）

本 repo `validate.py` 的 `check_pruned_policy()` 禁止以下模式，合并时已全部删除或改写：

| 原文件 | 行号 | 禁词 | 处置 |
|---|---|---|---|
| `codex-first-channel.md` | 14, 15, 48 | `claude-native` | 整个文件未进 pane-dispatch（runtime selection 归编排层） |
| `codex-first-channel.md` | 44 | `herdr wait agent-status` | 同上 |
| `herdr-pane-placement.md` | 161 | `herdr wait agent-status` | 改写成 `herdr agent wait` |
| `child-monitoring.md` | 20 | `herdr wait agent-status` | 未合并（45 行旧版被丢弃） |

**为什么这些是禁词**：
- `claude-native` — 已被 01 票的"按 ticket label 查表选 packet 模板"取代，不再做复杂 runtime selection
- `herdr wait agent-status` — 旧语法，正确形式是 `herdr agent wait`；本次派发实测验证

## 机械细节修正（4 条）

**(1) 多行 `send-text` 丢失问题**
- **原写法**：`herdr pane send-text "$pane_id" '<multi-line-packet>'`（会静默丢失）
- **修正**：packet 先写文件，只 send 单行 `完整读取 <path> 并严格按其中全部指令执行。`

**(2) Agent 启动命令格式**
- **原写法**：`-- codex -s danger-full-access` (把 agent 当成 native arg)
- **修正**：`--kind codex -- -s danger-full-access` (`--kind` 定引擎，`--` 后才是 native flags)

**(3) `agent_status=done` 不等于票 resolved**
- **原写法**：检查 `agent_status` 判断完成
- **修正**：只到 "agent 已 working + packet 已投递 + listener 已挂"，`done` 的解释权归编排层，必须读 `FINAL_REPORT` marker

**(4) Tab 自动消失**
- **原写法**：`herdr tab close <tab_id>`（最后一个 pane 关闭时手动删 tab）
- **修正**：删除手动 `tab close` 指令，tab 会自动消失（实测验证）

## 名称与语义变化

| 项 | 旧 | 新 |
|---|---|---|
| Skill 名 | `dispatch-to-codex` | `pane-dispatch` |
| 语义 | Codex-only | Kind-generic (claude \| codex) |
| 树结构 | Claude-only（无 git） | Claude-only（本 repo git） |
| 调用形式 | `/dispatch-to-codex <issue1> <issue2> ...` | `/pane-dispatch --kind <kind> --tab-type <letter> --workspace-key <key> --packet-file <path> ...` |

**为什么改成 kind-generic**：
- HITL 票（grilling/prototype）也需要同一套落点机械（G/P tab 4-pane 容量 + lifecycle 配对）
- 01 票定的 kind 路由已在"选择哪个 packet 模板"时完成，派发层只需验证 kind 存在、tab-kind 合法
- 避免重复 —— 写两份派发机械（一份 Codex、一份 Claude）违反 `/do-not-repeat-yourself`

## 物理结构

**Codex 侧**：无（Codex 用 thread-based dispatch，不用 herdr pane）

**Claude 侧**：
```
claude/skills/pane-dispatch/
├── SKILL.md
└── references/
    └── pane-placement-rules.md
```

**Bundle 改动**：
- `skill-bundle.json` — 保持现有单 entrypoint 格式（pane-dispatch 不是 entrypoint）
- `install.sh` — 新增 `install_claude_pane_dispatch()` 函数
- `validate.py` — 新增 `PANE_DISPATCH_CLAUDE` 常量 + 专项检查（frontmatter、references、禁词扫描）

## 验证

```bash
python3 scripts/validate.py  # pass
./scripts/install.sh --target claude  # 安装成功
ls -la ~/.claude/skills/pane-dispatch  # 软链正确
```

## 后续工作

delivery-pipeline 的 12 处 `/herdr` 引用需改指 `/pane-dispatch`（见 04 票 Answer）。
