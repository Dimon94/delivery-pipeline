# Orca 本地 worker dispatch packet

本 packet 只描述 `delivery-pipeline-orca` 的本地 worker 操作；项目 gate、owner、registry 与输出模式沿用 canonical 合同，不复制 Herdr transport。

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
```

## Worker preamble

1. 先从共享 worker policy 解析并冻结 agent、model、effort；不创建 Orca override，不做 fallback。
2. 先持久化 `task-create`/`dispatch` intent 和 owner/readback 字段，再调用当前 version-matched Orca 的原生 `worker-start`。
3. `worker-start` 必须使用 `--task`、`--worktree new-child`、冻结 Integration HEAD 的显式 base、明确 selector、owner 与 setup policy；分别记录 Source、Map Integration 与 Execution 三个 Worktree 坐标，Source Worktree 不切 branch。
4. 仅以原生 receipt/readback 记录 Run、Task、Dispatch、requested/effective launch、terminal、Execution Worktree path/branch/base/HEAD、selector 和 execution host。参数回显不能代替实际 worker readback。
5. 整批 startup 结果和每条 `worker_done` 先写入共享 registry overlay，再处理项目 fan-in；写回前精确核对 lane Run/Task/attempt 与 native identity。失败、Unknown、identity mismatch 或缺 capability 均 fail closed。launch 与 setup 校验必须分别提供两份不同的可读绝对路径：`worker-start` receipt 作为 requested source，`worker-show` 作为 effective source；helper 解析其中 Run/Task/Dispatch 与 agent/model/effort/setup，不能接受 caller 重复声明代替 native readback。

## FIFO settlement

使用 version-matched orchestration guide 的 `check --wait` 读取一个原生 Delivery 中的完整 FIFO messages batch。完整 batch 可包含多个 worker；每条 message 保留 message ID、Run、sender terminal、subject、body、type 和 payload，并通过 `worker-list` bindings 绑定各自 Task/Dispatch/terminal，`worker_done` 还须精确匹配其 payload 身份。未持久化 Delivery、完整 message IDs、按 Task/Dispatch 去重的待 fan-in、terminal ownership 和下一步决策前，不执行该 Delivery 的 ack；完整 settlement 还须解析 ack receipt 与 ack 后 `worker-list` JSON，不得跳过未 ack 消息或以 PTY observation 代替 fleet verdict。

ack 前通过共享 overlay 的通用 `mutation`/`observation` 写入 repo 外 persistence/readback 引用；完整 Delivery/message IDs、Task/Dispatch fan-in、terminal ownership 与 nextAction 留在原生 JSON artifact，不扩展第二套 registry schema。

ack 后仍须分别读回 `worker-list` 的 worker/dispatch/terminal/resource 状态，明确 `reuse`、`retain` 或 `release`。`worker_done`、idle、settled 或 release 都不能直接写成项目 lane `integrated`/`closed`。

## Cleanup boundary

项目 integration/testing/review 与 output-mode gate 通过后，按 native readback 执行 `worker-release`，持久化 archive/ownership 证据，再执行 `worktree rm`；dirty、Unknown、未集成或清理失败时保留 Execution Worktree 和恢复坐标。
