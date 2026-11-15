# Lody 调度运行时路由

创建或替换 worker lane 前读取。本文件是 canonical 主干的 Lody transport adapter：coordinator
是当前 Lody session，所有新 worker 都是 `lody_session_create` 子 session。恢复既有 lane 直接读
`lody-lifecycle.md` §恢复，不运行新 lane 的配置 gate。

canonical 合同位于 `../../delivery-pipeline/references/`，下文以文件名引用。

## Preflight

每批 maximal safe batch 前做一次只读 snapshot：

1. `lody_session_create_options` 读回 `current.sessionId`、`workspaceId`、`machineId` 与
   `workContext`：要求 `kind: local`，`rootPath` 的 `git rev-parse --git-common-dir` 等于 Source repo
   的 common dir；`localProjects` 中该 `projectId` 为 `isGit: true`，所在 machine `online` 且
   `canUse: true`。Lody 在该 project 下建子 worktree；任一不符报告 `dispatch unavailable`。
2. 按 `integration-worktree-management.md` 核对 Integration branch 与 clean state，冻结本批
   `base_sha`：普通 map 为当前 Integration HEAD；`delivery_mode: ticket_release` 为刚 fetch 的
   远端默认分支 SHA。

## Target 映射与配置 gate

本节替代 `model-role-routing.md` §Dispatch 验证第 2、3 步；第 1、4 步不变。配置实例是 CLI 实例
`~/.config/delivery-pipeline/model-roles.json`，先按 `model-config-schema.md` 用 setup 的
`model_config.py validate` 校验，阶段计划按 `model-role-routing.md` 冻结。

| work `agent` | Lody `agentType` | branch prefix |
| --- | --- | --- |
| `pi` | `pi` | `pi/` |
| `codex` | `codex` | `codex/` |
| `claude` | `claude` | `claude/` |

每个不同的 agent 调一次 `lody_agent_config_list(machineId: <coordinator machine>)`，取
`agentType` 匹配且 `availability.state: available` 的唯一 config 作 `agent_config_id`；零个匹配写
`setup_blocked`，多个匹配列出候选并由用户点名，点名结果写入 overlay。对选中的 config：
`runConfig.models[].id` 与配置 model 完全一致，配置 effort 属于该项 `reasoningEffortValues`。
不一致时该 lane 写 `setup_blocked`，附候选 id，
交 `delivery-pipeline-setup` 改配置；配置值原样使用。

## Registry Overlay

`lody` overlay 归本壳所有。写入顺序：intent → create receipt → startup readback；每层
写入后精确 readback。

```yaml
lody:
  workspace_id: <workspaceId>
  machine_id: <machineId>
  project_id: <Source projectId>
  coordinator_session_id: <current.sessionId>
  coordinator_agent: pi | codex | claude
  agent_config_id: <agentConfigId>
  operation_id: <最近一次投递结果的 Operation id>
  session_id: <child sessionId-or-none>
  session_link: <lody://session/<session_id>?workspace=<workspace_id>-or-none>
  lody_branch: <Lody 初始分支-or-none>
```

base 字段：`runtime: lody-session`；`worktree` 取 Lody 子 worktree 绝对路径；`branch` 在 commit mode 为
`<prefix>issue-<coordinate>`，其他 mode 为 `none`；`base_commit` 为 `base_sha`。

## 派发关键路径

implementation 新建或 replacement 前，按 `gate-state-machine.md` 实施前置检查运行
`implementation_gate.py`，通过后执行：

1. registry 写 Base Schema 字段与 overlay intent（`operation_id: <lane_id>`），精确 readback。
2. 填写 `../assets/LODY_ROLE_DISPATCH_PACKET.md`，写入 `~/.config/delivery-pipeline/packets/<lane_id>.md`。
3. 同批 lanes 在同一轮并行调用 `lody_session_create`：`operationId: <lane_id>`；`prompt` 为 packet
   全文；`machineId` 与 `agentConfigId` 取 overlay；`modelId` 与 `reasoningEffort` 取冻结计划；
   `useCurrentSessionAsParent: false`；`workContext: {kind: "local", projectId, worktree: true}`。
   权限沿 agent config 默认：不传 `modeId` 与权限类 `configOptionValues`；不传 `branch`，基点由
   worker 对齐。
4. 返回 Operation handle 后，HITL lane 写 `awaiting_human`，其余写 `running`。调用报错或超时时保留 `launching`，在原 requester 下先查原 Operation；
   不重发 prompt、不将 NOT_FOUND 当 absent。create 返回采用的 id 时保留该 id，不能覆盖成 lane_id。
   缺证据写 Unknown/blocked，同批其余 lane 继续。

## Startup Readback

