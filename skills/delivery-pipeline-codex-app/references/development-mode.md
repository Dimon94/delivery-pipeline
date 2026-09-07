# Codex App 开发模式

coordinator 启动时与每个 worker 执行前读取。本文件拥有 App 工作分工、内部辅助和技术咨询；
正式双轴审查的模型规则由 resolved `code-review` owner 拥有，Pipeline 只传 Review Evidence Bundle。

## 工作分工

| 工作 | 请求 model | 请求 effort |
| --- | --- | --- |
| coordinator、独立搜索调查、whole-change 测试执行 | `gpt-5.6-sol` | `high` |
| 地图沟通/拷问、地图规划、spec、issue 拆分、原型 | `gpt-6-astra` | `low` |
| second opinion | `gpt-6-astra` | `low` |
| 执行会话内部检索、限定范围实现、测试、研究辅助 | `gpt-5.6-luna` | `max` |

按 work 判定，不只看 role：planning 中的搜索调查用 Sol，spec/tickets 用 Astra；design 中的
原型用 Astra，正式工程实现按下面的票级开发模式选择。whole-change review 先读 owner 合同：直接承担独立判断时
使用 Astra / low；若 owner 明确只汇总双轴结果，可由 Sol / high 主持。正式两轴不得整体交 Luna。
所有 Astra 用途默认 low；不自动提高推理档位。

外层是独立 App task + App-managed Execution Worktree，内层是该会话的 subagents。
内部辅助不创建正式 lane、不替代外层 implementation owner，也不产生独立 Integration。
创建外层 task 须有用户明确的新任务授权及角色模型选择；采用本模式表示选定上表，
但单纯安装或修改 skill 不授权创建业务 task。缺授权时保留待分派 packet 与下一动作。

当前调用会话仍是 coordinator。启动前从宿主可用元数据核对其 Sol / high；不匹配时请用户
在 App 调整当前任务再启动新工作，不能由 prompt 自述切换。无 readback 记 Unknown 并报告。
恢复已有工作不受此新建检查阻塞。

## 每次调用的执行核验

1. coordinator 解析本 skill realpath；packet 使用该 realpath 下的开发模式、helper 与
   transport 绝对路径。worker 完整读这些当前入口，不能读 Execution Worktree 内旧版本或
   `.scratch` 实验报告来代替合同。缺失文件阻塞新分派，已有 lane 保留恢复坐标。
2. 核对 Source 和 Execution Worktree 的有效配置与宿主工具 schema。配置未加载或来自其他
   repo 时，仍通过下方 subagent 入口显式传模型/effort并执行会话并发检查；不声称项目
   `.codex/config.toml` 会随软链传播，不改其他 repo 或全局配置来隐藏差异。宿主禁用 agents
   或拒绝所需模型时报告对应能力受阻；不把替代模型当作合同通过。
3. 内部辅助、咨询和正式 Review 前，父会话先读当前宿主子代理列表，调用
   `scripts/prewalk.py subagent`：输入 work（assistance / second-opinion / review / ticket-sizing）、
   active_count（当前父会话未结束的子代理数）、source（观测来源与时间）、read_only
   （父任务是否只读）。同一父会话串行做核验与分派，宿主更低上限仍优先。
   wait 表示等待并回读；spawn 才可使用返回参数，prompt 必须带父范围、允许编辑路径和
   read_only 约束。只读由宿主权限和任务边界共同执行，返回字段本身不是权限沙箱。
4. review 预留两轴容量，invoke-owner 后完整读取 resolved code-review；模型规则仍由 owner
   拥有。先核对 owner 的 Astra low 双轴合同和 Review Evidence Bundle；owner 不匹配时
   明确报告，不能使用安装目录里的旧副本。地图 artifact 的用户确认与 Terminal 回传沿下方
   和 transport 合同核验；任务 completed 不能代替用户确认。

完成标准：当前入口、模型请求、父权限、并发观测、owner与回传坐标齐备后才调用工具。
并发 3 是每个父会话的分派上限，不是全 map 上限；脚本不提供跨父会话锁，也不代替宿主
配置回读。运行证据缺失仍记 Unknown，历史探针通过不代替本次启动核验。

