# Orca Phase 1E recovery

本文件只持有 Orca transport 边界；checkpoint、send lease 与项目 lane state 仍由
[共享 registry/continuation 合同](../../delivery-pipeline/references/lane-registry.md) 持有。
每次先读固定 binary 的 `orchestration` guide 及 `references/recovery-and-cleanup.md`、
`references/messaging-and-gates.md`；不使用静态 capability matrix。

## 只读门禁

```text
python3 <Orca skill realpath>/scripts/recovery.py check <absolute-request.json>
```

返回始终包含 `authority: false`、`mutations: []`、`project_lane_transition: unchanged`。
`ready` 仅表示 caller-declared readback 的结构和绑定通过，不是 mutation 授权；coordinator
必须验证原始 native source、当前性、同一 caller identity 与本次 operation capability。
helper 不执行 Orca 命令、不写 registry、无第二个 project retry counter 或 receipt/journal。
输出由既有 registry owner 引用；更新沿 `registry_overlay.persist_overlay` 写后精确读回。

request 的 `operation` 为下表之一。`lane` 是共享 registry latest row（含 `orca` overlay）；
除 response-lost 外，还需已冻结 `lane_id/work_item/agent/worktree/branch` 和完整 attempt 身份。
所有 source 均为可读绝对路径，native source 保存完整 `ok/result/_meta.runtimeId` JSON envelope。
已有 retry attempt 还须提供 `previous_attempt`（共享 worker lifecycle 的原 attempt readback），
与当前 native `retryOfDispatchId` 和连续 attempt_index 一起核验；不能重置历史。

| operation | 额外输入 | 结果边界 |
| --- | --- | --- |
| `retry` | `worker_show`、`worker_list`、`approved: true`、`placement` | 仅正面 failed/stopped 且旧 writer exited，返回 `retry-same-task` |
| `cancel` | `worker_show`、`worker_list`、`approved: true` | 仅可行动的 live/exited 证据，返回 `stop-exact-dispatch`，不自动执行 |
| `response-lost` | `request_show`、`runtime_id`、`method`；pending 还需 `original_live: false`、`retry_contract` | 消费原 receipt / 按同 request 恢复 / inspect |
| `restart` | `worker_show`、`worker_list`、`map`、`run_show`、`task_list`、`coordinator_terminal`、`coordinator_writer_active: false` | 复用 `recover_map/recover_lane/recover_attempt`，三个 `create_*: false` |
| `question` | `worker_show`、`worker_list`、`binding`、`delivery`、`message_id`；可选 `reply` | 原问题 awaiting-human 或原 message reply-recorded，不触发 fan-in |
| `staged` | `worker_show`、`worker_list`、`binding`、`provider_readback`、`signal`、`gate_evidence`、`user_override` | 委托 canonical `continuation.prepare_continuation`，只返回 overlay/lease，不执行 transport |

`worker_show` 与 `worker_list` 必须来自同次 runtime；保留完整 Run-scoped fleet，分页未完成先
继续枚举，不以部分 fleet 排除 writer。fleet liveness 优先于 PTY；当前薄层遇任一来源
`unverifiable` 均阻塞。版本匹配 guide 允许 host-specific 复核时，coordinator 先取得新的正面
execution-host evidence，再重新核验；不能把 `missing_status`、`host_unavailable`、
`capability_unsupported` 或没有输出升级成退出。idle、timeout、outcome_unknown、host contact
loss 不自动 stop、abandon、retry 或 release。

## Retry / cancellation / restart

`placement` 必须精确包含已存 `task_id`、`retry_of`（当前 Dispatch）、`worktree_selector`、
`execution_host`、`worktree` 和 `agent`，值与 lane/native 完全相符。恢复使用具体
`path:<Execution Worktree>`、native Worktree ID 或 `id:<Worktree ID>` selector；
不能重用 `new-child`/`current` 创建另一现场。
原生失败计数 `dispatch.failureCount` 达三次或 Unknown 时保留 circuit-break，不创建新 Run、
第二 Task、无关 Dispatch 或 project counter 绕过。native `worker-start` 仍是 circuit-break owner。

核验后先沿同一 overlay 记录新 attempt intent，再按原合同 `worker-start --task <same Task>
--retry-of <old Dispatch>`，显式带 placement、agent、host 与冻结 launch/setup 参数；不使用
`--spec`。之后仍走 `worker_lifecycle.bind_startup`，验证 native `retryOfDispatchId` 和完整
requested/effective readback，才能推进同 Task 的 attempt；恢复 gate 不替代 startup gate。

取消必须是明确决策，作用域只到已证明且仍 owned 的 Dispatch；user-owned、retained、released
或 ownership 已转移不授权 stop。stop 后重新回读 host/fleet。
`worker-abandon` 只 fence orchestration，不证明旧进程已停。保留 dirty/checkpoint，release 与
worktree rm 留给项目 cleanup gate。

重启先恢复 registry + Run/Task/Dispatch；任一 active writer、identity、request outcome Unknown
都保留现场。`restart` 不自动 takeover；旧 coordinator writer 已排除、原生 `run-use` 接管同一
Run 并读回后，沿既有 `rebind_map_coordinator` 更新 map overlay，再核验恢复。不能以 terminal
handle 改变为由创建新 Run，不能对新旧 handle 双发。

