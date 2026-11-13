# Orca Phase 1E recovery

本文件只持有 Orca transport 边界；项目 lane state 仍由
[共享 registry 合同](../../delivery-pipeline/references/lane-registry.md) 持有。
每次先读固定 binary 的 `orchestration` guide 及该 guide 自带的 recovery-and-cleanup、
messaging-and-gates 两篇；不使用静态 capability matrix。

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
这是 transport 层的 dispatch 熔断；验收层（checks/verdict/prereq check 不过）的诊断-复验回路
归核心链路 `gate-state-machine.md` 的验收失败修复（ADR-0012），不占用派发失败计数。

核验后先沿同一 overlay 记录新 attempt intent，再按原合同 `worker-start --task <same Task>
--retry-of <old Dispatch>`，显式带 placement、agent、host 与冻结 launch/setup 参数；不使用
`--spec`。之后仍走 `worker_lifecycle.bind_startup`，验证 native `retryOfDispatchId` 和完整
requested/effective readback，才能推进同 Task 的 attempt；恢复 gate 不替代 startup gate。

### DD-418：旧身份与所选请求的边界

依据 [DD-407](https://linear.app/erplus/issue/DD-407) T14/T17/T18、R3/R4/R5/R7/R8/R9
及用户 2026-11-12 已批准的 M2 行为，本节定点修订 recovery 合同，不宣布新 ADR Accepted。

上文 `lane.agent`、`placement.agent` 和完整 placement 核验的是**旧 Dispatch**：
不能将它们改成备用 agent 来通过原身份检查，也不能删除旧 agent 一致性检查。
新 attempt 的已选 `{agent, model, effort}` 是另一请求值，应来自共享 Registry 已认领
successor 的冻结位置；不能从当前配置或静态 guide 字段推断动态可用性。

只读 `recovery.py` 仍拒绝显式 selected；生产入口为本壳
`scripts/native_replacement.py::NativeReplacement`。`claim` 从冻结计划取下一位置，先核验
原生 source 身份、完整 fleet、正面退出、failureCount 和精确 selected 动态读回，再进入唯一
Registry。`execute` 先 bind 唯一 native_request，持久 launching 后才调用同 Task 的 worker-start。
仅开放同 agent/model 的 effort 变化或重复 triple；跨 agent/model 保持 blocked。
selected_dispatch 指向当前 runtime 的既有精确 launch requested/effective 读回；不是静态 schema。
该字段不证明 actual model/provider applied effort，模型响应和独立执行信息仍需另留证。

Adapter 直接读取原生 Run 的 coordinator handle，并与当前 Orca 原生 terminal 身份核对；
外部 T3 不传伪 requester。structured worker 使用原生 Dispatch、worker、resource、fleet 与
独立 worktree readback 核对旧身份，不把 terminal=null 当 exited；旧 agent/model/effort
仍须精确匹配旧 launch。旧 writer、其他同 worktree writer、分页、计数或旧 mutation Unknown
均在 claim 前拒绝。原生 retryOf 与 Registry 连续 attempt_index 一起继承，不创建新 Task/Run。

`recover(path,lane)` 对 launching 的原生 request UUID 只做 request-show/worker-show；
原 UUID 必须与同 intent 的 native_request 一起保存。completed 的 receipt 还需验证同 Run/Task、
retryOf、host/worktree、连续计数与 requested/effective 后才能采用。pending/absent 均保留 launching；
本入口尚不自动 join pending。UUID 尚未返回时同样保持 Unknown，不拿 lane_id 冒充原生 UUID。
恢复后将同一 receipt 的新 attempt 身份投影到既有 orca overlay，不增加 receipt 库或计数器。

任何扩大放行范围必须先取得固定 executable 的版本匹配能力证据，证明至少一种 selected 变化。
共享 claim/bind_request/launch/recover_launch 仍是唯一 intent、successor 与两次 accepted 预算 owner；
Adapter 须在 claim 前完成原生拒绝门禁，不能先消费游标再检查能力。
逻辑 successor 必须继承同一 work_item、Run、Task、Execution Worktree/host，并保留旧 Dispatch
和 previous_attempt；新 native attempt 的 retry_of 指向当前旧 Dispatch，attempt_index 连续。
不得以 successor 为由创建新 Task/Run、独立计数器或清零 failureCount；原生 circuit-break
与共享预算取最严格限制。failureCount/能力/旧 writer/request outcome 任一 Unknown 均不得 mutation。

响应丢失只沿持久化的原 mutation/request ID 使用本文件 `response-lost` 合同；completed 采用
原 receipt，pending 仅原调用退出且匹配原生恢复合同时 join，absent/歧义保持 inspect。
requested、receipt、独立 actual model、runtime thinking/provider applied effort、nonce 响应
分别留证；缺项写 Unknown，静态字段与启动成功不能证明 inference。

取消必须是明确决策，作用域只到已证明且仍 owned 的 Dispatch；user-owned、retained、released
或 ownership 已转移不授权 stop。stop 后重新回读 host/fleet。
`worker-abandon` 只 fence orchestration，不证明旧进程已停。保留 dirty 现场，release 与
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
`question`、`taskId`、`dispatchId`、`lane_id`、`work_item`；`escalation`
将同样 context 放入原生 `send --payload`。`binding` 与 lane 的 orca 坐标一致；不新增 pending-question journal。

超时保留原 `messageId`，使用 `ask --resume <id>`；coordinator `reply --id <id>`，不新建 gate
替代回复。`reply` 输入是同一问题的原生 ask/resume readback；超时/取消/断连/answer Unknown
都不算回答。attempt-specific follow-up 用 `dispatch:<id>`，不以 terminal 地址代替。
整批 Delivery 仍按 `worker_lifecycle` 的 FIFO persist/readback/ack 合同处理；本门禁只核验其中
一个问题，绝不授权提前 ack 或跳过同批其他消息。

## 验收边界

`recovery_check.py` 只证明机械合同和 no-mutation，模拟成功不等于 Orca 成功。
必须真实证明同 Task failed/stopped retry、重启原 Run/身份接管、
question/reply、取消，以及 request-show completed/pending/absent；缺任何必需项记
`not-run/Unknown`，#124 / Phase 1 保持 blocked。

DRY record:

- scope：Orca recovery readback。
- searched：registry_overlay、worker_lifecycle、project_lifecycle、原生 guides。
- reused：overlay recovery/persistence、worker evidence parser。
- remaining duplication：原生 Orca 坐标绑定位于 transport 边界；不复制共享状态机或运行计数。
