# Durable Lane Registry

每个 dispatched work item 用 tracker checkpoint保存可恢复坐标；聊天摘要与 pane label不是 registry。
Canonical 本文件只定义 Herdr/base schema；特殊 transport overlay 与其所有者共置。

## Base Schema

新写入的 row 以 `<!-- wayfinder-lane-registry:v3 -->` 开头：

```yaml
work_item: <url-or-gate-coordinate>
role: planning | design | frontend | backend | testing | review | map
output_mode: commit | artifact | checks | verdict | none
lane_id: <stable-id>
agent_name: <stable-herdr-agent-name-or-none>
packet_path: <absolute-path-or-none>
packet_sha256: <hash-or-none>
runtime: herdr-pi-pane | herdr-codex-pane | herdr-claude-pane | orchestrator
state: created | running | awaiting_human | terminal | consumed | integrated | blocked | setup_blocked | integration_conflict | integration_checks_failed | path_conflict | stale | close_pending | test_decision_paused | rebase_in_progress | push_failed | cleanup_in_progress | closed
agent: pi | codex | claude | none
model: <ordinary-role-model-or-none>
effort: <ordinary-role-effort-or-none>
bootstrap_model: <configured-bootstrap-model-or-none>
bootstrap_effort: <configured-bootstrap-effort-or-none>
model_evidence: pi-list-models | codex-catalog | claude-env | none
gearshift_mode: off | opt_in | all_eligible | none
gearshift_enabled: true | false | none
gearshift_eligibility: off | ticket-label | all-eligible | ineligible | none
gearshift_opt_in_label: <JSON-string-or-none>
gearshift_profile: delivery-bootstrap | none
gearshift_shift_id: <id-or-none>
gearshift_source_model: <model-or-none>
gearshift_target_model: <model-or-none>
gearshift_adapter: delivery-pipeline/bootstrap-slice | none
gearshift_state: requested | armed | ready | shifting | shifted | blocked | cancelled | none
gearshift_evidence_ref: <session-record-reference-or-none>
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

## Legacy v2 Recovery

`<!-- wayfinder-lane-registry:v2 -->` 是已发布的既有 lane 格式，必须继续可恢复；不把旧 row 原地迁移成
v3，也不因用户配置已升级或仍为 version 2 而阻塞。读取 v2 row 时：

- `agent`、`model`、`effort`、runtime、pane、worktree、branch 与 commit 坐标保持原义；v2 缺失
  agent name 或 packet 坐标时保持 none，不猜测；
- 缺失的 Bootstrap/Gearshift 字段解释为 disabled/none；不得从当前配置补入 Source、Target、policy 或 Shift ID；
- 恢复、fan-in、cleanup 和 replacement 不读取当前 Worker Role Configuration，而是继续沿 v2 row 的
  ordinary route；replacement 在排除 active writer 后可创建替代 agent并重新生成 packet，不要求旧 row
  不存在的 agent/session/packet 坐标，且始终禁用 Gearshift；
- v2 row 的 output mode、state 与 fixed-point 语义保持不变；只有 v2 当时不存在的字段使用上述缺省；
- 更新既有 v2 lane 时保留 v2 marker 与字段集合；新 work item 才写 v3 row。

因此 existing lane recovery 先于任何新 lane 配置 Gate。无法由 v2 坐标唯一证明的状态仍按 `stale`
fail closed，而不是通过 schema migration 猜测。

## Gearshift Projection Checkpoints

Pi session branch 的 Shift Record 是独立真相源；registry 只是 coordinator-owned Projection，worker final
report 不拥有它。所有更新使用一个 bounded tracker transaction 并 exact readback：

1. **Requested。** 首次创建 eligible lane 时，先写 policy、eligibility、JSON-quoted opt-in label、profile、
   planned Source/Target、Adapter、`gearshift_state: requested`，Shift ID/evidence ref 为 none；然后创建 pane。
2. **Armed。** 只启动 Pi agent，不投递工作 packet。Coordinator 读取同一 session 输出的
   `GEARSHIFT_ARMED <json>`，验证 profile、完整 Shift ID、Source/Target、Adapter 与
   `gearshift-shift:<shiftId>` reference。成功后把这些字段和 `gearshift_state: armed` 写入 registry 并
   readback；Armed Projection readback 后才生成最终 packet。将 packet absolute path 与 SHA-256 写入
   registry 并 exact readback 后才 prompt。失败按 startup failure state 处理，worker 不接收 work item。
3. **Monitor/Recovery。** 仅在显式 monitor、terminal wake 或 recovery 时读取同一 session 的
   `GEARSHIFT_STATUS <json>` 与对应 Shift Record。先用 registry Armed Projection 验证 Shift ID 和不可变
   route 字段，再投影 `ready | shifting | shifted | blocked | cancelled`；缺失、冲突或损坏写 `stale`，不猜测。
4. **Terminal。** Coordinator 独立读取并验证 Shift Record 后，把 terminal state 与 evidence ref 作为一个
   tracker transaction 写入并 readback；随后才与 worker final report 交叉验证。final report 不作为
   Projection 更新依据，也不能单独证明 Shift。`shifted` 要求 Target model change 可读回；
   `blocked/cancelled` 保留 Source 和 blocker。事务失败保留旧 Projection 并阻止 fan-in。
5. **Disabled v3。** disabled v3 row 保留实际 mode、deterministic eligibility 与 JSON-quoted label，并写
   `gearshift_enabled: false`；只把 profile、Shift ID、Source/Target、Adapter、state、evidence ref 等运行态
   字段写 none。这样 off、opt-in 未命中与 role ineligible 可区分并可和 packet 对账。
6. **Legacy v2。** legacy row 才把缺失 Gearshift 字段解释为 disabled/none，不创建 Projection 事务。

`gearshift_opt_in_label` 保存配置 label 的 JSON string 表示；`gearshift_eligibility: ticket-label` 只表示
命中类型，不拼接自由文本。这样冒号、空格或 `#` 不改变 registry 结构。

