# Durable Lane Registry

每个 dispatched work item 用 tracker checkpoint保存可恢复坐标；聊天摘要与 pane label不是 registry。
Canonical 本文件只定义共享 base schema 与 transport markers；特殊 transport overlay 与其所有者共置。

## 轻量交接

派发、恢复只用下面两个固定模板，终态只用 §终态行。每项写一句或证据指针；输入有多个来源时逐条列出。
壳只追加 transport 坐标，其他信息放入现有 registry/工件并引用，不扩展交接字段。
无事项写“无”，无法确认写 Unknown。机器字段与指纹保持原合同，旧 lane 沿原证据恢复。

- 仅展开当前分支，输入省略不适用项；Unknown、失败、权限与未决事项显式保留。
- 指针包含绝对路径或 tracker URL、读取条件、定点或字段；派发前验证可读，动作前读目标。
  可变来源保留快照/时间；缺失、过期或冲突按原 gate 阻塞。唯一约束和本次差异写在范围/验收，
  Spec、ticket、repo instructions、冻结计划和日志正文留在各自来源。
- helper 校验完整输入，模型只接收判定与必要字段。大 JSON/日志用 python/jq/rg 定位读取；
  写入 readback 仍逐项比较 expected/actual。错误原文、命令、来源与历史失败留在原工件。
- 文件级哈希与指纹清单只留在机器工件；
  base/head/交付 commit 的 Git SHA 保留为版本坐标。发布/完整性验收需要的 digest 沿原合同。

### 派发模板

```text
Lane ID：<stable-id>
Work item：<URL 或 gate 坐标；含本项目标>
执行：<role/output_mode；当前 phase；请求 agent/model/effort>
Owner：<name>; <absolute SKILL.md path>; <runtime invocation label>
Registry：<absolute path；当前 lane>
现场：<Execution Worktree；branch；base commit>
范围：<允许路径、权限与本次边界>
验收：<验收来源/章节；本次补充或差异>
输入：<必要来源及读取条件；实施前置证据/冻结计划/审查参数按当前分支引用>
Worker 合同：<absolute 所属壳 packet path，读取 Worker 执行节>
```

### 终态行

worker 终态只输出一行：

```text
LANE_DONE <lane_id> <交付坐标>
LANE_DONE <lane_id> BLOCKED <一句原因；失败工件绝对路径>
```

交付坐标：commit → commit SHA；artifact → tracker/artifact URL；checks → 结果文件绝对路径；
verdict → verdict 文件绝对路径；integration → Integration HEAD。证据留在 Git、tracker 与 artifact，
收口方从原证据验收，不要求 worker 复述。用户决定写入 tracker 评论，由坐标指向。

### 恢复模板

```text
Map/Spec：<URL 或输入坐标>
Registry：<map registry 与全部 active lane 的可枚举坐标>
Gate/状态：<最早未完成 gate；持久状态>
现场：<原 coordinator runtime/session；Integration worktree/branch/base/HEAD/dirty；全部 active writers 及观测来源/时间；artifacts_root <本 map 工件绝对目录>>
证据：<当前有效的用户决定、独有业务约束、通过/失败/审查/检查点来源；阻断与待核验项写 Unknown>
下一步：<一个动作；所需权限或决定>；合同入口 <file>§<section>
```

本记录的持久化、更新与恢复核验由 `fresh-session-boundaries.md` §Coordinator Recovery 定义。
`artifacts_root` 让恢复直接定位本 map 的 review bundle 与 checks，不扫描全局 artifacts 树；
`合同入口` 是下一步动作所需的唯一 reference 章节。
工件只存证据（日志、diff、结果 JSON、截图），依赖树、构建产物与数据库副本用路径引用原位置。
`scripts/artifact_gc.py` 清理 14 天无写入的工件单元；需长期保留时在该单元放 `.keep`。

### Worker 共同行为

入口从所属壳 packet 的 Worker 执行/加载章节开始；按当前 role/output_mode/phase 读取必需章节，
包含其子节。coordinator 的建图、分派与收尾入口不作为 worker 的默认输入。

