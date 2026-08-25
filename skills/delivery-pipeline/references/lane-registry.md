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
created -> running -> test_decision_paused -> rebase_in_progress -> cleanup_in_progress -> closed
                                           \-> push_failed -> rebase_in_progress | closed
```

map row使用 `role: map`、`output_mode: none`、`runtime: orchestrator`，并持久化 Integration
Worktree/branch、Map Run Authority与 test strategy。Herdr session/workspace/tab/pane是 lane坐标；
同一 map后续新 lane可随 Coordinator Pane 的 current-workspace 默认落到另一 Workspace。

## Recovery

1. 枚举 map/spec/ticket items，读取每个 lane_id latest registry。
2. Herdr runtime验证 session/workspace/tab/pane、kind、role/output_mode、agent/model/effort与 worktree；
   existing lane不应用新 config也不迁移 Workspace，新 lane重新解析 Coordinator Pane当前坐标。
3. 用 Git验证 worktree、branch、commits与 dirty state。pane消失但持久 evidence存在时按
   output_mode fan-in；两者都不存在且排除 active writer后才 replacement。
4. `awaiting_human` 只在用户返回时 fan-in；恢复不挂 listener、不定时 wait。
5. `integrated` / `consumed` / `close_pending` 按 cleanup contract readback或重试。
6. registry 与现实不一致时写 `stale`并保留证据，不覆盖可能存在的 writer。
