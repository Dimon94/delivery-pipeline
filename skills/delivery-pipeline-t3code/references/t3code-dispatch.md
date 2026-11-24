# T3Code 调度运行时路由

创建或替换 worker lane 前读取。本文件是 canonical 主干的 T3Code transport adapter：coordinator
是当前 T3 线程，所有新 worker 都是 `delegate_task` 子任务。恢复既有 lane 直接读
`t3code-lifecycle.md` §恢复，不运行新 lane 的配置 gate。

canonical 合同位于 `../../delivery-pipeline/references/`，下文以文件名引用。

## 跨仓路由

T3 只从 coordinator 线程所属项目的根目录建子 worktree。目标仓库（Spec 或票面 `Repo:`）的 common dir
与 coordinator checkout 不同时，本线程派不出 lane（Preflight 第 2 步必然失败）；先做路由，不先派发再失败。
失败例子：在父仓线程里对子仓 map 直接 `delegate_task`，子 worktree 建在父仓，startup readback 报 common dir 不符。

1. 读目标仓库 AGENTS.md 的 Git 规则，再读 coordinator 所在仓库 instructions 里点名该目标仓库的覆盖段
   （例：ads-decision-system 根 AGENTS.md `<tk_ada>`「交付覆盖」）。目标仓库禁止建分支且没有用户覆盖授权时，
   停下问用户。
2. 按 `integration-worktree-management.md` 在目标仓库建或复用 Map Integration Worktree；路径与分支名取覆盖段，
   没有覆盖段时取目标仓库约定。
3. `t3_project_list` 找 workspace root 等于该集成 worktree 的 T3 项目，没有就 `t3_project_create`。
4. 写 map registry：`source_worktree_path` 为目标仓库主 checkout，`integration_worktree_path` 为集成 worktree，
   `target_override` 为覆盖段的「绝对路径§小节」（无则 `none`），`t3_project_id` 为第 3 步的项目 id，
   Coordinator Recovery 写明来源线程。
5. `t3_thread_launch` 显式传 `projectId: <t3_project_id>` 开 coordinator 线程，prompt 为 `/delivery-pipeline-t3code`
   加 registry 绝对路径，要求它按 §恢复 接管。用户对跨仓 map 调用本壳即是开这个线程的请求，不再问用户。
   只用 `t3_thread_launch`：`create_threads`、`delegate_task` 和缺 `projectId` 的调用都继承调用方项目，线程会落回原仓。
   工具清单里看不到 `t3_thread_launch` 时先直接调用一次（T3 工具可能延迟加载），调用报不存在才算不可用。
6. `t3_thread_read(新 threadId)` 读回 `thread.projectId` 等于 `t3_project_id`，再写 registry `coordinator_thread`。
   不等时 `t3_thread_organize(archive)` 错落线程，回第 5 步重开一次；仍不等或工具不可用时报告
   `dispatch unavailable`，附期望与实际 projectId。
7. 回复新线程 `link` 后结束本轮；来源线程不再派发、不 fan-in 该 map。

失败例子（JB-528）：来源线程以为没有 `t3_thread_launch`，改用 `create_threads` 并传 `target.projectId`；
该参数被静默忽略，新 coordinator 落在父仓项目。来源线程没读回就宣告移交，新线程 Preflight 失败后又把
「手动新建线程」交给用户，自动化调度停在人工步骤上。

完成条件：registry 可读回目标仓库坐标、`target_override`、`t3_project_id` 与新 coordinator 线程；
新线程的 `projectId` 读回一致。

### 错落项目自愈

本线程按 registry 接管，registry 有 `t3_project_id`，而 `t3_thread_read(本线程)` 的 `projectId` 与之不同：
本线程派不出 lane，但不把开线程交给用户。由本线程执行上文第 5–7 步重开 coordinator，prompt 沿用接管请求；
第 6 步的读回保证重开不会循环。本线程不写 lane、不运行 Driver，只回复新线程 `link`。

## Preflight

每批 maximal safe batch 前做一次只读 snapshot：

1. `orchestrator_capabilities` 读回 `parentThreadId`、`inheritedProviderInstanceId`，目标 provider
   `canRunChildTask: true`；跨 provider 时还要 `canRunCrossProviderChildTask: true`。
2. `t3_worktree_status` 读回 `projectWorkspaceRoot`；它与 coordinator 当前 checkout（`attached: true`
   时为 `worktreePath`）的 `git rev-parse --git-common-dir` 都等于 Source repo 的 common dir。T3 从
   coordinator HEAD 在该 project 根下建子 worktree；任一 common dir 不同时，registry 的 `t3_project_id`
   与本线程项目不同则走 §错落项目自愈，否则报告 `dispatch unavailable`。
