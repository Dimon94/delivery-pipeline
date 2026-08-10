# 01 — agent kind 按 ticket 类别显式绑定

Status: resolved
Type: wayfinder:grilling
Blocked by:

## Question

派发时 agent kind 目前**从不被绑定**——`--kind` 在整个 delivery-pipeline repo 里
出现 0 次。规则已经定了（HITL 拷问票 → Claude Code；实现票 → Codex），这张票要定的是
这条规则**写在哪一层、以什么形式表达**，使得任何一次派发都不可能漏掉 kind。

要决定的点：

1. **绑定点落在哪份文件**。候选：`references/frontier-lanes.md`（已经分了 Design
   Fan-out / Execution Lanes 两节）、`references/child-monitoring.md` 的 Startup — Pane
   一节、或者派发 packet 模板自身（`WAYFINDER_GRILLING_DISPATCH_PACKET.md` 与
   `CODEX_PANE_DISPATCH_PACKET.md`）。这个选择直接决定第 04 票融合后的派发层要不要
   承载 kind 路由，也决定 map 中 "融合后派发层归属" 那片 fog 怎么graduate。

2. **表达成硬规则还是查找表**。`dispatch-to-codex/references/codex-first-channel.md`
   已有一份 `codex-pane` / `claude-native` 的 Automatic Runtime Selection 判据（按
   scope 冻结、self-contained、是否需要 HITL 等条件推导 runtime）。它比"按 ticket 类别
   查表"更细，但正是它没能阻止拷问票落进 Codex。要定：沿用这套条件判据、改成
   ticket-type 直接查表、还是查表为主判据为辅。

3. **缺失 kind 时的行为**。packet 没写 kind 时应当 fail closed（拒绝派发）还是有默认值。
   考虑到本次故障正是"没绑定就默认成了 Codex"，默认值的存在本身可能就是缺陷源。

4. **五类 tab 字母与 kind 的关系**。`herdr-pane-placement.md` 的 X tab 注明"claude 或
   codex pane"，G tab 是拷问/规划。tab 字母是否足以推出 kind，还是两者必须各自显式。

## Answer

**决策已确认并落地**（2026-08-01）：

### 1. 绑定点：Packet 模板自身
`--kind` 参数直接写在派发 packet 模板文件中：
- `WAYFINDER_GRILLING_DISPATCH_PACKET.md` 内置 `--kind claude`
- `CODEX_PANE_DISPATCH_PACKET.md` 内置 `--kind codex`
- `ISSUE_IMPLEMENT_DISPATCH_PACKET.md`（Codex 侧）内置 `--kind codex`

### 2. 路由方式：简单查表
根据 ticket label 直接选择对应 packet 模板：
- `wayfinder:grilling`、`wayfinder:prototype` → `WAYFINDER_GRILLING_DISPATCH_PACKET.md`
- implementation tickets → `CODEX_PANE_DISPATCH_PACKET.md` 或 `ISSUE_IMPLEMENT_DISPATCH_PACKET.md`

不再使用复杂的条件判断（scope 冻结、self-contained 等），避免判断遗漏。

### 3. 缺失行为：Fail closed
Packet 缺少 `--kind` 参数时，派发层必须拒绝派发并报错。
不提供默认值，强制要求显式指定 kind，防止默认行为导致错误派发。

### 4. Tab-Kind 关系：可推导 + 交叉验证
- G tab（grilling/规划）、P tab（prototype）、R tab（research）→ 必须 `--kind claude`
- X tab（execution）→ 可以 `--kind claude` 或 `--kind codex`
- D tab（data/debug）→ 待定
- 派发时做交叉验证：tab-kind 组合不符合规则时拒绝派发

### 落地文件
**Claude 侧**（`claude/skills/delivery-pipeline/`）：
- `assets/WAYFINDER_GRILLING_DISPATCH_PACKET.md` — 添加 `--kind claude` 说明
- `assets/CODEX_PANE_DISPATCH_PACKET.md` — 添加 `--kind codex` 说明
- `references/frontier-lanes.md` — 添加 "Agent Kind 绑定规则" 章节

**Codex 侧**（`skills/delivery-pipeline/`）：
- `assets/WAYFINDER_GRILLING_DISPATCH_PACKET.md` — 添加 `--kind claude` 说明
- `assets/ISSUE_IMPLEMENT_DISPATCH_PACKET.md` — 添加 `--kind codex` 说明
- `references/frontier-lanes.md` — 添加 "Agent Kind 绑定规则" 章节

### 影响 04 票
本决策确认：融合后的派发层**不需要承载 kind 路由逻辑**。
路由已在"选择哪个 packet 模板"时完成，派发层只需填写模板、验证 kind 存在性和 tab-kind 合法性。
