---
name: delivery-pipeline
description: Orchestrate a loose idea, Wayfinder map, spec, or implementation ticket graph through discovery, spec and ticket publication, configured CLI worker dispatch, integration, testing, review, and one summary PR/MR.
disable-model-invocation: true
---

# Delivery Pipeline

唯一 canonical CLI/Herdr 编排主干。同一份 skill 供 pi、Codex CLI 与 Claude CLI 使用；
当前调用会话就是 coordinator，当前会话的 agent/model 不进入 worker 配置。

```text
idea/map -> discovery -> spec -> implementation tickets
  -> configured role dispatch -> collect/integrate -> testing -> review -> summary PR/MR
```

`wayfinder`、`to-spec`、`to-tickets`、`implement` 和 `code-review` owner 各自拥有自己的
产物质量。本 skill 只识别当前 gate、解析 owner 的真实 SKILL.md、按六角色配置派发、
验证持久坐标并完成 Integration。

## 启动与配置 Gate

1. **读取配置。** 首先加载 `references/model-role-routing.md`。检查
   `~/.config/delivery-pipeline/model-roles.json`：必须是 version 3，具有严格 `gearshift` policy，且
   `planning`、`design`、`frontend`、`backend`、`testing`、`review` 六个角色都具有非空的
   `agent`、`model`、`effort`；只有 pi frontend/backend 可以额外声明 bootstrap model/effort。
   先从 setup skill realpath 运行其 `scripts/model_config.py validate <config>`，再验证普通与 bootstrap
   model evidence；缺失、非法或不完整时，在当前会话完整读取
   `../delivery-pipeline-setup/SKILL.md` 并执行初始化。配置 readback 通过前不进入下一步；skill 内没有默认 route，也不静默回落。
2. **识别输入、worktree 与 Coordinator Runtime。** 当前调用会话就是 coordinator，所在 pane 是
   Coordinator Pane；按宿主记录 `coordinator_runtime: pi-cli | codex-cli | claude-cli`，统一记录
   `dispatch_runtime: herdr`。从 Herdr caller context 读回当前 session/workspace/tab/pane；默认把当前
   Herdr Workspace 固定为新 lane 的 dispatch target，只有用户显式要求新 Workspace 才创建。
   读取 repo instructions、tracker operations 和输入 artifact，
   按当前 gate 渐进加载 references：fresh coordinator 才加载
   `references/gate-state-machine.md`、`references/fresh-session-boundaries.md` 与
   `references/lane-registry.md`；worktree create/recovery 才加载
   `references/integration-worktree-management.md`；lane dispatch 才加载
   `references/owner-skill-resolution.md`、`references/dispatch-runtime-routing.md`、
   `references/frontier-lanes.md` 与 `references/pane-lifecycle-rules.md`；fan-in 才加载
   `references/execution-worktree-integration.md`。同一 coordinator task 不因下一 lane 重读
   未变化的合同。
3. **重建链路。** 接受松散想法、Wayfinder map issue、已批准 spec issue 或已发布
   implementation tickets。裸 issue 编号必须能从当前 repo tracker 唯一解析；沿持久
   relationships 从最早未完成的 gate 继续。创建前先恢复该 map 已登记的 Map Integration Worktree/
   branch；不存在时创建独立 worktree 与 branch。所有 Git 操作显式指向隔离 worktree，不切换
   Coordinator Pane 当前目录的 branch。

启动完成标准：配置 version 3 与 Bootstrap Gearshift Policy 完整、当前会话已确认为 coordinator、
当前 Herdr session/workspace/tab/pane 已读回、输入/gate/worktree 已识别、`dispatch_runtime: herdr`
已持久化、active writers 已 readback。

## Gate 链

1. **Discovery。** 加载 `references/wayfinder-frontier-loop.md`。松散想法先执行
   `wayfinder` owner 建图；建图本身留在当前交互会话。AFK research 与 spec/ticket gate work
   使用 `planning` 角色 + `output_mode: artifact`；grilling、prototype 等 HITL lane 使用
   `design` 角色 + `output_mode: artifact`。配置决定 agent/model/effort，coordinator 不按宿主
   改写角色路由。完成标准：所有 in-scope decision
   tickets closed，resolution 与 artifacts 可读回。
2. **Spec。** 链路没有已批准 spec 时，解析 `to-spec` owner，填写
   `assets/HERDR_ROLE_DISPATCH_PACKET.md` 并按 `planning` 角色 + `output_mode: artifact` 派发。完成标准：已发布 spec 的
   URL/ID/body 可读回。
3. **Tickets。** 读取 spec 的 native children/sub-issues 与精确回链；命中为零时解析
   `to-tickets` owner并按 `planning` 角色 + `output_mode: artifact` 派发。完成标准：至少一张真实 ticket 的 ID、spec
   回链和 dependency edges 可读回。
