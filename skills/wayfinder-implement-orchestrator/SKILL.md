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

1. **识别输入与 worktree routing。** 读取 repo instructions、tracker operations 和输入 artifact。
   加载 `references/gate-state-machine.md`、`references/integration-worktree-management.md`、
   `references/fresh-session-boundaries.md`、`references/lane-registry.md`、
   `references/child-monitoring.md` 和 `references/owner-skill-resolution.md`。
   识别当前是 source worktree（main）还是 integration worktree（`feature/map-*`）。
   输入是 map 且在 source worktree 时：检查该 map 的 integration worktree 是否存在（registry + 路径）；
   存在且 valid 则提示 resume，不存在则创建 integration worktree + Herdr workspace，切换过去。
   已在 integration worktree 时直接继续。完成标准：worktree 位置正确（integration worktree 或已确认在 source）、
   输入已识别类型（map/spec/tickets）、所有 existing child 坐标已 readback。
2. **Run discovery。** 加载 `references/wayfinder-frontier-loop.md`、
   `assets/WAYFINDER_TICKET_DISPATCH_PACKET.md`、
   `assets/WAYFINDER_GRILLING_DISPATCH_PACKET.md`（因果/冲突/假设时再加载 `references/toc-thinking-processes.md`）。
   松散想法先调用 `wayfinder` owner 建图，随后自动派发 ready AFK decision tickets（HITL 只阻塞自身）。
   完成标准：所有 in-scope child issues closed、resolution 与 artifacts 可读回。
3. **Generate spec。** 如果当前链路还没有已批准 spec，解析并执行 `to-spec` owner，遵守它自己的
   提案、用户判断和发布流程。交给 fresh worker 时加载 `assets/GATE_CHILD_DISPATCH_PACKET.md`。
   完成标准：已发布 spec 的真实 URL/ID 与 body 可读回。
4. **Generate tickets。** 读取 spec 的 native children/sub-issues 和 body 中 `Parent` 精确回链该 spec 的
   implementation tickets，按 issue ID 去重。命中为零时解析并执行 `to-tickets` owner；
   交给 fresh worker 时加载 `assets/GATE_CHILD_DISPATCH_PACKET.md`。
   完成标准：至少一张真实 ticket 的 ID、spec 回链和 dependency edges 可读回。
5. **Dispatch execution。** 加载 `references/frontier-lanes.md`、`references/integration-worktree-management.md`、
   `assets/ISSUE_IMPLEMENT_DISPATCH_PACKET.md`。从 dependency graph 重算 ready frontier，
   选择无 mutable-resource 冲突的 maximal safe batch。解析 `implement` owner 后，每张入选票：
   先从 integration worktree 创建 execution worktree（path: `<source-parent>/worktrees/<repo>-map-<M>-issue-<N>/`，
   branch: `codex/issue-<N>` based on integration branch），验证 Git state（worktree registered、branch correct、
   working tree clean），创建 fresh Codex task 和 Herdr pane（X tabs，4-pane capacity，tab label
   自动更新），投递完整 dispatch packet；coordinator 不亲自实现。完成标准：ticket 的 durable registry
   已 readback thread ID、projectId、execution_worktree_path、branch、base commit 和 herdr_pane_id。
6. **Probe startup。** 每个 task 创建后验证：`Source owner projectId` 属于同一 repo、`cwd` 位于
   execution worktree、完整 packet 已收到、child 已 readback owner name/resolved path。
   错误落点或未读 owner file 时用同一 projectId 重建一次；第二次失败标记 `setup_blocked`，
   立即删除 execution worktree/branch/pane（参考 `references/execution-worktree-integration.md`）。
7. **Integrate changes。** 加载 `references/execution-worktree-integration.md`。Workers 运行时只消费
   terminal final report；验证 commit、extraction worktree、integration worktree state，按 dependency order
   执行 cherry-pick。成功后运行 focused checks，通过则删除 execution worktree/branch、关闭 Herdr pane、
   更新 tab label、更新 registry 为 `integrated`、立即重算 frontier。冲突时中止 cherry-pick，
   标记 `integration_conflict`，保留 execution worktree 供调试。Lane blocker 不停止其他 ready tickets。
8. **Close out remotely。** Execution graph 清空后，运行 whole-change checks。
   全部通过时进入 test decision：提示用户选择（1）在 integration worktree 测试、（2）立即 rebase 到 main 再测试、
   或（3）跳过测试。用户确认继续后，rebase integration branch 到最新 main（遇冲突委托
   `/mattpocock-skills:resolving-merge-conflicts`），从 source worktree push 到 main（默认直接 push，
   不创建 PR/MR 除非用户明确要求）。Push 成功后删除所有 worktrees/branches，关闭 Herdr workspace
   panes（保留 workspace），关闭 map issue。获得 remote publication authority 时加载
   `references/remote-closeout-checklist.md`。

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
