---
name: wayfinder-implement-orchestrator
description: Orchestrate a loose idea, Wayfinder map, spec, or implementation ticket graph through discovery, spec and ticket publication, automatic Codex worktree dispatch, integration, and one summary PR/MR.
---

# Wayfinder Implement Orchestrator for Claude

把输入推进到一条完整交付链：

```text
idea/map -> discovery -> spec -> implementation tickets
  -> automatic Codex dispatch -> collect/integrate -> summary PR/MR
```

`/wayfinder`、`/to-spec`、`/to-tickets`、`/implement` 和 `/code-review` 各自拥有自己的产物
质量。本 skill 只识别当前 gate、调用对应 owner、验证持久坐标并自动分配执行。

## 输入与 Gate

接受松散想法、Wayfinder map issue、已批准 spec issue 或已发布 implementation tickets。
裸 issue 编号必须能从当前 repo 的 tracker 配置唯一解析。每次新会话都沿持久 relationships
重建链路，从最早未完成的 gate 自动继续。

1. 读取 repo instructions、tracker operations 和输入 artifact，加载
   `references/gate-state-machine.md`、`references/fresh-session-boundaries.md`、
   `references/lane-registry.md`、`references/child-monitoring.md` 和
   `references/owner-skill-resolution.md`。完成标准：输入已归入唯一 gate，
   map/spec/ticket 与 existing child 坐标均已 readback。
2. `discovery`：加载 `references/wayfinder-frontier-loop.md`、
   `assets/WAYFINDER_TICKET_DISPATCH_PACKET.md` 和
   `assets/WAYFINDER_GRILLING_DISPATCH_PACKET.md`。涉及因果、冲突或隐藏假设时再加载
   `references/toc-thinking-processes.md`。松散想法先解析并执行 `wayfinder` owner 建图；
   随后通过 `/herdr` skill 自动派发 ready AFK decision tickets。HITL ticket
   只阻塞自身。完成标准：所有 in-scope child issues 已关闭，resolution 与必要 artifacts
   可读回。
3. `spec`：如果当前链路还没有已批准 spec，解析并执行 `to-spec` owner，遵守它自己的
   提案、用户判断和发布流程。交给 fresh pane 时加载
   `assets/GATE_CHILD_DISPATCH_PACKET.md`。
   完成标准：已发布 spec 的真实 URL/ID 与 body 可读回。
4. `tickets`：读取 spec 的 native children/sub-issues，以及 body 中 `Parent` 精确回链该
   spec 的 implementation tickets；按 issue ID 去重。命中为零时解析并执行 `to-tickets`
   owner；交给 fresh pane 时加载 `assets/GATE_CHILD_DISPATCH_PACKET.md`。
   完成标准：至少一张真实 ticket 的 ID、spec 回链和 dependency edges 可读回。
   `/to-tickets` 的已发布结果直接成为 execution graph。
5. `dispatch`：加载 `references/frontier-lanes.md`、`references/integration-worktree-management.md` 和
   `assets/CODEX_PANE_DISPATCH_PACKET.md`。从 dependency graph 重算 ready frontier，选择无
   mutable-resource 冲突的 maximal safe batch。解析 `implement` owner 后，每张入选票：
   先从 integration worktree 创建 execution worktree（path: `<source-parent>/worktrees/<repo>-map-<M>-issue-<N>/`，
   branch: `codex/issue-<N>` based on integration branch），验证 Git state（worktree registered、branch correct、
   working tree clean），再通过 `/herdr` skill 创建 pane（X tabs，4-pane capacity，tab label 自动更新）
   并启动 Codex 后投递完整 owner packet。完成标准：ticket 的 durable registry 已 readback
   pane ID、workspace/tab、execution_worktree_path、branch、base commit 和 attached waiter。
6. 每个 pane 做 startup probe：workspace、tab、cwd、pane label 和 agent status 均需匹配；
   `cwd` 必须精确等于该票 execution worktree，pane 必须 readback 相同的 owner name/resolved path。
   错误落点或未读 owner file 时通过 `/herdr` skill 重试一次，第二次失败标记 `setup_blocked`，
   立即删除 execution worktree/branch/pane（参考 `references/execution-worktree-integration.md`）。
7. 加载 `references/execution-worktree-integration.md`。workers 运行时只消费 terminal final report；
   验证 commit、execution worktree、integration worktree state，按 dependency order 执行 cherry-pick。
   成功后运行 focused checks，通过则删除 execution worktree/branch、通过 `/herdr` skill 关闭 pane、
   更新 tab label、更新 registry 为 `integrated`、立即重算 frontier。冲突时中止 cherry-pick，
   标记 `integration_conflict`，保留 execution worktree 供调试。关闭 pane 失败只留下可恢复
   `pane_close_pending` lane。
8. execution graph 清空后运行 whole-change checks。获得 remote publication authority 时
   加载 `references/remote-closeout-checklist.md`，push/open summary PR/MR，并等待 CI/CD
   与 remote review verdict。

## 分配规则

- ready ticket = open、未被 claim、全部 blockers completed。
- 不评估 ticket 大小、是否需要拆分、描述/验收是否够详细，或这张票“是否合理”；
  `/to-tickets` 已发布的 tickets 直接作为待分配 execution graph。
- dependency 相连、显式文件/可变资源重叠或写集合无法证明独立的 tickets 串行；其余并发。
- 按 tracker priority、dependency order、issue ID 做确定性选择。
- 每张 ticket 一个 Codex pane、一个 worktree/branch。lane terminal 后由 lead 重算下一批，
  不让 worker 自领 sibling tickets。
- 新会话先从每张 ticket 的 durable lane registry 恢复 existing panes，再创建 replacement。
- `HERDR_ENV` 不可用或 `/herdr` skill 找不到匹配 workspace 时，输出完整 packets；不假装已经派发。

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
