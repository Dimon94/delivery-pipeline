# Role-aware Execution Worktree Fan-in

Configured Herdr lane terminal 后读取。WAKE/final report只负责唤醒；Git、tracker、artifact、registry、
checks与 verdict 是执行真相源。

## Common Preflight

1. 从 registry读取 role、output_mode、agent、ordinary/bootstrap route、Gearshift Projection、runtime、pane、
   worktree、branch、base commit。
2. 验证 pane kind/runtime、worktree common dir、branch、HEAD、dirty state与 final evidence。Gearshift enabled
   时额外验证 final report 的 Shift ID、Source/Target、Adapter、`shifted` state 与 session record reference
   精确匹配 registry；缺失、blocked 或手动模型变化冒充 Shift 时阻塞。
3. final marker 缺字段记 Unknown；不要求 worker 重显。
4. output_mode 与 role/gate packet 不一致时阻塞；unknown active writer时不 cleanup。

## Commit Mode

适用于 design/frontend/backend implementation。

1. 要求 terminal commit包含 base commit，且只承载 packet work item；验证内嵌 code-review 的
   Review fixed point 等于 lane base commit、bundle 七文件 readback存在；Gearshift enabled 时 Bootstrap
   Checkpoint 与 Shift Record readback存在。无 commit、review/Gearshift evidence 或 dirty未说明时阻塞。
2. 在 Map Integration Worktree按 dependency order执行 `git cherry-pick "$TERMINAL_COMMIT"`。
3. 冲突时 `git cherry-pick --abort`，写 `integration_conflict`，保留 pane/worktree/branch并解析
   `resolving-merge-conflicts` owner。
4. cherry-pick 后运行 focused checks；失败写 `integration_checks_failed`并保留现场；通过写
   `integrated`。

## Artifact / Checks / Verdict Modes

- `artifact`：验证 tracker/artifact URL/ID/body与 expected work item一致。
- `checks`：验证完整命令、结果与失败细节；失败写 `blocked`并阻止 review。
- `verdict`：验证 Review fixed point 等于 map registry base commit、bundle 七文件在 fan-in 时可读、
  verdict/findings完整；blocking finding写 `blocked`并阻止 closeout。

三类都不要求 commit、不 cherry-pick。worktree必须 clean；若 owner确实需要 repo 变更，packet应改成
`commit` mode并重派，不能把 dirty state当 artifact。成功写 `consumed`。

## Cleanup

`integrated` 或 `consumed` 后统一：

1. 关闭本 lane pane并同步 tab label:从 X tab label 移除该 work item 编号;X tab 空后 label
   还原并保留 tab。
2. 删除 clean Execution Worktree。
3. 删除对应 agent-prefixed branch。
4. readback pane/worktree registration/branch均不存在。
5. cleanup失败写 `close_pending`并保留坐标；已完成的 Integration/consumption不回滚。
6. cleanup readback成功写 `closed`，完成 tracker resolution并自动重算 ready frontier。

完成标准：output-mode evidence已验证，状态为 integrated/consumed/closed，transport/worktree/branch
cleanup一致；失败时现场与精确 blocker被保留。
