# Frontier、Configured Role Lane 与 Terminal Fan-in

任一 gate dispatch、implementation dispatch 或 worker terminal 后读取。

## Ready Frontier

先按 `gate-state-machine.md` 的实施前置检查限定当前 gate 的候选集合。
`ready frontier` 是该集合中所有 open、未被 dependency 阻塞且未被 claim 的 work items。
每次派发和 terminal event 都从 tracker/Git 重算；ready 计算只使用 tracker state、dependencies 与 claim。
dependencies 来自票面唯一一行 `Blocked by: #a, #b` 或 `Blocked by: None`；依赖票尚未创建时写
`Blocked by: Unknown（原因）`，按 Unknown 处理、不进 frontier。`lane_graph.py` 报其他 Unknown 时先修票面。
open 且无 blocker 不等于 ready：候选、不再推进项由票面标签或状态排除；closed blocker 只有已验收才算解除，
取消或迁移须改写下游票的 `Blocked by`。

按 tracker priority、dependency order、issue ID 选 maximal safe batch。无前序依赖的 ready items
同批并发派发；只有 active writer、无法由 Execution Worktree 隔离的 external mutable resource，
或用户明确要求串行时排除。普通 repo 文件路径重叠只进入 Integration 冲突检测，不构成
Dispatch blocker。

## Task Binding

| 工作 | Task type | Output mode |
| --- | --- | --- |
| AFK discovery/research、spec、tickets gate worker | `planning` | `artifact` |
| grilling/prototype HITL | `design` | `artifact` |
| design implementation | `design` | `commit` |
| frontend implementation | `frontend` | `commit` |
| backend/other implementation | `backend` | `commit` |
| whole-change tests | `testing` | `checks` |
| code review | review 矩阵（见下） | `verdict` |
| terminal fan-in（merger） | `integration`（CLI 配置未定义时用 `backend` 项） | `integration` |

review lane 无独立 work 项：用配置 `review.<scope>.standards` 的 `{agent, model, effort}`
启动 worker，packet 携带该 scope 的两轴矩阵配置给 resolved code-review owner。

task type 只选择配置项，不暗含 agent。agent/model/effort 只从 `model-config-schema.md` 定义的
version 5 配置读取；implementation lane 的 mode 名/source 也必须随 packet 和 registry 保存。

## Execution Lanes

- 每个 work item 一个 fresh lane、一个 Execution Worktree、一个 active writer。
- 落点拓扑、容量、worker kind 映射与 packet 模板只按所属壳的合同执行（CLI/Herdr 为
  `delivery-pipeline-herdr` 壳）；本文件不枚举 transport 细节。
- worker 只处理 packet 的 work item，不领取 sibling/dependent item或进入下一 gate。
- blocked 只暂停对应 item；其余 ready work继续。

## Dispatch Handoff

每条 lane 的 worker transport、Execution Worktree、packet、owner/work item、role config 与 registry 已互相验证，
worker 进入 `working`，registry readback 为 `running` 或 `awaiting_human`，即完成该 lane startup。
`working` 确认后立即按所属壳的 terminal-signal 合同建立唤醒通道；未建立的 lane
不算完成 Dispatch Handoff——terminal 不会唤醒 coordinator，只能靠用户手动发现。
整批成功 lanes 完成 startup、失败项隔离为 `setup_blocked` 后，统一报告全部坐标并立即 yield；
不等待 routine progress、首个问题或最终结果。报告时重跑一次
`skills/delivery-pipeline/scripts/lane_graph.py --registry-root <本机 registry root>`，
让全局 lane 静态页反映新批次（首次运行即自动新建该页）。

## Terminal Fan-in

coordinator 不亲自 fan-in。terminal event（HITL 为用户完成信号）到达后：

1. 把该 lane 加入待收口队列；无 active merger 时派发一条 integration lane（merger），
   worktree/branch 为 Map Integration Worktree，packet 只给待收口 lane_id 列表与本文件指针。
   merger 运行中到达的 terminal 累积到下一批；Map Integration Worktree 同时只有一个 merger。
2. merger 按 dependency order 对每条 lane 执行 `execution-worktree-integration.md`（验证、
   cherry-pick 或 `consumed`、focused checks、Cleanup、tracker transitions），逐条写 registry，
   刷新 `lane_graph.py`，终态只回 `LANE_DONE <merger_lane> <integration HEAD>`。
   worker transport 由所属壳指定的一方释放：壳未指定时由 coordinator 在 merger 终态后按壳
   Cleanup 第 1 步释放。
3. merger 终态后 coordinator 只读 registry state：重算 ready frontier 并派发下一批，
   `integration_conflict` 等阻塞项按 gate 报告；不等待“继续”。

final report 是 transport cache，Git、tracker、artifact 与 registry 是持久证据。watchdog 只处理
startup failure、terminal signal 丢失或工具 timeout；不固定轮询。

## Authority

local execution authority 覆盖 worktree、文件修改与本地 commit；Map Run Authority 覆盖 named map
canonical tracker transitions；remote publication authority 只在 push/main/PR/MR/merge/final closeout
前检查。