## 票级开发模式

仅 design/frontend/backend 的 implementation（output_mode: commit）使用以下选择；planning、
whole-change testing/review 和 coordinator 沿工作分工表。实现阶段自己的测试由执行模型完成。

| development_mode | 起步 | 接续实现与测试 |
| --- | --- | --- |
| `astra-luna`（默认） | Astra / low | Luna / max |
| `astra-sol` | Astra / low | Sol / high |
| `sol-direct` | 无单独起步 | Sol / high 从头执行 |

新 lane 选择顺序：用户对本票的明确选择 → 本 map 已持久化的选择 → `astra-luna`。
packet 与 registry 同时保存 development_mode 和选择来源；非法值阻塞分派，不猜测。
非 implementation 填 none。恢复旧 lane 时使用已保存模式；旧 lane 缺该字段时按原流程恢复，
不追补 Prewalk。用户可指定“本票 astra-sol”或“后续新票 sol-direct”，先持久化作用范围。
修改默认值只影响新 lane；运行中切换须等原执行轮停止并核验现场后，沿原 task 接续。

### 机械核验入口

从本 skill realpath 调用 `scripts/prewalk.py`，命令为 resolve / snapshot / prepare / subagent，JSON 从
stdin 输入、结果从 stdout 读取；非零退出就保留现场并报告。脚本不调用 App、不写 registry。

- resolve 输入 role、output_mode，以及可选 ticket_mode / map_mode / existing_lane。新 implementation
  还必须输入 canonical `../../delivery-pipeline/references/gate-state-machine.md` 定义的
  work_item、可选 map 与 gate_evidence；helper 在选择任何开发模式前验证实施前置证据。返回
  overlay 和创建用 model/thinking；existing_lane 直接返回 recover，不套用默认值。
- snapshot 输入 worktree（Git 顶层绝对路径），输出 HEAD、branch（detached 时为 HEAD）、
  common_dir、暂存 diff 指纹与所有非 ignored dirty 文件的内容/模式指纹。ignored 文件不是
  交付输入；若任务依赖它们，先将相关输入显式纳入证据或报告 Unknown。特殊 dirty 类型受阻。
- checkpoint 是 repo 外 JSON：lane_id、thread_id、host_id、base_commit、first_edit（非空首改路径列表，必须属于 dirty）、snapshot 以及非空 todo、checks、
  evidence、decision。Astra 完成首处修改时生成 snapshot，结束后 coordinator 核验；不能在
  文件已变后补造一份“相同”检查点。通过 packet 的 Lane registry 坐标保存路径。
- prepare 输入 lane（App overlay 与 lane_id/state/worktree/base_commit）、checkpoint、checkpoint_path、
  observation（thread_id/host_id/status/source，取自刚完成的宿主 readback），以及刚核验的
  work_item、可选 map 与 gate_evidence；不能仅凭旧 lane 存在继续实施。只有 idle 且
  检查点坐标、持久内容、Git 现场都一致才返回 persist-before-send 和原 task 的 request。
  active 返回 wait-for-stop 和原 task 坐标，不返回发送请求；按 transport 中间回传合同
  有界等待原轮停止，再重新 prepare，不能把此正常时序当作最终受阻。
- coordinator 先把返回 overlay 合并写回既有 registry 并 readback，才调用
  send_message_to_thread 的 request 参数。一个 lane 只由已登记的 coordinator 分派；脚本
  不提供跨协调器锁。switching/executing 返回 readback、request: null，禁止把空请求当重试。
  prepare 与发送之间出现新消息或文件变化时重新核验；工具结果未知按原任务证据恢复。

完成标准：helper 通过、overlay 持久读回、原 task 请求与回读证据对应。此入口没有新增
canonical gate；phase 到 executing 的确认及最终 fan-in 仍按下方与 transport 合同执行。

### Prewalk 接续

