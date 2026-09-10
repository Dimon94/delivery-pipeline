# Codex App 开发模式

coordinator 启动时与每个 worker 执行前读取。本文件拥有 App 工作分工、内部辅助和技术咨询；
所有模型选择读取 `../config/models.json`；正式双轴审查仍由 resolved `code-review` owner 执行。

正式 Review 的生命周期与放行由 coordinator 管理，优先于下文及旧 owner 的 worker 内嵌
Review 步骤。implementation worker 可保存候选 commit，缺最终结论则 blocked 回传并注明待审；
coordinator 接收后按 `codex-app-dispatch.md` 的“独立 Review 放行”启动两轴并验收。
worker 内已有审查只作预审；可由 coordinator 回读现有有效结果复用，不必再做相同审查。
coordinator 将 resolved owner triple 与 `review_scope: implementation | whole-change` 一并传递，
App 壳从配置解析两轴模型作为显式参数传给 owner，不选择或替换 owner。中断复核、自评或测试通过不能替代 verdict；
模型覆盖不等于用户豁免审查。

## 工作分工

模型与 effort 的唯一默认来源是本 skill realpath 下的 `config/models.json`，用户明确选择优先。
启动与新分派用 `scripts/prewalk.py models` 校验并回读该文件；JSON stdin 可指定绝对
`config_path` 使用另一份完整配置，并把返回绝对路径传入 packet/registry 和每次 helper 调用。
不合并隐式全局/项目配置，不读取 CLI 的 model-roles.json；缺文件、缺键、非法值时阻塞新分派。
配置文件由用户编辑，helper 不改配置、不发 App 请求。模型可用性由当前宿主 schema/接受结果核验。

| 模型选择位置 | 查询配置 | 执行入口 |
| --- | --- | --- |
| 当前 coordinator 推荐值 | `work.coordinator` | `coordinator`；只记录观测，不切换当前会话 |
| 独立调查、搜索 | `work.research` | `model`，work 为 research |
| design 原型/HITL | `work.prototype` | `model`，work 为 prototype |
| 地图沟通、规划、spec、issue 拆分 | `work.planning` | `model`，work 为 planning |
| implementation 起步、实现接续、直接实现 | `default_mode`、`modes` | `resolve` 冻结计划，`prepare` 接续 |
| 内部辅助、whole-change testing、逐票 Integration | 对应 `work.assistance/testing/integration` | `subagent` |
| second opinion、ticket-sizing 评估 | 对应 `work.second-opinion/ticket-sizing` | `subagent` |
| 正式 implementation / whole-change 双轴 | `review.<scope>.standards/spec` | `subagent` 返回 review_models，传给 resolved owner |
| 旧无 phase_plan 的 legacy checkpoint | `legacy_execution` | 仅 `prepare` 的显式 legacy 恢复 |

`model` 输入 work，输出 target（model/effort/source/scope）与外层 task 的 model/thinking。
内部入口把同一 target 翻译为 model/reasoning_effort。按工作内容选择 key，不从角色名猜模型。
单次覆盖用 `model_override: {model 或 effort, source, scope}`，scope 等于 work；未指定字段继承配置。
新 implementation 用 `model_overrides`，key 为 starting/execution/direct，值为同结构，scope 等于阶段。
Review 入口必须给 review_scope，可传 `review_overrides` 的 standards/spec 单轴覆盖，scope 为
`implementation.standards` 等 `<review_scope>.<axis>`。coordinator 把返回 review_models 与来源
作为用户选择的 App 配置参数传给 owner，优先于 owner 的模型默认；owner 仍负责两轴独立性与结论。

配置修改只影响下一次新选择。新 lane 将 config_path、execution_kind、phase_plan、phase_targets、
execution_target 同时冻结到 packet/registry；恢复和 prepare 使用持久计划，不重新套当前默认。
接续覆盖走 `execution_override`（非空 source、scope: execution，至少指定 model/effort 之一），
未指定字段继承冻结的 execution_target；旧 canonical lane 无该字段时使用 checkpoint.phase_plan。
checkpoint 把完整 execution_target 写入 canonical evidence 指纹，必须与 phase_plan.execution 一致；
prepare 精确核对 model/effort/source/scope，再返回 overlay 和 request。调用者先持久化并回读 overlay，
再原样发送 request；不要发送前改写参数。已有覆盖持续生效，修改配置不能改变运行中 lane。
覆盖不改变权限、独立双轴、审查放行或同任务接续要求。宿主拒绝参数时报告错误，不静默替换。

