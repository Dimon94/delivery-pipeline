# Orca 本地 worker dispatch packet

本 packet 只描述 `delivery-pipeline-orca` 的本地 worker 操作；项目 gate、owner、registry 与输出模式沿用 canonical 合同，不复制 Herdr transport。coordinator 侧的 `worker-start` startup/readback、FIFO settlement 与 cleanup（`worker-release`、`worktree rm`）合同在 `../references/orca-dispatch.md`，本 packet 不复制。

```text
Coordinator task：<ticket/map>
Lane ID：<lane_id>
Role：<planning|design|frontend|backend|testing|review>
Output mode：<commit|artifact|checks|verdict>
Owner：<name>; <absolute SKILL.md path>; <runtime invocation label>
Mode：<staged|direct|none>（冻结）
Review fixed point：<base commit>
Integration base：<commit>
Execution worktree：<absolute path>
Execution branch：<branch>
Permissions：<declared project/runtime permissions>
Orca runtime/host/terminal：<native readback>
Coordinator terminal：<coordinator_terminal_handle>
```

## Worker 义务

worker 生命周期义务由 Orca 注入的 native preamble 定义：Task/Dispatch ID、`worker_done`
恰好一次带 `--outcome`、心跳节奏、阻塞提问走 `ask`、`worker_done` 前先 `orchestration check`
清空 queued follow-up。本 packet 只补 pipeline 特有部分：

1. 每条发向 coordinator 的 orchestration send（worker_done/escalation/question/reply）后紧跟一次
   `terminal send --terminal <coordinator_terminal_handle> --enter` nudge（文本
   `<lane_id> <信号类型>，请结算`）；nudge 只负责唤醒，事实以 orchestration 消息与 registry
   为准；nudge 失败不撤回已入 inbox 的消息，在汇报中注明。
2. question/escalation 绑定本 lane、Task/Dispatch、checkpoint 与 work item；ask timeout 按原
   message ID resume，不新建问题。
3. worker 不写共享 registry overlay；startup、settlement 与 cleanup 的 readback/overlay 纪律归
   coordinator。

## Recovery 与 starting 边界

先读 [`../references/orca-recovery.md`](../references/orca-recovery.md)。starting 的首改与最小检查
之后，用 canonical checkpoint helper 写 repo 外原子 checkpoint；session_id 必须是已证明的
provider session，Run/Task/Dispatch 绑定放现有 evidence。发送 PREWALK_READY / WORKER_STOPPED
中间信号后结束当前轮，不发最终 worker_done，不进入 terminal fan-in。
取消、retry、response lost、restart 均先核验原生 readback；Unknown 保留现场。