1. 从 registry 核对本 lane 的 role/output_mode、冻结计划和隔离坐标；用 Git 核验实际 cwd、
   common dir、branch、base/HEAD 与 dirty state。cwd 必须为属于 Source repo 的 Execution Worktree，
   排除 Source/Integration，HEAD 包含 base。只处理本项，tracker fan-in、Integration、
   下一 gate 和远程动作由 coordinator 处理。
2. 完整读取 Owner SKILL.md 与当前分支必要引用，记录 frontmatter name + resolved path 与 runtime invocation label。
   `commit` 写入前按 `gate-state-machine.md` §实施前置检查核对 to-spec、to-tickets 与用户确认；
   缺失则 blocked。请求值和实际模型 readback 分开留证，缺证据写 Unknown。
3. 按 output_mode 交付：commit 保存本项候选；artifact 给产物坐标；checks 给完整命令/结果；
   verdict 给原始独立结论。后三者保持 clean。verdict lane 先读
   `code-review-evidence-preflight.md`，使用输入中的 fixed point 与同一不可变 bundle；
   终态按 §终态行，通知按所属壳合同。

完成标准：固定模板可定位当前分支的输入与原始验收证据，权限、失败和恢复坐标完整。

## Base Schema

以 `<!-- wayfinder-lane-registry:v2 -->` 开头。lane row 只写下列字段；权限、model evidence
与日志可由 Agent 从 transport/Git/工件读回，不进 registry。

```yaml
lane_id: <stable-id>
work_item: <url-or-gate-coordinate>
role: planning | design | frontend | backend | testing | review | integration | map   # 持久化字段名保留；新 lane 写入任务类型
output_mode: commit | artifact | checks | verdict | integration | none
runtime: herdr-pi-pane | herdr-codex-pane | herdr-claude-pane | t3-task | lody-session | orchestrator | orca
state: created | running | awaiting_human | terminal | consumed | integrated | blocked | setup_blocked | integration_conflict | integration_checks_failed | path_conflict | stale | close_pending | test_decision_paused | rebase_in_progress | push_failed | cleanup_in_progress | closed | superseded
agent: pi | codex | claude | none
model: <configured-model-or-none>
effort: <configured-effort-or-none>
mode: <modes 中的命名预设-or-none>
worktree: <absolute-path-or-none>
branch: <branch-or-none>
base_commit: <hash-or-none>
updated_at: <ISO-8601>
```

按需字段，只在适用时出现：

- `recovery_plan` / `recovery_progress`：CLI 五 work 新 lane 使用 canonical `model_config.py freeze` 的值拷贝；
  两字段在 YAML 块中分别写成单行 JSON flow value，所有 transport 原样保存，不自行解析配置。
  `recovery_plan` 为不可变 `{plan_version: 1, source: work|explicit_mode, primary: ModelTriple, fallbacks: ModelTriple[]}`；
  保留完整顺序及重复位置。`recovery_progress` 初值为 `{current_index: null, next_cursor: 0}`。
  current_index 为 null 表示 primary，否则是 fallbacks 的零基下标；next_cursor 是已消费备用数，
  primary 时必须为 0，备用时必须等于 current_index + 1，
  next_cursor 范围为 0..len(fallbacks)。重复 triple 仍必须显式存位置，禁止按值寻找。
  读回/恢复运行 `model_config.py recover <registry.md> [lane_id]`（或 `recover_overlay(row)`），
  沿共享 Registry parser 返回 `status: frozen` 与计划/进度/当前 triple；失败返回非零、`invalid_recovery_plan`，
  不重 resolve。两字段都缺返回 `status: legacy` 及原 triple，沿 ADR-0023；部分缺失、版本错误、越界、
  mode/source 或当前 triple 不一致均拒绝，不能降级 legacy。replacement 保留原计划、显式推进位置；
  冻结接口本身不选择备用；replacement 见下文 Replacement Registry Interface。
- `head_commit` / `integrated_commit`：commit lane 终态与 Integration 后写入。
- `prereq_check` / `prereq_check_result`：ticket 声明前提能力时（ADR-0011）。
- `map`：所属 map registry 的 `lane_id`；`lane_graph.py` 据此把 lane 归入地图。
- `contract_rev`：派发时 skill 仓 HEAD。恢复或收口时与当前 HEAD 不同，就按
  `git -C <skill 仓> show <contract_rev>:<合同路径>` 读该 lane 冻结时的合同。
