# Orca 原生 worker / Execution Worktree 生命周期 prototype

调研日期：2026-09-12
关联 Wayfinder：[#114](https://github.com/Dimon94/delivery-pipeline/issues/114)
研究票：[#115](https://github.com/Dimon94/delivery-pipeline/issues/115)

> 这是一次真实本机 Orca 1.4.200 原型，不是模拟。原型只验证成功路径，不修改仓库文件、不提交、不推送；失败、重启和丢失 mutation response 仍标记为 Unknown。

## 原型目标

验证以下最小本地路径：

```text
Run → Task → worker-start → Execution Worktree / terminal
    → worker_done → check --wait → ack
    → worker-list settlement/readback
    → worker-release → worktree rm
```

## 执行参数

运行前确认：

```text
orca --version → 1.4.200
orca status --json → runtime ready / reachable / connected
```

创建的原生对象：

| 对象 | 实际坐标 |
| --- | --- |
| Run | `run_94d0eb591c98` |
| Task | `task_e4ab79166013` |
| Dispatch | `ctx_85c47a9ce56c` |
| Agent | `codex` |
| Effective model | `gpt-5.6-terra` |
| Terminal | `term_4c197c15-cd38-4f30-8282-ba1b0dbf5c3a` |
| Worktree resource | `wtr_0c9c691e985f` |
| Worktree selector/id | `4ea05d9f-90d5-4383-8325-37fc1f380634::/Users/dimon/orca/workspaces/delivery-pipeline/orca-prototype-115` |
| Worktree path | `/Users/dimon/orca/workspaces/delivery-pipeline/orca-prototype-115` |
| Branch | `Dimon94/orca-prototype-115` |
| Base / observed HEAD | `7f69584ff30d7f248e21007f28af1196eb1905c7` |
| Execution host | local runtime `3122f52b-673d-4732-9e80-a066649a5650` |

实际启动使用 `worker-start --task ... --worktree new-child --repo path:/Users/dimon/01-Personal/10-Projects/delivery-pipeline --base-branch main --name orca-prototype-115 --agent codex --setup skip --json`。启动 receipt 同时返回 `runId`、`taskId`、`dispatchId`、`launch.requested`、`launch.effective`、terminal/worktree effects 和 mutation request ID。

## 结果

### 1. Worktree 与 terminal 创建

启动成功 receipt：

- `state: ready`
- `stage: input_accepted`
- `turnStart: observed`
- `launch.effective.agent: codex`
- `launch.effective.model: null`（CLI 未显式传 model；worker readback 后显示实际 provider model `gpt-5.6-terra`）
- `setup.effective: skip`
- effect 创建了独立 worktree 和 agent terminal。

worker 在 worktree 内回报：

```text
pwd=/Users/dimon/orca/workspaces/delivery-pipeline/orca-prototype-115
branch=Dimon94/orca-prototype-115
HEAD=7f69584ff30d7f248e21007f28af1196eb1905c7
worktree 清单独立登记该路径
未编辑文件、未提交、未推送
```

这证明 Phase 1 可以使用 Orca 原生 `new-child` 建立 Execution Worktree；项目侧仍需把真实 path、branch、base/head 和 Orca selector 写入 lane registry 并重新 readback。

### 2. `worker_done` 与项目侧 fan-in 边界

coordinator 使用：

```bash
orca orchestration check \
  --run run_94d0eb591c98 \
  --wait \
  --types 'worker_done,escalation,question' \
  --timeout-ms 180000 \
  --json
```

收到一条 `worker_done`：

```json
{
  "type": "worker_done",
  "payload": {
    "taskId": "task_e4ab79166013",
    "dispatchId": "ctx_85c47a9ce56c",
    "outcome": "succeeded"
  }
}
```

Delivery 必须通过 `check --ack delivery_c3e378a61308` 确认。原型验证了：

- `--types` 只控制唤醒条件，返回的是完整 FIFO batch；
- 未 ack 前应处理整批，不能跳过旧消息；
- `worker_done` 带有 Task/Dispatch 坐标和 Orca outcome；
- `worker_done` 不包含项目侧 Git integration、artifact、review 或 cleanup 结论，因此不能直接把 delivery-pipeline lane 写成 `integrated` 或 `closed`。

### 3. settlement、release 与 worktree cleanup

ack 后 `worker-list --run run_94d0eb591c98 --json` 返回：

```text
workerState: succeeded
dispatchStatus: completed
terminalState: reclaimable
projection.outcome: succeeded
projection.nextAction: orchestration worker-release --dispatch ctx_85c47a9ce56c
resource.ownershipState: owned
resource.releaseState: not_requested
```

注意：`workerState/dispatchStatus`、terminal resource accounting 和 PTY observation 是不同维度。原型中 `worker-show` 仍可能显示 PTY `liveness.verdict: live`，不能用该字段替代 fleet settlement/readback。

执行：

```bash
orca orchestration worker-release \
  --dispatch ctx_85c47a9ce56c \
  --json
```

结果：

```text
state: released
processAction: closed_agent_terminal
archive.source: terminal
archive.status: captured
```

随后执行：

```bash
orca worktree rm \
  --worktree id:4ea05d9f-90d5-4383-8325-37fc1f380634::/Users/dimon/orca/workspaces/delivery-pipeline/orca-prototype-115 \
  --json
```

结果为 `removed: true`；回读 `git worktree list --porcelain` 已无该 worktree。源 worktree 仍保持原有 dirty 状态，未被 prototype 修改。

## 结论（设计输入）

1. 普通 Phase 1 worker 应走 Orca 原生 `worker-start`，不要复制 terminal 生命周期。
2. 启动后必须把真实 Run/Task/Dispatch/terminal/worktree/host 坐标写入项目侧 `orca:` overlay；不能从名称或当前焦点推断。
3. 正式链路中，`worker_done` 后先持久化待 fan-in 与 terminal ownership 决策、readback，再 ack Delivery，之后执行项目 Git、checkpoint、artifact 和 output-mode gate。该项目级恢复顺序来自 version-matched messaging/coordinator references；本原型未写项目 registry，不构成 ack 后恢复的验证。
4. 项目侧 cleanup gate 通过后，顺序为：Orca `worker-release` → 项目侧确认 output/archive → Orca `worktree rm`；任何 dirty、未集成或证据 Unknown 都保留 worktree。
5. Orca release 与项目 lane close 是两个独立动作；release 只关闭 Orca-owned agent terminal，不等于交付 closeout。

## 已验证 / 未验证

| 项目 | 结果 |
| --- | --- |
| 本地 Run/Task/Dispatch 创建与绑定 | 已验证 |
| `new-child` Execution Worktree 创建与真实 path/branch/HEAD | 已验证 |
| codex worker 启动及 effective readback | 已验证 |
| worker 回报 `worker_done` | 已验证 |
| FIFO Delivery wait + ack | 已验证 |
| settlement 与 reclaimable resource readback | 已验证 |
| worker-release 及 output archive | 已验证 |
| Orca worktree rm 与 Git worktree 消失 | 已验证 |
| 失败 / stopped / `--retry-of` | Unknown，本次未执行失败原型 |
| coordinator 或 runtime 重启恢复 | Unknown |
| mutation response 丢失与 `--retry-request` | Unknown |
| remote execution / federation | Unknown |
| 项目 lane registry 写入和恢复 | Unknown，本次按约束未写项目 registry |

## 原型边界

原型没有修改 canonical skill、registry schema 或 manifest，没有创建 commit/PR，也没有把临时 Run 当作项目 map Run。临时 worker 已 release、Execution Worktree 已删除；Run/Task/Dispatch 是持久运行记录，本次未执行删除或 reset，不能声称这些记录已清除。
