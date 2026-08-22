# Durable Child Registry

每个 dispatched work item 用 tracker checkpoint comment 保存可恢复坐标：

- decision child：写在该 decision issue。
- spec gate：写在 source map issue。
- tickets gate：写在 source spec issue。
- implementation：写在该 implementation issue。

聊天、pane label、本地快照和后台 listener 都不是持久状态。

## Schema

以 `<!-- wayfinder-lane-registry:v1 -->` 开头：

```yaml
work_item: <url>
role: discovery | spec | tickets | implementation | review | map
lane_id: <stable-id>
runtime: subagent | herdr-claude-pane | herdr-codex-pane | orchestrator
state: created | running | terminal_report_pending | terminal | consumed | integrated | closed | blocked | close_pending | test_decision_paused | rebase_in_progress | push_failed | cleanup_in_progress
# --- subagent fields (runtime: subagent) ---
agent_name: <Agent tool name parameter | none>
# --- pane fields (runtime: herdr-*) ---
workspace_id: <id | none>
tab_id: <id | none>
pane_id: <id | none>
lead_pane_id: <id | none>
waiter_owner: <lead-pane-id | none>
waiter_state: attached | terminal | needs_reattach | none
waiter_attached_at: <ISO-8601 | none>
# --- map fields (role: map, runtime: orchestrator) ---
coordinator_runtime: claude-cli
dispatch_runtime: herdr
integration_worktree_path: <absolute-path-or-none>
integration_branch: <branch-or-none>
herdr_workspace_label: <label-or-none>
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
created -> running -> terminal_report_pending -> terminal
                   \---------------------------> terminal
terminal -> consumed -> closed
terminal -> integrated -> closed
terminal -> blocked
integrated -> close_pending -> closed
```

**Map states:**

```text
created -> running -> test_decision_paused -> rebase_in_progress -> cleanup_in_progress -> closed
                                           \-------------------> push_failed -> (retry) -> closed
```

listener 是会话内进程；`waiter_state: attached` 只描述最近一次挂载。新 lead 必须重新挂载，
不能把旧值当作活 listener。

`runtime: subagent` 的 lane 没有 pane listener；完成通知由 `Agent` tool 直接推送给
lead 会话。subagent lane 的 pane 字段全部为 `none`。

registry 写入或 readback 失败时，关闭尚未接单的 pane（或取消 subagent）并把该 work item
标为 setup blocked；不声称该 child 可恢复。

## Fresh-session Recovery

1. 从 map/spec/tickets 向下枚举 work items，读取每个 `lane_id` 的 latest registry。
2. `runtime: subagent`：subagent 完成状态无法跨会话恢复——若 registry 仍为 `running`，
   检查 branch/artifact 是否存在；存在则从持久证据继续 fan-in；不存在则标 `blocked`
   并由 lead 决定是否重新派发。
3. `runtime: herdr-*`：通过 `/pane-dispatch` skill 验证 pane 的 workspace、tab、cwd 和 lifecycle。
4. 用 `git worktree list --porcelain`、branch 和 commit 验证有 Git lane 的坐标。
5. `running` 且 pane 存在：按 `child-monitoring.md` 给新 lead 重挂 listener。
6. pane 已 terminal：执行 marker-based Terminal Readback。
7. pane 消失但 commit/artifact 存在：从持久证据继续 fan-in。
8. `integrated`/`consumed`/`close_pending` 且 pane 存在：重试关闭；pane 已消失则写 `closed`。
9. registry 与现实不一致：保留证据并标 stale；确认没有 active writer 后才能 replacement。

没有 registry 的旧 child 只做一次 bounded recovery：按精确 work-item URL/编号、role、branch
和 cwd 交叉匹配 herdr agent list（通过 `/pane-dispatch` skill）。唯一匹配且全部验证通过时补写 registry；零个或多个匹配时
报告 unknown，不覆盖可能存在的 writer。

关闭 pane 不删除 worktree；worktree 清理由独立、明确授权的流程负责。
