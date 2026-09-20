# Dispatch Frontier（Multica 编排）

计算 frontier、执行一次派发、消费一次终态回流的完整流程。新 coordinator 会话读完本文件
+ SKILL.md 应能独立完成一次派发，无需口头补充。

## Frontier 算法

输入（全部持久证据，现读现算）：

1. 本 map/spec 下全部 open Issue（未 closed/cancelled）；
2. 每票 Orchestration 块的 `blocked_by` 列表；
3. 每个被依赖票的验收状态（见验收合同：产物 + checks + 状态机读回，不是「已 closed」
   这种代理信号；验收未通过 = 仍 blocked）；
4. 每票当前活跃写入 run 情况（预筛用，最终以宿主事务内校验为准）；
5. 是否存在未回答的 waiting 指针挡住该票（见 `hitl-waiting-recovery.md`）。

规则：

- `frontier` = 所有 open 且 `blocked_by` 全部验收通过且未在派的票。
- 依赖解析失败（Orchestration 块缺失/JSON 非法/引用不存在的票）→ 该票记 Unknown，
  按 blocked 处理并在汇报中列出，不猜测放行。
- 同 frontier 内多票可并行派发；仅当共享无法隔离的外部可变资源或用户明确要求串行时
  才串行。普通 repo 文件路径重叠不构成 dispatch blocker（继承 delivery-pipeline
  frontier-lanes 语义）。
- 一票失败回投或升级只影响该票及其传递依赖方；其余 frontier 照常推进
  （blocked 只暂停对应 item）。

## 一次派发（写入类票）

按序执行；任一步失败即停止该票派发并保留现场（不部分推进）：

1. **预筛**：`GET /api/issues/{id}/active-task`；已存在活跃任务则跳过本票（视为已有
   写入者，等其终态）。
2. **归属引用**：构造 `orchestration_ref = "<map-run-id>/<lane-id>"`（如
   `run_2d35ab058917/lane-08`）。同一票重派必须生成新 lane-id 后缀，不复用旧引用——
   旧 run 的 stamp 是 append-only 历史，新 run 需要一个新值。
3. **派发**：经宿主链路调用 `TaskService.DispatchOrchestratedIssueTask(ctx, issue,
   orchestrationRef, actorUserID)`（`server/internal/service/orchestration.go`）。
   该函数在单事务内：`LockIssueForOrchestrationDispatch`（锁 Issue 行，串行化并发
   编排派发）→ `CountActiveWriteRunsForIssue`（`queued|dispatched|running` 计数，
   >0 拒绝并返回可读原因）→ enqueue → `StampOrchestrationRef`（append-only，
   `agent_task_queue.orchestration_ref` 列，迁移 491 引入；影响行数 ≠1 即整体回滚）。
   查询定义在 `server/pkg/db/queries/orchestration.sql`；claim 路径另有
   `CheckOrchestrationWriteSlot` 前置校验兜底（fail-closed：计数查询失败即拒绝）。
4. **拒绝处理**：拒绝原因含既有活跃 run 的冲突说明；把票留 blocked，不重试覆盖、
   不绕过校验走无归属派发。
5. **work_class 声明**（当前边界）：票 05 交付的 Daemon 侧
   `Task.WorkClass`/`localDirectoryUsesWorktree` 已生效，但 server 端「dispatch 时从
   issue metadata 复制 work_class」的填充点尚未交付（票 05 Result 注明属票 08 范围，
   运行时为空 = fail closed 按写入类 = 照旧 worktree 隔离）。因此本版合同：
   - 写入类票：什么都不用做，默认即安全。
   - 纯读类票：在 Issue metadata 写 `work_class="read"`
     （`PUT /api/issues/{id}/metadata/work_class`），作为将来 server 填充点读取的
     声明；在填充点交付前它**不改变运行时行为**，不要据此预期豁免生效。
6. **记录**：派发坐标（issue、orchestration_ref、task id、会话）写入 coordinator 会话
   消息/汇报；这是 lane registry 的持久证据来源之一。

## 终态回流与重算

- worker 终态（completed / final failure）经 delegated 回边自动回流到本 coordinator
  会话（票 03/04，`server/internal/service/delegated_chat_backflow.go`）：沿
  `delegated_from_task_id` 链走到链顶，链顶是 chat 会话（无 Issue 归属、无 autopilot）
  时向该会话投递一条终态消息。
- 幂等：同一 (task, 终态) 重复投递（FailTask 与 sweeper 竞争等）只产生一条消息；
  coordinator 侧看到重复回流时按已处理忽略即可，不要二次验收。
- Issue 归属链的既有唤醒路径不受影响（各有归属，互不接管）。
- 收到终态 → 先验收（验收合同，票 09）→ pass 则重算 frontier 自动推进；失败按失败
  签名（同 verdict + 同 SHA 计同一签名）回投原 lane，同签名 2 次上限后升级 HITL。
- coordinator 被杀/换会话后恢复：从 Issue 正文依赖声明 + `agent_task_queue` 血缘
  （`orchestration_ref` / `delegated_from_task_id`）+ Git 读回重建现场；registry 是
  可重建缓存，丢失不阻塞恢复。

## 不做什么

- 不改 `ClaimAgentTask` 本体；不新增调度端点；不向 queue 写入任何 skill 自有状态
  （queue 只存运行引用）。
- 不在派发热路径做依赖计算；frontier 永远在 coordinator 会话内计算。
