---
name: delivery-pipeline
description: Orchestrate a loose idea, Wayfinder map, spec, or implementation ticket graph through discovery, spec and ticket publication, automatic worktree dispatch, integration, and one summary PR/MR.
disable-model-invocation: true
---

# Delivery Pipeline

把输入推进到一条完整交付链：

```text
idea/map -> discovery -> spec -> implementation tickets
  -> automatic dispatch -> collect/integrate -> summary PR/MR
```

`$wayfinder`、`$to-spec`、`$to-tickets`、`$implement` 和 `$code-review` 各自拥有自己的产物
质量。本 skill 只识别当前 gate、调用对应 owner、验证持久坐标并自动分配执行。

## 输入与 Gate

接受以下任一输入：

- 松散想法或 Wayfinder map issue：从 `discovery` 开始。
- 已批准 spec issue：从 `tickets` 开始。
- 已发布 implementation tickets：从 `dispatch` 开始。

裸 issue 编号必须能从当前 repo 的 tracker 配置唯一解析。每次新会话都沿持久 relationships
重建链路，从最早未完成的 gate 自动继续。

1. **识别输入、worktree 与调度运行时。** 读取 repo instructions、tracker operations 和输入 artifact，
   按当前 gate 渐进加载 references：fresh coordinator task 才加载 `references/gate-state-machine.md`、
   `references/fresh-session-boundaries.md` 与 `references/lane-registry.md`；worktree create/recovery 才加载
   `references/integration-worktree-management.md`；lane dispatch 才加载
   `references/owner-skill-resolution.md` 与 `references/dispatch-runtime-routing.md`；AFK discovery 才加载
   `references/child-monitoring.md`。同一 coordinator task 不因下一 lane 重读未变化的共享合同；只有
   owner path、文件内容、registry/Git 证据或 coordinator task 改变时才重读对应 owner。
   Codex App 原生 thread tools 全部可用时默认选择
   `dispatch_runtime: codex-app`；Herdr Control Route 的 capability probe 通过后，用户明确要求
   Herdr 或 CLI runtime 才选择 `dispatch_runtime: herdr`。Codex App 不在 Herdr pane 时使用
   Codex App Herdr Bridge，并把 transport approval 持久化为 `trusted_execution_bootstrap`；
   bridge 优先选择运行中的 user-visible `default` Herdr session。Herdr 再按用户指定或 binding table 选择 `herdr-codex-pane` /
   `herdr-claude-pane`。Existing lanes 按各自 registry runtime 恢复，新 lane 才使用本次选择。
   用户启动或恢复 named map 时，把 `map_run_authority: canonical_tracker_transitions` 写入 map registry；
   后续 canonical tracker 收口和下一 ready frontier 不再逐项询问。
   识别当前是 source worktree（main）还是 integration worktree（`feature/map-*`）。
   输入是 map 且在 source worktree 时：检查该 map 的 integration worktree 是否存在（registry + 路径）；
   存在且 valid 则提示 resume，不存在则创建 integration worktree 并切换过去；Herdr workspace
   只在首次 Herdr lane 前懒创建。
   已在 integration worktree 时直接继续。完成标准：worktree 位置正确（integration worktree 或已确认在 source）、
   输入已识别类型（map/spec/tickets）、本次 `dispatch_runtime` 已持久化；fresh recovery 已 readback 所有
   active writers，同一 task 续派只 readback target lane 与资源冲突 lanes。
2. **Run discovery。** 加载 `references/wayfinder-frontier-loop.md`、
   `assets/WAYFINDER_TICKET_DISPATCH_PACKET.md`、
   `assets/WAYFINDER_GRILLING_DISPATCH_PACKET.md`（因果/冲突/假设时再加载 `references/toc-thinking-processes.md`）。
   松散想法先调用 `wayfinder` owner 建图（建图拷问在当前会话进行，不派发），随后自动派发 ready AFK decision tickets。
   Herdr HITL lane 完成 startup terminal 后写 `awaiting_human` 并立即 yield；用户在 Herdr 完成对话后
   回到 Codex App，coordinator 按持久证据 fan-in，自动完成 canonical tracker transitions、重算并派发
   下一 ready frontier。HITL 只阻塞自身。
   完成标准：所有 in-scope child issues closed、resolution 与 artifacts 可读回。
3. **Generate spec。** 如果当前链路还没有已批准 spec，解析并执行 `to-spec` owner，遵守它自己的
   提案、用户判断和发布流程。交给 fresh worker 时加载 `assets/GATE_CHILD_DISPATCH_PACKET.md`。
   完成标准：已发布 spec 的真实 URL/ID 与 body 可读回。
4. **Generate tickets。** 读取 spec 的 native children/sub-issues 和 body 中 `Parent` 精确回链该 spec 的
   implementation tickets，按 issue ID 去重。命中为零时解析并执行 `to-tickets` owner；
   交给 fresh worker 时加载 `assets/GATE_CHILD_DISPATCH_PACKET.md`。
   完成标准：至少一张真实 ticket 的 ID、spec 回链和 dependency edges 可读回。
5. **Dispatch execution。** 加载 `references/frontier-lanes.md`、`references/integration-worktree-management.md`、
   `assets/ISSUE_IMPLEMENT_DISPATCH_PACKET.md`；Herdr 路由再按 worker kind 加载
   `assets/HERDR_CODEX_IMPLEMENT_DISPATCH_PACKET.md` 或
   `assets/HERDR_CLAUDE_IMPLEMENT_DISPATCH_PACKET.md`。从 dependency graph 重算 ready frontier，
   选择无 mutable-resource 冲突的 maximal safe batch。解析 `implement` owner 后，每张入选票按已选
   调度运行时创建唯一 lane：`codex-thread` 按 Task Coordinate Title 用 `create_thread` 从
   Integration branch 创建 fresh Codex App task + App-managed Execution Worktree；Herdr Control Route
   创建手工 Execution Worktree + fresh Codex CLI/Claude Code pane。coordinator 不亲自实现。
   完成标准：ticket registry 已以 `created` readback runtime 对应的 task 或 pane 坐标、Task Coordinate
   Title（Codex App）、实际 worktree、branch 与 base commit。
