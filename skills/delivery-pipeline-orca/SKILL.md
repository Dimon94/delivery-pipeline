---
name: delivery-pipeline-orca
description: 在 Orca runtime 中检查交付编排入口、原生 discovery 与当前操作能力；证据不足时明确阻塞，不切换其他 transport。
disable-model-invocation: true
---

# Delivery Pipeline（Orca）

本入口与 CLI/Herdr、Codex App 并列，严格绑定 Orca。当前 Orca terminal 是 coordinator；
外部会话不能冒充该身份。本入口先做 preflight；coordinator 核验 native provenance 后，才可通过
既有共享 registry 的 overlay caller 创建或恢复 map Run / lane Task。Dispatch 与 Execution
Worktree 尚未交付时返回 `dispatch unavailable`，不调用其他入口代办。

本票只允许在 native `worker-start`、`worker-list` 和 overlay readback 均可核验时继续；机械核验返回的 `project_lane_transition` 永远不直接推进 project lane integrated/closed。

## 复用边界

从本文件的 realpath 解析 canonical siblings，不从调用者 cwd 猜路径，也不完整执行
`../delivery-pipeline/SKILL.md` 的 Herdr startup。

- gate 与实施前置证据：`../delivery-pipeline/references/gate-state-machine.md`。
- owner 解析：`../delivery-pipeline/references/owner-skill-resolution.md`；保留 name、绝对
  SKILL.md path、runtime-specific invocation label 三字段。
- worker policy：`../delivery-pipeline/references/model-config-schema.md`；只读现有
  `~/.config/delivery-pipeline/model-roles.json`，复用 setup 的 `model_config.py`
  `resolve`/`freeze` 与 version 4 schema/model evidence。不创建 Orca override、第二份配置
  或 dispatcher。Herdr 的 `startup_request` / `continuation_request` 不用于 Orca。
- worker packet：`assets/ORCA_ROLE_DISPATCH_PACKET.md`；本票本地 dispatch/Execution Worktree/FIFO settlement 合同：`references/orca-dispatch.md`。
- 本地 worker 的机械 readback 核验：`scripts/worker_lifecycle.py`；它逐字段解析 caller 提供的 `worker-start` receipt、独立 `worker-show` launch readback、原生 FIFO Delivery/ack JSON 和 ack 前后 `worker-list`，并核验 registry readback/fleet verdict；不发送 worker、不执行 ack，也不拥有第二套 registry。
- 项目侧 fan-in/cleanup 的机械 readback 核验：`scripts/project_lifecycle.py`；它只把已 settlement 的 Orca Run/Task/Dispatch、`worker-list` fleet verdict 与 FIFO ack 送入共享 output-mode/Integration/cleanup gate，不推进 project lane state，也不执行 cherry-pick、`worker-release`、archive 或 `worktree rm`。

## 每次进入操作前

1. 完整读取原生 `orca-cli` discovery stub；优先使用 `ORCA_CLI_COMMAND`，否则按 guide
   的 dev/Linux/默认规则只解析并固定一个 executable。后续所有命令使用该绝对路径；
   选择失败时保留原始错误，不尝试另一 binary。
2. 从该 executable 读取 `skills get orca-cli --full --json`、
   `skills get orchestration --full --json` 与 `--version`，记录版本、路径和读取来源。原生 guide 必须 version-matched；
   缺失时可用该 binary 的 `--help` 做只读诊断，不猜命令、不用旧 guide 代替。
3. 按本次 guide 的 `agent-context` / help 核对 runtime ready/reachable/connected、
   coordinator terminal 与目标 host identity；加载 guide 清单中当前 operation 所需的
   references。不能用本机 CLI 可执行替代 runtime readback，也不强制加载 browser/remote。
4. 用该 binary 的 `skills installed --json` 核对本入口的 exact id/name/providers/
   sourceKind/sourceLabel，并独立读回目标 agent 解析到的 owner SKILL.md realpath。
   同名或安装成功不等于 agent 可发现、身份匹配或可运行。复用既有软链 helper 安装到
   被选 agent 的原生 discovery 目录；`skills install` 只管理 bundled skills，不猜造
   自定义安装命令，不创建 lockfile、静态 capability/version matrix。
