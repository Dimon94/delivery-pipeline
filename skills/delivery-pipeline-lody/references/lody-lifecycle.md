# Lody 生命周期

Operation 结果投递、用户完成信号或显式 monitor 时读取。canonical 合同位于
`../../delivery-pipeline/references/`，下文以文件名引用；output mode 的终态证据与 fan-in 判据只在
`execution-worktree-integration.md`。

## 结果投递

Lody 在 coordinator 轮次释放后或随下一条用户输入投递已完成 Operation 的结果。对每个相关 lane：

1. 按 overlay `operation_id` 匹配结果；需要补读时，原 coordinator session 用一次
   `lody_operation_get(operation_id)`，其他 session 用 `lody_session_history(session_id)` 读最新页。
   `lody_operation_get` 只读本 session 拥有的 Operation。
2. worker 最终回复首个独立行为 `LANE_WAITING <lane_id>` → 进入 §HITL。
3. 首个独立行为 `LANE_DONE <lane_id>`，其后为 `lane-registry.md` 终态模板 → 进入 §Fan-in。
4. Operation 为 failed、cancelled 或超过 deadline，或回复缺少锚点 → 写 `blocked` 并保留现场，
   原始结果作为失败证据。

终态报告缺字段记 Unknown；Git、tracker、artifact 与 registry 是持久证据，不要求 worker 重显。

## HITL

lane 写 `awaiting_human`，在对话里给出 `session_link` 与问题原文。两条回答路径：

- 用户进入子 session 直接回答：该轮由用户发起，其结果投递给子 session 本身；用户回到 coordinator
  发出完成信号后，按 §结果投递 第 1 步读子 session 历史。
- 用户在 coordinator 对话里明确给出答案并同意转发：用 `lody_session_chat(sessionId: session_id,
  operationId: <lane_id>-r<n>, prompt: <答案原文>)` 代为提交，overlay `operation_id` 更新为该 id，
  结果照常投递。

权限审批始终由用户在 Lody 界面完成。

## Fan-in

按 `execution-worktree-integration.md` 的 Common Preflight 与对应 output mode 验收；本壳的 transport
核对项：

- 终态报告「现场」给出 worktree 绝对路径与 worker 对齐前的 Lody 初始分支：worktree 写回 registry，
  并在 `git worktree list --porcelain` 中读回；初始分支写回 overlay `lody_branch`。
- worktree common dir 等于 Source repo，HEAD 包含 `base_commit`。
- commit mode 的 `branch` 等于 registry 登记值；其他 mode 的 HEAD 处于 detached 且 worktree clean。

只有 commit mode 由 coordinator 在 Map Integration Worktree cherry-pick。验收失败按
`gate-state-machine.md` 的验收失败修复执行。lane blocked 不停止其他 ready work。

## Cleanup

`integrated` 或 `consumed` 后，等价落实 `execution-worktree-integration.md` §Cleanup 六步：

1. `lody_session_archive(sessionId: session_id)` 释放 transport。
2. 在 Source repo `git worktree remove <worktree>`；worktree 不 clean 时停在这一步。
3. 删除 `branch`（commit mode）与 `lody_branch`。
4. readback：`lody_session_list(archive: "archived")` 含该 session；`git worktree list --porcelain`
   无该路径；两个分支 `git branch --list` 为空。Lody 归档若已先删掉 worktree，以 Git readback 为准。
5. 任一步失败写 `close_pending` 并保留坐标；已完成的 Integration 或 consumption 不回滚。
6. readback 成功写 `closed`，完成 tracker resolution 并重算 ready frontier。

独立票模式下 2–6 步推迟到 `release_stage: deployed` 读回之后，之前只做第 1 步。

## 恢复

按 `fresh-session-boundaries.md` §Coordinator Recovery 读取六项短记录，再对全部 `runtime: lody-session`
lane 调一次 `lody_session_status_many`：

- idle → 用 `lody_session_history(session_id)` 读最新回复，走 §结果投递 第 2–4 步。
- busy → 保持 active writer，状态沿 registry。
- session 缺失 → 按 `integration-worktree-management.md` §Recovery 以 Git 证据判定 fan-in 或 replacement。

Operation 结果只投递给拥有它的 `coordinator_session_id`。新 coordinator session 接管时把 overlay
`coordinator_session_id` 更新为当前 session 并报告：既有 lane 的终态由用户完成信号或显式 monitor 触发
fan-in。

## 取消与 Replacement

停止 lane 用 `lody_session_cancel(sessionId: session_id)` 取消活动轮，再用
`lody_operation_cancel(operation_id)` 结束 Operation。Replacement 先按 `lane-registry.md` 排除
active writer，以新 lane_id 沿原 registry agent/model/effort 走 `lody-dispatch.md` 派发关键路径；
旧 lane 的 cleanup 照 §Cleanup 执行。
