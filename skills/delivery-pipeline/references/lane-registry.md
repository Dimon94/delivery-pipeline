# Durable Lane Registry

每个 dispatched work item 用 tracker checkpoint保存可恢复坐标；聊天摘要与 pane label不是 registry。
Canonical 本文件只定义共享 base schema 与 transport markers；特殊 transport overlay 与其所有者共置。

## 轻量交接

派发、终态回传、恢复只用下面三个固定模板。每项写一句或证据指针；输入有多个来源时逐条列出。
壳只追加 transport 坐标，其他信息放入现有 registry/工件并引用，不扩展交接字段。
无事项写“无”，无法确认写 Unknown。机器字段与指纹保持原合同，旧 lane 沿原证据恢复。

- 仅展开当前分支，输入省略不适用项；Unknown、失败、权限与未决事项显式保留。
- 指针包含绝对路径或 tracker URL、读取条件、定点或字段；派发前验证可读，动作前读目标。
  可变来源保留快照/时间；缺失、过期或冲突按原 gate 阻塞。唯一约束和本次差异写在范围/验收，
  Spec、ticket、repo instructions、冻结计划和日志正文留在各自来源。
- helper 校验完整输入，模型只接收判定与必要字段。大 JSON/日志用 python/jq/rg 定位读取；
  写入 readback 仍逐项比较 expected/actual。错误原文、命令、来源与历史失败留在原工件。
- 文件级哈希、component/checkpoint SHA256 和 ignored 指纹清单只留在机器工件；
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

### 终态模板

```text
FINAL_REPORT_BEGIN
Lane ID：<原 lane_id>
状态：completed | blocked
交付：<commit SHA 或 artifact/checks/verdict 坐标>
证据：<完整命令/结果、模型实际 readback、独立审查结论的来源/字段>
现场：<HEAD；实际 dirty 状态；dirty/untracked 精确路径>
确认：<本次用户决定与来源、未决事项；无新增确认写无>
阻断：<原因与失败工件；无阻断写无>
下一步：<coordinator 应执行的动作>
FINAL_REPORT_END
```

`completed` 是 outcome，不是 registry state。通知与最终回复使用同一短报告，coordinator 从
原证据验收，指针不构成 PASS。Review 的证据须可恢复 scope、owner、fixed point、HEAD、bundle
目录和七文件校验结果；clean commit 的 touched paths 从 `git diff <base> <commit> --name-status`
恢复。省去未变化的坐标和配置；额外工件仍给精确路径。

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
`artifacts_root` 让恢复直接定位本 map 的 review bundle、checks 与 checkpoint，不扫描全局 artifacts 树；
`合同入口` 是下一步动作所需的唯一 reference 章节。

### Worker 共同行为

入口从所属壳 packet 的 Worker 执行/加载章节开始；按当前 role/output_mode/phase 读取必需章节，
包含其子节。coordinator 的建图、分派与收尾入口不作为 worker 的默认输入。

1. 从 registry 核对本 lane 的 role/output_mode、冻结计划和隔离坐标；用 Git 核验实际 cwd、
   common dir、branch、base/HEAD 与 dirty state。cwd 必须为属于 Source repo 的 Execution Worktree，
   排除 Source/Integration，HEAD 包含 base。只处理本项，tracker fan-in、Integration、
   下一 gate 和远程动作由 coordinator 处理。
2. 完整读取 Owner SKILL.md 与当前分支必要引用，记录 frontmatter name + resolved path 与 runtime invocation label。
   `commit` 写入前按 `gate-state-machine.md` §实施前置检查核对 to-spec、to-tickets、ticket-sizing 与用户确认；
   缺失则 blocked。请求值和实际模型 readback 分开留证，缺证据写 Unknown。
3. 按 output_mode 交付：commit 保存本项候选；artifact 给产物坐标；checks 给完整命令/结果；
   verdict 给原始独立结论。后三者保持 clean。需要 Review 时先读
   `code-review-evidence-preflight.md`，使用输入中的 scope/fixed point 与同一不可变 bundle；
   审查权限、阶段停止与终态通知按所属壳合同执行。

完成标准：固定模板可定位当前分支的输入与原始验收证据，权限、失败和恢复坐标完整。

## Base Schema

以 `<!-- wayfinder-lane-registry:v2 -->` 开头：

