# Durable Lane Registry

每个 dispatched work item 用 tracker checkpoint保存可恢复坐标；聊天摘要与 pane label不是 registry。
Canonical 本文件只定义 Herdr/base schema；特殊 transport overlay 与其所有者共置。

## Base Schema

以 `<!-- wayfinder-lane-registry:v2 -->` 开头：

```yaml
work_item: <url-or-gate-coordinate>
role: planning | design | frontend | backend | testing | review | map
output_mode: commit | artifact | checks | verdict | none
lane_id: <stable-id>
runtime: herdr-pi-pane | herdr-codex-pane | herdr-claude-pane | orchestrator
state: created | running | awaiting_human | terminal | consumed | integrated | blocked | setup_blocked | integration_conflict | integration_checks_failed | path_conflict | stale | close_pending | test_decision_paused | rebase_in_progress | push_failed | cleanup_in_progress | closed
agent: pi | codex | claude | none
model: <configured-model-or-none>
effort: <configured-effort-or-none>
model_evidence: pi-list-models | codex-catalog | claude-env | none
execution_mode: legacy | staged | direct | none
execution_source: role-config | ticket | map | user-config | none
starting_model: <frozen-model-or-none>
starting_effort: <frozen-effort-or-none>
execution_model: <frozen-model-or-none>
execution_effort: <frozen-effort-or-none>
direct_model: <frozen-model-or-none>
direct_effort: <frozen-effort-or-none>
execution_phase: starting | switching | executing | direct | none
checkpoint: <repo-external absolute path-or-none>
checkpoint_version: <supported version-or-none>
checkpoint_sha256: <whole-checkpoint sha256-or-none>
continuation: <single persisted continuation overlay-or-none>
workspace_id: <id-or-none>
tab_id: <id-or-none>
pane_id: <id-or-none>
coordinator_runtime: pi-cli | codex-cli | claude-cli | none
dispatch_runtime: herdr | none
herdr_session_name: <name-or-none>
herdr_session_owned: true | false | none
bootstrap_authority: trusted_execution_bootstrap | none
agent_permission_mode: approve | danger-full-access | dangerously-skip-permissions | none
worktree: <absolute-path-or-none>
branch: <branch-or-none>
base_commit: <hash-or-none>
head_commit: <hash-or-none>
integrated_commit: <hash-or-none>
integration_worktree_path: <absolute-path-or-none>
integration_branch: <feature/map-N-or-none>
map_run_authority: canonical_tracker_transitions | none
herdr_workspace_label: <actual-workspace-label-or-none>
test_strategy: test_in_integration | rebase_then_test | skip_extra_test | none
updated_at: <ISO-8601>
```

不写 secrets。更新后精确 readback；失败时不声称 lane可恢复。特殊 transport 字段不进入本 schema。

## Worker State Machine

```text
created -> running | awaiting_human
running/awaiting_human -> terminal | blocked
created -> setup_blocked
terminal(commit) -> integrated | integration_conflict | integration_checks_failed | blocked
terminal(artifact/checks/verdict) -> consumed | blocked
integrated/consumed -> cleanup_in_progress -> closed
cleanup_in_progress -> close_pending -> closed
any active state -> path_conflict | stale
```

`awaiting_human` 表示 packet accepted且 agent working，用户正在 Herdr参与。整批 user-visible lanes
完成 registry readback即 Dispatch Handoff，不持续 monitoring。

## Map State Machine

```text
created -> running -> rebase_in_progress -> cleanup_in_progress -> closed
running -> test_decision_paused -> rebase_in_progress
rebase_in_progress -> push_failed -> rebase_in_progress | closed
```

map row使用 `role: map`、`output_mode: none`、`runtime: orchestrator`，并持久化 Integration
Worktree/branch、Map Run Authority与 test strategy；测试选择是否仍适用及额外测试证据按
`test-decision-and-rebase.md` 核对，只有需要询问时进入 `test_decision_paused`。
`base_commit` 固定为创建 Map Integration Worktree
时的 Source HEAD，作为 whole-change Review fixed point，后续 Integration 不改写。Herdr
session/workspace/tab/pane是 lane坐标；
同一 map后续新 lane可随 Coordinator Pane 的 current-workspace 默认落到另一 Workspace。

## Recovery

1. 枚举 map/spec/ticket items，读取每个 lane_id latest registry。
2. Herdr runtime 验证 session/workspace/tab/pane、kind、role/output_mode、agent/model/effort 与 worktree；
   execution mode/source 与阶段参数也必须一致；agent/model/effort 是 stored 启动坐标，不与 pane 的
   运行中模型对账。existing lane 不应用新 config 也不迁移 Workspace，新 lane 重新解析 Coordinator Pane
   当前坐标。
3. 用 Git验证 worktree、branch、commits与 dirty state。pane消失但持久 evidence存在时按
   output_mode fan-in；两者都不存在且排除 active writer后才 replacement。
4. `awaiting_human` 只在用户返回时 fan-in；恢复不挂 watcher、不定时 wait。
5. `integrated` / `consumed` / `close_pending` 按 cleanup contract readback或重试。
6. registry 与现实不一致时写 `stale`并保留证据，不覆盖可能存在的 writer。