1. **起步。** 按所选模式创建一个 implementation task；astra-luna/astra-sol 请求
   `gpt-6-astra` + `low`，execution_phase: starting，checkpoint: none。Astra 完整读取规则、owner、spec 与直接调用者，确定最小路径，
   列出剩余 TODO 与验收命令，只完成第一处有意义的实现和最小检查，然后停止本轮。
   设计仍有关键 Unknown 时按 blocked 回传，不为了交接伪造首处修改。
2. **检查点。** Astra 在 packet 指定的 repo 外 lane registry 旁保存 checkpoint artifact：lane/task、
   worktree/branch、base/HEAD、全部 dirty 路径及其内容指纹（含未跟踪文件）、已读证据、
   决策理由、首处修改、检查结果、剩余 TODO。发送 `PREWALK_READY <lane_id> <checkpoint_path>`
   到 coordinator 后结束本轮；这是中间通知，不发送 completed FINAL_REPORT，不提交或集成。
   coordinator 用 wait_threads/read_thread 核验起步轮已停止，检查点和当前文件一致才接续。
3. **切换。** coordinator 先保存 checkpoint、目标 model/effort 与 phase: switching，随后调用
   `send_message_to_thread`，沿同一个 threadId/hostId 显式传接续模型与模式对应的 thinking
   （Luna 为 max，Sol 为 high）。
   prompt 带 checkpoint 路径、原 owner/范围、剩余 TODO，并明确“起步轮限制已结束，完成余下
   实现、测试与 owner 要求的审查和提交”。不创建第二个 task/worktree；旧消息与工具轨迹
   必须通过原任务历史接续；checkpoint 只用于恢复与核对。接续不得改用新任务、fork、
   独立 subagent 或仅文档交接。宿主无法在原任务换模型时保留现场并报告受阻，不拆分上下文。
   同一任务仍可能发生宿主自动压缩；不承诺原始历史逐 token 保留或传递模型隐藏推理。
4. **确认。** 请求前后分别保留证据；工具接受、执行轮启动、模型 readback 是三件事。
   观察到原 task 新执行轮后保存 phase: executing；模型读不到仍为 Unknown。发送结果未知时
   保持 switching，先读原 task 是否收到接续消息/产生新轮，不能盲目重发；无法消歧则报告
   恢复坐标。App 工具没有已验证的幂等键，registry 标记本身不保证外部调用 exactly-once。
5. **交付。** Luna/Sol 完成剩余 owner 流程后走原 FINAL_REPORT 与 fan-in。Astra 起步不算
   Review；正式 Standards/Spec 独立审查仍按 code-review owner 使用 Astra / low。
   blocking finding 修复后按 owner 复核；不额外增加 Sol 全量核验 gate。

sol-direct 创建时直接请求 `gpt-5.6-sol` + `high`，phase: executing，checkpoint: none，
跳过起步与换模型步骤；其测试、Review 与集成标准相同。Prewalk phase 是 App overlay 的
子阶段，不新增 canonical gate 或第二个 lane owner。执行者需要重判方案时使用下方
second opinion；模式升级由用户明确选择，沿同一 task 保存变更原因和现场证据。

当前证据边界：2026-09-07 的 #94 历史探针曾验证 Astra low → Luna high（该配置现已废止）、
Astra low → Sol high 在原 task/worktree 接续，以及 Sol high 直接执行。切换为 max 后，复用原
Astra/Luna task 完成 Astra low → Luna max 新探针；宿主 turn_context 回读 model/effort 为
`gpt-5.6-luna` / `max`，口令、三个合法转换及九个非法组合检查通过。另一个隔离检查链已验证
空闲 coordinator 被回传唤醒、自动发送同 worker 的
下一阶段并收齐结果回传；完整业务 map 的 Review 与 Integration 尚未做端到端验证。此合同采用
轮次间接续，不宣称工具调用边界自动热切换；实际票仍需保留全链路证据。
Luna 不启用 fast，沿宿主默认 service tier 运行；本机全局配置为 `service_tier = "default"`，
项目配置不增加 fast 覆盖。当前 task/spawn schema 未提供 service tier readback 时记 Unknown，
不以模型、effort 或任务标题推断 fast 状态。

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

