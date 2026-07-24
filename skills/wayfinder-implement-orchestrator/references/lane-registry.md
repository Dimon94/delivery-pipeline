# Durable Child Registry

每个 dispatched work item 用 tracker checkpoint comment 保存可恢复坐标：decision child 写在
decision issue，spec gate 写在 map，tickets gate 写在 spec，implementation 写在自己的 issue。
聊天摘要和 task 标题不是 registry。

## Schema

以 `<!-- wayfinder-lane-registry:v1 -->` 开头：

```yaml
work_item: <url>
role: discovery | spec | tickets | implementation | review
lane_id: <stable-id>
runtime: codex-thread
state: created | running | terminal | consumed | integrated | blocked
project_id: <Source-owner-projectId>
thread_id: <id>
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
created -> running -> terminal -> consumed
                            \-> integrated
                            \-> blocked
```

registry 写入或 readback 失败时，不声称该 child 可恢复。

## Fresh-session Recovery

1. 从 map/spec/tickets 向下枚举 work items，读取每个 `lane_id` 的 latest registry。
2. 用 thread tools 验证 `thread_id`、`project_id`、task lifecycle 和 worktree。
3. 用 Git 验证 worktree、branch 和 commits。
4. `running` 且 task 存在：按 `child-monitoring.md` 重新调用 `wait_threads`。
5. task 已 terminal：读取 final report，进入 fan-in。
6. task 消失但 commit/artifact 存在：从持久证据继续 fan-in。
7. registry 与现实不一致：保留证据并标 stale；确认没有 active writer 后才能 replacement。

没有 registry 的旧 child 只做一次 bounded recovery：用 recent thread lookup 按精确 work-item
URL、role、projectId、branch 和 worktree 交叉匹配。唯一匹配且全部验证通过时补写 registry；
零个或多个匹配时报告 unknown，不覆盖可能存在的 writer。