5. 按共享 schema 读取当前 work/两轴 review 与 implementation mode 的冻结计划，分别保存
   agent/model/effort/mode 请求和原生证据。shared agent 不可证明可用时不映射其他 agent；
   model/effort 必须由当前 binary 与目标 runtime 的证据支持。staged 还须证明 native
   同 session 能力，不降级 direct；参数回显不充当实际 model/effort。
6. 只验证当前操作的 capability；readback 缺失、Unknown、不一致或 runtime 不可达，
   均停止依赖该证据的操作，保留已持久 registry、Git 与 artifact 的只读恢复能力。

## 机械 preflight

先把本次操作证据写入 repo 外 request JSON，再运行：

```text
python3 <Orca skill realpath>/scripts/preflight.py run <absolute-request.json>
```

request 精确包含 `operation`、`skill_name`、`references`、`required_commands`、
`required_capabilities`、`config`、`model_evidence`、`task`、`output_mode`、`phase`、
`target_host`、`owner`、`agent_readback` 与 `same_session_readback`；可选 `ticket_mode`、`map_mode`、
`terminal_handle`。`skill_name` 固定为 `delivery-pipeline-orca`；`target_host` 精确匹配原生
`status` 的 target + runtimeId。owner 精确为 name、absolute SKILL.md path、invocation label。
agent readback 精确匹配解析后的 agent/model/effort 和 `status: ready`；staged 还要求
匹配同一 agent 的 `status: verified` same-session capability readback。二者的 `source` 必须是
可读绝对 evidence 文件，但仍是 caller-declared：helper 只校验字段、路径与绑定，不证明原生
provenance。coordinator 必须读回 source 的原始 native receipt 后才可授权。当前 coordinator
terminal identity 由 `terminal_handle` 与原生 `terminal show` 独立核对。operation requirements
来自刚读取的原生 guide，不在仓库维护 capability/version matrix。

helper 只调用 `--version`、`skills get`、`agent-context`、`status`、`terminal show` 和
`skills installed`，并复用 setup `model_config.py resolve/freeze`；required command 只与
`agent-context` 对照，不执行。结构和路径均通过时返回 `status: ready`、
`dispatch: preflight-ready`、`authority: false`；这不是 dispatch 授权。失败返回带具体 blockers
的 `blocked`，不产生 mutation。

- Orca-specific Run/Task 坐标不进入共享 base 顶层；由
  `scripts/registry_overlay.py` 以 `orca:` 嵌套 opaque overlay 表达。该 helper 只翻译并核验
  caller 提供的 registry readback，不创建第二份 registry、dispatcher 或 Orca API schema。
- 使用顺序固定为：先用 `record_mutation(..., request_id=None, receipt_reference=None)` 持久化
  intent/readback，再补 native request/receipt；原生坐标通过 `record_native_coordinates` /
  `record_readback` 由 caller 提供真实 readback。写入由共享 registry owner 的 `persist_overlay`
  callback 完成，写后必须精确读回。
- `recover_map` / `recover_lane` 只在 stored identity、native identity 与 `writer_active: false`
  全部明确且一致时返回 `create_*: false`；Unknown、冲突或 active writer 返回 `blocked`，不创建
  第二 Run/Task/writer。

## 共享 registry caller

`preflight-ready` 本身不能进入此步骤。coordinator 核验 native source provenance 后，从既有
tracker registry 读取 latest map/lane row，把一个操作写入 repo 外 JSON：

```json
{
  "action": "record_mutation",
  "kind": "map",
  "row": {"runtime": "orchestrator", "dispatch_runtime": "orca", "coordinator_runtime": "orca-terminal", "orca": null},
  "arguments": {"operation": "run-create"}
}
```

然后调用唯一的 Orca overlay 入口：

```text
python3 <Orca skill realpath>/scripts/registry_overlay.py apply <absolute-request.json>
```

`kind` 必须为 `map` 或 `lane`，caller 会在操作前后核验对应 transport markers。`action` 只允许
`record_mutation`、`record_native_coordinates`、`record_readback`、`bind_map_run`、
`rebind_map_coordinator`、`bind_lane_task`、`bind_attempt`、`recover_map`、`recover_lane`、
`recover_attempt`。
每次输出仍由同一个 tracker registry owner 写回原 row 并精确 readback；下一次请求只消费该
readback。helper 不直接访问 tracker，也不缓存 row。