6. **Probe startup。** 每个 lane 创建后验证：`cwd` 位于 Execution Worktree、完整 packet 已收到、
   owner name/resolved path 与 ticket 由 coordinator 的 realpath/frontmatter、packet 与 registry 确认；`codex-thread`
   还要验证 Source owner projectId，
   Herdr pane 还要验证 session/workspace/tab/pane placement 与 kind。Claude pane 以
   `--dangerously-skip-permissions` 启动；`trusted_execution_bootstrap` 自动确认精确匹配的 workspace
   trust 和 applicable external imports。未知或越界 UI 才是可恢复的 `blocked` lane。
   Herdr HITL 的 `agent prompt` accepted 且状态从 `idle` 进入 `working` 即 startup terminal：
   直接写 `awaiting_human` 并 yield，不等待首个业务问题，也不读取 routine terminal、可见屏幕或进程信息。
   错误落点或未读 owner file 时沿同一
   runtime 重建一次；第二次失败标记 `setup_blocked`，
   按 lane runtime 清理 task/pane 与 execution worktree/branch（参考
   `references/execution-worktree-integration.md`）。完成标准：达到 `references/frontier-lanes.md` 的
   Dispatch Handoff；报告坐标并立即结束本轮。
7. **Integrate changes。** 加载 `references/execution-worktree-integration.md`。用户完成信号或 worker
   terminal event 只负责唤醒；以 Git、tracker、artifact 和 registry 验证 commit、Execution Worktree、
   Integration Worktree state，按 dependency order
   执行 cherry-pick。成功后运行 focused checks，通过则持久化 `integrated`、删除 execution
   worktree/branch，并按 runtime 归档 Codex App task 或关闭 Herdr pane；transport readback 成功后
   registry 写为 `closed`，否则写为 `close_pending`；随后按 Map Run Authority 完成 tracker 收口，自动重算并
   派发下一 ready frontier，不等待“继续”。冲突时中止 cherry-pick，
   标记 `integration_conflict`，保留 execution worktree 供调试。Lane blocker 不停止其他 ready tickets。
8. **Close out remotely。** Execution graph 清空后，运行 whole-change checks。全部通过时加载
   `references/test-decision-and-rebase.md`，暂停在 test decision point，由用户选择：(1) 在 integration
   worktree 测试，(2) rebase 后在 main 测试，(3) 跳过测试直接 push。用户选择后自动 rebase integration
   branch 到最新 main，检测冲突时委托 `$resolving-merge-conflicts`。Rebase 成功后
   push 到 main（默认直接 push，不创建 PR/MR 除非用户明确要求），删除所有 worktrees（integration +
   残留 execution），删除所有 branches（`feature/map-X` + execution branches）；map 曾使用
   Herdr 时关闭 workspace 所有 panes（保留 workspace）。关闭 map issue并写入 completion comment。获得 remote publication
   authority 时加载 `references/remote-closeout-checklist.md`，push/open summary PR/MR，
   并等待 CI/CD 与 remote review verdict。

## 分配规则

- ready ticket = open、未被 claim、全部 blockers completed。
- 不评估 ticket 大小、是否需要拆分、描述/验收是否够详细，或这张票“是否合理”；
  `$to-tickets` 已发布的 tickets 直接作为待分配 execution graph。
- dependency 相连、显式文件/可变资源重叠或写集合无法证明独立的 tickets 串行；其余并发。
- 按 tracker priority、dependency order、issue ID 做确定性选择。
- 每张 ticket 一个 execution lane、一个 owner、一个 worktree/branch。lane terminal 后由
  coordinator 重算下一批，不让 worker 自领 sibling tickets。
- 新会话先从每张 ticket 的 durable lane registry 恢复 existing tasks，再创建 replacement。
- 调度运行时按 `references/dispatch-runtime-routing.md` 选择；ticket domain 不改写调度运行时。
- Codex App thread tools 不完整时按 `codex-cli` 使用 Herdr；Herdr Control Route 不可用时输出每张 ready
  ticket 的完整 dispatch packet，不假装已经派发。

## 真相源与权限

- map 只索引 discovery decisions；spec 承载共同 scope；tracker tickets 是 execution graph；
  lane reports、Git commits 和 checks 是执行证据；PR/MR 是远程收尾真相源。
- spec 与 tickets 的内容由对应 skill 决定。orchestrator 的 gate 只检查存在性、回链、依赖
  和发布 readback，不增加内容质量或拆票复审 gate。
- Map Run Authority 覆盖 named map 的 claim/registry、child resolution/close、map gist、dependency
  blocker、owner-required follow-up decision ticket 和下一 ready frontier。每个 dependency layer 聚合
  readback；并发改写、越界或 destructive ambiguity fail closed。
- 本地 worktree、文件修改与 commit 使用 local execution authority；push、main、PR/MR、merge 和最终
  publication closeout 需要 remote publication authority。
- 所有面向用户、workers、tracker 和 PR/MR 的自然语言使用中文；skill/tool/status/path/hash
  保持原样。

## 完成标准

map decisions、spec、implementation ticket graph、lane commits/checks 和 summary PR/MR
已形成可追溯链路；execution graph 为空，whole-change checks 与远程 CI/CD 通过，remote
review Agent 明确 can pass。没有 remote authority 时完成本地 integration 并报告唯一剩余
remote gate。
