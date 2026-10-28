# T3Code 调度运行时路由

创建或替换 worker lane 前读取。本文件是 canonical 主干的 T3Code transport adapter：coordinator
是当前 T3 线程，所有新 worker 都是 `delegate_task` 子任务。恢复既有 lane 直接读
`t3code-lifecycle.md` §恢复，不运行新 lane 的配置 gate。

canonical 合同位于 `../../delivery-pipeline/references/`，下文以文件名引用。

## Preflight

每批 maximal safe batch 前做一次只读 snapshot：

1. `orchestrator_capabilities` 读回 `parentThreadId`、`inheritedProviderInstanceId`，目标 provider
   `canRunChildTask: true`；跨 provider 时还要 `canRunCrossProviderChildTask: true`。
2. `t3_worktree_status` 读回 `attached: false`，且 `projectWorkspaceRoot` 的
   `git rev-parse --git-common-dir` 等于 Source repo 的 common dir。T3 在该 project 根下建子
   worktree；coordinator 绑定在其他 worktree 或其他 project 时报告 `dispatch unavailable`。
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
完全一致，effort 属于该 option 的 `values`。读回写 `model_evidence: t3-capabilities`。不一致时该
lane 写 `setup_blocked`，附目录候选 id，交 `delivery-pipeline-setup` 改配置；配置值原样使用。
冻结为 staged 的 implementation lane 写 `blocked`，原因 `t3 staged adapter unavailable`。

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
```

base 字段：`runtime: t3-task`；`worktree` 取子线程 `worktreePath`；`branch` 在 commit mode 为
`<prefix>issue-<coordinate>`，其他 mode 为 `none`；`base_commit` 为 `base_sha`；`workspace_id`、
`tab_id`、`pane_id` 与 `herdr_*` 字段为 `none`。

## 派发关键路径

implementation 新建或 replacement 前，按 `gate-state-machine.md` 实施前置检查运行
`implementation_gate.py`，通过后执行：

1. registry 写 task type、output_mode、agent/model/effort、`model_evidence`、阶段计划与来源、
   `base_commit` 与 overlay intent，精确 readback。
2. 填写 `../assets/T3CODE_ROLE_DISPATCH_PACKET.md`，写入 `~/.config/delivery-pipeline/packets/<lane_id>.md`。
3. 调用 `delegate_task`：`task` 为 packet 全文；`title` 为 `map-<map> <role> #<coordinate>`；
   `target` 按上表映射，`options` 只含 effort option；`isolation: "worktree"`；`mode: "async"`；
   `clientRequestId: <lane_id>`；`role` 取 commit→`implementation`、checks→`test`、
   verdict→`review`、artifact→`research`（design HITL 用 `design`）。`runtimeMode` 与
   `interactionMode` 继承 coordinator。
4. receipt 写 `task_id`、`child_thread_id`、`link`；HITL lane 写 `awaiting_human`，其余写 `running`。
   调用报错或回复丢失时用同一 `clientRequestId` 重试一次，T3 按该 key 去重；仍失败写
   `setup_blocked`，同批其余 lane 继续。

## Startup Readback

对每个 `child_thread_id` 调 `t3_thread_read`，要求 `relationshipToParent: subagent`、`worktreePath`
非空、`status` 属于 `preparing | queued | starting | running | waiting`，且 worktree 的
common dir 等于 Source repo。写 `worktree` 与 `t3_branch` 并 readback。不一致写 `setup_blocked`
并保留现场。

整批每项都已 `running`/`awaiting_human` 或 `setup_blocked` 后到达 Dispatch Handoff：逐条报告
lane 的 `link`，结束本轮。T3 完成唤醒接管后续，coordinator 不轮询。
