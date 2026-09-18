# Orca 独立 delivery-pipeline 开发 Spec

状态：Spec、测试切入点与九票粒度/依赖已确认，规划已收口。本次确认不启动代码实施。

确认记录：四阶段、按操作检查 capability、复用原生 discovery 的既有决策保持。用户针对完整测试切入点与九票报告回复“确认，”，批准记录及获批快照 hash 见 [Spec #129 确认记录](https://github.com/Dimon94/delivery-pipeline/issues/129#issuecomment-5646715861)。后续复用这份确认，不重新询问；依赖、capability 和各票真实验收仍须核验。

Tracker spec issue：[#129](https://github.com/Dimon94/delivery-pipeline/issues/129)

关联 Wayfinder map：[#114](https://github.com/Dimon94/delivery-pipeline/issues/114)
研究与决策票：[#115](https://github.com/Dimon94/delivery-pipeline/issues/115)、[#116](https://github.com/Dimon94/delivery-pipeline/issues/116)、[#117](https://github.com/Dimon94/delivery-pipeline/issues/117)、[#118](https://github.com/Dimon94/delivery-pipeline/issues/118)、[#119](https://github.com/Dimon94/delivery-pipeline/issues/119)

研究 artifact：

- [初步可行性研究](../research/2026-09-12-herdr-orca-feasibility.md)
- [lane registry 合同](../research/2026-09-12-orca-lane-registry-contract.md)
- [真实本地 worker 原型](../research/2026-09-12-orca-worker-lifecycle-prototype.md)
- [CLI/capability/discovery 合同](../research/2026-09-12-orca-cli-capability-contract.md)

> 事实优先级：真实 Orca 运行证据 > 代码与 validator > 本 spec/accepted ADR > 推断。没有当前运行证据的能力必须写为 Unknown，不得以 capability 宣布、CLI help 或名称推断项目交付事实。

## Problem Statement

当前仓库提供共享的 `delivery-pipeline` CLI/Herdr 主干和独立的 Codex App transport 壳，但没有独立的 Orca 入口。用户无法在不迁移既有 lane、不复制 Herdr 调度器、不中断 Codex App 的前提下，使用 Orca 原生 Run/Task/Dispatch、Execution Worktree、worker lifecycle、等待、恢复和远程能力完成一条可审计的交付链。

该入口复用 map、ticket、lane registry、checkpoint、Integration、testing、review 和 cleanup 合同，将 Orca 的原生坐标和 observation 绑定到项目侧证据。

## Solution

新增独立 `$delivery-pipeline-orca` 入口。它是 Orca runtime-specific transport shell，不替代 `delivery-pipeline` 主干，也不替代 `$delivery-pipeline-codex-app`。

该入口：

1. 先读取当前 Orca binary 提供的 version-matched `orca-cli` / `orchestration` skill/reference；CLI schema 是执行接口，未声明的 command、flag、field 或状态不得猜测。
2. 检查当前 runtime、目标 execution host 和本次 operation 所需 capability；以 receipt/readback 证明 effective agent、model、effort、Run、Task、Dispatch、terminal 和 worktree 坐标。
3. 复用项目侧 map/spec/ticket gate、共享 lane registry、checkpoint、Git Integration、testing、review、cleanup 和 remote authority。
4. 以一个 map 一个 Orca Run、一个 work item 一个 delivery lane、一个 lane 一个 long-lived Task、一个 Task 允许多个 Dispatch attempts 的方式运行。
5. 在 project-side authority gate 未通过前，不把 `worker_done`、PTY idle、settled 或 release 当作项目交付完成，不删除 dirty、未集成或 Unknown 的现场。
6. Orca runtime、CLI、capability 或 readback 不可用时 fail-closed，报告 `dispatch unavailable` 或具体 blocked 原因；不静默 fallback 到 Herdr 或 Codex App。

### 目标用户路径

```text
map → discovery → spec → tickets
→ Orca Run
→ Task / Dispatch
→ Execution Worktree / worker
→ worker_done / question / escalation
→ FIFO wait / ack / recovery
→ project-side fan-in
→ Integration
→ testing
→ review
→ cleanup / closeout
```

## User Stories

1. 作为交付协调者，我希望明确调用 `$delivery-pipeline-orca`，以便不会因环境检测而静默切换 transport。
2. 作为交付协调者，我希望 Herdr、Codex App 和 Orca 长期共存，以便已有 lane 不需要迁移。
3. 作为 lane 恢复者，我希望按 registry 保存的 `runtime` 恢复既有 lane，以便配置或当前宿主变化不会改变原 lane 的 owner。
4. 作为 map 协调者，我希望一张 map 只有一个 Orca Run，以便 coordinator 重启可以回到同一 namespace/inbox。
5. 作为项目维护者，我希望 project ticket 是 work item 事实源，以便 Orca Task 只承担执行映射，不取代 tracker。
6. 作为协调者，我希望每个 work item 只有一个 delivery lane 和一个 active writer，以便避免并发写坏同一交付物。
7. 作为协调者，我希望一个 lane 绑定一个长期 Orca Task，以便 retry 不创建语义重复的项目 ticket 或 lane。
8. 作为协调者，我希望失败 retry 在同一 Task 上创建新的 Dispatch attempt，以便保留 Task 历史和原生 circuit-break。
9. 作为协调者，我希望 retry 明确重复 agent、worktree、execution host 和 placement，以便不依赖隐式继承。
10. 作为 worker policy owner，我希望 Orca 复用共享 agent/model/effort/mode 配置，以便不存在第二份 routing policy。
11. 作为协调者，我希望仅在当前 Orca capability/readback 证明 agent 可用时启动，以便不把 pi 静默映射为 codex 或 claude。
12. 作为协调者，我希望 worker receipt 同时报告 requested/effective launch，以便区分请求参数和真实运行配置。
13. 作为协调者，我希望普通 worker 走 Orca 原生 `worker-start`，以便不复制 terminal lifecycle。
14. 作为协调者，我希望特殊 topology 才能使用低层 terminal API，以便低层路径不会成为默认第二套生命周期。
15. 作为项目维护者，我希望真实 Execution Worktree path、branch、base、HEAD、selector 和 execution host 被持久化，以便恢复时不靠名称猜测。
16. 作为协调者，我希望 Map Integration Worktree 仍由项目侧管理，以便它和 Execution Worktree 的 ownership 不混淆。
17. 作为协调者，我希望 Orca worker 先报告 `worker_done`，再由项目侧执行 Git/artifact/output-mode gate，以便 worker 完成不越权替代 Integration。
18. 作为协调者，我希望 `check --wait` 的完整 FIFO Delivery 被逐批处理后再 ack，以便不跳过旧消息或重复消费。
19. 作为恢复者，我希望 `worker-list` fleet verdict 优先于 `worker-show` PTY status，以便 idle 或 stale PTY 不被误判为完成。
20. 作为恢复者，我希望 `unverifiable` 或 execution host 失联时保留现场，以便不误 stop、abandon、retry 或 release。
21. 作为恢复者，我希望 mutation response 丢失时先 query 原 request，再用同一 retry request 幂等恢复，以便不重复创建资源。
22. 作为恢复者，我希望 coordinator 或 Orca runtime 重启后复用既有 Run、Task 和 registry 坐标，以便不产生第二个 writer。
23. 作为协作者，我希望 worker 可以提出 question、escalation 或 staged continuation，以便人类决策与接续都保留在同一 delivery lane。
24. 作为项目维护者，我希望 continuation 复用同一 Task 和项目 registry，而不是创建第二个 sidecar journal，以便恢复证据集中。
25. 作为 reviewer，我希望 `worker_done` 不直接把 lane 写为 `integrated`、`consumed` 或 `closed`，以便项目侧证据仍然独立。
26. 作为 cleanup owner，我希望先通过项目 cleanup gate，再 release Orca worker，再确认 archive/output，最后删除 worktree，以便不丢交付现场。
27. 作为 cleanup owner，我希望 dirty、未集成或证据 Unknown 时保留 worker/worktree，并进入可恢复状态。
28. 作为用户，我希望 Phase 1 就包含本地成功路径和最小失败恢复，以便首次交付不是只能 happy path。
29. 作为用户，我希望 browser、automation、GitHub/Linear、artifact、remote federation、PR/MR 和 merge 有明确进入条件，以便未来目标不会膨胀进不可验证的首版。
30. 作为维护者，我希望 Orca skill 复用 version-matched references 和项目已有合同，以便不复制完整产品链、状态机或 capability registry。
31. 作为安装者，我希望 manifest 只声明 Orca entrypoint 和原生 discovery 所需的 bundle 信息，以便不维护第二套 installer、lockfile 或 version matrix。
32. 作为维护者，我希望新增抽象可通过同一验收清单做删除/内联消融，以便最小实现可以被证据审查。

## Implementation Decisions

### 1. Runtime 与入口边界

- 新增与 `delivery-pipeline`、`delivery-pipeline-codex-app` 并列的 `$delivery-pipeline-orca`。
- 同一 map 的新 lane 只绑定一种 transport；不静默混用。跨 transport 混用需未来单独定义。
- 既有 lane 始终沿持久化 `runtime` 恢复，不迁移。新 Orca worker 使用 `runtime: orca`、`dispatch_runtime: orca`、`coordinator_runtime: orca-terminal`；map row 保留 `runtime: orchestrator`，另记 `dispatch_runtime: orca`。这些是项目 schema 扩展，不是 Orca API 枚举。
- Orca skill 严格依赖 Orca CLI/runtime；不可用时 blocked，不 fallback。
- Orca coordinator 是当前 Orca terminal；外部 coordinator 属于后续能力。

### 2. 复用边界

- 不抽取 `delivery-pipeline-core`。
- 共享语义仍由 canonical CLI 主干和其 runtime-neutral references 持有：gate、owner、work item、lane state、checkpoint、Integration、testing、review、cleanup 和 remote authority。
- Orca 壳只持有 Orca-specific entry instructions、capability gate、Run/Task/Dispatch lifecycle mapping、receipt/readback、Orca recovery 和 Orca cleanup adapter。
- 不复制 Herdr pane lifecycle、Codex App task lifecycle、完整 tracker state machine 或 Orca capability catalog。
- Orca 原生 skill/reference 是调度规范；Orca CLI 是执行接口；仓库 skill 不复制版本匹配 reference 正文。
- 不完整加载 canonical SKILL 后执行其 Herdr startup。共享 reference 中的 gate、Git 和 output-mode 段按索引复用；pane/session/watcher/cleanup 命令由 Orca 壳替换。共享配置 helper 的解析和冻结计划可复用，当前 `startup_request` 与 `continuation_request` 绑定 Herdr，不能直接调用来启动 Orca。
- planning 仍负责 discovery/spec/tickets，implementation 负责单票 commit，testing 负责 checks，resolved code-review owner 负责 Standards/Spec 两轴 verdict。三字段 owner 合同（name、绝对 SKILL.md path、runtime invocation label）沿用。Orca 负责运行这些 owner；不把 testing/review 偷换成 Herdr 调度或 worker 自评。
- 已 accepted ADR 的两级 worktree、配置唯一性与 current-workspace Herdr 规则保持各自作用域。实施时补充 Orca 独立 transport 的 ADR/术语及必要枚举，不能改写历史 ADR 来声称旧实现已支持 Orca。

### 3. 版本匹配和 capability gate

每次进入 Orca skill 或执行 capability-sensitive operation 时：

```text
resolve one Orca executable
→ read version-matched skill/reference
→ check runtime ready/reachable/connected
→ check operation-scoped capability / target-host readback
→ execute declared CLI command
→ read receipt and effective state
→ persist project-side coordinates/evidence
```

- 不新增 `orca-capabilities.yaml`、`orca-version-matrix.json` 或静态镜像 registry。
- Phase 1 必需能力缺失时整个当前 operation blocked；后续阶段能力缺失只阻塞当前 operation，不阻塞本地交付链。
- capability 宣布不是项目证据；远程 host 必须单独 readback。
- Unknown 只阻塞依赖该证据的操作。runtime/目标 host 不可达时禁止该 host 上的 mutation；仍可读取项目 registry、Git 与已持久 artifact。
- 只检查当前操作需要的 capability。以本次 binary 的 `agent-context`/`--help` 找命令，按 `skills get` 的 references 清单加载；不因首版缺 browser/remote capability 阻止本地 dispatch。`launch.requested/effective` 不足以证明实际 model/effort 时还需绑定当前 worker/turn 的独立 readback，禁止以参数回显充数。

### 4. 共享 lane registry 与 Orca overlay

共享 lane state machine 与 delivery 字段复用。新 transport 枚举见上一节，Orca-specific 坐标由壳内 overlay 合同定义。下列字段是项目设计，不能冒充 Orca 原生 JSON schema：

```yaml
orca:
  run_id: <id-or-none>
  task_id: <id-or-none>
  dispatch_id: <id-or-none>
  terminal_handle: <handle-or-none>
  worktree_selector: <exact-selector-or-none>
  execution_host: <proven-runtime-or-environment-identity-or-none>
  attempt_index: <native-observed-integer-or-none>
  coordinator_host_id: <runtime-identity>
  coordinator_terminal_handle: <proven-handle>
  mutation: <latest-operation/request-id/receipt-reference-or-none>
  observation: <source/observed-at/evidence-reference-or-none>
```

map row 持有 Run 与 coordinator 身份，worker 专属字段为 none；lane 的 Run 必须匹配 map。Task/Dispatch 创建前允许对应字段为 none，`running` 前必须齐全。`attempt_index` 只保存 Orca 已证实值，不派生第二个 retry counter。真实 Git path/branch/base/HEAD 继续使用 base registry 字段。

`mutation` 只保存当前操作的 operation、request ID 与 repo 外 receipt 引用；`observation` 只保存来源、时间与 evidence 引用，原始 CLI 输出留在既有 artifact 位置。没有第二份状态数据库或 journal。历史 attempt 由 Orca Task/Dispatch 与 tracker 原记录回读，不抹掉旧证据；Orca liveness、settlement、`nextAction` 均不能直接改写项目 lane state。

首次 Run/Task 创建与每次 Dispatch 前先持久化操作意图并 readback；返回后原位补真实 ID、effective launch 与证据，再 readback。若 request ID 随响应全部丢失，先按已知 Run/Task/资源枚举对账，Unknown 时禁止重发。只有当前 CLI 明确支持的 request identity 才可用于原生幂等恢复，不能用自行生成的 ID 宣称 exactly-once。

恢复先核对 map、Run、coordinator host 和旧 active writers，再读原 Task/Dispatch/Execution Worktree；terminal handle 失效时按 Dispatch 回读更新，不能对新旧 handle 双发。coordinator 接管必须证明旧 coordinator 不再拥有写权限，保留 origin identity；不新建 Run 绕过绑定问题。

一个 project ticket/work item 映射为：

```text
1 project work item → 1 delivery lane → 1 long-lived Orca Task → 1..N Dispatch attempts
```

一个 map 映射为一个 Orca Run。Run 是 coordinator namespace/inbox，不是项目交付状态机。

### 5. Phase 1 调度与本地生命周期

Phase 1 的普通 worker 使用 `task-create` + `worker-start --task`，确保已知 Task 可恢复。`worker-start --spec` 是 Orca 可用能力，但本壳不以它绕过项目的先记账步骤。agent、冻结 model/effort/mode、host、setup policy 和 worktree placement 必须明确。

新 Execution Worktree 从当前 Map Integration HEAD 建立，启动前冻结该 SHA，启动后核对 Git base、实际 path/branch 与完整 selector；不能把 prototype 的 `--base-branch main` 当生产默认。Source Worktree 不切 branch。ready frontier 同批从同一 Integration HEAD 分派，读回所有成功/失败 lane 后才交接；只有真实依赖或共享可变资源冲突限制并发。Orca Task ready 只是必要条件，项目 ticket 依赖、Integration 与 implementation gate 仍须通过。

Phase 1 复用既有 `gh` tracker 合同完成 map/spec/ticket 创建和 named-map 状态变更；Phase 2 扩展 Orca 原生 provider 联动，不推迟本地交付必需的 tracker 能力。

本地成功路径必须可证明：

```text
Run → Task → Dispatch → Execution Worktree/terminal
→ worker_done → check --wait → full FIFO batch ack
→ worker-list settlement/readback
→ project-side fan-in → Integration/testing/review
→ project cleanup gate → worker-release → archive/output readback → worktree rm
```

Orca `worker_done` 只表示 Orca Task/Dispatch settlement；不能直接授权项目 lane 进入 `integrated`、`consumed` 或 `closed`。

### 6. Wait、message、question、escalation、continuation

- `check --wait` 的 type filter 只控制唤醒，返回完整 FIFO Delivery。ack 前处理每条消息并完成所需 terminal ownership 决策，先把 Delivery/Task/Dispatch、待 fan-in 证据引用与下一动作持久化/readback，再 ack。ack 后崩溃从这些记录继续；重复 Delivery 不重复 Integration。不能先 ack 再丢失唯一 output。
- durable send/ask 不等于对方已读、已接受或已开始；question timeout 留下 durable question，必须显式 reply。涉及用户决策记 `awaiting_human`；其余 wait/timeout 保持可恢复检查点，不自动算失败。
- worker address 使用稳定 Dispatch ID，不以 terminal handle 替代。Orca worker preamble 的发送身份必须原样使用；不能猜造 capability token。
- staged 的 `starting` 必须首改、最小检查、repo 外原子 checkpoint，然后发中间信号并结束当前轮。它不发最终 `worker_done`、不进入 terminal fan-in。checkpoint 复用 canonical helper：`session_id` 是实际 provider session，绝不能拿 Task ID/terminal handle 替代；coordinator identity 与 Git/dirty/index/hash 必须匹配，Orca Task/Dispatch/Run 绑定保存在现有 evidence 引用。
- 接续保持同一 lane、Task、Execution Worktree 和原生 provider session；先证明停止/无 active writer、checkpoint 未过期，再经 canonical continuation 的 persist/readback/send lease 发送。request、accepted、新 turn、actual model/effort 分开留证；`execution_phase` 只在原 session 新轮 started 后转 executing。`worker-start --terminal` 不支持 model/effort，不能用它伪称完成换模；薄 Orca adapter 只有证明原生同 session 路径可行才执行，否则 blocked，不退回 direct。
- retry 是新 Dispatch attempt，continuation 是同一执行上下文的下一轮，两者不可混用。完整 Phase 1 必须提供至少一条共享配置 agent 的真实 staged 成功证据；只有 blocked/模拟结果不算功能交付。其他 agent 能力逐项验证，不建立映射或 fallback。

### 7. Retry、重启和 fail-closed recovery

- 只有正面 `failed` / `stopped` 证据才允许 retry；idle、timeout、missing response、`outcome_unknown` 和 `unverifiable` 不自动 retry。
- retry 在同一 Task 上创建新 Dispatch，显式重复 placement、agent、Execution Worktree 和 host；不新建 Run 或 project ticket。
- 复用 Orca 原生三次连续失败 circuit-break；不增加 project-side retry counter，也不通过新 Run 绕过 circuit-break。
- mutation response 丢失时先 `request-show`：`completed` 消费原 receipt，`pending` 按原合同用同一 `--retry-request` join/recover，`absent` 仍先 inspect，不能推断未执行。
- fleet 通常优先于 PTY。若 fleet 的 `missing_status`/`capability_unsupported` 等只是客户端证据缺口，按版本匹配 recovery reference 读取 execution-host 的正面 verdict；任一来源的 `unverifiable` 都不能提升为退出。
- 显式取消先取得可行动的 fleet/host 证据，再按 scope 调用 `worker-stop`；`worker-abandon` 只 fence orchestration，不证明进程已停。旧 writer 未排除时不可 replacement；取消保留 checkpoint/dirty，等待项目 cleanup gate。
- coordinator/runtime 重启时先读取已有 Run、Task、Dispatch 和 registry；无法确认 active writer、身份或 request outcome 时保留现场。
- host contact loss 和 `unverifiable` 时 fail-closed：不得自动 stop、abandon、retry 或 release。

### 8. Worktree 与 cleanup authority

- Map Integration Worktree 由项目侧管理；Execution Worktree 由 Orca 原生 worker 管理。
- 启动 receipt 返回的 path、branch、base、HEAD、selector、terminal 和 host 必须写入 overlay 并 readback。
- cleanup authority 在项目侧：先通过项目 cleanup gate，再 Orca `worker-release`，确认 archive/output，最后 Orca `worktree rm`。
- release 不等于 lane close；dirty、未集成、未归档或 Unknown 时保留现场。
- `commit` 沿 Execution Base review → 串行 cherry-pick → focused checks 进入 integrated；`artifact/checks/verdict` 验证后 consumed，不 cherry-pick。冲突/检查失败保留相应项目 state。独立 testing/review owners 经 Orca 运行，复用原质量 gate，不另造审查器。
- `worktree rm` 后核对 Orca registration、Git worktree 和本 lane branch。Orca 可能保留无法证明已合并的 branch；先证明范围/归属/集成证据再按既有 Git cleanup 删除，不能猜测 `rm` 已全清。失败记 `close_pending`，不回滚 integrated/consumed；最终 tracker resolution 与 lane closed 必须在清理读回后。
- settled worker 必须显式选择 reuse、retain 或 release。先决定 ownership 再 ack；最终 release 仍等项目 cleanup gate。reuse 只给同一 agent 的合法下一工作，显式 transfer ownership；dirty/Unknown 时保留现场，不调用 release 来伪装 cleanup。

### 9. 四阶段目标范围

#### Phase 1：本地可恢复交付闭环（首批必须实现）

包括 map/discovery/spec/tickets 到本地 worker dispatch、Execution Worktree、completion、project fan-in、Integration、testing、review、cleanup；同时包括 failed/stopped inspect、同 Task retry、coordinator/runtime restart readback、mutation response lost 的幂等处理、unverifiable fail-closed 和最小 staged continuation。

进入条件：本地 Orca runtime ready/reachable/connected；版本匹配 references 可读取；共享 agent/model/effort/mode 能证明可启动；receipt/readback 能证明所有必要坐标；项目侧 checkpoint、Git 和 cleanup evidence 可持久化。

#### Phase 2：本地外部协作

包括 browser/automation、GitHub/Linear mutation、artifact publish/read、PR/MR ready-for-review 和外部 evidence/readback。

进入条件：对应 operation capability、provider/host readback、project-side authority、幂等 mutation/recovery 和结果 readback 均有真实验证。Phase 2 失败不应破坏 Phase 1 本地交付。

#### Phase 3：远程执行

包括 federation/SSH、多 execution host、remote worktree/terminal、host capability negotiation、remote worker recovery 和 cleanup authority 交接。

进入条件：目标 host 单独 capability/readback；remote selector/path/branch/host 身份可绑定；连接丢失、stop verdict、release/archive 和 active-writer 交接有可重复验证。不能以本地 runtime capability 代替目标 host 证据。

#### Phase 4：远程交付收口

包括 PR/MR 创建、merge/rebase、remote closeout、远程 artifact/tracker/review/cleanup fan-in。

进入条件：remote publication authority 明确；provider mutation 有幂等 request/readback；merge/rebase、CI、review、artifact、tracker 和 cleanup 的项目 gate 完整；失败可恢复且不降低需求。

### 10. Manifest、安装与 discovery

- bundle manifest 增加 `entrypoints.orca: skills/delivery-pipeline-orca/SKILL.md` 与 `install.orcaSkillDirectory: skills/delivery-pipeline-orca`。共享依赖加 `orca-cli`、`orchestration`，按入口验证 runtime 依赖，Orca 不以安装 Herdr 为前提。
- 当前 CLI 已声明 `orca skills installed --json`（已安装 skill selectors）、`orca skills install`（Orca 自带 skill 注册表）、`skills get`（版本匹配 guide）。`skills install` 不能被假设为任意自定义 bundle 安装器；绝不能猜造 `orca skills install --skill delivery-pipeline-orca` 可用。
- 本仓继续以 source directory/软链安装：复用现有 installer 的 link helper，把独立 skill 交给被选 agent 的现有 discovery 目录；从 realpath 找 canonical siblings，不能只复制 Orca 壳后丢失共享依赖。Orca 端以 `skills installed --json` 的 exact selector/name 和目标 agent 的实际 owner 解析回读验收。安装结果不等于 runtime 可运行。
- 壳不实现注册、登录、发布、自动更新或版本管理。Orca 原生共享/安装能力只在当前 reference 证实支持该 artifact 且已授权时使用。跨 host 持久化/version pin 的运行结果仍是 Unknown。
- README 增加三入口、共享配置、严格 Orca 绑定和 blocked 行为；同批扩充既有 validator 的入口、依赖、路径和 runtime ownership 检查。现有 Herdr/App 安装验证必须持续通过。

最小文件与调用关系（实现坐标，当前不创建）：

| 坐标 | 责任与复用 |
| --- | --- |
| `skills/delivery-pipeline-orca/SKILL.md` | 独立入口，按最早 gate 引用共享 owner 合同，载入 Orca guide |
| `skills/delivery-pipeline-orca/assets/ORCA_ROLE_DISPATCH_PACKET.md` | work item/output mode、owner 三字段、冻结配置、Integration Base、checkpoint、项目权限和 Orca worker preamble |
| `skills/delivery-pipeline-orca/references/orca-dispatch.md` | overlay、操作顺序、startup/readback、FIFO 与 fan-in 的唯一 Orca 合同 |
| `skills/delivery-pipeline-orca/references/orca-recovery.md` | 原生恢复证据、same-session continuation、cleanup adaptation；引用 native guide，不复制整套状态机 |
| 壳内最小 helper（仅确有机械核验缺口时） | 解析/翻译与 evidence 校验；不拥有第二 scheduler、registry 或 event journal |
| `skill-bundle.json`、`scripts/install.sh`、`scripts/validate.py`、两份 README | 新入口安装、发现与校验；扩展已有机制 |

共享入口索引：`gate-state-machine.md`、`owner-skill-resolution.md`、`wayfinder-frontier-loop.md`、`frontier-lanes.md`、`lane-registry.md`、`integration-worktree-management.md`、`execution-worktree-integration.md`、`test-decision-and-rebase.md`、`code-review-evidence-preflight.md` 均位于 canonical `skills/delivery-pipeline/references/`。复用其中交付语义，排除 Herdr transport 命令。Checkpoint/continuation helper 位于其 `scripts/`；schema/配置解析复用 setup owner，原 Herdr 启动和 adapter caller 不复用。`checkpoint-and-recovery.md` 不存在，不作为依赖。

### 11. Shared worker policy

Orca worker 直接读取共享 worker policy。没有 Orca override；不将 agent 映射或替换。只有 capability/readback 证明目标 agent 可用才 dispatch。若 shared policy 指向当前 Orca 不支持的 agent，报告 blocked，并保留可恢复 packet/registry，不静默改用其他 agent。

## Testing Decisions

### 测试原则

测试最高层可观察行为：输入 map/spec/ticket、Orca CLI invocation、receipt/readback、project registry、Git/worktree、artifact/checkpoint、tracker transition 和最终 gate。不要把 skill 文案、私有 helper 布局或单个 JSON parser 的覆盖率当作 delivery correctness。

优先复用既有 seam：bundle `validate.py`、lane registry/checkpoint helper、项目现有 gate/readback、Orca CLI `--json` receipt 和真实临时 worktree。只有现有 seam 无法观察外部行为时，才添加最小 helper。

最高测试切入点是 coordinator 的一次操作：输入 map/spec/ticket 与已持久证据，观察真实 CLI argv/receipt、tracker registry、Git/worktree 与 gate 结果。用同一套场景校验原生适配和故障注入；真机 unavailable 时只记录 Unknown，不能把它当通过。运行真机前限定临时 repo/worktree 与资源所有权；不为测试重启用户整个 Orca runtime 或干扰无关 worker。Phase 1 完成需 #120–#124 全部验收通过，尤其 staged/recovery 成功证据，不接受仅能正常启动的半条链路。

### Phase 1 验收矩阵

| 场景 | 必须证明 | 不通过时 |
| --- | --- | --- |
| runtime preflight | Orca version、runtime ready/reachable/connected、version-matched references 可读 | blocked，不 fallback |
| local success | Run/Task/Dispatch、effective launch、terminal、Execution Worktree、worker_done、FIFO ack、settlement、project fan-in、Integration、testing、review、cleanup | 不得宣称完成 |
| duplicate/restart | 同 map 复用 Run；重启不创建第二 Run/Task/active writer | 保留现场，标 Unknown/blocked |
| failed/stopped retry | inspect 后同 Task 新 Dispatch，placement/agent/worktree 明确，原生 circuit-break 生效 | 禁止自动 retry |
| request response lost | request-show/readback；同 retry-request 幂等；无重复资源 | 保留现场 |
| question/escalation | durable message/question、reply/decision 可回读并绑定 Dispatch | 保留 awaiting_human |
| continuation | 同 lane/Task/worktree/provider session；起步停止、checkpoint hash、send lease、新 turn 与 actual model/effort 分开证明；至少一条真实 staged 成功路径 | blocked，不能只凭 blocked 宣称完成 |
| unverifiable | 不 stop/abandon/retry/release，不删 worktree；正面 host 证据另行回读 | 保留现场 |
| cleanup gate | 项目 gate → worker-release → archive/output → worktree rm；dirty/Unknown 保留 | `close_pending` |
| shared agent policy | requested/effective agent/model/effort readback；无映射/fallback | `dispatch unavailable` |
| missing capability | operation-specific blocked reason | 不影响已完成本地链路 |

### 后续阶段验收

每个后续阶段必须新增真实 capability/readback 和 provider/host-specific mutation test；其失败不能把 Phase 1 的已完成证据重置为 Orca worker idle 或 done。Remote/PR/MR/merge 测试必须覆盖 active-writer、权限、幂等 mutation、恢复和 cleanup authority。

#### Phase 2 外部协作

选择 delivery 相关 browser/automation 场景（如测试页面操作/截图与有限自动任务），结果绑定 map/lane、execution host、URL 或 job ID、artifact 与验证时间。创建/触发/暂停自动任务分别核对既有授权；不自行扩大成无限 recurring scheduler。Browser 发出外部消息或修改外部数据沿对应 authority，而只读检查不新增确认。

Provider operation 必须核对登录身份、目标坐标、capability 与 authority；mutation 以原生 request/结果 readback 幂等恢复。Provider 没有 retry-request 时，回读已有对象和稳定身份，不能把 Orca orchestration 的参数套用到别的 CLI。GitHub/Linear tracker 联动、artifact publish/read/archive 和既有 PR/MR ready 状态分别有真实用例；发布/删除仅在已授权时执行。provider 的成功状态不替代项目 testing/review，失败不能抹掉本地证据。

#### Phase 3 与 Phase 4

远程先验证 exact host/repo selector、明确 placement、源代码 base 与 artifact 取回；local coordinator 仍持有该 map Run，execution host 只拥有原生执行事实。多 host 的 writer 排他、host contact loss、分页 fleet、transcript source/cursor、release/archive 都有失效测试。外部 coordinator 接管需证明原 coordinator 已退出并复用同 Run；该真实能力未验证前 blocked。

Phase 4 使用既有 test-decision/rebase/remote-closeout 与 code-review owner：本地集成/整体验证证据 → remote authority → push → PR/MR → CI/remote review → 明确 merge 权限 → parity/readback → cleanup。外部 API 的未知响应先检查已存在 PR/MR、remote ref、合并状态，禁止盲重做。以实测 provider 场景证明 CI 失败、审查失败、冲突、推送失败、merge 成功响应丢失的恢复；所有 provider 无关性只是设计要求，不是未经验证的兼容承诺。

### Prototype 证据边界

原型 [#115](https://github.com/Dimon94/delivery-pipeline/issues/115) 真实验证了本地成功生命周期和 cleanup 的 Orca 原生部分；没有验证失败 retry、runtime restart、mutation response lost、remote federation 或项目 registry recovery。它不能替代对应 Phase 1 实现票的测试。

## Out of Scope

- Herdr 或 Codex App 既有 transport 行为改造；
- 既有 lane 自动迁移、跨 transport 静默混用、agent fallback 或第二份 worker policy；
- `delivery-pipeline-core` 抽取；
- 把全部 Orca 产品命令代理进 skill；只覆盖影响 delivery-pipeline 的能力；
- 在 spec 阶段实现 Orca skill、manifest、registry、脚本或 runtime code；
- 未有证据的 capability/version compatibility 承诺；
- 无 remote publication authority 时的 push、PR、merge、closeout；
- 用文档交接、新任务、fork 或独立 subagent 冒充同 Task continuation；
- 通过项目侧第二个 retry counter 或新 Run 绕过 Orca circuit-break；
- 把隐藏推理、宿主压缩后的逐 token 历史完整性当成可交付保证。

## Further Notes

### Known / Unknown

已知：本机 Orca 1.4.200 已验证 runtime ready/reachable/connected；本地 Run/Task/Dispatch、Codex worker、new-child Execution Worktree、真实 path/branch/HEAD、worker_done、FIFO wait/ack、settlement、worker-release、archive 和 worktree rm 已完成 prototype。

Unknown：失败/stopped/`--retry-of` 真机路径；coordinator/runtime restart；mutation response lost 和 `--retry-request`；项目 registry 写入/恢复；worker_done 最终 evidence 字段；所有 agent id 稳定闭集；远程 host effective model/effort；skill install/discovery 持久化/version pin；browser、GitHub/Linear、artifact、federation、PR/MR mutation 的完整项目证据合同。

### Avoid-overengineering 消融记录

使用同一验收集合：三 transport 共存、持久身份、无重复 writer、项目证据后 fan-in、缺能力阻塞、dirty 保留、可恢复清理。下表是设计反例检查，均为“推断”；本轮未实现 Orca 壳，原生行为删除实验全部为 **Unknown / 未运行**。不能据此宣称 Phase 1 已运行通过。

| 候选设计 | 删除/内联尝试 | 同一验收清单结果 | 结论 |
| --- | --- | --- | --- |
| 独立 Orca shell | 直接在 canonical skill 中自动检测 Orca | 会破坏显式 runtime 绑定、三 transport 共存和 existing lane 按 marker 恢复；缺少 Orca 时可能改变既有 transport 行为 | 保留独立 shell |
| 嵌套 `orca:` overlay | 将 Orca 坐标铺到 base registry 顶层 | 会把 transport-specific 字段扩散到 Herdr/App lane，并增加未来并存冲突；不满足 runtime-neutral base | 保留 overlay |
| project-side receipt/readback | 直接把 Orca settled 当 project lane completion | 无法证明 Git、Integration、artifact、review 和 cleanup authority；会把 `worker_done` 越权成 close | 保留 project evidence gate |
| 每 map 一个 Run | 所有 map 共用一个 Run | 破坏 map namespace 隔离和 coordinator restart 的幂等恢复 | 保留 one-map-one-Run |
| 同 Task retry | 失败时新建 Task | 丢失 Task 历史并绕过 Orca 原生 circuit-break，且产生重复 lane 语义 | 保留 same-Task retry |
| operation-scoped capability gate | 先创建资源，再在 operation 中发现 capability 不足 | 可能产生半创建资源，且无法在执行前给出 blocked reason | 保留 preflight gate |
| 低层 terminal helper | 让普通 worker 默认走低层 terminal API | 与已验证的 `worker-start` 生命周期重复；增加第二套 stop/read/release 语义 | 不新增 helper；只保留特殊拓扑边界说明 |
| 自定义 installer/version matrix | 复制 Orca capability、安装和版本判断 | 形成漂移源；当前 host install/discovery/version pin 仍 Unknown，无法证明复制后更可靠 | 不新增；复用 bundle metadata + Orca native discovery |

本轮实际文档简化：移除重复消融清单，以本表为唯一记录；区分共享配置解析与 Herdr 命令生成；testing/review 质量逻辑复用原 owner。设计验收仍覆盖同一集合。实施前后行为消融必须随实现重跑，暂不以删行后的静态验证证明 runtime 等价。

DRY record：scope 为 Orca 薄壳设计；searched 为 canonical references、checkpoint/continuation、setup model_config、App 壳、manifest、installer 和原生 guides；reused 为项目 gate/Git/config 与 Orca lifecycle；remaining duplication 仅为必要的 transport 证据翻译和远程审阅快照，canonical copy 唯一。

### 交付顺序

1. 先实现 Orca entrypoint、manifest/discovery、runtime/capability preflight 和共享 policy readback。
2. 再实现 registry overlay、Run/Task/Dispatch/local worktree、FIFO wait/ack 和 project fan-in。
3. 再实现 Phase 1 recovery、continuation、cleanup 和真实验证。
4. 然后按 Phase 2、3、4 分别交付 operation-specific tickets；每阶段保留自己的 authority gate 和 readback。

### Implementation tickets

- [#120](https://github.com/Dimon94/delivery-pipeline/issues/120)：Phase 1A 独立入口与 capability preflight
- [#121](https://github.com/Dimon94/delivery-pipeline/issues/121)：Phase 1B lane overlay 与 map Run 恢复
- [#122](https://github.com/Dimon94/delivery-pipeline/issues/122)：Phase 1C 本地 worker dispatch、Execution Worktree 与 FIFO settlement
- [#123](https://github.com/Dimon94/delivery-pipeline/issues/123)：Phase 1D 项目 fan-in、Integration 与 cleanup closeout
- [#124](https://github.com/Dimon94/delivery-pipeline/issues/124)：Phase 1E recovery、retry 与 staged continuation
- [#125](https://github.com/Dimon94/delivery-pipeline/issues/125)：Phase 2A browser/automation operation gate
- [#126](https://github.com/Dimon94/delivery-pipeline/issues/126)：Phase 2B tracker、artifact 与 PR/MR 状态 mutation
- [#127](https://github.com/Dimon94/delivery-pipeline/issues/127)：Phase 3 remote federation 与多 execution host
- [#128](https://github.com/Dimon94/delivery-pipeline/issues/128)：Phase 4 remote publication、PR/MR merge 与 closeout

逐票 token 预测、依赖、加载坐标与条件拆分见 [ticket sizing](2026-09-12-delivery-pipeline-orca-ticket-sizing.md)。规划确认不授权代码实施；后续收到实施指令时复用现有票及确认记录，不重复创建或重问。每票完成时仍须通过 assigned 外部行为验收和项目 authority gate。
