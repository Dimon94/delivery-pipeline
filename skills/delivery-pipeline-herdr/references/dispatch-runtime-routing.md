# CLI/Herdr 调度运行时路由

创建、恢复或替换 worker lane 前读取。Coordinator 是当前 pi/Codex CLI/Claude CLI 会话；
新 worker 都经 Herdr，worker kind 完全由 version 5 work config 的 `agent` 决定：
pi → `herdr-pi-pane`，codex → `herdr-codex-pane`，claude → `herdr-claude-pane`。

恢复既有 lane 直接进入“恢复与切换”，不运行新 lane 的配置 gate。

## 新 lane

implementation lane 先按 `gate-state-machine.md` 实施前置检查运行 `scripts/implementation_gate.py`。
随后每条 lane：

1. 从当前 Integration HEAD 建 Execution Worktree；packet 按 `assets/HERDR_ROLE_DISPATCH_PACKET.md`
   写到 repo 外 `~/.config/delivery-pipeline/packets/<lane_id>.md`。
2. 运行本壳 `scripts/dispatch.py`（参数见 `--help`），capability evidence 按 `model-role-routing.md`
   探测。它一次完成：Coordinator Pane 坐标 readback（`herdr pane current --current` 与
   `HERDR_WORKSPACE_ID`/`HERDR_TAB_ID`/`HERDR_PANE_ID` 一致）、计划解析与冻结、registry
   先于 worker 写入、worker tab 落位与 readback、agent start、packet 单行投递、working 确认
   （重投一次）、lane watcher、registry `running`。成功只回一行 JSON 坐标；失败写 `setup_blocked`
   并回原因。落位前的拒绝（lane 名超 32 字符、map registry 未过 `recovery_record.py check`、
   链路外 owner 缺 `--off-chain-reason`）不写 registry、不开 pane：按报错修正后重跑。
3. 同批 lane 并发运行 dispatch；默认复用 coordinator 当前所在的 Herdr Workspace，
   只有用户显式要求新 Workspace 才创建。整批成功/失败项都完成 startup readback 后才到达 Dispatch Handoff。

配置或 evidence 校验失败时阻塞并运行 setup，不替换成 coordinator 自身 agent。trusted execution
bootstrap 覆盖已配置 worker 在精确 Execution Worktree 内的 kind-specific startup permission；
不覆盖 remote publication。Herdr unavailable 时输出完整 durable packet 并报告 `dispatch unavailable`。

## 恢复与切换

- 各 kind 按 registry 的 agent/model/effort 与 `herdr` overlay 恢复；配置变化不迁移 running lane。
- replacement 先按 `lane-registry.md` 排除 active writer，再按其 §Recovery 的中断原因处理：
  重派沿原 lane runtime/model/effort，验证实时可用性，不要求当前配置与 stored 一致；
  失败时保留 `setup_blocked`。
- cleanup 只关闭本 lane pane 与本 lane Execution Worktree/branch；保留 Coordinator Pane 及其 Workspace。

### 冻结 work replacement（DD-414）

非空冻结计划的正面失败走 canonical `lane_registry.claim`，参数与门禁见
`lane-registry.md` §Replacement Registry Interface；不得调用新 lane 的 resolve_plan。
本壳 `scripts/replacement.py execute` 仅消费已认领 lane，复用 canonical startup_request；
observe 必须在 Registry 锁内真实读取旧 writer/identity/能力/原生 gate。
verify_target 必须真实核验本 lane 隔离 pane 的身份、可用 shell 与作用域；Unknown 时不绑定、不启动。
原生 argv/pane/name 在 launch 前绑定到同 intent；响应丢失沿 native_request 对账后调用
recover_launch，不换 pane/name、不新建 successor、不重发原生启动。
当前 T3 宿主不满足 HERDR_ENV=1 时禁止控制用户 focused pane；不修改实施 map 的 transport。
本 helper 的接口检查不等于已完成真实 Herdr 模型验收，实际模型和 effort 必须独立留证。

生产调用入口为 `scripts/replacement_native.py`（`--help` 列出精确 scope/文件参数）。
`probe` 先采集 pane identity、process-info、agent list 和 schema；`claim`/`execute`/
`reconcile` 复用唯一 Registry，不用固定观察字典。原 pane 的 terminal_id/cwd 缺失时
必须先由可信原生采样形成完整 overlay，不猜测或借用当前目标坐标。
`init`/`primary` 是隔离 checks lane 的有界验收入口；nonce/fault 仅发只读提示，sample
独立采集响应，均不生成实际模型或 effort 的断言。验收过程不启动 watcher。

Herdr 0.9.5 已采集的帮助未提供持久历史请求账本。当前 Adapter 只在原 name/pane/kind
唯一且 ready 的独立读回后消费启动 receipt；CLI 非零（包括 agent_not_ready）不等于正面
startup_failed，shell 空闲和 agent 缺席也不等于原请求未启动。不能独立对账时保持
launching 并 blocked，不重发、不推进 C；需补版本匹配的原请求正面拒绝/历史账本证据。
尚无这样的原生证据时，不把 A→B→C 的 seam 检查当作原生验收通过。

## whole-change 单模型入口

`dispatch.py --task review --output-mode verdict --review-scope whole-change
--required-axes standards spec --request-id <round-id>` 使用 review resolver，拒绝 implementation
scope 与 ticket/map mode。其余 work 参数沿原合同。`--implementation-registry <file> ...`
可传完整贡献 lane Registry 文件；未传时只读 map registry（适用于贡献 row 共置的 Registry）。
调用方必须提供 fixed point 的完整贡献集合，不得仅传 coordinator/testing 的快照。
packet 的 Owner 三字段须为已解析 code-review；派发前写入并读回冻结 plan 与轴调用清单，
Registry 精确读回后才创建 pane。lane 启动前仅复核冻结目标能力，不再选模型。

独立回归命令：`python3 skills/delivery-pipeline-herdr/scripts/check_review_dispatch.py --case single-model`。
该命令使用 fake Herdr，不声称执行了模型。真实入口的逐轴 owner findings/readback 另由 root 验收。
