# 02 — HITL 票自动开 pane：消除两份文件的矛盾

Status: resolved
Type: wayfinder:grilling
Blocked by:

## Question

两份文件对 HITL 票的处置互相矛盾，执行时读了后者，所以拷问票没被派发：

- `SKILL.md:30` — HITL tickets（grilling、prototype）通过 `/herdr` 创建 pane。
- `references/wayfinder-frontier-loop.md:35-38` — 下一个 frontier 票是 grilling /
  prototype / HITL task 时**停止 frontier loop**，输出一个填好的 prompt 等用户。

用户已定：**自动开 pane，拷问在新 pane 里进行**。这张票要定的是怎么改到没有残留矛盾。

要决定的点：

1. **`wayfinder-frontier-loop.md` 的"停止"条目怎么改**。那条现在是 4 个停止条件之一。
   删掉它、还是改成"开 pane 后继续 loop"？注意同一节还有 `ask-user` 停止条件
   （第 39 行）和"没有可参与的用户 pane 时…停止为 `ask-user`"（第 20 行），这些是否
   仍然成立、什么情况下才算真的没有可参与的 pane。

2. **HITL pane 开出来之后 lead 做什么**。自动开 pane 的已知故障模式：pane 里的拷问
   会话你不进去就是死的，而且没有东西提醒你。要定 lead 的报告义务——每次派发后是否
   必须明确报告"N 张 HITL 票在 pane X 等你"，以及 frontier 只剩 HITL 票时 lead 是继续
   等待、停下汇报，还是收尾退出。

3. **`WAYFINDER_GRILLING_DISPATCH_PACKET.md` 的定位随之变化**。它现在的开头写着
   "填写这个 packet…输出一个用于完整 HITL 会话的已填写 prompt"，语气是给人看的
   copy-paste 稿。自动开 pane 后它应当变成投递进 pane 的 packet，措辞和交付方式都要跟着改。
   两棵树各有一份且内容不同。

4. **Codex 侧同一份文件的对应改法**。`skills/.../wayfinder-frontier-loop.md` 的停止
   条目措辞是"输出一个已填写 brief，让 successor 在用户反馈后继续作为 owner"——
   Codex runtime 下没有 `/herdr` pane 的同等概念，要定它是照抄 Claude 侧、保留
   successor 交接、还是声明该路径只在 Claude 侧可用。

## Answer

**决策已确认并落地**（2026-08-01）：

### 1. 删除"遇到 HITL 就停止"规则

**Claude 侧**：删除 wayfinder-frontier-loop.md 停止列表中的"遇到 grilling/prototype/HITL task 就停止"条目。

**Codex 侧**：同样删除该停止条目。

**理由**：
- HITL tickets 通过 `/herdr` 自动派发到 pane 后，与后台 research subagents 一样，lead 继续处理其他 frontier work
- 真正的停止条件是"frontier 只剩已派发的 HITL panes 且没有其他 ready work"，不是"遇到 HITL ticket"本身
- Codex 侧根本不会遇到 HITL tickets（01 票的路由规则已将它们路由到 Claude Code），该停止条目是死代码

### 2. Lead 的 HITL pane 报告义务

**(a) 强制报告** — 每次派发 HITL pane 后，lead 必须输出明确的 pane 坐标提醒（形如 `#02 grilling → w48:p7`）。

**(b) frontier 清空时停为 ask-user** — frontier 只剩已派发的 HITL panes 且没有其他 ready work 时，停止为 `ask-user`，输出等待中的 HITL panes 清单，结束当前回合但保持 listeners 挂载。HITL pane terminal 后恢复 frontier loop。

**理由**：
- HITL lane 是唯一一种 lead 沉默就等于死锁的 lane 类型（pane 在等用户回答，用户不知道就不会进去）
- 停为 `ask-user` 而非收尾退出，因为 discovery 还有未 resolved 的 decision tickets
- 这与"不停下流水线交还当前会话"不冲突——约束的是派发时刻（有其他 ready work 就别停），这里是 ready work 真的清空了

### 3. WAYFINDER_GRILLING_DISPATCH_PACKET.md 措辞修正

**Claude 侧**：packet 第 65 行改为明确说明交付方式：
```
本 packet 由 lead 填写并通过 `/herdr` 投递进新建的 worker pane。
```

**Codex 侧**：强化第 10 行的注意措辞：
```
**注意**：Codex runtime 不支持 `/herdr` pane 创建。遇到 HITL tickets 时应通过跨环境协调机制委托给 Claude Code runtime，或在 wayfinder-frontier-loop.md 中声明该路径不可用。本 packet 保留作为格式参考。
```

**理由**：
- packet 的读者是 worker agent，需要知道自己在什么环境下运行
- Codex 侧文件保留作为参考和对称性维护，但明确警告不可执行

### 4. Codex 侧对应改法

**照抄 Claude 侧改法（删除停止规则）**，因为 01 票的路由规则已保证 Codex 侧 frontier 不会出现 HITL tickets。

### 落地文件

**Claude 侧**（`claude/skills/delivery-pipeline/`）：
- `references/wayfinder-frontier-loop.md` — 删除"遇到 HITL 就停止"条目，改为"frontier 只剩 HITL panes 时停为 ask-user"；循环第 3 步添加 HITL 自动派发和强制报告义务
- `assets/WAYFINDER_GRILLING_DISPATCH_PACKET.md` — 第 65 行改为明确交付方式

**Codex 侧**（`skills/delivery-pipeline/`）：
- `references/wayfinder-frontier-loop.md` — 删除"遇到 HITL 就停止"条目
- `assets/WAYFINDER_GRILLING_DISPATCH_PACKET.md` — 强化第 10 行注意措辞

## 落地

决策定下后直接改文件（本 map 授权 execution）：双树都改，
跑 `python3 scripts/validate.py`。