```yaml
work_item: <url-or-gate-coordinate>
role: planning | design | frontend | backend | testing | review | map   # 持久化字段名保留；新 lane 写入任务类型
output_mode: commit | artifact | checks | verdict | none
lane_id: <stable-id>
runtime: herdr-pi-pane | herdr-codex-pane | herdr-claude-pane | orchestrator | orca
state: created | running | awaiting_human | terminal | consumed | integrated | blocked | setup_blocked | integration_conflict | integration_checks_failed | path_conflict | stale | close_pending | test_decision_paused | rebase_in_progress | push_failed | cleanup_in_progress | closed | superseded
agent: pi | codex | claude | none
model: <configured-model-or-none>
effort: <configured-effort-or-none>
model_evidence: pi-list-models | codex-catalog | claude-env | none
execution_mode: legacy | staged | direct | none   # legacy 仅 version 4 前 lane；新 lane 用 staged | direct | none
execution_mode_name: <modes 中的命名预设-or-none>   # version 5 新 lane 记录 mode 名；默认路径为 none
execution_source: role-config | ticket | map | user-config | work | none   # role-config 仅旧 lane；非实现任务用 work
starting_model: <frozen-model-or-none>
starting_effort: <frozen-effort-or-none>
execution_model: <frozen-model-or-none>
execution_effort: <frozen-effort-or-none>
direct_model: <frozen-model-or-none>
direct_effort: <frozen-effort-or-none>
execution_phase: starting | switching | executing | direct | none
prereq_check: <command-or-probe + expected evidence-or-none>   # ADR-0011；ticket 声明前提能力时必填
prereq_check_result: <persisted run evidence-or-none>
checkpoint: <repo-external absolute path-or-none>
checkpoint_version: <supported version-or-none>
checkpoint_sha256: <whole-checkpoint sha256-or-none>
continuation: <single persisted continuation overlay-or-none>
workspace_id: <id-or-none>
tab_id: <id-or-none>
pane_id: <id-or-none>
coordinator_runtime: pi-cli | codex-cli | claude-cli | orca-terminal | none
dispatch_runtime: herdr | orca | none
orca: <opaque-overlay-or-none>
herdr_session_name: <name-or-none>
herdr_session_owned: true | false | none
bootstrap_authority: trusted_execution_bootstrap | none
agent_permission_mode: approve | danger-full-access | dangerously-skip-permissions | none
worktree: <absolute-path-or-none>
branch: <branch-or-none>
base_commit: <hash-or-none>
head_commit: <hash-or-none>
integrated_commit: <hash-or-none>
integration_worktree_path: <absolute-path-or-none>
integration_branch: <feature/map-N-or-none>
map_run_authority: canonical_tracker_transitions | none
herdr_workspace_label: <actual-workspace-label-or-none>
test_strategy: test_in_integration | rebase_then_test | skip_extra_test | none
updated_at: <ISO-8601>
```

`orca` 仅为共享 registry 的嵌套 opaque overlay 槽位；其内部字段、操作与恢复合同全部归
写入方 runtime 的入口 skill 及其 helper 所有，本文件不枚举 runtime-specific schema。
overlay 写入方必须先持久化 intent、再补真实坐标与 receipt；共享 registry owner 必须在
写入后精确 readback。写入方 helper 不持有第二份 registry、dispatcher 或 event journal。

Orca worker 使用 `runtime: orca`，map 仍使用 `runtime: orchestrator`；
两者都显式记录 `dispatch_runtime: orca`，coordinator 为 `coordinator_runtime: orca-terminal`。
非 Orca lane 不补写这些 markers，也不因当前配置自动迁移。

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

map row使用 `role: map`、`output_mode: none`、`runtime: orchestrator`，并持久化 Integration
Worktree/branch、Map Run Authority与 test strategy；测试选择是否仍适用及额外测试证据按
`test-decision-and-rebase.md` 核对，只有需要询问时进入 `test_decision_paused`。
`base_commit` 固定为创建 Map Integration Worktree
时的 Source HEAD，作为 whole-change Review fixed point，后续 Integration 不改写。Herdr
session/workspace/tab/pane是 lane坐标；
同一 map后续新 lane可随 Coordinator Pane 的 current-workspace 默认落到另一 Workspace。

## Recovery

1. 枚举 map/spec/ticket items，读取每个 lane_id latest registry；按持久化的 `runtime` 与 `dispatch_runtime` 选择原 transport。
   Orca markers 缺失或互相矛盾时保留现场并 blocked/stale，不从当前 coordinator、配置或环境推断。
2. Herdr runtime 验证 session/workspace/tab/pane、kind、role/output_mode、agent/model/effort 与 worktree；
   execution mode/source 与阶段参数也必须一致；agent/model/effort 是 stored 启动坐标，不与 pane 的
   运行中模型对账。existing lane 不应用新 config 也不迁移 Workspace，新 lane 重新解析 Coordinator Pane
   当前坐标。
3. 用 Git验证 worktree、branch、commits与 dirty state。pane消失但持久 evidence存在时按
   output_mode fan-in；两者都不存在且排除 active writer后才 replacement。
4. `awaiting_human` 只在用户返回时 fan-in；恢复不挂 watcher、不定时 wait。
5. `integrated` / `consumed` / `close_pending` 按 cleanup contract readback或重试。
6. registry 与现实不一致时写 `stale`并保留证据，不覆盖可能存在的 writer。

## Prewalk Checkpoint

