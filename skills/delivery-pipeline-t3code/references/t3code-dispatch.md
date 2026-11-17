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
   `target_override` 为覆盖段的「绝对路径§小节」（无则 `none`），Coordinator Recovery 写明来源线程。
5. `t3_thread_launch` 在该项目开 coordinator 线程，prompt 为 `/delivery-pipeline-t3code` 加 registry 绝对路径，
   要求它按 §恢复 接管。用户对跨仓 map 调用本壳即是开这个线程的请求。
6. 回复新线程 `link` 后结束本轮；来源线程不再派发、不 fan-in 该 map。

完成条件：registry 可读回目标仓库坐标、`target_override` 与新 coordinator 线程；新线程的 Preflight 第 2 步通过。

## Preflight

每批 maximal safe batch 前做一次只读 snapshot：

1. `orchestrator_capabilities` 读回 `parentThreadId`、`inheritedProviderInstanceId`，目标 provider
   `canRunChildTask: true`；跨 provider 时还要 `canRunCrossProviderChildTask: true`。
2. `t3_worktree_status` 读回 `projectWorkspaceRoot`；它与 coordinator 当前 checkout（`attached: true`
   时为 `worktreePath`）的 `git rev-parse --git-common-dir` 都等于 Source repo 的 common dir。T3 从
   coordinator HEAD 在该 project 根下建子 worktree；任一 common dir 不同时报告 `dispatch unavailable`。
3. 按 `integration-worktree-management.md` 核对 Integration branch 与 clean state，冻结本批
   `base_sha`：普通 map 为当前 Integration HEAD；`delivery_mode: ticket_release` 为刚 fetch 的
   远端默认分支 SHA。

## Target 映射与配置 gate

本节替代 `model-role-routing.md` §Dispatch 验证第 2、3 步；第 1、4 步不变。配置实例是 CLI 实例
`~/.config/delivery-pipeline/model-roles.json`，先按 `model-config-schema.md` 用 setup 的
`model_config.py validate` 校验，阶段计划按 `model-role-routing.md` 冻结。

| work `agent` | `target.providerInstanceId` | effort option id | branch prefix |
| --- | --- | --- | --- |
| `pi` | `pi` | `thinking` | `pi/` |
| `codex` | `codex` | `reasoningEffort` | `codex/` |
| `claude` | `claudeAgent` | `effort` | `claude/` |

每个不同的 `(agent, model)` 调一次 `orchestrator_capabilities(search: <model>)`：model id 与目录项
完全一致，effort 属于该 option 的 `values`。不一致时该
lane 写 `setup_blocked`，附目录候选 id，交 `delivery-pipeline-setup` 改配置；配置值原样使用。

## Registry Overlay

`t3code` overlay 归本壳所有。写入顺序：intent → `delegate_task` receipt → startup readback；每层
写入后精确 readback。

```yaml
t3code:
  coordinator_thread_id: <parentThreadId>
  coordinator_provider: pi | codex | claudeAgent
  provider_instance_id: pi | codex | claudeAgent
  effort_option: thinking | reasoningEffort | effort
  client_request_id: <lane_id>
  task_id: <taskId-or-none>
  child_thread_id: <childThreadId-or-none>
  link: <link-or-none>
  t3_branch: <T3 临时分支-or-none>
  executed_model: <executedModel-or-Unknown>
```

base 字段：`runtime: t3-task`；`worktree` 取子线程 `worktreePath`；`branch` 在 commit mode 为
`<prefix>issue-<coordinate>`，其他 mode 为 `none`；`base_commit` 为 `base_sha`。

## 派发关键路径

implementation 新建或 replacement 前，按 `gate-state-machine.md` 实施前置检查运行
`implementation_gate.py`，通过后执行：

1. registry 写 Base Schema 字段与 overlay intent，精确 readback。
2. 填写 `../assets/T3CODE_ROLE_DISPATCH_PACKET.md`，写入 `~/.config/delivery-pipeline/packets/<lane_id>.md`。
3. 调用 `delegate_task`：`task` 为 packet 全文；`title` 为 `map-<map> <role> #<coordinate>`；
   `target` 按上表映射，`options` 只含 effort option，不带 `environmentId`（linked environment
   不在本壳范围）；`isolation: "worktree"`；`mode: "async"`；
   `clientRequestId: <lane_id>`；`role` 取 commit→`implementation`、checks→`test`、
   verdict→`review`、artifact→`research`（design HITL 用 `design`）。`runtimeMode` 与
   `interactionMode` 继承 coordinator。
4. receipt 写 `task_id`、`child_thread_id`、`link`；HITL lane 写 `awaiting_human`，其余写 `running`。
   调用报错或回复丢失时保留原请求；原生请求键还受 provider session namespace 约束，
   不以 `clientRequestId` 相同推断跨 session 可安全重试。先沿原 receipt 读回；没有原坐标则
   保持 Unknown/blocked，不重发。同批其余 lane 继续。

## Startup Readback

receipt 的 `childThreadId` 为 null 时，任务落在 linked environment：`task_cancel(task_id)` 后写
`setup_blocked`。其余对每个 `child_thread_id` 调 `t3_thread_read`，要求 `relationshipToParent: subagent`、`worktreePath`
非空、`status` 属于 `preparing | queued | starting | running | waiting`，且 worktree 的
common dir 等于 Source repo。写 `worktree` 与 `t3_branch` 并 readback。不一致写 `setup_blocked`
并保留现场。

整批每项都已 `running`/`awaiting_human` 或 `setup_blocked` 后到达 Dispatch Handoff：逐条报告
lane 的 `link`，结束本轮。T3 完成唤醒接管后续，coordinator 不轮询。

## CLI 冻结计划

创建新五 work lane 前使用 canonical `model_config.py resolve` / `freeze_overlay`；packet 与
Registry base row 原样持久化 recovery_plan、recovery_progress（单行 JSON flow value），
写入 intent、真实 receipt、startup readback 后均用 `verify_overlay` 对账，不另造计划形状。
恢复先运行 `model_config.py recover <registry.md> [lane_id]`；错误/legacy 识别与字段语义
统一见 `../../delivery-pipeline/references/lane-registry.md`，不从当前配置补读。

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