3. 按 `integration-worktree-management.md` 核对 Integration branch 与 clean state，冻结本批
   `base_sha`：普通 map 为当前 Integration HEAD；`delivery_mode: ticket_release` 为刚 fetch 的
   远端默认分支 SHA。

## 新 work lane 的入口

implementation 新建或 replacement 前，按 `gate-state-machine.md` 实施前置检查运行
`implementation_gate.py`。新派发统一调用本壳 [work_dispatch.py](../scripts/work_dispatch.py)，由
[native_host.js](../scripts/native_host.js) 转发。正式 review 走下文 Whole-change ReviewPlan，
已认领 replacement 走原 Registry intent。

- `action: dispatch`，`path` 为 map 目录下本 lane Registry 的绝对路径，`source` 为 Source repo 绝对路径。
  `row` 给 `lane_id`、`work_item`、`map`、`role`（Task Binding）、`output_mode`、`base_commit`；
  有票时可加 `ticket_url`、`wave`，merger 加 `merges`。
  `task` 给派发模板的工作合同（owner、范围、验收、输入）。`target_override` 仅填 map Registry 的目标仓覆盖章节坐标。
  `ticket_mode`、`map_mode` 仅传票面或 map 显式点名的配置预设。
- Adapter 从 `~/.config/delivery-pipeline/model-roles.json` 取计划，用实时能力证据核验精确 provider、
  model 和 effort，并复核同仓。用原样冻结计划生成 packet 和原生请求。安装配置或能力不足时返回 `setup_blocked`，
  拒绝在 Registry 预留前发生时无 lane 行。目标仓说明只影响工作合同，人工传入模型/配置路径会被拒绝。
- Adapter 在 Registry 预留本 lane 并读回后，转发持久化的唯一原生请求。收到 async `next` 先保存原回执，
  用返回的 lane/link 结束本轮。Driver 后续直接读取该 Registry，普通 work lane 不再手写派发回执。
- `action: recover` 接原 `path` 和 `lane`；沿原任务及子线程读回父线程、provider、model 与 worktree，
  独立 `executedModel` 缺失记 Unknown，明确不符则保留现场并阻塞。成功写 `running` 或 `awaiting_human`。
  缺原回执坐标时保留 Unknown/blocked，同一 lane 的派发入口拒绝再次启动。

### 宿主调用

Pi 的 codemode 转发示例。`adapter` 是本壳已解析的绝对 `scripts` 路径，`invocation` 按上文填写。

```js
const module = {exports: {}};
eval(await tools.read({path: adapter + '/native_host.js'}));
const native = {
  orchestrator_capabilities: tools.mcp__t3_code__orchestrator_capabilities,
  t3_worktree_status: tools.mcp__t3_code__t3_worktree_status,
  t3_thread_read: tools.mcp__t3_code__t3_thread_read,
  delegate_task: tools.mcp__t3_code__delegate_task,
  task_cancel: tools.mcp__t3_code__task_cancel,
};
const response = await module.exports.runWorkDispatchWithBash(
  ['python3', adapter + '/work_dispatch.py'], invocation, tools.bash, native);
text({state: response.result.state, lane: response.result.lane_id,
      link: response.result.t3code?.link,
      gap: response.result.reason ?? response.result.t3code?.startup_gap,
      next: response.result.t3code?.receipt?.next});
```

有持续标准输入接口的宿主使用 `runWorkDispatch(command, invocation, processIO, native)`，
`processIO.exec/write` 绑定宿主终端 I/O。两种宿主均直接转发 Adapter 的工具参数。
缺少可用转发时报告 `dispatch unavailable`，保留原工作合同。

`t3code` overlay 保存 `native_request`、`receipt`、`startup_state` 和原生任务坐标；核验后补
`worktree`、`t3_branch`、`executed_model`。完成或提问唤醒后走 [生命周期](t3code-lifecycle.md)。

## 已认领 replacement 的生产调用

有冻结计划的 replacement 不走上面的新 lane 配置解析。唯一执行入口为
`../scripts/native_replacement.py::NativeReplacement.execute`，宿主调用方为
`../scripts/native_host.js::runNativeReplacement(command, invocation, processIO, native)`。
`native` 绑定当前线程官方 `task_status`、`t3_thread_read`、`delegate_task`；
`processIO.exec/write` 分别绑定宿主终端执行/标准输入接口。它只转发 Python 发出的工具请求，
不能把观察替换成固定 writer/capability 真值。