4. **Implementation Dispatch。** 从 dependency graph 重算 ready frontier，选择无 external
   mutable-resource 冲突的 maximal safe batch；无前序依赖的 ready tickets 同批并发派发。
   每张 ticket 先分类为 `design`、`frontend` 或 `backend`，设置 `output_mode: commit`，再从配置
   取得 ordinary route。对 frontend/backend 机械计算 Gearshift eligibility：mode=`off` 时禁用；
   `opt_in` 要求 ticket 带配置 label；`all_eligible` 要求 pi role 有 bootstrap。enabled lane 使用
   bootstrap model 启动、ordinary model 作为 Target，并从 canonical skill realpath 用 `-e` 加载
   `adapters/bootstrap-trigger.ts`；其他 lane 不加载。解析 `implement` owner并创建唯一 Herdr lane +
   Execution Worktree。commit packet 同时写 `Review fixed point: <Execution Base commit>`、Review
   preflight 与 Gearshift Projection；`implement` owner 在本 lane 内调用 `code-review` 时先执行
   preflight。coordinator 不亲自实现。
   完成标准：本批每条 lane 已持久化 role、agent、ordinary model/effort、bootstrap route 或 none、
   Gearshift policy/projection、runtime、pane、worktree、branch 与 base commit。
5. **Startup Probe 与 Dispatch Handoff。** 按 `references/pane-lifecycle-rules.md` 的容量管理规则
   在 dispatch target Workspace 放置 lane pane(worker tab 最多 4 pane、四角分布、溢出开新
   tab),并将 cwd 绑定到对应 Execution Worktree;Coordinator Pane 只调度,不作为 worker
   pane。验证落点、启动配置指定的 CLI、投递 packet、聚合确认
   `working`。kind 与 runtime 必须匹配：
   pi → `herdr-pi-pane`，codex → `herdr-codex-pane`，claude → `herdr-claude-pane`。
   错误落点、owner 未读、ordinary/bootstrap model 不可用、Gearshift Core flags 或 Adapter realpath
   缺失时沿同一配置重建一次；第二次失败记 `setup_blocked`。enabled lane 必须 readback Source/Target、
   Adapter 与 Armed Shift 坐标；整批 startup readback 后统一 Dispatch Handoff 并结束本轮。
6. **Role-aware Fan-in / Integration。** 用户完成信号或 terminal event 只负责唤醒；按
   `output_mode` 验证持久证据：`commit` lane 才要求 commit并按 dependency order cherry-pick 到
   Map Integration Worktree，focused checks通过后写 `integrated`；`artifact` lane验证 tracker/
   artifact坐标后写 `consumed`，不要求 commit、不 cherry-pick。两类成功后都清理 pane/worktree/
   branch；unexpected dirty state fail closed。随后自动重算下一 ready frontier。
7. **Testing。** execution graph 清空后，按 `testing` 角色 + `output_mode: checks` 派发
   whole-change checks lane。配置决定 agent/model/effort；测试证据 readback后写 `consumed`，
   不要求 commit。通过才进入 review；失败时保留现场并报告精确失败。
8. **Review 与远程收尾。** 按 `review` 角色 + `output_mode: verdict` 解析并派发
   `code-review` owner。进入本 gate 时加载 `references/code-review-evidence-preflight.md`，从 map
   registry 的 `role: map` 行读取 Map Integration Worktree 创建时的 `base_commit` 作为唯一
   Review fixed point，并把该 fixed point 与 preflight reference 的绝对路径写入 dispatch packet；
   review worker 在 owner 派生 Standards/Spec 子审查前完成 Review Evidence Bundle。verdict/findings
   readback后写 `consumed`，不要求 commit。通过后加载
   `references/test-decision-and-rebase.md`，暂停在 test decision point；用户选择后 rebase 到
   最新 main，冲突时解析 `resolving-merge-conflicts` owner。remote publication authority 覆盖
   push、PR/MR、merge 与最终 closeout；没有 authority 时停在本地 Integration。

## 分配与权限不变量

- 配置文件是新 worker lane 启动 route 与 Gearshift policy 的唯一真相源；临时路由改变通过重新运行
  `delivery-pipeline-setup` 持久化，不做只存在于 coordinator 对话里的覆盖。
- Ordinary/bootstrap model 与 Gearshift route 只在 lane 启动时绑定；派发后用户在 worker pane 中
  手动改模型仍属正常操作，运行中与 fan-in 不做 pane model 对账，不因此重建 lane。Worker final
  report 必须记录实际模型历史；只有匹配 registry 的 Shift Record 才能声称 Bootstrap Handoff 完成。
- ready ticket = open、未被 claim、全部 blockers completed。dependency 相连的 tickets 按 graph
  顺序；普通 repo 文件路径重叠留给 Integration，不产生隐式 dependency。
- 每张 ticket 一个 lane、一个 owner、一个 Execution Worktree/branch；worker 不领取 sibling。
- 新 lane 默认留在 Coordinator Pane 当前 Herdr Workspace；新 Workspace 是显式用户选择，不承担
  Git 隔离。
- registry 先于 worker；一个 active writer；Execution Worktree 从当前 Integration HEAD 创建。
- owner 通过 name、绝对 SKILL.md path、runtime-specific invocation label 三字段解析；绝对路径是
  执行真相源，label 只用于说明。
- 本地 worktree、文件修改与 commit 使用 local execution authority；push、main、PR/MR、merge 与
  最终 publication 需要 remote publication authority。
- 所有面向用户、workers、tracker 和 PR/MR 的自然语言使用中文；skill/tool/status/path/hash 保持原样。

## 完成标准

map decisions、spec、implementation graph、lane commits/checks、testing 与 review 已形成可追溯
链路；execution graph 为空，whole-change checks 通过。获得 remote authority 时远程 CI/CD 与
review verdict 通过；否则报告唯一剩余 remote gate。
