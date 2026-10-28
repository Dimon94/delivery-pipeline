# T3Code 生命周期

完成唤醒、用户完成信号或显式 monitor 时读取。canonical 合同位于
`../../delivery-pipeline/references/`，下文以文件名引用；output mode 的终态证据与 fan-in 判据只在
`execution-worktree-integration.md`。

## 唤醒

T3 在子任务终态或子任务提问时唤醒 `coordinator_thread_id` 对应线程。被唤醒后对每个相关 lane：

1. 原 coordinator 线程用 `task_status(task_id)`；其他线程用 `t3_thread_read(child_thread_id)`。
   `task_status` 只读本线程派发的任务。
2. `hasPendingQuestion: true` 或 `pendingApproval` 非空 → 进入 §HITL。
3. `status: completed` → 取 `summary`，首个独立行须为 `LANE_DONE <lane_id>`，其后为
   `lane-registry.md` 终态模板；进入 §Fan-in。
4. `failed`、`interrupted`、`cancelled` → 写 `blocked` 并保留现场，原始 summary 作为失败证据。

终态报告缺字段记 Unknown；Git、tracker、artifact 与 registry 是持久证据，不要求 worker 重显。

## HITL

lane 写 `awaiting_human`，在对话里给出 `link`，由用户进入子线程回答；子线程继续运行，终态再次
唤醒。用户在 coordinator 对话里明确给出答案并同意转发时，才用 `t3_pending_request` 的 `respond`
代为提交。权限审批始终由用户在 T3 界面完成。

## Fan-in

按 `execution-worktree-integration.md` 的 Common Preflight 与对应 output mode 验收；本壳的 transport
核对项：

- worktree common dir 等于 Source repo，HEAD 包含 `base_commit`。
- commit mode 的 `branch` 等于 registry 登记值；其他 mode 的 HEAD 处于 detached 且 worktree clean。
- 终态报告的「现场」给出 worker 对齐前的 T3 初始分支，写回 overlay `t3_branch`。

只有 commit mode 由 coordinator 在 Map Integration Worktree cherry-pick。验收失败按
`gate-state-machine.md` 的验收失败修复执行。lane blocked 不停止其他 ready work。

## Cleanup

`integrated` 或 `consumed` 后，等价落实 `execution-worktree-integration.md` §Cleanup 六步：

1. `t3_thread_organize(threadId: child_thread_id, action: "archive")` 释放 transport。
2. 在 Source repo `git worktree remove <worktree>`；worktree 不 clean 时停在这一步。
3. 删除 `branch`（commit mode）与 `t3_branch`。
4. readback：`t3_thread_read` 显示 `archived: true`；`git worktree list --porcelain` 无该路径；
   两个分支 `git branch --list` 为空。T3 自动清理已先删掉的 worktree，以 Git readback 为准。
5. 任一步失败写 `close_pending` 并保留坐标；已完成的 Integration 或 consumption 不回滚。
6. readback 成功写 `closed`，完成 tracker resolution 并重算 ready frontier。

独立票模式下 2–6 步推迟到 `release_stage: deployed` 读回之后，之前只做第 1 步。

## 恢复

按 `fresh-session-boundaries.md` §Coordinator Recovery 读取六项短记录，再逐个 `runtime: t3-task`
lane 调 `t3_thread_read(child_thread_id)`：

- 终态 → 走 §唤醒 第 2–4 步。
- `preparing | queued | starting | running | waiting` → 保持 active writer，状态沿 registry。
- 线程缺失 → 按 `integration-worktree-management.md` §Recovery 以 Git 证据判定 fan-in 或 replacement。

完成唤醒只投递给 `coordinator_thread_id`。新 coordinator 线程接管时把 overlay
`coordinator_thread_id` 更新为当前线程并报告：既有 lane 的终态由用户完成信号或显式 monitor 触发
fan-in。

## 取消与 Replacement

停止 lane 用 `task_cancel(task_id)`，它连带停止该 task 的后续 run。Replacement 先按
`lane-registry.md` 排除 active writer，再沿原 registry agent/model/effort 走 `t3code-dispatch.md`
派发关键路径；旧 lane 的 cleanup 照 §Cleanup 执行。