- `off_chain_reason`：packet owner 已移出交付链路（如 ticket-sizing）仍在链路内派发时的用户决定或 gate。
- transport overlay 槽位 `herdr` / `orca` / `t3code` / `lody`：opaque，内部字段归写入方壳。
- `coordinator_runtime` / `dispatch_runtime`：非 Herdr transport 的 markers。
- map row：`integration_worktree_path`、`integration_branch`、`map_run_authority`、`test_strategy`、
  `coordinator_runtime`。

overlay 内部字段、操作与恢复合同全部归写入方 runtime 的入口 skill 及其 helper 所有。
overlay 写入方先持久化 intent、再补真实坐标与 receipt；共享 registry owner 写入后精确 readback。
写入方 helper 不持有第二份 registry、dispatcher 或 event journal。旧 lane 的额外字段原样保留，
恢复时照常读取。

Orca worker 使用 `runtime: orca`，T3Code worker `runtime: t3-task`，Lody worker `runtime: lody-session`；
map 均为 `runtime: orchestrator`。三者 lane/map 都写 `dispatch_runtime`（`orca|t3code|lody`）与
`coordinator_runtime`（`orca-terminal|t3code|lody`）；Herdr lane 不写这两项。

## Worker State Machine

```text
created -> running | awaiting_human
running/awaiting_human -> terminal | blocked
created -> setup_blocked
terminal(commit) -> integrated | integration_conflict | integration_checks_failed | blocked
terminal(artifact/checks/verdict) -> consumed | blocked
integrated/consumed -> cleanup_in_progress -> closed
cleanup_in_progress -> close_pending -> closed
any active state -> path_conflict | stale
any active state -> superseded   # ADR-0011：上游前提被证据推翻时由 coordinator 整体置终态；
                                  # 保留 worktree 与坐标，不 fan-in、不计入失败、不原地复活
```

`awaiting_human` 表示 packet accepted且 agent working，用户正在 Herdr参与。整批 user-visible lanes
完成 registry readback即 Dispatch Handoff，不持续 monitoring。

## Map State Machine

```text
created -> running -> rebase_in_progress -> cleanup_in_progress -> closed
running -> test_decision_paused -> rebase_in_progress
rebase_in_progress -> push_failed -> rebase_in_progress | closed
```

map registry 只含 map row 与唯一 `## Coordinator Recovery` 节：批次结果、lane 清单与交付边界写进
`artifacts_root` 或原 tracker，恢复节用证据指针引用。`recovery_record.py check` 机械执行此形状与字段长度，
派发 helper 在落位前调用它；存量 registry 用 `recovery_record.py compact` 一次性迁移。

map row使用 `role: map`、`output_mode: none`、`runtime: orchestrator`，并持久化 Integration
Worktree/branch、Map Run Authority与 test strategy；测试选择是否仍适用及额外测试证据按
`test-decision-and-rebase.md` 核对，只有需要询问时进入 `test_decision_paused`。
`base_commit` 固定为创建 Map Integration Worktree
时的 Source HEAD，作为 whole-change Review fixed point，后续 Integration 不改写。Herdr
session/workspace/tab/pane是 lane坐标；
同一 map后续新 lane可随 Coordinator Pane 的 current-workspace 默认落到另一 Workspace。

## Recovery

1. 先对原 row 运行 canonical `recover` 读取冻结计划或识别 legacy；不读取当前配置补计划。
   枚举 map/spec/ticket items，读取每个 lane_id latest registry；按持久化的 `runtime` 与 `dispatch_runtime` 选择原 transport。
   Orca markers 缺失或互相矛盾时保留现场并 blocked/stale，不从当前 coordinator、配置或环境推断。
2. Herdr runtime 验证 `herdr` overlay 的 workspace/tab/pane、kind、role/output_mode、
   agent/model/effort/mode 与 worktree；agent/model/effort 是 stored 启动坐标，不与 pane 的
   运行中模型对账。existing lane 不应用新 config 也不迁移 Workspace，新 lane 重新解析 Coordinator Pane
   当前坐标。