本仓项目级 `.codex/config.toml` 已保存下列内部默认值。本 skill 不覆盖全局配置，也不把
项目配置自动安装到其他业务仓库；外层 task 与关键内部 spawn 仍显式传 model/effort。
需要在其他 repo 落盘时按当次授权修改对应键，并读回有效配置和角色覆盖。该配置不强制委派。

```toml
[agents]
enabled = true
max_concurrent_threads_per_session = 3
default_subagent_model = "gpt-5.6-luna"
default_subagent_reasoning_effort = "max"
```

字段与角色覆盖顺序参见 [OpenAI subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents)
及 [配置参考](https://learn.chatgpt.com/docs/config-file/config-reference)；实际接口以宿主 schema 为准。

## Astra 直接沟通与回传

松散想法建图、地图拷问与规划进入 Astra 的 artifact lane；用户直接打开该 App task 沟通。
Sol 提供调查证据、已确认决定、未知点、owner 与当前 gate，不逐句转述用户对话。
首次尚无 map 时使用输入 artifact/gate 坐标登记 planning lane，并记录 Source HEAD 为临时 base；
在 repo 外的持久 artifact 旁保存临时 registry（gate、project/task/host、base、worktree、确认与产物），
作为恢复唯一入口；packet 的 map/Integration 坐标填 none，并显式注明只允许建图 artifact。
获明确新任务授权后从该 base 的已验证 ref 创建 App worktree，不包含 Source dirty。
该首次建图分支尚未进入 map 的 Execution Worktree 图，不执行实现或 cherry-pick。
map 发布后再建立 canonical Map Integration
Worktree，回填 map/Integration 坐标；后续 lanes 均从 Integration HEAD 创建。

Astra 按 owner 合同保留用户确认：决定内容、确认来源、未决问题及可读回的 map/spec/artifact
坐标，并沿 Terminal 回传合同交给 Sol。需要用户交互时登记 awaiting_human，保留 task；
task completed 只是唤醒信号。Sol 核验用户确认及当前 gate 的持久通过证据后才推进，
缺失确认不因 artifact 存在而自动通过。既有确认仍适用时直接接续。

## Ticket-sizing 评估子代理

`to-tickets` owner 可通过 subagent 入口指定 `work: ticket-sizing`，请求 `gpt-5.6-sol` / `high`。
沿同一父会话并发上限，占一个 slot，强制只读；不回落到通用 assistance 的 Luna。
输入与逐票结果按 resolved ticket-sizing 合同；owner 核验并持久化为 tickets gate 的 sizing 证据，
用户对拆分与依赖的批准仍是必需条件。能力不可用时可由 owner 直接执行评估，不跳过 ticket-sizing。

## 内部 Luna 辅助

Sol、Astra 与获授权的执行会话均可按需直接派生 Luna / max，承担独立检索、研究、测试或有界实现。
父会话分配允许编辑的文件边界，避免同时写同一文件；核验结果并承担最终交付。
子代理继承父任务范围与权限：Review / second opinion 只读，Luna 也只读；规划判断、
咨询建议和正式 Astra Review 仍由 Astra 负责。不要为没有独立工作的步骤强制派生。

## Second opinion

coordinator 与 implementation 均可在调查或最小实验后按需咨询：重要不确定性仍未解决、
方案影响模块边界/接口/依赖/持久化、修复扩大范围或引入新机制、反复失败需要重判根因。
普通事实先查文档，可实验的问题先实验；不把每个小选择变成咨询 gate。

coordinator 或执行模型在当前会话内请求 Astra / low 只读 subagent，提供问题、约束、已核实证据、Unknown、
最小可行方案、其他方案代价和具体咨询问题。Astra 返回推荐及理由、不必要的设计、最小验证
和剩余 Unknown。请求方核验并落实；咨询不改代码、不扩大授权、不替代产品决定或正式 Review。
启动失败明确报告，不以 Luna/Sol 冒充咨询结果。
