# 04 — 把 Codex 派发抽成一个实质承载的独立 skill

Status: resolved
Type: wayfinder:grilling
Blocked by: 01, 03

## Question

用户已定的方向：**Codex 派发是一个可以抽出来的单一变量**，所有"分配给 Codex 的工作"
由一个专门的 skill 实质承载；不做薄转发中间层，也不抽第三方共享层。
`dispatch-to-codex` 并入本 repo 作为这个 skill 的起点。

现状事实：

- `delivery-pipeline` 从未引用 `dispatch-to-codex`（0 处命中）。两者是两个抽象层：
  编排层跑 gate 状态机、持有 worktree/registry/integration，谈派发时是抽象的
  （"通过 `/herdr` 创建 pane"）；机械层持有编排层**完全没有**的可执行 bash——
  tab 容量、pane split、落点校验、失败重试、agent 命名规则、`--kind codex` 实参。
- 唯一重叠是 `child-monitoring.md` 两份同名文件（45 行 vs 75 行），
  `dispatch-to-codex` 那份是旧窄版，只有 pane runtime，没有 subagent runtime。
- `dispatch-to-codex` 不在任何 git 下（纯目录，无版本控制）。
- 它的 `disable-model-invocation: true` 与 delivery-pipeline Codex 侧的
  `allow_implicit_invocation: false` 是同类闸门：不让模型自己看见就调。

要决定的点：

1. **这个 skill 的职责边界**。"所有分配给 Codex 的工作"具体包含什么：只到"把 ticket
   落成一个正在工作的 Codex pane"（派发+校验+投递+监听挂载），还是也包含 terminal
   readback 与 final report 解析？后者现在归 `child-monitoring.md`。边界画在哪决定
   `child-monitoring.md` 的重叠怎么消解——谁保留、谁引用。

2. **它与 delivery-pipeline 的调用关系**。编排器在 dispatch gate 调它时，
   `disable-model-invocation: true` 是障碍（模型调不动）。要定：去掉这道闸门、
   换成只允许被 delivery-pipeline 调用的形式、还是别的表达。同时要保住你手动批量
   派发的入口不被牺牲。

3. **它在 repo 里的物理位置与安装形态**。本 repo 现在是单 skill 双树
   （`skills/` + `claude/skills/`）+ `skill-bundle.json` 单 entrypoint +
   `install.sh --target codex|claude|all`。新增第二个 skill 要求 bundle 格式、
   install 脚本、`validate.py` 都能容纳多 skill。要定这个扩展怎么做。

4. **HITL/Claude pane 派发归谁**。第 01 票绑定 agent kind 后，Claude pane 也需要同一套
   落点校验机械（`herdr-pane-placement.md` 的硬规则对两种 kind 同样适用）。若这个 skill
   只管 Codex，Claude pane 的派发机械要么重复一遍、要么留在编排层——两者都与
   `/do-not-repeat-yourself` 相抵。要定这个矛盾怎么解：skill 改成按 kind 派发的通用
   派发器（名字随之变化），还是 Claude pane 机械另有归属。

5. **硬编码 tracker 坐标的处置**。`SKILL.md:184` 写死
   `https://192.168.121.43/junbo/official/comic-drama-studio/-/work_items/${issue}`，
   `:38`、`:45` 也带 GitLab IP。本 repo 要跨 repo 复用，这些必须参数化。要定参数来源：
   repo tracker 文档、显式实参、还是环境变量。

6. **回灌本地安装的做法**。`~/.claude/skills/dispatch-to-codex` 是无版本控制的实体
   目录，改坏无法 revert。要定：并入前是否先备份/纳入 git，并入后该路径变成指向本 repo
   的 symlink、还是删除只留新 skill 名。

## Answer

**决策已确认并落地**（2026-08-01）：

### 1. 职责边界：机械执行层

`pane-dispatch` 只负责：**接收已填 packet → 创建验证的 pane + listener → 回报坐标**。