外层是独立 App task + App-managed Execution Worktree，内层是该会话的 subagents。
内部辅助不创建正式 lane、不替代外层 implementation owner。Testing 和 Integration 是
coordinator 在原 canonical gate 内显式委派的内部工作，不增加第二个 gate 或 owner。
创建外层 task 须有用户明确的新任务授权及角色模型选择；采用本模式表示选定配置中的模型分工，
但单纯安装或修改 skill 不授权创建业务 task。缺授权时保留待分派 packet 与下一动作。

当前调用会话仍是 coordinator，推荐值查询 work.coordinator。每次启动或恢复前读取宿主实际
model、effort 与来源，调用 `scripts/prewalk.py coordinator` 记录观测；该入口不限制模型。
缺 readback 记 Unknown，不仅因此停止编排；偏离推荐值也不阻断用户选择。
实际值与用户明确请求不一致时报告差异，不能把请求值冒充运行证据或用 prompt 自述切换。

## 每次调用的执行核验

1. coordinator 解析本 skill realpath；packet 使用该 realpath 下的开发模式、helper 与
   transport 绝对路径。worker 完整读这些当前入口，不能读 Execution Worktree 内旧版本或
   `.scratch` 实验报告来代替合同。缺失文件阻塞新分派，已有 lane 保留恢复坐标。
2. 核对 Source 和 Execution Worktree 的有效配置与宿主工具 schema。宿主项目配置未加载或来自其他
   repo 时，仍通过本 skill 模型配置及下方 subagent 入口显式传模型/effort并执行会话并发检查；不声称项目
   `.codex/config.toml` 会随软链传播，不改其他 repo 或全局配置来隐藏差异。宿主禁用 agents
   或拒绝所需模型时报告对应能力受阻；不把替代模型当作合同通过。
3. 内部辅助、咨询、Testing、Integration 和正式 Review 前，父会话先读当前宿主子代理列表，调用
   `scripts/prewalk.py subagent`：输入 work（assistance / second-opinion / review / ticket-sizing / testing / integration）、
   active_count（当前父会话未结束的子代理数）、source（观测来源与时间）、read_only
   （父任务是否只读）。同一父会话串行做核验与分派，宿主更低上限仍优先。
   wait 表示等待并回读；spawn 才可使用返回参数，prompt 必须带父范围、允许编辑路径和
   read_only 约束。只读由宿主权限和任务边界共同执行，返回字段本身不是权限沙箱。
4. review 预留 owner 要求的两轴容量，invoke-owner 后完整读取 resolved code-review；把
   implementation 或 whole-change scope 与 Review Evidence Bundle 传入，同时传入配置解析的 review_models、
   config_path 与 helper 绝对路径；每个 reviewer 的内部辅助也走该配置的 subagent 入口。
   owner 负责执行审查。owner 或 scope 不匹配时明确报告，不能使用安装目录里的旧副本。
   地图 artifact 的用户确认与 Terminal 回传沿下方
   和 transport 合同核验；任务 completed 不能代替用户确认。

完成标准：当前入口、模型请求、父权限、并发观测、owner与回传坐标齐备后才调用工具。
并发 3 是每个父会话的分派上限，不是全 map 上限；脚本不提供跨父会话锁，也不代替宿主
配置回读。运行证据缺失仍记 Unknown，历史探针通过不代替本次启动核验。

## 票级开发模式

仅 design/frontend/backend 的 implementation（output_mode: commit）使用以下选择；planning、
whole-change testing/review 和 coordinator 沿工作分工表。实现阶段自己的测试由执行模型完成。

可选模式和阶段模型从 `scripts/prewalk.py models` 输出的 modes 查询；默认模式来自 default_mode。
新 lane 顺序：本票 ticket_mode → 本 map 已持久化 map_mode → 配置 default_mode。
kind: staged 表示起步后同任务接续，kind: direct 表示直接执行；模型含义由 phase_plan 决定，
不解析模式名。非法模式阻塞分派。非 implementation 填 none。
恢复旧 lane 使用已保存计划；缺开发模式的旧 lane 按原流程恢复，不追补 Prewalk。
修改默认值只影响新 lane；运行中切换须等原执行轮停止并核验现场后，沿原 task 接续。

### 机械核验入口

从本 skill realpath 调用 `scripts/prewalk.py`，命令为 models / model / coordinator / resolve / snapshot / checkpoint / prepare /
review / subagent，JSON 从
stdin 输入、结果从 stdout 读取；非零退出就保留现场并报告。脚本不调用 App、不写 registry。