## Mutation response lost

先读取 `orca.mutation` 的 intent/request，再执行原生 `request-show --request <id>`：

- `completed`：校验 method/request/Run 与已知 Task/Dispatch，直接消费原 receipt，不重新发命令。
  Task/Dispatch 首次 ID 尚未返回时允许稀疏 lane；由原 receipt 补齐，不新建资源。
- `pending`：先等仍运行的原命令；只有版本匹配 `retry_contract` 明确允许且原调用已不在运行，
  才以完全相同命令与同一 `--retry-request` join/recover。不得重新生成 request ID。
- `absent`：只 inspect 原 Task/Dispatch/terminal，不把缺 receipt 解释为未执行。
- request ID 全丢失：只读枚举、对账，仍不可唯一消歧就 blocked，保留 intent。

`method` 必须与已持久 `mutation.operation` 对应；native method 未证实时 Unknown。
新操作不得覆盖未完成 mutation。helper 返回原 receipt 引用，不创建新的 receipt 数据库。

## Question / escalation / reply

worker 原样使用 preamble 中身份与 capability。`ask` 的问题正文使用 JSON，含
`question`、`taskId`、`dispatchId`、`lane_id`、`work_item`、`checkpoint_sha256`；`escalation`
将同样 context 放入原生 `send --payload`。`binding` 必须位于既有 checkpoint 的 evidence 中。
这只是 message 与 checkpoint 的关联，不新增 pending-question journal。

超时保留原 `messageId`，使用 `ask --resume <id>`；coordinator `reply --id <id>`，不新建 gate
替代回复。`reply` 输入是同一问题的原生 ask/resume readback；超时/取消/断连/answer Unknown
都不算回答。attempt-specific follow-up 用 `dispatch:<id>`，不以 terminal 地址代替。
整批 Delivery 仍按 `worker_lifecycle` 的 FIFO persist/readback/ack 合同处理；本门禁只核验其中
一个问题，绝不授权提前 ack 或跳过同批其他消息。

## 最小 staged continuation

starting worker 首改 → 最小检查 → canonical `checkpoint.py` repo 外原子 checkpoint →
中间 `PREWALK_READY` / `WORKER_STOPPED` 信号 → 结束当前轮，不发最终 `worker_done`。
checkpoint 的 `runtime: orca`、`session_id` 是已证明的 provider session，Task ID、Dispatch ID
或 terminal handle 不能替代；Orca 坐标只放入已有 `evidence`，不扩展 checkpoint schema。

`binding` 为该 evidence 中的 caller-normalized JSON，精确包含当前
`run_id/task_id/dispatch_id/terminal_handle/worktree_selector/execution_host`、
`lane_id/work_item/worktree/provider_session_id/provider_session_source`。最后一项引用未经改写的
provider session 原始证据，coordinator 必须核验 provenance，文件存在本身不证明原生身份。

`provider_readback` 是 provider 专属采集器的 normalized evidence（不是 Orca 原生 API schema）：
`status: verified`、`same_session: true`、`agent`、`session_id`、`worktree`、`transport`、
`source`（原生能力证据）与 `observation`（共享 continuation 的同 session 停止/readback 字段）。
当前 runtime 没有此能力或采集器时保持 blocked，不伪造该 document 来解锁。

helper 先核对同 lane/Task/Dispatch/worktree/session、checkpoint/Git/hash，再复用 canonical
prepare/persist/readback/send lease。每次返回 overlay 都写回并精确读回同一 lane 后再重入；
只有 coordinator 证明可用的 provider 同 session transport 才能消费一次 send lease。
`worker-start --terminal` 不能加 model/effort，不能用它伪称换模；不降级 direct、不转 Herdr。

request、accepted、new turn、actual model/effort 分别由 canonical
`continuation.record_event` 记入同一 `continuation` overlay；request Unknown 只回读原 session，
不能再次发送。新轮须绑定原 session/request/new turn，实际 model/effort 须绑定该 turn；
仅 new turn started 后推进 executing。复用 shared checks，不复制事件状态机。

## 验收边界

`recovery_check.py` 只证明机械合同和 no-mutation，模拟成功不等于 Orca 成功。
必须真实证明共享配置 agent staged 成功、同 Task failed/stopped retry、重启原 Run/身份接管、
question/reply、取消，以及 request-show completed/pending/absent；缺任何必需项记
`not-run/Unknown`，#124 / Phase 1 保持 blocked。若必须扩展 Orca continuation 协议，交由
coordinator 拆依赖子票，保留本票完整验收，不删需求。

DRY record:

- scope：Orca recovery readback 与 staged 接入。
- searched：registry_overlay、worker_lifecycle、project_lifecycle、共享 checkpoint/continuation、原生 guides。
- reused：overlay recovery/persistence、worker evidence parser、canonical checkpoint/hash/send lease/event ledger。
- remaining duplication：原生 Orca 坐标绑定位于 transport 边界；不复制共享状态机或运行计数。
