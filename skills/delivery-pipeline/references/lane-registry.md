# Durable Child Registry

每个 dispatched work item 用 tracker checkpoint comment 保存可恢复坐标：decision child 写在
decision issue，spec gate 写在 map，tickets gate 写在 spec，implementation 写在自己的 issue。
聊天摘要和 task 标题不是 registry。

## Schema

以 `<!-- wayfinder-lane-registry:v1 -->` 开头：

```yaml
work_item: <url>
role: discovery | spec | tickets | implementation | review | map
lane_id: <stable-id>
runtime: subagent | codex-thread | herdr-codex-pane | herdr-claude-pane | orchestrator
state: created | running | awaiting_human | terminal | consumed | integrated | closed | blocked | close_pending | test_decision_paused | rebase_in_progress | push_failed | cleanup_in_progress
# --- codex-thread fields (runtime: codex-thread) ---
project_id: <Source-owner-projectId>
host_id: <host-id>
thread_id: <id>
thread_archived: true | false | unknown
# --- pane fields (runtime: herdr-codex-pane | herdr-claude-pane) ---
workspace_id: <id>
tab_id: <id>
pane_id: <id>
# --- subagent fields (runtime: subagent) ---
agent_name: <Agent tool name parameter | none>
# --- map fields (role: map, runtime: orchestrator) ---
integration_worktree_path: <absolute-path-or-none>
integration_branch: <feature/map-N-or-none>
coordinator_runtime: codex-app | codex-cli | claude-cli | none
dispatch_runtime: codex-app | herdr | none
map_run_authority: canonical_tracker_transitions | none
herdr_workspace_label: <map-title-map-N-or-none>
test_strategy: test_in_integration | rebase_then_test | skip_test_and_push | none
# --- common fields ---
herdr_session_name: <explicit-target-session-or-none>
herdr_session_owned: true | false | none
bootstrap_authority: trusted_execution_bootstrap | none
agent_permission_mode: dangerously-skip-permissions | default | none
worktree: <absolute-path-or-none>
branch: <branch-or-none>
base_commit: <hash-or-none>
head_commit: <hash-or-none>
integrated_commit: <hash-or-none>
updated_at: <ISO-8601>
```

不写入 secrets。优先更新原 checkpoint；tracker 不支持编辑时追加新 checkpoint，并按
tracker 顺序取同一 `lane_id` 的最后一条。每次写入都 readback 精确字段。

## State Machine

**Implementation ticket states:**

```text
created -> running -> terminal -> consumed -> closed
                            \-> integrated -> closed
                            \-> blocked
integrated -> close_pending -> closed
```

**Herdr HITL states:**

```text
created -> awaiting_human -> terminal -> consumed -> closed
       \-> blocked (startup only)
```

`awaiting_human` 表示 `agent prompt` 已 accepted、agent 已从 `idle` 进入 `working`，用户正在 Herdr 与 worker 交互。
coordinator 在该状态 yield；用户回到 Codex App 报告完成后才启动 terminal fan-in。
未知或越界 startup UI 才把 registry 写为 `blocked`；handoff 后的业务问题即使 Herdr agent
呈现 `blocked`，registry 仍保持 `awaiting_human`。

**Map states:**

```text
created -> running -> test_decision_paused -> rebase_in_progress -> cleanup_in_progress -> closed
                                           \-------------------> push_failed -> (retry) -> closed
```

**Integration worktree lifecycle (tracked in map issue registry):**

```text
created -> discovery_complete -> spec_complete -> tickets_complete 
  -> all_integrated -> test_decision -> rebasing -> merged -> closed
```

registry 写入或 readback 失败时，不声称该 child 可恢复。

`running` 或 `awaiting_human` 的 user-visible lane 完成 registry readback 即 Dispatch Handoff；coordinator
结束本轮。running 不是要求持续 monitoring 的状态。

## Fresh-session Recovery

1. 从 map/spec/tickets 向下枚举 work items，读取每个 `lane_id` 的 latest registry。
2. `runtime: codex-thread` 的 `running` / `terminal` lane 用 active thread tools 验证
   `thread_id`、`host_id`、`project_id`、task lifecycle 和 worktree；running task 只报告坐标，
   用户完成信号或显式 monitor 请求才调用 `wait_threads`。
3. `runtime: codex-thread` 的 `integrated` / `close_pending` / `closed` lane 用
   `list_archived_threads` 验证 `thread_archived`；`close_pending` 重试 `set_thread_archived` 并
   readback，成功后写 `closed`。
4. `runtime: herdr-codex-pane | herdr-claude-pane` 按 `dispatch-runtime-routing.md` 的 Herdr
   Control Route，用 `herdr_session_name` 验证 workspace/tab/pane 与 worker kind。
   lane 缺少 session name 时坐标为 `Unknown`；`herdr_session_owned: false` 时只收口 lane pane，
   保留 user-visible session。
5. `state: awaiting_human` 只在用户返回触发时按 `frontier-lanes.md` fan-in；恢复过程不读取 pane、
   不挂 listener、不启动定时 wait。
6. 用 Git 验证所有 runtime 的 worktree、branch 和 commits。
7. lane 已 terminal：按 `frontier-lanes.md` 从持久证据进入 fan-in。
8. task/pane 消失但 commit/artifact 存在：从持久证据继续 fan-in。
9. registry 与现实不一致：保留证据并标 stale；确认没有 active writer 后才能 replacement。

没有 registry 的旧 child 只做一次 bounded recovery：用 recent thread lookup 按精确 work-item
URL、role、projectId、branch 和 worktree 交叉匹配。唯一匹配且全部验证通过时补写 registry；
零个或多个匹配时报告 unknown，不覆盖可能存在的 writer。