- resolve 输入 role、output_mode，以及可选 ticket_mode / map_mode / existing_lane。新 implementation
  还必须输入 canonical `../../delivery-pipeline/references/gate-state-machine.md` 定义的
  work_item、可选 map 与 gate_evidence；helper 在选择任何开发模式前验证实施前置证据。返回
  含冻结 phase_plan/phase_targets/execution_target/config_path 的 overlay 和创建用 model/thinking；existing_lane 直接返回 recover，不套用默认值。
- snapshot 直接复用 canonical `../../delivery-pipeline/scripts/checkpoint.py`，输入 Git 顶层
  worktree 与可选 required_ignored，输出隔离 GIT_* 后的 HEAD/branch/common_dir、ignored、
  staged/index、working-tree diff 及全部 dirty 内容/模式指纹。ignored 交付输入未确认无关时受阻。
- checkpoint 输入 worktree、repo 外 checkpoint_path、canonical payload 与可选 required_ignored；
  helper 复用 canonical build/write/read，生成 component_sha256 与 checkpoint_sha256，以紧凑
  UTF-8 JSON 原子写入并立即完整读回。payload 使用 runtime: codex-thread、session_id: App thread、
  coordinator 坐标、phase: starting、development_mode: staged、完整 phase_plan、模型请求/接受/
  readback、first_edit、checks、todo、decision 与 evidence。新 lane 必须把冻结 phase_plan 与
  execution_target 原样传入 payload；canonical mode_source 将 App default 映射为 user-config，
  ticket/map 保留原值，完整配置路径来源保留在 execution_target.source。旧 caller 未传 target 时
  仅按 phase_plan.execution 与 mode_source 生成历史 target。wrapper
  将 model/effort/source/scope 四字段作为保留 evidence 记录写入 canonical payload，因此
  checkpoint 指纹覆盖完整 resolved target；缺少该记录的 prepare 必须 fail-closed。文件变化后不得补造旧证据。
- prepare 输入 lane（App overlay 与 lane_id/state/worktree/base_commit）、checkpoint、checkpoint_path、
  observation（thread_id/host_id/status/source，取自刚完成的宿主 readback）、可选的
  `execution_override`，以及刚核验的 work_item、可选 map 与 gate_evidence；不能仅凭旧 lane
  存在继续实施。`execution_override` 只允许 `source`、`scope`、`model`、`effort`，其中
  `source` 必须是非空且非 `Unknown` 的来源，`scope` 必须为 `execution`，并至少指定
  `model`/`effort` 之一；未指定字段继承 lane 冻结的 execution_target。helper 将解析出的
  `execution_target` 与 canonical checkpoint 的 `phase_plan.execution` 做精确比较，同时核对 source/scope；缺失或不一致均 fail-closed。只有 idle 且 canonical 指纹、持久内容、Git/ignored/staged/unstaged
  现场都一致，并由 canonical `evaluate_signal` 判定 tool acceptance、停止证据与
  critical_design_unknown 均可继续，才返回 persist-before-send、含 `execution_target` 的
  overlay 和原 task 的 request。
  active 返回 wait-for-stop 和原 task 坐标，不返回发送请求；按 transport 中间回传合同
  有界等待原轮停止，再重新 prepare，不能把此正常时序当作最终受阻。
- coordinator 先把返回 overlay（包括 `execution_target` 及 requested model/effort）合并写回既有
  registry 并 readback，确认持久值与 request 使用同一 target 后，才调用
  send_message_to_thread 的 request 参数。一个 lane 只由已登记的 coordinator 分派；脚本
  不提供跨协调器锁。switching/executing 返回 readback、request: null，禁止把空请求当重试。
  prepare 与发送之间出现新消息或文件变化时重新核验；工具结果未知按原任务证据恢复。
- 旧已持久 App checkpoint 只有 registry 中旧 `astra-*` mode、legacy-app-v0 format 与 exact
  checkpoint path 同时匹配，且 snapshot 明确 `ignored.delivery_input: none` 时可显式传
  legacy_checkpoint: true；helper 只按旧内容原样核验并标记 legacy-app-v0 / Unknown，不生成或
  回填 canonical 指纹。新 checkpoint、canonical checkpoint 或缺既有恢复证据时禁止走 legacy 分支。