**做的事**：
- 解析/创建 workspace（按 map key 匹配 `herdr workspace list`）
- 解析/创建 tab（按类型字母 + <4 容量）
- 创建 pane（复用默认 pane / split 既有 pane）
- 启动 agent（`--kind claude|codex`，native args 按 kind 分支）
- 投递 packet（**写文件 + 单行引用**，避免多行 `send-text` 丢失）
- Rename pane + 同步 tab label（lifecycle 配对）
- 验证落点（`herdr pane get` 断言 workspace/tab 匹配）
- 挂载 listener（`herdr agent wait` 后台）
- 回报坐标（workspace/tab/pane IDs）

**不做的事**（归编排层）：
- Maximal safe batch 计算（留 `frontier-lanes.md`，真相源是 tracker+Git）
- Worktree 创建（留 `integration-worktree-management.md`）
- Terminal readback、final report 解析、集成（留 `child-monitoring.md`）
- Tracker URL 拼接（调用方在 packet 里提供完整 URL）

**完成标准**：pane 已创建 + 坐标已验证 + packet 已投递 + agent 已 working + listener 已挂。`agent_status=done` 的解释权归编排层。

理由：边界可判定（机械可验证），与本次派发踩坑一致（`done` ≠ 票 resolved）。

### 2. 名称与 kind 范围：kind-generic pane dispatcher

**名称**：`pane-dispatch`（去掉 Codex 限定）

**kind 范围**：通用（claude | codex），启动命令按 kind 分支：
- Claude pane：`-- --dangerously-skip-permissions [--model claude-fable-5]`
- Codex pane：`-- -s danger-full-access -a never`

理由：
- HITL 票（grilling/prototype）也需要同一套落点机械（G/P tab 4-pane 容量 + lifecycle 配对）
- 01 票定的 kind 路由已在"选择哪个 packet 模板"时完成，派发层只验证 kind 存在、tab-kind 合法
- 避免重复 —— 写两份派发机械违反 `/do-not-repeat-yourself`

### 3. 物理位置：Claude-only 单树

**路径**：`claude/skills/pane-dispatch/`（无 Codex 侧副本）

理由：
- Codex 侧用 thread-based dispatch（`send_message_to_thread`），不用 herdr pane
- 单树避免需要同步的漂移面（07 票在防的问题）
- 最小骨架改动（`skill-bundle.json` 保持单 entrypoint）

**骨架扩展**（最小化）：
- `install.sh` — 新增 `install_claude_pane_dispatch()` 函数
- `validate.py` — 新增 `PANE_DISPATCH_CLAUDE` 常量 + 专项检查（frontmatter、references、禁词扫描）
- 不动 `skill-bundle.json`（pane-dispatch 不是 entrypoint）

### 4. disable-model-invocation：保留

`disable-model-invocation: true` **保留**。

理由：
- 不影响编排器的 `Skill` tool 显式调用
- 防止模型在非编排场景误用（用户聊天时看到 "pane" 就尝试派发）
- 手动 `/pane-dispatch` 仍然有效（frontmatter 不拦用户显式调用）

### 5. Tracker 坐标参数化：完全不管

pane-dispatch **不含 tracker URL 拼接逻辑**，由调用方在 packet 里提供完整 URL。

理由：
- 符合职责边界（"拿已填 packet"）
- pane-dispatch 完全 tracker-agnostic，可服务 GitLab / GitHub / local-markdown 任何形态

### 6. 回灌本地安装：备份 + 删除 + migration note

**(a) 备份到带时间戳目录**：`~/.claude/skills/.backup-dispatch-to-codex-20260801-223746`

**(b) 删除旧目录**：`~/.claude/skills/dispatch-to-codex` 已删除

**(c) 留 migration note**：`docs/pane-dispatch-migration.md` 记录：
- 来源、备份路径、合并日期
- 职责边界调整（哪些进、哪些删）
- 禁词替换（6 处：`claude-native` ×3、`herdr wait agent-status` ×3）
- 机械细节修正（4 条：多行 `send-text`、agent 启动命令、`done` 语义、tab 自动消失）
- 名称与语义变化（Codex-only → kind-generic）

