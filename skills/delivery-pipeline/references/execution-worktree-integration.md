# Role-aware Execution Worktree Fan-in

integration lane（merger）对每条待收口 lane 执行；coordinator 不亲自执行。WAKE/final report只负责唤醒；Git、tracker、artifact、registry、
checks与 verdict 是执行真相源。

## Common Preflight

1. 从 registry读取 role、output_mode、agent/model/effort、runtime、pane、worktree、branch、base commit。
2. 验证 pane kind/runtime、worktree common dir、branch、HEAD、dirty state与 final evidence。
3. final marker 缺字段记 Unknown；不要求 worker 重显。
4. output_mode 与 role/gate packet 不一致时阻塞；unknown active writer时不 cleanup。

## Commit Mode

适用于 design/frontend/backend implementation。
先按 `gate-state-machine.md` 回读实施前置证据；越过 gate 的旧 lane 保留现场并阻塞 Integration。

1. 要求 terminal commit包含 base commit，且只承载 packet work item；无 commit 或 dirty 未说明时阻塞。
   所属壳仍启用逐票 review 时另验其 verdict 与 bundle。
2. 在 Map Integration Worktree按 dependency order执行 `git cherry-pick "$TERMINAL_COMMIT"`。
   独立票模式不 cherry-pick，按 `integration-worktree-management.md` §独立票模式走本票 MR 与状态分段。
3. 冲突时先判定能否语义合并（跨 lane 双实现按 spec/合同取舍）；解冲突后、`--continue` 前跑
   `git diff --check` 并 `grep -rn '<<<<<<<' <touched-files>`，确认零冲突标记残留；无法合并才
   `git cherry-pick --abort`，写 `integration_conflict`，保留 pane/worktree/branch并解析
   `resolving-merge-conflicts` owner。
4. cherry-pick 后比较 `git rev-parse HEAD^{tree}` 与 `"$TERMINAL_COMMIT^{tree}"`：相同说明 Integration
   内容就是 worker 已验证的树，沿用其 checks 证据并在 registry 记该 tree SHA；不同时运行 focused checks，
   失败写 `integration_checks_failed`并保留现场。通过写 `integrated`。检查用的依赖树与数据库副本
   按路径引用原位置。

## Artifact / Checks / Verdict Modes

- `artifact`：验证 tracker/artifact URL/ID/body与 expected work item一致。
- `checks`：验证完整命令、结果与失败细节；失败写 `blocked`并阻止 review。
- `verdict`：验证 Review fixed point 等于 map registry base commit、bundle 三文件在 fan-in 时可读、
  verdict/findings完整；`review_gate.py` 为 `FIX` 时把 findings 交给同一个 implementer lane 修复后
  开下一轮，`REVIEW_EXHAUSTED` 写 `blocked`并阻止 closeout。

三类都不要求 commit、不 cherry-pick。worktree必须 clean；若 owner确实需要 repo 变更，packet应改成
`commit` mode并重派，不能把 dirty state当 artifact。成功写 `consumed`。

三类失败以及 commit mode 的 focused checks 失败都按 `gate-state-machine.md` 的
验收失败修复（ADR-0012）执行：先诊断、修复，再按原判据复验。

## Cleanup

`integrated` 或 `consumed` 后统一，各壳只换第 1 步：

1. 所属壳释放 transport（Herdr：关闭本 lane pane，空 worker tab 保留复用）。
2. 运行 `scripts/closeout.py lane <本 lane registry 文件>`，壳登记的额外 branch 用 `--branch` 传入；
   它删 clean worktree 与 branch 并 readback，dirty 或被 Integration/未结束 lane 占用时不动。
3. 按首行写回 `closed` 或 `close_pending`（保留坐标，恢复时重跑；已完成的 Integration/consumption
   不回滚）；`closed` 后完成 tracker resolution 并重算 ready frontier。
   独立票模式下第 2–3 步推迟到 `release_stage: deployed` 读回之后。

完成标准：output-mode evidence 已验证，状态为 integrated/consumed/closed，closeout 首行与 registry
一致；失败时现场与精确 blocker 被保留。