`command` 是当前独立 checkout 中 `python3 <绝对路径>/native_replacement.py`；
`invocation` 含 `action: execute`、`registry` 绝对路径、已认领的 `lane`、完整 `task` packet、
本线程最近一次官方 `orchestrator_capabilities` 原始 `structuredContent`（`capabilities`）。
原生版本/合同须在本批 preflight 留证：稳定键、隔离和原请求读回缺证据时不启动。
先核对本机版本匹配合同，再用该入口，不能把 payload 构造视为已派发。

认领仍归 canonical `lane_registry.claim`；`action: claim` 仅将该接口与 Adapter 的实时
`observe` 接线，参数为原 `source/revision/failure_id/category`，不另选模型或计数。
先有 source 终态通知再认领：读取原 task/thread，要求原父线程、provider/model 一致，
无 active run 或待子任务。没有原生 task/thread 坐标时拒绝，不用别的 transport 回执代替。

执行使用冻结 triple、`isolation: worktree` 和 successor `lane_id` 作为 `clientRequestId`。
唯一 intent 在 I/O 前写 launching，原生 receipt 仍存在同一字段。收到 async `next` 后只做
本地持久化并结束本轮；完成唤醒后再次 execute，沿原 receipt 的 child thread 独立读回，
核对父线程/target/worktree 同仓与 executedModel；请求值不能当 applied effort。
同一 receipt 的 task/thread/link/worktree/临时 branch/executedModel 同步投影到既有
`t3code` overlay，供生命周期直接消费；不另存一份 receipt。`completed` intent 表示启动已对账，
lane 的最终结果继续由既有 fan-in 负责。

receipt 缺失、原生拒绝、读回失败或身份冲突保留 launching/Unknown；不再 delegate，不换键，
不推进游标，不声称未启动。已完成 intent 重放直接返回原行；启动失败的正面分类若无原生
绑定证据仍 Unknown，不能凭工具异常把后项消费掉。跨 provider session 的无回执对账能力
当前 Unknown。普通无冻结计划 lane 继续走原合同，不由本入口重建计划。


## Whole-change ReviewPlan 原生入口

Review 不走 work replacement。使用 `native_host.js::runReviewDispatch` 转发
`python3 <本树绝对路径>/scripts/review_dispatch.py`（同目录 helper）；宿主绑定再增加
`orchestrator_capabilities`。沿用同一个 JSON lines driver，不创建第二路由或账本。

1. action=prepare：输入 config 原文、ledger 路径、round 参数（round_no/base/head/request_id/
   implementations/interface_changed/dependencies_changed）。implementations 必须由 canonical
   collect_implementation_identities 从所有已集成贡献 Registry 收集，含修复者。
   prepare_round 决定 required axes/复用；same head 返回原完整 result，不创建 lane。
   各参与池现场 `orchestrator_capabilities(search=精确 model)`，冻结完整 snapshot；
   provider/model/options/permission 缺证据阻断，截断目录未命中记 Unknown，正面不可用可跳过。
   canonical resolver 唯一选序，单模型也执行原生 preflight。结果为 packet，尚无派发。
2. action=dispatch：path=本轮 Registry、row=唯一 lane/work_item 等 base 字段、packet、
   owner={name,path,invocation_label}、task=完整 evidence bundle/固定点/只读工作合同。
   所选 lane 与轴再核验，reserve_review 冻结同轮 plan/packet/request，再持久 launching，
   最后唯一 delegate_task；receipt 在 t3code overlay。收到 next 立即交还宿主，不轮询。
3. action=recover：path/lane，只读原 plan/packet/receipt。inspect_original 时沿原坐标读取，
   没回执为 Unknown，不再次 dispatch；cancelled/consumed/closed/failed 返回 stop。
4. action=fan_in：packet、完整 axes（含 findings）、coordinates={axis:{thread_id,run_id}}、
   ledger、round_no、p2_issues。坐标来自 owner 原生轴结果，不传 lane 坐标冒充各轴。
   只从精确 run 的 recentRuns.executedModel 取实际模型；model/options 不作证明。
   当前 schema 无 applied effort，保留 Unknown。唯一 review_gate 分类并保存 findings，
   只有 PASS 放行；REVIEW_BLOCKED 不自动重跑。不重复 gate；恢复读原 ledger。

公开检查：setup `check_config_review.py --case t3-review-plan` 与本壳
`check_review_dispatch.py --case native-evidence`。这些是外部 I/O 替身检查；真实能力、
派发、逐轴执行和 applied effort 验收独立由 Root 受控完成，未运行时 Unknown。
