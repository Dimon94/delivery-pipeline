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
role: discovery | spec | tickets | implementation | review
lane_id: <stable-id>
runtime: herdr-claude-pane | herdr-codex-pane
state: created | running | terminal_report_pending | terminal | consumed | integrated | closed | blocked | close_pending
workspace_id: <id>
tab_id: <id>
pane_id: <id>
lead_pane_id: <id>
waiter_owner: <lead-pane-id>
waiter_state: attached | terminal | needs_reattach
waiter_attached_at: <ISO-8601>
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

```text
created -> running -> terminal_report_pending -> terminal
                   \---------------------------> terminal
terminal -> consumed -> closed
terminal -> integrated -> closed
terminal -> blocked
integrated -> close_pending -> closed
```

listener 是会话内进程；`waiter_state: attached` 只描述最近一次挂载。新 lead 必须重新挂载，
不能把旧值当作活 listener。

registry 写入或 readback 失败时，关闭尚未接单的 pane并把该 work item 标为 setup blocked；
不声称该 child 可恢复。

## Fresh-session Recovery

1. 从 map/spec/tickets 向下枚举 work items，读取每个 `lane_id` 的 latest registry。
2. 通过 `/herdr` skill 验证 pane 的 workspace、tab、cwd 和 lifecycle。
3. 用 `git worktree list --porcelain`、branch 和 commit 验证有 Git lane 的坐标。
4. `running` 且 pane 存在：按 `child-monitoring.md` 给新 lead 重挂 listener。
5. pane 已 terminal：执行 marker-based Terminal Readback。
6. pane 消失但 commit/artifact 存在：从持久证据继续 fan-in。
7. `integrated`/`consumed`/`close_pending` 且 pane 存在：重试关闭；pane 已消失则写 `closed`。
8. registry 与现实不一致：保留证据并标 stale；确认没有 active writer 后才能 replacement。

没有 registry 的旧 child 只做一次 bounded recovery：按精确 work-item URL/编号、role、branch
和 cwd 交叉匹配 `/herdr` agent list。唯一匹配且全部验证通过时补写 registry；零个或多个匹配时
报告 unknown，不覆盖可能存在的 writer。

关闭 pane 不删除 worktree；worktree 清理由独立、明确授权的流程负责。
