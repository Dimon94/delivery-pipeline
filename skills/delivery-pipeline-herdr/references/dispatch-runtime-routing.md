# CLI/Herdr 调度运行时路由

创建、恢复或替换 worker lane 前读取。Coordinator 是当前 pi/Codex CLI/Claude CLI 会话；
带冻结派发合同的票经 Driver 批量执行。其余新 worker 经 Herdr，pane kind 由 work config 的 `agent` 决定：
pi → `herdr-pi-pane`，codex → `herdr-codex-pane`，claude → `herdr-claude-pane`，antigravity → `herdr-agy-pane`（`--kind agy`）。

恢复既有 lane 直接进入“恢复与切换”，不运行新 lane 的配置 gate。

## Driver 收取派发合同

派发合同与拆片的票按 `../../delivery-pipeline/references/brief-dispatch.md` 执行；本壳只多出 `driver_run.py watch` 交回终态行。

## 新 lane

implementation lane 先按 `gate-state-machine.md` 实施前置检查运行 `scripts/implementation_gate.py`。
随后每条 lane：

1. 从当前 Integration HEAD 建 Execution Worktree；packet 按 `assets/HERDR_ROLE_DISPATCH_PACKET.md`
   写到 repo 外 `~/.config/delivery-pipeline/packets/<lane_id>.md`。
2. 运行本壳 `scripts/dispatch.py`（参数见 `--help`），capability evidence 按 `model-role-routing.md`
   探测。新 work lane 读取 setup 的 `~/.config/delivery-pipeline/model-roles.json`。它一次完成：Coordinator Pane 坐标 readback（`herdr pane current --current` 与
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

已采集的 Herdr 帮助未提供持久历史请求账本。当前 Adapter 只在原 name/pane/kind
唯一且 ready 的独立读回后消费启动 receipt；CLI 非零（包括 agent_not_ready）不等于正面
startup_failed，shell 空闲和 agent 缺席也不等于原请求未启动。不能独立对账时保持
launching 并 blocked，不重发、不推进 C；需补原请求正面拒绝/历史账本证据。
尚无这样的原生证据时，不把 A→B→C 的 seam 检查当作原生验收通过。

## whole-change Review Plan 入口

`dispatch.py --task review --output-mode verdict --review-scope whole-change
--required-axes standards spec --request-id <round-id>` 使用 review resolver，拒绝 implementation
scope 与 ticket/map mode。其余 work 参数沿原合同。`--implementation-registry <file> ...`
可传完整贡献 lane Registry 文件；未传时只读 map registry（适用于贡献 row 共置的 Registry）。
调用方必须提供 fixed point 的完整贡献集合，不得仅传 coordinator/testing 的快照。
packet 的 Owner 三字段须为已解析 code-review；派发前写入并读回冻结 plan 与轴调用清单，
Registry 精确读回后才创建 pane。lane 启动前仅复核冻结目标能力，不再选模型。

独立回归命令：`python3 skills/delivery-pipeline-herdr/scripts/check_review_dispatch.py --case single-model`。
该命令使用 fake Herdr，不声称执行了模型。真实入口的逐轴 owner findings/readback 另由 root 验收。


## 逐轴执行证据 fan-in

resolved owner 完成 required axes 后，运行 `python3 <本壳绝对路径>/scripts/review_execution.py
--ledger <原 whole-change 账本>`；stdin 是 `round/axes/p2_issues/review_packet/native_readbacks`。
`review_packet` 原样取冻结 packet，读回 schema 见 canonical `code-review-evidence-preflight.md`。
该入口只执行原 review gate；不读取配置、不选候选、不创建 lane。逐轴缺 readback 写 Unknown，
known mismatch 返回 `REVIEW_BLOCKED` 并保存全部 findings；不得自动重跑。退出 0 表示账本写入成功，
只有 stdout `PASS` 才允许继续放行，不能仅凭退出码判 PASS。

独立检查：`python3 skills/delivery-pipeline-herdr/scripts/check_review_dispatch.py --case axis-evidence-mismatch`。
该检查仅模拟 Adapter 证据，不证明真实 Herdr/provider 的 model 或 applied effort。

## 有序候选的只读 preflight 输入

非空参与池要求 `--evidence` 为本 request 的当前 ProbeEvidence envelope（request_id、observed_at、
sources、capabilities）。生产 dispatch 在任何 packet/Registry/pane mutation 前调用本壳
`native_review_preflight.preflight_review_candidates`；`--native-capabilities` 外部自述文件不再授权派发，
非空池传入此参数会拒绝。canonical CLI 的文件输入仅用于纯计划接口，不能替代 Adapter 现场来源。

Harness 版本号不作门（Herdr、Pi 会持续升级）：只核 `agent start --help` 仍有 AGENT_ARG 透传，并逐身份核对该 agent 的 kind（antigravity 为 `agy`）
出现在 `agent start --help` 的可选值里。Pi 加载当前安装包的原生 parseArgs、ModelConfig schema、
精确模型解析和 thinking level 支持/clamp，只覆盖当前 models.json 注册项，不做 fuzzy/custom fallback。
codex、claude、antigravity 在本次 preflight 内重新读取工具自身的模型目录（`codex debug models`、
Claude 官方模型清单、`agy models`），精确 model 与 effort 都在目录里才为 runnable。不从 probe 文件复制
native 成功。AGENT_ARG 透传或 kind 缺失、原生接口加载失败、目录读不到为 Unknown；目录明确不含该 model/effort 才为 unavailable。尚不具备未来启动、认证、网络、额度或审查成功保证。

逐项证据绑定 request、真实采集时间、完整 ordered pools（重复位置保留）、精确 identity、
原生命令/退出码/结果及 binary/解析源码 hash；evidence_id 为这些绑定的 SHA256。models.json
只保留 hash，不输出凭据。成功来源随 review_plan.native_preflight 冻结；失败结果在 stdout
保留缺口，不写 packet/Registry。`--preflight-only` 穿过同一生产 whole-change 入口并在写入前返回
计划与 owner_calls，供 Root 读回零创建证据；不是另一个 selector。空池不采集新 native 来源。

canonical resolver 先核验参与池，再逐轴选择首个 runnable+different；无 different 时取首个
runnable 并记录退化理由。standards lane 与 required standards 选择深等；spec 只消费冻结
owner_calls。顺序、重复、比较依据和 declared_at_review 声明随 config hash 冻结。
requested/mixed basis 是配置级偏好。空 candidates 保持旧 evidence map 和单模型门槛。
公开检查：`check_review_dispatch.py --case different-family`；fixture 不代表真实执行。