## Worker State Machine

```text
created -> running | awaiting_human
running/awaiting_human -> terminal | blocked
created -> setup_blocked
created(requested replacement) -> blocked
created(armed-without-packet replacement) -> running | blocked
terminal(commit) -> integrated | integration_conflict | integration_checks_failed | blocked
terminal(artifact/checks/verdict) -> consumed | blocked
integrated/consumed -> cleanup_in_progress -> closed
cleanup_in_progress -> close_pending -> closed
any active state -> path_conflict | stale
```

`created(requested replacement) -> blocked` 仅用于 pane 消失且已排除 active writer、Requested Projection
尚无最终 packet时，重开同一 Worker session并读回 Core crash-window blocked status；不允许 prompt。
`created(armed-without-packet replacement) -> running | blocked` 只覆盖 Armed Projection 已 readback 但 packet
checkpoint 未完成的窗口；验证同一 Shift 后重新生成 packet，成功 Working 才进入 running。

`awaiting_human` 表示 packet accepted且 agent working，用户正在 Herdr参与。整批 user-visible lanes
完成 registry readback即 Dispatch Handoff，不持续 monitoring。

## Map State Machine

```text
created -> running -> test_decision_paused -> rebase_in_progress -> cleanup_in_progress -> closed
                                           \-> push_failed -> rebase_in_progress | closed
```

map row使用 `role: map`、`output_mode: none`、`runtime: orchestrator`，并持久化 Integration
Worktree/branch、Map Run Authority与 test strategy；`base_commit` 固定为创建 Map Integration Worktree
时的 Source HEAD，作为 whole-change Review fixed point，后续 Integration 不改写。Herdr
session/workspace/tab/pane是 lane坐标；
同一 map后续新 lane可随 Coordinator Pane 的 current-workspace 默认落到另一 Workspace。

## Recovery

1. 枚举 map/spec/ticket items，读取每个 lane_id latest registry。
2. 按 marker 选择 Base Schema 或 Legacy v2 Recovery，再验证 Herdr session/workspace/tab/pane、kind、
   role/output_mode、agent、registry-owned route 与 worktree；v3 Gearshift-enabled lane 才验证 Gearshift
   Projection。existing lane 不应用新 config、不迁移 Workspace；新 lane 重新解析 Coordinator Pane 当前坐标。
3. 用 Git验证 worktree、branch、commits与 dirty state。pane消失但持久 evidence存在时按
   output_mode fan-in；两者都不存在且排除 active writer后才 replacement。
4. `awaiting_human` 只在用户返回时 fan-in；恢复不挂 watcher、不定时 wait。
5. `integrated` / `consumed` / `close_pending` 按 cleanup contract readback或重试。
6. registry 与现实不一致时写 `stale`并保留证据，不覆盖可能存在的 writer。
