# Fresh Session Boundaries

coordinator 交接、压缩前保存当前状态，或恢复 named map 时读取。

## Coordinator

当前调用会话就是 coordinator；记录所属壳的实际 runtime/session，模型沿当前会话，不读取
worker role config。恢复只依赖 repo instructions、tracker、Git、latest lane registry 与当前 gate
所需 reference；同一未压缩上下文不重读未变化的 owner body。

## Coordinator Recovery

在既有 map registry 中维护唯一的 `## Coordinator Recovery` 节，正文使用
`lane-registry.md` §恢复模板的六项字段。当前记录覆盖更新，原决定和失败历史保留在原证据；
它是导航快照，不能代替 registry、Git、tracker、宿主 readback 或原始审查。
写入用 `scripts/recovery_record.py set <registry>`（stdin 六项正文）：它覆盖唯一节、把旧恢复段移入
同目录 `history-<registry>` 并 readback；读取用 `scripts/recovery_record.py show <registry>`，不整读 registry。

### 保存

1. gate、active writer、阻断或用户决定出现新事实时，在该次 registry/tracker 写入与核验中
   更新本节；Dispatch Handoff、coordinator 交接或可控压缩前确认记录与当前事实一致。
2. 独有业务约束、用户决定与尚未持久化的失败先持久化到原 spec/ticket/artifact，逐项 readback
   后再引用。证据注明定点或来源/时间；缺失仍内联保留并标 Unknown，不能为缩短正文丢弃。
3. 现场保留 Integration 的 base/HEAD/dirty 与全部 active writers 的枚举入口、lane/session、
   停止/活动判定及观测来源。证据保留有效权限、未决决定、当前阻断和审查 scope/fixed point/head。
   已消费 lane、过期请求与旧检查只留原证据指针，下一步写一个动作及其前置条件。

普通正文目标 2k tokens；超出时先移动已持久化的历史背景，必要约束保留并说明超出原因。
当前 gate 的必读证据另计，预算不构成放行或截断条件。

### 恢复

先用 `scripts/recovery_record.py show <registry>` 读本节六项记录，再枚举全部 active writers，
核验 Git/宿主现场与当前 gate 原证据。记录有效时只读 下一步 所列合同入口，不按 gate 顺序重读全部
reference；记录缺失或无效时才按 `gate-state-machine.md` 的从任意 Issue 重建、Gates、Resume State
选择最早未完成 gate。权限、未决决定与原始审查完整回读后才动作。
实时状态只从恢复记录、registry、Git 与 tracker 读取；memory 检索只用于跨 map 教训，冷启动最多一次、
limit 3，结果不作为 gate、lane 或 head 的证据。
记录缺失、陈旧或互相矛盾时沿原 registry/tracker/Git 重建，Unknown 阻断受影响动作；
已有 writer 的状态未消歧前不 replacement，旧 head 的审查不能用于新 head。
压缩后或冷恢复只重读合同入口所指章节；“历史上已读”不证明该内容仍在当前上下文。

### 宿主压缩边界

可控压缩时以已核验的本记录和未决约束为摘要输入，保留原证据入口；完成后 readback 摘要，
确认没有丢失新事实。宿主不暴露压缩入口时保留短记录供下一次恢复，不声称已替换其自动摘要。
本流程不新建 runtime 会话；staged worker 始终沿原 task/session 和冻结 checkpoint 接续。

## Worker Session

每条新 configured worker lane 使用所属壳的独立执行上下文与隔离 worktree。Packet 只包含本 role/
work item、resolved owner path、配置的 agent/model/effort、允许/禁止范围与持久坐标；worker 不继承
coordinator 对话，也不领取 sibling。

- planning worker：一个 research/spec/tickets gate及其持久 artifact。
- design/frontend/backend worker：一张 implementation/HITL work item。
- testing worker：一次 whole-change checks与证据。
- review worker：一次 code-review verdict与证据。

## Recovery

新会话按 Coordinator Recovery 核验；既有 lane 按 stored runtime/model/effort 恢复，不应用
新 config。路径、pane或 Git 证据不唯一时记 Unknown并停止 replacement。只有事实变化或
coordinator session 改变时重读对应边界。
