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
state: created | running | terminal | consumed | integrated | closed | blocked | close_pending | test_decision_paused | rebase_in_progress | push_failed | cleanup_in_progress
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
herdr_workspace_label: <map-title-map-N-or-none>
test_strategy: test_in_integration | rebase_then_test | skip_test_and_push | none
# --- common fields ---
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

## Fresh-session Recovery

1. 从 map/spec/tickets 向下枚举 work items，读取每个 `lane_id` 的 latest registry。
2. `runtime: codex-thread` 的 `running` / `terminal` lane 用 active thread tools 验证
   `thread_id`、`host_id`、`project_id`、task lifecycle 和 worktree；running task 重新调用
   `wait_threads`。
3. `runtime: codex-thread` 的 `integrated` / `close_pending` / `closed` lane 用
   `list_archived_threads` 验证 `thread_archived`；`close_pending` 重试 `set_thread_archived` 并
   readback，成功后写 `closed`。
4. `runtime: herdr-codex-pane | herdr-claude-pane` 用 `$herdr` 验证
   workspace/tab/pane、worker kind 与 final marker。
5. 用 Git 验证所有 runtime 的 worktree、branch 和 commits。
6. lane 已 terminal：读取 final report，进入 fan-in。
7. task/pane 消失但 commit/artifact 存在：从持久证据继续 fan-in。
8. registry 与现实不一致：保留证据并标 stale；确认没有 active writer 后才能 replacement。

没有 registry 的旧 child 只做一次 bounded recovery：用 recent thread lookup 按精确 work-item
URL、role、projectId、branch 和 worktree 交叉匹配。唯一匹配且全部验证通过时补写 registry；
零个或多个匹配时报告 unknown，不覆盖可能存在的 writer。
