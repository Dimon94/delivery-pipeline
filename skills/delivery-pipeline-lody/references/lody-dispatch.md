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
不传 Role、modeId 或权限扩展。packet 仍要求 worker 对齐冻结 base_commit。
恢复只调用原 requester 的 operation_get；0.112 的 `session_create({operationId,resume:true})`
也是只读快照入口，不是重新 join/启动授权。本候选只用 operation_get，不自动重发或轮询。

当前候选仅正面接受原 Operation result 的 succeeded turn 加 fresh idle/no-active/no-queue
状态作为旧 writer 退出；cancelled/error/timeout/idle 单独均阻塞。原生启动目录、独立模型和 effort
尚未验收，receipt 保留 launching，不投影为 lifecycle 的成功 lane、不自动推进下一备用。
这不是 DD-417 Done：完整 startup readback、产品 nonce、独立 actual model/runtime thinking/provider
applied effort 分项证据仍待原生 caller；缺项均 Unknown。