`starting` implementation worker 的首改现场由 canonical
`skills/delivery-pipeline/scripts/checkpoint.py` 生成；checkpoint 必须位于 repo 外，并由同目录临时
文件 `flush` + `fsync` 后原子替换。JSON 使用 UTF-8、键排序和紧凑分隔；`component_sha256` 分别
覆盖 dirty content、file mode、staged/index 与完整 snapshot，`checkpoint_sha256` 计算时排除自身。
同一路径只允许相同指纹幂等重写；任何更新必须写入新的 repo 外 artifact 路径，旧 checkpoint 不覆盖。

checkpoint 至少包含 lane/work item、runtime 与原生 session、Coordinator 坐标、CLI version、Execution
Worktree/branch/base/HEAD、phase/development mode/source/plan、requested/tool acceptance/actual
readback（不可读时显式 `Unknown`）、首改、检查、TODO、decision 和 evidence。dirty 路径按路径排序，
删除项显式记录，未跟踪项纳入；ignored 路径只保存内容/模式指纹并标记 `delivery_input: Unknown`，
直到确认没有 ignored 路径才可继续；unsupported 文件类型、缺字段、旧版本、hash 不匹配或当前 Git
snapshot 改变均不得登记成功引用。

阶段计划必须完整冻结 `starting`、`execution`、`direct` 三组 model/effort，并与当前 phase、
`development_mode`（`legacy|staged|direct`）及 `mode_source`（`role-config|ticket|map|user-config`）
一致；`tool_acceptance` 必须是明确的 accepted/status/source 结构。阶段信号分层：
`PREWALK_READY` 只触发 checkpoint 持久读回；只有原 runtime 的 `runtime`、原生 `session_id`、
coordinator thread/host 身份全部匹配，且已停止、单写者明确为 false 的 `WORKER_STOPPED` 才能返回
`ready-for-coordinator`。active 返回等待，活动状态或身份 Unknown、关键设计 Unknown、ignored 路径、
工具拒绝或实际模型/effort Unknown 均保留现场；该入口不发送接续、不触发 Terminal fan-in。

## Continuation Overlay

接续复用同一 lane registry，不创建第二份 registry、receipt 或 journal。`continuation.py` 只返回
overlay 和 runtime-neutral request；coordinator 必须先把一个 `continuation` overlay 写入既有 registry
并 readback，再向原 session 发送。overlay 的 `intent` 由 lane、原 session、source phase、checkpoint
SHA-256 和 target request 唯一确定；`state` 依次记录 `prepared`、`dispatching`、`send-authorized`、`sent`、`send-unknown`、`accepted`、
`started`、`executing` 或 `blocked`。

`dispatching` 只能在带当前 `request_id`、`after_marker: true`、`settled: true`、非空来源/时间的发送后
readback 且明确 `not_seen` 时返回可发送请求；旧 stopped 观测、在途调用或缺少 readback 只能回读，不能重发。

`send-authorized` 已落盘但发送前崩溃时，只有当前 `request_id` 的权威回读明确
`request_seen: false`、`not_seen`、`after_marker: true`、`after_lease: true`、`settled: true`，
且来源/时间非空、不是生成当前 lease 的同一 `send_probe`，才返回恢复到 `dispatching` 的 overlay。
该步返回 `request: null`；coordinator 必须持久化并读回后，再生成、持久化并读回新的 send lease 才发送。
同一 intent 保持既有 request_id；恢复回读保存在 `send_probe`，不新增协议或 journal。
seen、Unknown、身份不匹配或仅有 lease 前回读均保留现场，不重发；acceptance 可独立先于发送回执到达。

`request`、`tool_acceptance`、`new_turn`、`actual_model` 是四个独立字段；发送结果 Unknown 只允许
回读原 session，不允许增加请求数。`new_turn` 必须绑定本次 `request_id`、原 session 和新的
`turn_id`；只有原 session 的 `new_turn.started: true` 才能把 `execution_phase` 写为 `executing`。
`actual_model` 必须绑定该 `turn_id` 并带非空 `readback_at`；实际 model/effort Unknown 或 mismatch 不通过换模验收，
但后续同一 turn 的漂移只更新验收证据，不自动阻断已有交付 fan-in。用户手动
目标保留在 intent，`configuration_unchanged: true`，不回写 Worker Role Configuration。重复 terminal
和 fan-in 以稳定 ID 幂等消费，冲突或无法消歧时保持现场并 fail-closed。适用 gate 必须同时绑定
当前 `checkpoint_sha256`、`work_item` 和非空 `source`；旧版本批准不能替代当前用户确认。
未改动目标可沿既有分派授权以 `authorization: inherited-dispatch` 接续；用户改码或手动换模必须带新的
`approved: true` 覆盖，不回写全局配置。
`terminal.outcome: blocked` 可以在新轮前记录受阻终态但不得 fan-in；`completed` 必须绑定当前原
session、接续 request 和新轮 `turn_id`，并与 lane 的 `output_mode` 一致，`commit` 只可 `integrated`，
`artifact/checks/verdict` 只可 `consumed`。