- 已有 Orca map/lane 先分别调用 `recover_map` / `recover_lane`；map 的 Run 与 coordinator
  origin、lane 的 Run/Task、以及 `writer_active` 必须来自本次 native readback。旧 coordinator
  已确认终止后，native `run-use` 只复用同一 Run，再由 `rebind_map_coordinator` 更新当前 host/terminal
  并写入新的 mutation/readback。已有 `dispatch_id` 时还必须调用 `recover_attempt` 精确核对五项
  attempt 坐标。任一步返回 `blocked` 都不运行 create。
- 新 map 先用 `record_mutation` 持久化 `run-create` intent，再按 version-matched guide 做一次真实
  Run mutation；只有真实 Run ID/request/receipt 可读时，才依次用 `bind_map_run`、
  `record_mutation`、`record_readback` 写回并读回同一 map row。
- 新 lane 沿已持久 map Run，先持久化 `task-create` intent，再做一次真实 Task mutation；只有真实
  Task/Run readback 可用时，才依次用 `bind_lane_task`、`record_mutation`、`record_readback` 写回并
  读回同一 lane row。`bind_attempt` 只记录后续阶段提供的真实 Dispatch readback，并由
  `recover_attempt` 恢复；本票不创建 Dispatch。
- mutation 响应或 native identity 丢失时先只读枚举；仍不能唯一消歧就保留 intent 并明确
  `blocked`，不得再次 create、猜 ID 或声称恢复成功。

## Recovery 与 staged continuation

失败、取消、response lost、重启、question/escalation 或 staged 中间信号进入
[`references/orca-recovery.md`](references/orca-recovery.md)，先运行
`scripts/recovery.py check <absolute-request.json>`。只消费 latest registry 与 native readback；
返回 `authority: false`、`mutations: []`，不创建 Run/Task、counter 或第二份 journal。
只有正面 failed/stopped 才考虑同 Task retry；Unknown 保留现场。staged 复用 canonical
checkpoint/continuation，同 provider session 的真实 transport 未证明就 blocked，不降级 direct。
真实 staged/retry/restart/pending 验收为 `not-run/Unknown` 时，#124 / Phase 1 不得关闭。

## 项目侧 fan-in 与 cleanup

`worker_done`、settled 或 reclaimable 只触发项目证据检查。coordinator 必须把 `project_lifecycle.py`
的 readback 交给既有共享 gate：`commit` 在 Execution Base review 通过后串行 cherry-pick 与 focused
checks，`artifact`/`checks`/`verdict` 只验证对应 evidence 并写 `consumed`，不 cherry-pick；任何成功
结果都保持 `authority: false` 与 `project_lane_transition: unchanged`，由既有 lane state machine 写入
`integrated`/`consumed`。

cleanup readback 的固定顺序是：项目 cleanup gate → Orca `worker-release` → archive/output readback →
Orca `worktree rm` → Git branch readback。dirty、未集成、未归档、active writer、身份冲突或 Unknown
返回 `close_pending` 并保留 Execution Worktree；release 证据与 project lane close 证据分离。helper
只验证 caller 提供的绝对 evidence/readback，不拥有第二套 Integration、testing、review 或 cleanup
调度器；cleanup retry 沿已完成步骤前缀幂等重试，重复 closed readback 返回 `deduplicated`。

## 结果与权限

preflight 报告必须包含 executable/version、operation、runtime/host/terminal identity、
带固定 executable 与实际读取命令的 guide/reference 来源、discovery 与 owner realpath、冻结
worker policy、capability readback 及证据时间。`preflight-ready` 只表示 caller-declared 结构齐全；
coordinator 必须核验原生 source provenance。它不授权 dispatch 或推进项目 gate。

缺 CLI/runtime/reference/discovery/capability、shared agent/model/effort、native 同 session
证据或 identity 不一致时，输出 `blocked` 与具体缺口；dispatch 请求输出
`dispatch unavailable` 与同一原因。不 fallback 到 Herdr 或 Codex App，不启动 worker。
真机未运行明确写 `not-run/Unknown`，静态 validator 通过不等于 Orca 能力已验证。
