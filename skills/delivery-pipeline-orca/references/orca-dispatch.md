# Orca dispatch 与本地 worker 合同

本文件是 Orca 入口的本地 worker 操作合同。它只适配原生 lifecycle，不复制共享 registry、worker policy、terminal lifecycle 或项目 fan-in 状态机。

## 操作顺序

1. coordinator 从已通过的 implementation gate 读取 lane、owner 三字段、output mode、冻结 mode、Integration HEAD、权限和 review fixed point。
2. 沿 #121 的共享 overlay 先写 `task-create` intent；创建真实 Task 后写回 Task/Run readback。随后写 Dispatch intent，再执行原生 `orchestration worker-start`。
3. `worker-start` 必须绑定 `--task`、冻结 Integration HEAD 的显式 base、明确 worker name/selector、共享 policy 的 agent 与 setup policy。Source Worktree 不切 branch。launch transport 按 agent 能力二选一（见下节）。

## Launch transport

model/effort 的传递有两条原生链路，按目标 agent 的 launch-preference 能力选择；二者不得混用：

- **`launch-preferences`**（Claude/Codex/Cursor）：`worker-start --worktree new-child --base-branch <Integration HEAD> --agent <id> --model <model> --effort <effort>`。receipt 的 `launch.requested` 与 worker-show 的 `startOptions.launch.effective` 均携带非空 agent/model/effort，必须分别与声明一致。
- **`agent-argv`**（pi 及任何被 `worker-start` 原生拒绝 launch-time model selection 的 agent，native 错误 `Agent <id> does not support launch-time model selection`）：`--terminal` 与 worktree creation flags 不兼容，顺序改为——
  1. `orca worktree create --name <worker> --base-branch <Integration HEAD>`（不带 `--agent`，setup policy 按共享 policy）；此时 Orca 物化一个兜底 shell tab；
  2. `terminal list` 确认该 tab 是 unused shell（唯一终端、无命令运行；repo default-terminal 配置可能物化其他 tab，非 unused shell 时改用 `terminal create --command` 另起终端），然后 `terminal send --enter` 直接复用它，把共享 model_config 的冻结 argv 打进去（pi 为 `pi --approve --model <model> --thinking <effort>`，与 Herdr 主干同一 argv，不引入第二套映射）；send 是 queued 语义，shell 未就绪也不丢输入（已实测），poll `terminal read` 等 agent 状态行出现；
  3. `orca orchestration worker-start --task <task_id> --terminal <handle> --worktree <新 worktree>`。

  该路径 receipt/readback 的 `launch.requested`/`effective` 字段按设计全部为 `null`（Orca 未做 launch-time model selection），**不是缺口**；model/effort 的 effective 证据是 worker 终端的原生读回（`terminal read` 状态行，pi 形如 `glm-5.3-flash[low]` / `thinking low`）。声明的 requested=冻结计划、effective=终端读回，两者必须逐字段一致；`terminal_source` 必须绑定 Dispatch 的 terminal handle 且文本包含 effective model id 与 effort。
4. 原生 receipt/readback 缺任一 Run/Task/Dispatch、requested/effective launch、terminal、Execution Worktree path/branch/base/HEAD、selector 或 execution host 时，保持 blocked，不猜坐标、不重建资源。
5. 将完整 startup success/failure 与上述坐标沿 `registry_overlay.py` 写入同一 lane row；写前必须核对 lane Run/Task，首个与 retry attempt index 来自已持久身份并与 native `retryOfDispatchId` 相符。写后精确 readback，再把控制权交给 worker。worker_done 只作为唤醒，不是项目完成证据。

retry/startup 前先走 [`orca-recovery.md`](orca-recovery.md) 的 `recovery.py` 门禁，证明原 attempt
failed/stopped、旧 writer 已退出、原生 circuit-break 未触发；仍用同 Task，不以新 Run 绕过。
response lost 先 request-show，重启沿原 registry 身份；该门禁不替代下面的 startup readback。

## Receipt/readback 最小字段

```json
{
  "run_id": "<native Run>",
  "task_id": "<native Task>",
  "dispatch_id": "<native Dispatch>",
  "terminal_handle": "<native terminal>",
  "worktree_selector": "<native selector>",
  "execution_host": "<native host>",
  "previous_attempt": null,
  "source": {"path": "<absolute user worktree>", "branch": "<unchanged branch>", "head": "<unchanged HEAD>", "base": "<source base or explicit Unknown>", "selector": "<native source selector>", "host": "<native source host>", "dirty_fingerprint": "<unchanged>"},
  "integration_worktree": {"path": "<absolute map worktree>", "branch": "<map branch>", "head": "<Integration HEAD>", "base": "<Integration HEAD>", "selector": "<native integration selector>", "host": "<native integration host>", "dirty_fingerprint": "<integration readback>"},
  "execution_worktree": {"path": "<absolute child>", "branch": "<isolated branch>", "head": "<Integration HEAD>", "base": "<Integration HEAD>", "selector": "<native execution selector>", "host": "<native execution host>", "dirty_fingerprint": "<execution readback>"},
  "launch": {"transport": "launch-preferences | agent-argv", "requested": {"agent": "<shared policy>", "model": "<shared model>", "effort": "<shared effort>"}, "effective": {"agent": "<native readback>", "model": "<native readback>", "effort": "<native readback>"}, "terminal_source": "<agent-argv 专用：worker 终端 readback 绝对路径>"},
  "setup": {"requested": "<policy>", "effective": "<native readback>", "requested_source": "<worker-start receipt>", "effective_source": "<worker-show readback>"}
}
```