对每条 lane 调一次 `lody_operation_get(operationId)` 取 target session id，再用
`lody_session_status_many` 一次读回整批：session 存在、machine 等于 overlay、执行状态为 busy 或
已结束。写 `session_id`、`session_link`，用 `lody_session_rename` 设标题
`map-<map> <role> #<coordinate>`，并 readback。宿主读回给出 worktree 路径时写入 `worktree`，
否则记 Unknown，由终态报告「现场」与 `git worktree list --porcelain` 在 fan-in 补齐。
session 与 overlay 不一致写 `setup_blocked` 并保留现场。

整批每项都已 `running`/`awaiting_human` 或 `setup_blocked` 后到达 Dispatch Handoff：逐条报告
lane 的 `session_link`，结束本轮。Lody 在下一个输入边界投递 Operation 结果，coordinator 不轮询。

## CLI 冻结计划

创建新五 work lane 前使用 canonical `model_config.py resolve` / `freeze_overlay`；packet 与
Registry base row 原样持久化 recovery_plan、recovery_progress（单行 JSON flow value），
写入 intent、真实 receipt、startup readback 后均用 `verify_overlay` 对账，不另造计划形状。
恢复先运行 `model_config.py recover <registry.md> [lane_id]`；错误/legacy 识别与字段语义
统一见 `../../delivery-pipeline/references/lane-registry.md`，不从当前配置补读。

## M2 replacement 调用方（DD-417，本机原生验收 blocked）

replacement 的 `target()` 复用 `lody_session_create_options(machineId, agentConfigQuery, localProjectQuery)`。
Lody 0.112 的 query 只按 config id/name/description 子串过滤；返回后仍须精确核对
agentType、machineId、唯一 config 与 runConfig 中 model/effort。此 discovery summary
正常省略 `availability`，仅 quota exhausted 时附 `unavailable`；字段缺失按该摘要合同处理，
显式状态只接受 `available`，`unavailable`、未知状态均拒绝。无需另调 config_get。
该摘要仅证明声明的能力，不能证明模型服务端可用或实际模型执行；身份、在线 machine、
本地 project 与冻结 base 门禁继续生效。

`../scripts/native_replacement.py` 消费 canonical Registry 已 claim 的 successor；
`../scripts/native_host.js` 将 JSON lines 转发给**原 Lody requester** 的正式 MCP 工具绑定。
不在 T3 里构造 LODY_SESSION_ID，不连内部 socket、不读原生 operation 数据库。
调用前核对本机安装版本；本候选按 0.112.0 打包合同实现，跨版本须重新核对。

调用输入为 `{action:"execute",registry:<绝对路径>,lane:<successor lane_id>,prompt:<完整packet>,
binding:{sessionId,workspaceId,machineId,projectId,sourceRepo}}`。
claim 输入使用同一 binding、`action:"claim"`、`source/revision/failure_id/category`；共享 owner
决定选序、重复位置与两次预算。宿主以 `runNativeReplacement(command, invocation, processIO, native)`
调用；command 是本脚本的 python3 命令，native 必须是当前 Lody 会话实际公开工具，不能使用静态回包。

目标实时从 create-options 取得 agent config/runConfig/machine/project；不重读用户 work 配置。
先绑定请求，再由共享 launch 持久 launching 后调用 session_create。worktree 由 Lody 创建，
不传 Role、modeId 或权限扩展。local workContext.branch 是基线参数：从 canonical row
继承的 worktree 读真实 Git symbolic HEAD，核对 common dir、HEAD 和该 local ref 均精确等于
base_commit 后显式传入；不用 row.branch 显示名、caller 当前分支或 SHA 猜测支持。
缺失、detached、异库或已漂移的 source 保留 Unknown，create 前停止；不能默认 main。
claim 删除 lody overlay 但保留 worktree/base_commit，二者仍是唯一来源，不新增 base owner。
branch 是可移动 ref，预检和原生创建之间的外部移动仍需 startup Git readback 检出。
packet 仍要求 worker 对齐冻结 base_commit。
恢复只调用原 requester 的 operation_get；0.112 的 `session_create({operationId,resume:true})`
也是只读快照入口，不是重新 join/启动授权。本候选只用 operation_get，不自动重发或轮询。

startup 恢复用一次 operation_get，采用实际 id 与唯一 target.userTurnId；status 必须 fresh/online，
匹配 requester、machine、agentConfigId、local project、worktree:true 与非 Tab。将原生 branch
与 Git worktree list 的唯一路径对账，common dir 相同、独立目录且 HEAD 包含 base_commit。
同一 target turn 正在 busy，或 Operation succeeded 且 fresh idle/no-queue 并在 history 找到精确
assistantTurnId 时，canonical recover_launch 完成 startup，再以 canonical write 幂等补齐 lody
坐标与 worktree。running 表示 startup 已证实，不表示模型/业务结果已经验收。重放不 create。