3. 用 Git验证 worktree、branch、commits与 dirty state。pane消失但持久 evidence存在时按
   output_mode fan-in；两者都不存在且排除 active writer后才 replacement。replacement 按中断原因选做法：
   冻结的非空 work 计划的正面失败先进入下文 Replacement Registry Interface，按位置认领；
   legacy、空清单、显式 mode 沿原政策。连接中断或原因 Unknown 先核实原调用，不明时 inspect；
   原样重派使用原 packet 与原配置；packet 末尾追加上次失败
   说明：原 `lane_id`、中断原因、最后的持久证据坐标与失败位置。上下文耗尽不重派，
   按 `gate-state-machine.md` §证据触发的运行中补票 拆小。
   原 lane 写 `blocked` 并记原因，replacement 用新 `lane_id`、同一 `work_item`。同一 `work_item`
   已有两次 replacement 仍中断时不再重派：原票置 `superseded`，经同一通道重拆。
4. `awaiting_human` 只在用户返回时 fan-in；恢复不挂 watcher、不定时 wait。
5. `integrated` / `consumed` / `close_pending` 按 cleanup contract readback或重试。
6. registry 与现实不一致时写 `stale`并保留证据，不覆盖可能存在的 writer。

## Replacement Registry Interface（DD-414）

唯一持久 owner 为本 Registry 的 `scripts/lane_registry.py`；Recovery 纯决定面为
`scripts/replacement.py decide`。同一 map 的全部源与 successor 放在同一个 Registry 文件，
所有合作写者使用 resolved path 的永久 sidecar flock；不支持跨文件预算、外部编辑器并写、NFS 或断电保证。
沿已有 v2 块保存快照，latest row 为当前状态；不建事件表、receipt 库或重试计数器。

claim(path, source_id, revision, failure_id, category, observe) 在锁内调用原生只读 observe(source)：
必须返回 writer=exited、identity=match、capability=verified、gate=allowed；证据必须来自原生状态，
不能由 metadata 猜测。source/failure 为稳定身份，同源最多一个 successor，冲突事件拒绝。
source revision 来自 read()；已存在相同 intent 则返回原值，不再次消费游标。预算按同 work_item
所有不同 replacement_of lane 数计，含 accepted/launching/failed；已有非终态 writer 或未决 intent 拒绝。

successor 保留冻结计划、work_item、replacement_of、failure_id、failure_category；replacement_intent
保存 request_id（等于 lane_id）、status=accepted|launching|completed|failed、原 receipt。
launch 只接受已认领 intent，锁内先写 launching 并读回，再调用 Adapter；崩溃/异常保留 launching。
recover_launch 只对账原 request_id，completed/failed 消费原 receipt；Unknown/absent 保留 inspect，
本版本不在 launching 后重发。native readback 不可证明安全时牺牲进展，不能声称 exactly-once。

六类 category 接口：tool_or_model/startup_failed 为正面失败；connection_interrupted/unknown
只 inspect，context_exhausted 交重拆、cancelled 停止。本票对非空 work 清单实现；空/mode/legacy
返回 existing_policy，由 DD-415 闭环。耗尽或两次预算返回 exhausted/budget，不启动第三次。
Herdr Adapter 只执行已认领 triple，不能调用 resolve_plan 或自行选择备用。

DD-415 Recovery 分类：`unknown` 表示失败原因 Unknown，`connection_interrupted` 表示断连；只有 Adapter 正面排除原 writer 后，二者沿当前冻结 triple 原样 claim，游标不变，仍消耗共享预算。`outcome_unknown` 表示运行结果本身不明，只 inspect；launching 仍只能 recover 原请求。空 work 备用及 explicit_mode 同样原样 claim，不读当前配置。非空耗尽返回 exhausted 并保留源 blocked；budget 优先于耗尽与剩余项，交既有 superseded/运行中补票重拆路径，不再启动。cancelled 返回 stop，context_exhausted 返回 resplit，均不产生 successor。此处不代替 coordinator 修改 Tracker。
