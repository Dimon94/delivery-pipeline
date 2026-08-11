---
name: delivery-pipeline
description: Orchestrate a loose idea, Wayfinder map, spec, or implementation ticket graph through discovery, spec and ticket publication, automatic worktree dispatch, integration, and one summary PR/MR.
---

# Delivery Pipeline for Claude

把输入推进到一条完整交付链：

```text
idea/map -> discovery -> spec -> implementation tickets
  -> automatic dispatch -> collect/integrate -> summary PR/MR
```

`/mattpocock-skills:wayfinder`、`/mattpocock-skills:to-spec`、`/mattpocock-skills:to-tickets`、`/mattpocock-skills:implement` 和 `/mattpocock-skills:code-review` 各自拥有自己的产物
质量。本 skill 只识别当前 gate、调用对应 owner、验证持久坐标并自动分配执行。

## 执行流程

从任意输入自动推进到下一个未完成 gate。每个 gate 调用对应的 owner skill，
验证产物，派发 workers，等待完成。

**输入识别：** 读取 repo tracker 和输入（想法/map/spec/tickets），
沿 parent relationships 重建链路，定位最早未完成的 gate。参考
`references/gate-state-machine.md`、`references/fresh-session-boundaries.md`、
`references/lane-registry.md`。

**Discovery gate：** 松散想法调用 `wayfinder` 建图（建图拷问在当前会话进行，不派发），AFK decision tickets
（research、task）自动派发为后台 subagents（`Agent` tool, `run_in_background: true`），
HITL tickets（grilling、prototype）通过 `/pane-dispatch` 创建 pane。完成标准：
所有 decision issues 已关闭，resolution 可读回。参考 `references/wayfinder-frontier-loop.md`。

**Spec gate：** 无已批准 spec 时调用 `to-spec` owner。完成标准：
spec URL/ID 与 body 可读回。

**Tickets gate：** 读取 spec 的 native children 和 body 中 `Parent` 回链。
命中为零时调用 `to-tickets` owner。完成标准：至少一张 ticket 的 ID、
spec 回链和 dependency edges 可读回。`/mattpocock-skills:to-tickets` 已发布的 tickets 直接作为待分配 execution graph。

**Dispatch gate：** 从 dependency graph 重算 ready frontier，选择无 mutable-resource
冲突的 maximal safe batch。从 integration worktree 为每张 ready ticket 创建 execution worktree
（`<parent>/worktrees/<repo>-map-<M>-issue-<N>/`），按 `references/frontier-lanes.md` 绑定规则
分流 kind 与 packet 模板，通过 `/pane-dispatch` 创建 pane（X tabs，4-pane capacity），派发 `implement` owner packet。
完成标准：registry 已 readback pane ID、worktree path、branch、base commit 和 attached waiter。
参考 `references/frontier-lanes.md`、`references/integration-worktree-management.md`。

**Startup probe：** 验证每个 pane 的 workspace/tab/cwd 正确，owner file 已读取。
错误时重试一次，第二次失败删除 worktree/branch/pane 并标记 `setup_blocked`。

**Integration gate：** 消费 worker terminal reports，按 dependency order cherry-pick commits
到 integration worktree。成功后运行 focused checks，通过则删除 execution worktree/branch、
关闭 pane、更新 registry 为 `integrated`、重算 frontier。冲突时中止并标记 `integration_conflict`，
保留 worktree 供调试。参考 `references/execution-worktree-integration.md`。

**Closeout gate：** execution graph 清空后运行 whole-change checks。通过后暂停在
test decision point，用户选择：(1) 在 integration worktree 测试，(2) rebase 后在 main 测试，
(3) 跳过测试直接 push。自动 rebase 到最新 main（冲突委托 `/mattpocock-skills:resolving-merge-conflicts`），
push 到 main，删除所有 worktrees/branches，关闭 panes（保留 workspace），关闭 map issue。
获得 remote publication authority 时 push/open summary PR/MR，等待 CI/CD 与 review verdict。
参考 `references/test-decision-and-rebase.md`、`references/remote-closeout-checklist.md`。

## 分配与恢复

**Ready 判断：** open、未被 claim、全部 blockers completed。不评估 ticket 大小、
拆分合理性或描述质量；`/mattpocock-skills:to-tickets` 已发布的 tickets 直接作为 execution graph。

**并发控制：** dependency 相连、文件/资源重叠或写集合无法证明独立时串行；其余并发。
按 tracker priority、dependency order、issue ID 确定性选择 maximal safe batch。

**Worker 隔离：** 每张 ticket 一个 lane、一个 owner、一个 worktree/branch。
Discovery AFK tickets 用 `Agent` tool subagent + 可选 worktree；implementation tickets
用 execution pane（claude 或 codex）+ 必需 worktree。Lane terminal 后由 coordinator 重算下一批，
worker 不自领 sibling tickets。

**Session recovery：** 新会话从 durable lane registry 恢复 existing lanes，
验证 worktree/pane 状态，重新挂载 listeners。参考 `references/child-monitoring.md`、
`references/lane-registry.md`。

**Fallback 模式：** `Agent` tool 不可用时输出完整 packets 作为 copy-paste fallback；
不假装已派发。`HERDR_ENV` 不可用或 `/pane-dispatch` 找不到 workspace 时，HITL panes 同理。

## 真相源

**产物层级：** map 索引 discovery decisions；spec 承载 scope；tracker tickets 是 execution graph；
lane reports + Git commits + checks 是执行证据；PR/MR 是远程收尾真相源。

**Gate 边界：** orchestrator 只检查产物存在性、回链、依赖和发布 readback。
内容质量由 owner skills 决定（`/mattpocock-skills:wayfinder`、`/mattpocock-skills:to-spec`、`/mattpocock-skills:to-tickets`、`/mattpocock-skills:implement`、`/mattpocock-skills:code-review`）。
不增加内容质量或拆票复审 gate。

**权限模型：** 自动分配使用 tracker write authority（lane registry checkpoint）。
本地 worktree/文件修改使用 local execution authority。Remote comment/push/PR/MR
需要 remote publication authority。

**语言约定：** 面向用户、workers、tracker、PR/MR 的自然语言使用中文；
skill/tool/status/path/hash 保持原样。

## 完成标准

Map decisions、spec、implementation tickets、lane commits/checks 和 summary PR/MR
已形成可追溯链路。Execution graph 为空，whole-change checks 与远程 CI/CD 通过，
remote review Agent 明确 can pass。没有 remote authority 时完成本地 integration，
报告唯一剩余 remote gate。