原生 status/history 没有独立 executedModel/applied effort 字段；receipt 保留 requested、startup、
history，executedModel/runtime_thinking/applied_effort/nonce 独立写 Unknown，不能从文本推定。
旧 writer 仍须原 succeeded turn 加 fresh idle/no-active/no-queue；cancel/error/timeout 不放行。
业务拒绝缺少可证明“没有 writer”的动态样本时仍 Unknown/launching，不能猜 failed 或自动 claim。
本票原生验收仍 blocked，不代表 DD-417 Done。

只读诊断输入 `{action:"inspect",operationId:<实际 adopted id>,binding:<同一 caller binding>}`
输出原 operation 与自动提取的 target status/history，不修改 Registry，不创建 session。
脚本可用 `--request <JSON绝对路径>` 读取输入；其余 stdout/stdin 仍为公开工具 JSON-lines 协议。
`native_host.js` 可处理正式 MCP content/structuredContent 与宿主已解包的 JSON；在当前原生
Codex 工具执行环境载入函数并显式绑定实际终端 exec/write 与五个正式工具。不要启动第二个
Codex CLI 来取得 requester。宿主不可执行该函数时，直接由原 caller 驱动同一 JSON-lines
协议，一行请求对应一次正式工具调用，一行原始结果回送；不要补造身份、结果或环境变量。

## M3 whole-change review（DD-518）

whole-change review 必须走本节，不使用 work resolve/replacement。原 coordinator requester 通过
`../scripts/native_host.js` 的现有 `runNativeReplacement` 协议，command 指向
`python3 <本壳绝对路径>/scripts/native_review.py`，invocation 为以下 JSON（不带 `--request`）：

- `action`: `preflight` / `dispatch` / `recover`；`registry`、`lane`、`request_id`、`binding`。
- 新轮另传 `config`（已保存的完整 CLI 配置快照）、`implementation_registries`（全部贡献
  Registry 绝对路径）、`fixed_point`、`head`、`ledger`、`required_axes`、`round`（默认 1）。
  `row` 给出原 whole-change 的 Base Schema、Integration `worktree` / `base_commit`；
  `owner` 为已解析 `{name,path,invocation}`，path 是绝对 SKILL.md；`prompt` 是完整原 packet
  和 Review Evidence Bundle 指针。不得把测试 fixture 当作输入。
- 后轮可传 `previous_review_registry`、`interface_changed`、`dependencies_changed`；轮次与
  required axes 由 canonical `review_gate.prepare_round` 决定。相同 base/head 返回完整原结论。
- `binding` 沿既有 `{sessionId,workspaceId,machineId,projectId,sourceRepo}`；必须是当前原
  Lody requester 的真实身份。T3 不补造身份或代调工具。

只读 discovery 逐项核对 agentType/machine、精确 modelId、该模型的 reasoningEffortValues
（或 measuredForModelId 精确绑定的档位）；缺失/歧义为 Unknown 并阻断。完整 runConfig 明确
不支持目标或显式 unavailable 可跳过。普通摘要省略 availability 沿 0.112 合同处理。
所有参与池项、所选 lane 与 required axes 均在 create 前核验；模型/家族选序仍只由
canonical resolve_review_plan 决定。空候选同样精确核验，但不新增家族声明要求。

preflight 返回 plan/owner_calls/原生 arguments，不写 Registry、packet 或创建 session。
dispatch 将 plan、packet 全文、owner、binding 和精确 arguments 一起 reserve 到唯一 Registry，
`lody.startup_state=launching` 后才 create。原 operation receipt 原样保存，completed 只表示
收到 receipt，不证明 startup 或实际模型。session/worktree startup 仍沿原 Startup Readback。
同 request 的重入只读原 plan/receipt；launching/响应丢失返回 inspect_original，不重发。
取消或终态 stop；没有自动 successor、work fallback 或跨 transport 路由。

resolved owner 必须逐轴消费冻结 owner_calls，spec-only 只执行 spec，standards 仍决定 lane。
调用 canonical `../../delivery-pipeline/scripts/review_gate.py --ledger <原账本>`，stdin 传
round、完整 axes findings/counts/verdict、原 review_packet、逐轴 native_readbacks 与 p2_issues。
缺独立 executedModel/applied effort 传 null（无 readback），canonical 逐轴记录 unknown；
不得将 session requested 或模型自述转为 executed。部分 known 冲突也会 REVIEW_BLOCKED，
完整 findings 保留，不重跑。恢复若已有账本必须传原 ledger，返回原完整结论，禁止再次 gate。
DD-417 的 work operation 证据不能用于本 review，DD-417 未 Done 也不总阻塞本票代码。

独立检查：`python3 skills/delivery-pipeline-lody/scripts/check_review_dispatch.py --case native-unknown`；
setup 同义入口：`python3 skills/delivery-pipeline-setup/scripts/check_config_review.py --case lody-review-plan`。
两者只证明真实临时文件/子进程与 native I/O 边界合同，真实 Lody session 与逐轴实际执行仍待 Root。