- review 输入 coordinator 直接回读的 resolved owner triple、review_scope、固定 base/head 与两轴
  宿主结论；helper 不返回任何模型选择，只验证 reviewer 独立性、终态、零阻断项和当前 Git 版本。

完成标准：helper 通过、overlay 持久读回、原 task 请求与回读证据对应。此入口没有新增
canonical gate；phase 到 executing 的确认及最终 fan-in 仍按下方与 transport 合同执行。

### Prewalk 接续

1. **起步。** 按 resolve 返回的 starting 请求创建一个 implementation task；
   execution_phase: starting，checkpoint: none。起步 worker 完整读取规则、owner、spec 与直接调用者，确定最小路径，
   列出剩余 TODO 与验收命令，只完成第一处有意义的实现和最小检查，然后停止本轮。
   设计仍有关键 Unknown 时按 blocked 回传，不为了交接伪造首处修改。
2. **检查点。** 起步 worker 通过 helper 的 checkpoint 命令在 packet 指定的 repo 外 lane registry 旁
   保存 canonical checkpoint artifact，包含 lane/task、worktree/branch、base/HEAD、ignored、
   staged/unstaged 与全部 dirty 指纹、组件/整体 SHA-256、已读证据、首改、检查及 TODO。
   完整持久读回后发送 `PREWALK_READY <lane_id> <checkpoint_path>`
   到 coordinator 后结束本轮；这是中间通知，不发送 completed FINAL_REPORT，不提交或集成。
   coordinator 用 wait_threads/read_thread 核验起步轮已停止，检查点和当前文件一致才接续。
3. **切换。** coordinator 先保存 checkpoint、目标 model/effort 与 phase: switching，随后调用
   `send_message_to_thread`，沿同一个 threadId/hostId 显式传接续模型与模式对应的 thinking
   （使用冻结 execution_target）。
   prompt 带 checkpoint 路径、原 owner/范围、剩余 TODO，并明确“起步轮限制已结束，完成余下
   实现、测试与 owner 要求的审查和提交”。不创建第二个 task/worktree；旧消息与工具轨迹
   必须通过原任务历史接续；checkpoint 只用于恢复与核对。接续不得改用新任务、fork、
   独立 subagent 或仅文档交接。宿主无法在原任务换模型时保留现场并报告受阻，不拆分上下文。
   同一任务仍可能发生宿主自动压缩；不承诺原始历史逐 token 保留或传递模型隐藏推理。
4. **确认。** 请求前后分别保留证据；工具接受、执行轮启动、模型 readback 是三件事。
   观察到原 task 新执行轮后保存 phase: executing；模型读不到仍为 Unknown。发送结果未知时
   保持 switching，先读原 task 是否收到接续消息/产生新轮，不能盲目重发；无法消歧则报告
   恢复坐标。App 工具没有已验证的幂等键，registry 标记本身不保证外部调用 exactly-once。
5. **交付。** 执行 worker 完成剩余 owner 流程后保存候选 commit并走原 FINAL_REPORT。起步 worker
   不算 Review；coordinator 按 resolved code-review owner 与 review_scope 启动正式 Standards/Spec
   独立审查。blocking finding 修复后按 owner 复核；App 壳不增加或替换模型 gate。

kind: direct 创建时使用 resolve 返回的 direct 请求，phase: executing，checkpoint: none，
跳过起步与换模型步骤；其测试、Review 与集成标准相同。Prewalk phase 是 App overlay 的
子阶段，不新增 canonical gate 或第二个 lane owner。执行者需要重判方案时使用下方
second opinion；模式升级由用户明确选择，沿同一 task 保存变更原因和现场证据。

当前证据边界：历史探针验证过轮次间同任务接续、直接执行和 coordinator 回传唤醒。
本次配置驱动分派尚未做 App 端到端模型 readback；helper 检查不证明宿主模型实际切换。
完整业务 map 的 Review 与 Integration 也需要当次运行证据。
service tier 沿宿主默认，不启用 fast；当前 task/spawn schema 没有逐次 service tier 参数和
readback 时记 Unknown，不以模型、effort 或任务标题推断 fast 状态。

## 参数与证据

- 每次先核对真实工具 schema：外层 `create_thread` 显式传 `model` + `thinking`；内层 spawn
  显式传 `model` + `reasoning_effort`（宿主名称不同时按当前 schema 翻译）。
- 仅内部独立辅助/只读审查的 spawn：完整历史 fork 若禁止模型覆盖，使用允许覆盖的独立
  上下文形式；当前接口为 `fork_turns: none`。此规则不适用于 Prewalk 主执行接续。
  prompt 带完整任务、规则/spec、证据绝对路径、读写范围与交付标准，不能依赖缺失的父历史。
