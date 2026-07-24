---
name: wayfinder-implement-orchestrator
description: Orchestrate a loose idea, Wayfinder map, spec, or implementation ticket graph through discovery, spec and ticket publication, automatic Codex worktree dispatch, integration, and one summary PR/MR.
disable-model-invocation: true
---

# Wayfinder Implement Orchestrator

把输入推进到一条完整交付链：

```text
idea/map -> discovery -> spec -> implementation tickets
  -> automatic Codex dispatch -> collect/integrate -> summary PR/MR
```

`/wayfinder`、`/to-spec`、`/to-tickets`、`/implement` 和 `/code-review` 各自拥有自己的产物
质量。本 skill 只识别当前 gate、调用对应 owner、验证持久坐标并自动分配执行。

## 输入与 Gate

接受以下任一输入：

- 松散想法或 Wayfinder map issue：从 `discovery` 开始。
- 已批准 spec issue：从 `tickets` 开始。
- 已发布 implementation tickets：从 `dispatch` 开始。

裸 issue 编号必须能从当前 repo 的 tracker 配置唯一解析。每次新会话都沿持久 relationships
重建链路，从最早未完成的 gate 自动继续。

1. 读取 repo instructions、tracker operations 和输入 artifact，加载
   `references/gate-state-machine.md`、`references/fresh-session-boundaries.md`、
   `references/lane-registry.md` 和 `references/child-monitoring.md`。完成标准：输入已归入
   唯一 gate，map/spec/ticket 与 existing child 坐标均已 readback。
2. `discovery`：加载 `references/wayfinder-frontier-loop.md`、
   `assets/WAYFINDER_TICKET_DISPATCH_PACKET.md` 和
   `assets/WAYFINDER_GRILLING_DISPATCH_PACKET.md`。涉及因果、冲突或隐藏假设时再加载
   `references/toc-thinking-processes.md`。松散想法先调用 `/wayfinder` 建图；随后自动派发
   ready AFK decision tickets，HITL ticket 只阻塞自身。
   完成标准：所有 in-scope child issues 已关闭，resolution 与必要 artifacts 可读回。
3. `spec`：如果当前链路还没有已批准 spec，调用 `/to-spec`，并遵守它自己的提案、用户
   判断和发布流程。交给 fresh worker 时加载 `assets/GATE_CHILD_DISPATCH_PACKET.md`。
   完成标准：已发布 spec 的真实 URL/ID 与 body 可读回。
4. `tickets`：读取 spec 的 native children/sub-issues，以及 body 中 `Parent` 精确回链该
   spec 的 implementation tickets；按 issue ID 去重。命中为零时调用
   `$to-tickets <spec-url>`；交给 fresh worker 时加载 `assets/GATE_CHILD_DISPATCH_PACKET.md`。
   完成标准：至少一张真实 ticket 的 ID、spec 回链和 dependency edges 可读回。
   `/to-tickets` 的已发布结果直接成为 execution graph。
5. `dispatch`：加载 `references/frontier-lanes.md` 和
   `assets/ISSUE_IMPLEMENT_DISPATCH_PACKET.md`。从 dependency graph 重算 ready frontier，
   选择无 mutable-resource 冲突的 maximal safe batch。每张入选票创建一个 fresh Codex
   task 和独立 worktree；coordinator 不亲自实现。完成标准：ticket 的 durable registry
   已 readback thread ID、projectId、worktree、branch 和 base commit。
6. 每个 task 创建后做一次 startup probe：确认 `Source owner projectId` 属于同一 repo、
   `cwd` 位于该票自己的 worktree、完整 packet 已收到。错误落点用同一 projectId 重建
   一次；第二次失败只把该票标成 setup blocked。
7. workers 运行时只消费 terminal final report；验证 commit、checks 和 dirty state 后按
   dependency order 集成，并立即重算 frontier。
   lane blocker 不停止其他 ready tickets。
8. execution graph 清空后运行 whole-change checks。获得 remote publication authority 时
   加载 `references/remote-closeout-checklist.md`，push/open summary PR/MR，并等待 CI/CD
   与 remote review verdict。

## 分配规则

- ready ticket = open、未被 claim、全部 blockers completed。
- 不评估 ticket 大小、是否需要拆分、描述/验收是否够详细，或这张票“是否合理”；
  `/to-tickets` 已发布的 tickets 直接作为待分配 execution graph。
- dependency 相连、显式文件/可变资源重叠或写集合无法证明独立的 tickets 串行；其余并发。
- 按 tracker priority、dependency order、issue ID 做确定性选择。
- 每张 ticket 一个 execution lane、一个 owner、一个 worktree/branch。lane terminal 后由
  coordinator 重算下一批，不让 worker 自领 sibling tickets。
- 新会话先从每张 ticket 的 durable lane registry 恢复 existing tasks，再创建 replacement。
- thread tools 不可用时，输出每张 ready ticket 的完整 dispatch packet；不假装已经派发。

## 真相源与权限

- map 只索引 discovery decisions；spec 承载共同 scope；tracker tickets 是 execution graph；
  lane reports、Git commits 和 checks 是执行证据；PR/MR 是远程收尾真相源。
- spec 与 tickets 的内容由对应 skill 决定。orchestrator 的 gate 只检查存在性、回链、依赖
  和发布 readback，不增加内容质量或拆票复审 gate。
- 自动分配包含 lane registry checkpoint 的 tracker write authority。本地 worktree、文件
  修改与 commit 使用 local execution authority；其他 remote comment、push 和 PR/MR 需要
  remote publication authority。
- 所有面向用户、workers、tracker 和 PR/MR 的自然语言使用中文；skill/tool/status/path/hash
  保持原样。

## 完成标准

map decisions、spec、implementation ticket graph、lane commits/checks 和 summary PR/MR
已形成可追溯链路；execution graph 为空，whole-change checks 与远程 CI/CD 通过，remote
review Agent 明确 can pass。没有 remote authority 时完成本地 integration 并报告唯一剩余
remote gate。
