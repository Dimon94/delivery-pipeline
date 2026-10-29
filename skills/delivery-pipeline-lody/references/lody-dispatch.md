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
读回写 `model_evidence: lody-run-config`。不一致时该 lane 写 `setup_blocked`，附候选 id，
交 `delivery-pipeline-setup` 改配置；配置值原样使用。
冻结为 staged 的 implementation lane 写 `blocked`，原因 `lody staged adapter unavailable`。

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
`<prefix>issue-<coordinate>`，其他 mode 为 `none`；`base_commit` 为 `base_sha`；`workspace_id`、
`tab_id`、`pane_id` 与 `herdr_*` 字段为 `none`。

## 派发关键路径

implementation 新建或 replacement 前，按 `gate-state-machine.md` 实施前置检查运行
`implementation_gate.py`，通过后执行：

1. registry 写 task type、output_mode、agent/model/effort、`model_evidence`、阶段计划与来源、
   `base_commit` 与 overlay intent（`operation_id: <lane_id>`），精确 readback。
2. 填写 `../assets/LODY_ROLE_DISPATCH_PACKET.md`，写入 `~/.config/delivery-pipeline/packets/<lane_id>.md`。
3. 同批 lanes 在同一轮并行调用 `lody_session_create`：`operationId: <lane_id>`；`prompt` 为 packet
   全文；`machineId` 与 `agentConfigId` 取 overlay；`modelId` 与 `reasoningEffort` 取冻结计划；
   `useCurrentSessionAsParent: false`；`workContext: {kind: "local", projectId, worktree: true}`。
   权限沿 agent config 默认：不传 `modeId` 与权限类 `configOptionValues`；不传 `branch`，基点由
   worker 对齐。
4. 返回 Operation handle 后，HITL lane 写 `awaiting_human`，其余写 `running`。调用报错或超时时用
   同一 `operationId` 重试，Lody 按该 id 去重；`SYNC_UNAVAILABLE` 按工具说明最多三次。仍失败写
   `setup_blocked`，同批其余 lane 继续。

## Startup Readback

对每条 lane 调一次 `lody_operation_get(operationId)` 取 target session id，再用
`lody_session_status_many` 一次读回整批：session 存在、machine 等于 overlay、执行状态为 busy 或
已结束。写 `session_id`、`session_link`，用 `lody_session_rename` 设标题
`map-<map> <role> #<coordinate>`，并 readback。宿主读回给出 worktree 路径时写入 `worktree`，
否则记 Unknown，由终态报告「现场」与 `git worktree list --porcelain` 在 fan-in 补齐。
session 与 overlay 不一致写 `setup_blocked` 并保留现场。

整批每项都已 `running`/`awaiting_human` 或 `setup_blocked` 后到达 Dispatch Handoff：逐条报告
lane 的 `session_link`，结束本轮。Lody 在下一个输入边界投递 Operation 结果，coordinator 不轮询。