- 创建请求、工具接受和实际运行 readback 分开记录。可读回模型/effort 时记录值、来源及时间；
  不可读回时记 Unknown，模型自述、标题和请求回显不是运行证明。启动拒绝时报告错误与恢复
  坐标，不静默换模型；已启动但证据 Unknown 时可按产物验收，同时保留模型验证缺口。
- 显式 spawn 值覆盖 `[agents]` 默认，但自定义 agent 文件可再次覆盖。选用角色前检查其
  resolved 文件的 `model` 与 `model_reasoning_effort`；不匹配则使用无冲突角色或报告受阻。

本仓 `.codex/config.toml` 只保存 agents 能力和并发设置。App 外层 task 与内部 spawn 都显式
传入本 skill 配置解析的模型，不依赖宿主 default_subagent_model。配置随 skill realpath 读取，
不需要向其他业务仓库复制 .codex 配置，也不修改全局或其他 repo 的配置。

## Planning 直接沟通与回传

松散想法建图、地图拷问与规划查询 work.planning 后进入 artifact lane；用户直接打开该 App task 沟通。
coordinator 提供调查证据、已确认决定、未知点、owner 与当前 gate，不逐句转述用户对话。
首次尚无 map 时使用输入 artifact/gate 坐标登记 planning lane，并记录 Source HEAD 为临时 base；
在 repo 外的持久 artifact 旁保存临时 registry（gate、project/task/host、base、worktree、确认与产物），
作为恢复唯一入口；packet 的 map/Integration 坐标填 none，并显式注明只允许建图 artifact。
获明确新任务授权后从该 base 的已验证 ref 创建 App worktree，不包含 Source dirty。
该首次建图分支尚未进入 map 的 Execution Worktree 图，不执行实现或 cherry-pick。
map 发布后再建立 canonical Map Integration
Worktree，回填 map/Integration 坐标；后续 lanes 均从 Integration HEAD 创建。

planning worker 按 owner 合同保留用户确认：决定内容、确认来源、未决问题及可读回的 map/spec/artifact
坐标，并沿 Terminal 回传合同交给 coordinator。需要用户交互时登记 awaiting_human，保留 task；
task completed 只是唤醒信号。coordinator 核验用户确认及当前 gate 的持久通过证据后才推进，
缺失确认不因 artifact 存在而自动通过。既有确认仍适用时直接接续。

## Ticket-sizing 评估子代理

`to-tickets` owner 可通过 subagent 入口指定 `work: ticket-sizing`，读取 work.ticket-sizing。
沿同一父会话并发上限，占一个 slot，强制只读；不回落到通用 assistance 配置。
输入与逐票结果按 resolved ticket-sizing 合同；owner 核验并持久化为 tickets gate 的 sizing 证据，
用户对拆分与依赖的批准仍是必需条件。能力不可用时可由 owner 直接执行评估，不跳过 ticket-sizing。

## 内部辅助工作

coordinator、planning 与获授权的执行会话均可按 work.assistance 派生子代理，承担独立检索、研究、测试或有界实现。
父会话分配允许编辑的文件边界，避免同时写同一文件；核验结果并承担最终交付。
子代理继承父任务范围与权限：Review / second opinion / testing 只读；Integration 仅在父任务
有写权限且 active_count 为 0 时可写指定 Integration Worktree。Testing 与 Integration 分两次串行
spawn，分别回传检查证据与精确 commit/readback；coordinator 复核后推进原 gate。
规划判断、咨询建议和正式 Review 仍由对应 owner 负责。其他步骤不强制派生。

## Second opinion

coordinator 与 implementation 均可在调查或最小实验后按需咨询：重要不确定性仍未解决、
方案影响模块边界/接口/依赖/持久化、修复扩大范围或引入新机制、反复失败需要重判根因。
普通事实先查文档，可实验的问题先实验；不把每个小选择变成咨询 gate。

coordinator 或执行模型在当前会话内通过 work.second-opinion 请求只读 subagent，提供问题、约束、已核实证据、Unknown、
最小可行方案、其他方案代价和具体咨询问题。咨询子代理返回推荐及理由、不必要的设计、最小验证
和剩余 Unknown。请求方核验并落实；咨询不改代码、不扩大授权、不替代产品决定或正式 Review。
启动失败明确报告，不静默换模型冒充咨询结果。