### 7. 多 skill repo 骨架：最小扩展

**A（采用）**：专项处理 pane-dispatch，不改通用骨架。

- `skill-bundle.json` 保持现有格式（单 entrypoint）
- `install.sh` 新增 `install_claude_pane_dispatch()` 函数
- `validate.py` 新增 `PANE_DISPATCH_CLAUDE` 常量 + 专项检查

理由：pane-dispatch 是内部机械，不是 bundle 的对外 entrypoint；改动最小；若将来真要加第三个 skill，到时再重构（YAGNI 原则）。

### 8. 本次派发实测的机械细节：全部进

**(1) 多行 `send-text` 丢失 → 写文件 + 单行引用**（硬规则）

**(2) Agent 启动命令格式 → `--kind <kind> -- <native-args>`**（修正原有错误）

**(3) `agent_status=done` 只是 lifecycle → 完成标准只到 listener 挂载**（边界声明）

**(4) Tab 自动消失 → 删除手动 `tab close` 指令**（修正多余动作）

**(5) `--kind` 可选值 21 种 → 只提一句不写死列表**（易变事实）

### 影响其他票

本决策确认：融合后的派发层**不需要承载 kind 路由逻辑**。路由已在"选择哪个 packet 模板"时完成（01 票），派发层只需填写模板、验证 kind 存在性和 tab-kind 合法性。

### 落地文件

**新增**：
- `claude/skills/pane-dispatch/SKILL.md`
- `claude/skills/pane-dispatch/references/pane-placement-rules.md`
- `docs/pane-dispatch-migration.md`

**修改**：
- `scripts/install.sh` — 新增 `install_claude_pane_dispatch()` 函数
- `scripts/validate.py` — 新增 `PANE_DISPATCH_CLAUDE` 检查，更新不变量（`/herdr` → `/pane-dispatch`）
- `claude/skills/delivery-pipeline/SKILL.md` — 3 处引用改为 `/pane-dispatch`
- `claude/skills/delivery-pipeline/references/frontier-lanes.md` — 2 处引用
- `claude/skills/delivery-pipeline/references/child-monitoring.md` — 8 处引用
- `claude/skills/delivery-pipeline/references/wayfinder-frontier-loop.md` — 1 处引用
- `claude/skills/delivery-pipeline/references/fresh-session-boundaries.md` — 4 处引用
- `claude/skills/delivery-pipeline/references/lane-registry.md` — 2 处引用
- `claude/skills/delivery-pipeline/references/execution-worktree-integration.md` — 1 处引用
- `claude/skills/delivery-pipeline/references/integration-worktree-management.md` — 5 处引用
- `claude/skills/delivery-pipeline/references/test-decision-and-rebase.md` — 5 处引用
- `claude/skills/delivery-pipeline/assets/CODEX_PANE_DISPATCH_PACKET.md` — 1 处引用
- `claude/skills/delivery-pipeline/assets/GATE_CHILD_DISPATCH_PACKET.md` — 1 处引用
- `claude/skills/delivery-pipeline/assets/WAYFINDER_GRILLING_DISPATCH_PACKET.md` — 1 处引用

**验证通过**：`python3 scripts/validate.py` → `bundle: pass`

**回灌安装**：`./scripts/install.sh --target claude` → 软链已建立
- `~/.claude/skills/pane-dispatch` → 本 repo
- `~/.claude/skills/dispatch-to-codex` 已删除
- 备份：`~/.claude/skills/.backup-dispatch-to-codex-20260801-223746`


决策定下后直接改文件（本 map 授权 execution）：并入 repo、按决策改造、扩展
`install.sh` 与 `validate.py`、跑 `python3 scripts/validate.py`、回灌本地安装并验证
symlink 指向正确。
