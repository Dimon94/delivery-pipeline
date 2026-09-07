# Test Decision、Rebase 与 Closeout

Execution graph 清空、configured testing/review lanes完成后读取。

## Preconditions

- 所有 implementation lanes integrated/closed；无 active writer或 unresolved blocker。
- testing role的 whole-change checks通过。
- review role的 code-review verdict允许通过。
- Map Integration Worktree clean，registry/Git/tracker一致。

## Test Decision Point

先读 map registry 的 `test_strategy`。已有用户明确选择且范围与风险未变化时复用；
选择缺失、范围变化、出现新风险或未知是否仍适用时，才写 `test_decision_paused` 并让用户选择：

1. 在 Integration Worktree 进行额外手动测试；
2. 先 rebase 到最新 main，再测试；
3. 跳过额外手动测试并进入获授权的 remote closeout。

选择持久化到 map registry，同时在 tracker checkpoint 记录对应范围与已知风险，供恢复时核对。
旧记录不足以判断适用性时补问，不猜测。测试选择不授予 remote publication authority。
Configured testing lane 的证据不因用户跳过额外手动测试而省略。

`test_in_integration` 在 rebase 前完成额外手测；`rebase_then_test` 在 rebase 后完成；
`skip_extra_test` 仅省略额外手测。所选手测没有通过证据时保留 gate 并请求用户验收。

## Rebase

在 Integration Worktree：

```bash
git fetch --all --prune
git rebase <remote>/<main-branch>
```

冲突时停止并解析 `resolving-merge-conflicts` owner；传递 Integration Worktree、冲突文件、完整
requirements与测试证据。解决后重新运行 testing/review所需的最小 gates；不得通过冲突解决减少需求。

## Remote Gate

没有 remote publication authority 时停在 clean、已验证的 Integration branch并报告唯一剩余
动作。获得 authority 后加载 `remote-closeout-checklist.md`，按用户选择 push main 或打开 summary
PR/MR，等待 CI/CD 与 provider-native review verdict。

## Cleanup

远程成功后按 lane registry关闭全部 map tabs/panes，删除 clean Execution Worktrees/branches与
Map Integration Worktree/branch；保留 Coordinator Pane及所有承载 Workspace。任何 dirty/Unknown
坐标 fail closed并报告。

完成标准：测试、review、rebase、remote readback与 tracker close一致；或在无 remote authority 时
给出唯一可恢复本地坐标。