`requested` 必须解析自 `worker-start` receipt，`effective` 必须解析自另一份 `worker-show` readback；launch 与 setup 两组 requested/effective 都必须分别核对独立 native 字段，两者提供不同的可读绝对证据路径，helper 同时核对 Run/Task/Dispatch、native mutation request ID 与 retry previous attempt chain。参数回显或 caller 重复声明不能充当实际 model/effort/setup 证据。identity mismatch、Unknown、missing native capability 或 execution host 不匹配均 fail closed。

`launch-preferences` 下 helper 额外核对 receipt/worker-show 的 native launch 字段与声明逐字段一致；`agent-argv` 下 native launch 字段必须全部为 null（证明 Orca 未做 launch-time model selection），并额外要求 `terminal_source`：原生 `terminal read` readback，其 handle 绑定 Dispatch terminal、文本包含 effective model id 与 effort（pi 状态行 `[effort]` 或 `thinking <effort>`）。这是 ADR-0009 证据纪律在 pi launch 上的具体化，不是放宽。

## FIFO wait/ack 与 settlement

使用 version-matched orchestration reference 的：

```bash
orca orchestration check --run <run_id> --wait --types 'worker_done,escalation,question' --timeout-ms <bounded> --json
```

`check` 的 `deliveryId` 标识整批 Delivery，`messages` 才是其中有序的完整 batch；不能把每条 message 伪建模成一个 Delivery。完整 batch 可以包含多个 worker 的消息，因此 caller 必须提供当前 Run 内由 native `worker-list` 读回的 Task/Dispatch/terminal bindings；每条 message 按 sender terminal 或原生 `dispatch:<id>` 唯一绑定对应 Dispatch，`worker_done` payload 还须精确匹配该 Task/Dispatch。每次返回先按顺序处理完整 batch：

- 通过共享 overlay 的通用 `mutation`/`observation` 字段记录本次 Delivery/完整 message IDs、Task/Dispatch、fan-in、terminal ownership 与下一步决策的 repo 外 readback 引用；完整细节保留在原生 JSON artifact，不扩展第二套 registry schema；
- 精确 readback 写入成功后，才 `check --ack <delivery_id>`；未 ack 消息不可跳过、不可伪消费；
- ack 后解析 ack receipt 的 `acknowledged` 与 native mutation request ID，再用 `worker-list --run <run_id> --json` 的独立 JSON readback 核验 worker/dispatch/terminal/resource 状态；PTY observation 只能补充，不能覆盖 fleet verdict；
- 明确下一步 `reuse`、`retain` 或 `release`。settled/reclaimable 不直接写成 project lane integrated/closed；该结果仅保留在 settlement readback，等待项目 fan-in。

startup 任一失败也必须先完整 readback 后交接；Unknown 保留现场。重复 Delivery 或 coordinator 重启时，先 readback 稳定身份和既有 overlay；fan-in 按每条 worker_done 的 Task/Dispatch 独立去重，即使新 Delivery 重复报告已 fan-in attempt 也不能再次进入 Integration，但完整持久化 readback 后仍 ack 当前 Delivery；禁止新建 active writer。

## Execution Worktree 与 cleanup

Execution Worktree 只能从冻结的 Integration HEAD 建立。成功后需分别回读 Source Worktree 前后快照、Map Integration Worktree path/branch/HEAD，以及 Execution Worktree path/branch/base/HEAD/selector/host；Source Worktree 保持原 branch、HEAD 与 dirty 状态不变，三者不得混作同一坐标。

项目 integration/testing/review 和 output-mode gate 完成后，按顺序执行 native `worker-release`、archive/ownership readback、`worktree rm`。任一 dirty、未集成、Unknown 或 cleanup failure 都保留 worktree 与恢复坐标并标记 `close_pending`；Orca release 不等于项目 lane closeout。

## 项目侧 fan-in / cleanup readback

`scripts/project_lifecycle.py` 是本壳唯一的项目侧（project-side）机械门禁。它接收 `worker_lifecycle.py` 的 settlement
readback（Run/Task/Dispatch、`worker_done`、`worker-list` fleet verdict、FIFO ack），并要求项目侧
review/Git/Integration evidence 后才返回可供既有 gate 消费的结果；返回始终是 `authority: false`、
`project_lane_transition: unchanged`，不把 `worker_done` 或 settled 直接变成 `integrated`、`consumed`
或 `closed`。

output mode 按共享合同处理：`commit` 必须绑定 Execution Base review、串行 cherry-pick 与 focused checks
的通过 readback；`artifact`、`checks`、`verdict` 必须 clean 且不携带 cherry-pick，成功目标为
`consumed`。Integration conflict 或 focused checks 失败保留现场，不回滚已经 integrated/consumed 的
结果。

cleanup request 的顺序必须精确为：项目 cleanup gate → `worker-release` → archive/output readback →
`worktree rm` → Git branch readback。任何 dirty、未集成、active writer、archive 不全、branch 残留、
身份冲突或 Unknown 都只返回可恢复的 `close_pending`；retry 只沿已完成步骤前缀继续，成功后仍须由
coordinator 在清理 readback 后单独写项目 resolution 与 `closed`，并完成 git branch readback。重复 closed cleanup 只返回
`deduplicated`，不重做 mutation。