## Prewalk Checkpoint

`starting` implementation worker 的首改现场由 canonical
`skills/delivery-pipeline/scripts/checkpoint.py` 生成；checkpoint 必须位于 repo 外，并由同目录临时
文件 `flush` + `fsync` 后原子替换。JSON 使用 UTF-8、键排序和紧凑分隔；`component_sha256` 分别
覆盖 dirty content、file mode、staged/index 与完整 snapshot，`checkpoint_sha256` 计算时排除自身。
同一路径只允许相同指纹幂等重写；任何更新必须写入新的 repo 外 artifact 路径，旧 checkpoint 不覆盖。

checkpoint 至少包含 lane/work item、runtime 与原生 session、Coordinator 坐标、CLI version、Execution
Worktree/branch/base/HEAD、phase/development mode/source/plan、requested/tool acceptance/actual
readback（不可读时显式 `Unknown`）、首改、检查、TODO、decision 和 evidence。dirty 路径按路径排序，
删除项显式记录，未跟踪项纳入；ignored 路径只保存内容/模式指纹并标记 `delivery_input: Unknown`，
直到确认没有 ignored 路径才可继续；unsupported 文件类型、缺字段、旧版本、hash 不匹配或当前 Git
snapshot 改变均不得登记成功引用。

阶段计划必须完整冻结 `starting`、`execution`、`direct` 三组 model/effort，并与当前 phase、
`development_mode`（`legacy|staged|direct`）及 `mode_source`（`role-config|ticket|map|user-config`）
一致；`tool_acceptance` 必须是明确的 accepted/status/source 结构。阶段信号分层：
`PREWALK_READY` 只触发 checkpoint 持久读回；只有原 runtime 的 `runtime`、原生 `session_id`、
coordinator thread/host 身份全部匹配，且已停止、单写者明确为 false 的 `WORKER_STOPPED` 才能返回
`ready-for-coordinator`。active 返回等待，活动状态或身份 Unknown、关键设计 Unknown、ignored 路径、
工具拒绝或实际模型/effort Unknown 均保留现场；该入口不发送接续、不触发 Terminal fan-in。

## Continuation Overlay

接续复用同一 lane registry，不创建第二份 registry、receipt 或 journal。`continuation.py` 只返回
overlay 和 runtime-neutral request；coordinator 必须先把一个 `continuation` overlay 写入既有 registry
并 readback，再向原 session 发送。overlay 的 `intent` 由 lane、原 session、source phase、checkpoint
SHA-256 和 target request 唯一确定；`state` 依次记录 `prepared`、`dispatching`、`send-authorized`、`sent`、`send-unknown`、`accepted`、
`started`、`executing` 或 `blocked`。

`dispatching` 只能在带当前 `request_id`、`after_marker: true`、`settled: true`、非空来源/时间的发送后
readback 且明确 `not_seen` 时返回可发送请求；旧 stopped 观测、在途调用或缺少 readback 只能回读，不能重发。

`send-authorized` 已落盘但发送前崩溃时，只有当前 `request_id` 的权威回读明确
`request_seen: false`、`not_seen`、`after_marker: true`、`after_lease: true`、`settled: true`，
且来源/时间非空、不是生成当前 lease 的同一 `send_probe`，才返回恢复到 `dispatching` 的 overlay。
该步返回 `request: null`；coordinator 必须持久化并读回后，再生成、持久化并读回新的 send lease 才发送。
同一 intent 保持既有 request_id；恢复回读保存在 `send_probe`，不新增协议或 journal。
seen、Unknown、身份不匹配或仅有 lease 前回读均保留现场，不重发；acceptance 可独立先于发送回执到达。

`request`、`tool_acceptance`、`new_turn`、`actual_model` 是四个独立字段；发送结果 Unknown 只允许
回读原 session，不允许增加请求数。`new_turn` 必须绑定本次 `request_id`、原 session 和新的
`turn_id`；只有原 session 的 `new_turn.started: true` 才能把 `execution_phase` 写为 `executing`。
`actual_model` 必须绑定该 `turn_id` 并带非空 `readback_at`；实际 model/effort Unknown 或 mismatch 不通过换模验收，
但后续同一 turn 的漂移只更新验收证据，不自动阻断已有交付 fan-in。用户手动
目标保留在 intent，`configuration_unchanged: true`，不回写 Worker Role Configuration。重复 terminal
和 fan-in 以稳定 ID 幂等消费，冲突或无法消歧时保持现场并 fail-closed。适用 gate 必须同时绑定
当前 `checkpoint_sha256`、`work_item` 和非空 `source`；旧版本批准不能替代当前用户确认。
未改动目标可沿既有分派授权以 `authorization: inherited-dispatch` 接续；用户改码或手动换模必须带新的
`approved: true` 覆盖，不回写全局配置。
`terminal.outcome: blocked` 可以在新轮前记录受阻终态但不得 fan-in；`completed` 必须绑定当前原
session、接续 request 和新轮 `turn_id`，并与 lane 的 `output_mode` 一致，`commit` 只可 `integrated`，
`artifact/checks/verdict` 只可 `consumed`。
