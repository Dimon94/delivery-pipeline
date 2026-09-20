# C1 演练脚本（单票闭环 + 三韧性演练）

可直接执行的演练脚本（票 10/11 的输入）。C1 = 单票闭环：派发一张票 → worker 在
worktree 内执行 → Finalize 自动提交 → 终态回流 → 自动验收通过。四个演练共用前置；
每步给出操作、观察点、通过判据。命令中的 `$BASE`、`$ISSUE`、`$WS` 按演练环境回填。

## 共用前置

1. 环境：`make up` 起本机环境；工作区存在且 daemon 在线（`make status`）。
2. 演练票：建一张写入类 Issue，正文含 `## Orchestration` 块：
   `{"blocked_by": [], "work_class": "write", "acceptance": ["产物文件 <path> 存在且内容含 marker"]}`。
   worker 任务提示只要求写该 marker 文件，保证产物可判定。
3. 观察工具：
   - queue 现场：`psql ... -c "SELECT id,status,orchestration_ref,delegated_from_task_id FROM agent_task_queue WHERE issue_id='$ISSUE' ORDER BY created_at"`；
   - Git 读回：`git -C <lane-worktree> log --oneline -3` / `git status`；
   - metadata：`GET /api/issues/$ISSUE/metadata`。
4. 清理约定：演练结束后取消演练票残留 run、删除演练 metadata 键
   （`DELETE /api/issues/$ISSUE/metadata/{verdict,waiting,authz.auto-integration}`）。

## 演练 0：主链路（单票闭环）

| # | 操作 | 观察点 | 通过判据 |
| --- | --- | --- | --- |
| 1 | coordinator 预筛：`GET /api/issues/$ISSUE/active-task` | 返回无活跃任务 | 预筛通过（否则本演练前置未满足） |
| 2 | 构造 `orchestration_ref="<map-run-id>/c1-lane"`，经宿主链路派发（`TaskService.DispatchOrchestratedIssueTask`） | queue 行 status 流转 `queued→dispatched`，`orchestration_ref` 已 stamp | psql 读回：行存在、ref 值正确、无第二行 |
| 3 | daemon claim 并执行 | claim 前置 `CheckOrchestrationWriteSlot` 通过；worktree 内出现产物写入 | status 到 `running`；`git status` 见未提交产物 |
| 4 | worker 完成 → Finalize 自动提交 → 终态回流 | coordinator 会话收到终态消息（沿 delegated 回边）；重复投递幂等 | 恰好一条终态消息；`git log` 见 Finalize checkpoint commit，记下 HEAD SHA |
| 5 | 验收（默认三件套 + 追加项） | 产物存在（文件系统读回）；checks 绿；任务终态且无残留活跃行 | 全 pass；写 `verdict` metadata：`{"verdict":"pass","sha":"<HEAD>","sig_count":0}` |
| 6 | 重算 frontier 推进 | 该票验收通过，依赖方（若有）解锁 | 无悬空 `waiting` 指针；汇报消息落 coordinator 会话 |

## 演练 A：杀 coordinator 重建

| # | 操作 | 观察点 | 通过判据 |
| --- | --- | --- | --- |
| 1 | 进入演练 0 步骤 3（run running 中）后，杀掉 coordinator 会话 | 会话终止；worker run 不受影响 | queue 行仍为 `running`，无状态翻转 |
| 2 | 起新 coordinator 会话，按恢复路径重建现场：Issue 正文 Orchestration 块 + `agent_task_queue` 血缘（`orchestration_ref`/`delegated_from_task_id`）+ Git 读回 | 重建出的在派票、ref、SHA 与 kill 前一致 | 重建 registry 与 psql/Git 证据一致；**不重复派发同票**（预筛 `active-task` 命中即跳过） |
| 3 | 等 worker 终态 | 终态回流沿回边投递到链顶（原发起会话）；新 coordinator 以 queue 终态 + Git 读回为准主动验收，不依赖回流消息到达新会话 | 验收照常完成且只验收一次（重复回流按已处理忽略）；verdict metadata 只写一次 pass |
| 4 | 收尾 | 无残留 | 演练票闭环，registry 可丢弃（可重建缓存） |

## 演练 B：暂停 = 取消 + Finalize checkpoint + PriorSessionID 接续

| # | 操作 | 观察点 | 通过判据 |
| --- | --- | --- | --- |
| 1 | 进入演练 0 步骤 3（run running、已有部分未提交改动）后，用户主动取消（宿主既有 cancel：`CancelTaskByUser` → `captureTaskCancelled` → Finalize 自动提交 checkpoint） | 任务行转 cancelled；worktree 分支出现 Finalize checkpoint commit | psql：status=cancelled；`git log` 见 checkpoint commit，部分改动已落 |
| 2 | 同票重新派发接续：新 lane-id 后缀的新 `orchestration_ref`（append-only 纪律），新 run 携带 `PriorSessionID` 指向上次会话（daemon 暖接续链路） | 新 run 沿 checkpoint 继续而非从零重做 | `git log`：checkpoint commit 在新 HEAD 历史中；无重复产物、无状态泄漏 |
| 3 | 变体（worktree 已回收）：删除/回收 worktree 后再接续 | 显式披露断链（`PriorSessionResumeUnavailable`），走分支 + Issue 正文重建现场（决策 04 Q5） | 断链被披露而非静默丢失；重建后产物可从分支恢复 |
| 4 | 接续 run 完成 | 终态回流 + 验收 | 默认三件套 + 追加项全 pass；verdict metadata 记录 pass |

## 演练 C：失败回投两次升级

| # | 操作 | 观察点 | 通过判据 |
| --- | --- | --- | --- |
| 1 | 建注定失败的演练票：acceptance 追加项要求一个 worker 不会产出的 marker 文件；派发并完成一次 run | 终态回流到达；验收按追加项判 fail | verdict metadata：`{"verdict":"fail","reason":"产物缺失","sha":"<SHA1>","sig_count":1}` |
| 2 | 自动回投原 lane（新 lane-id 后缀的 `orchestration_ref`，附失败证据）；worker 不改代码（同 SHA）再次完成 | 第二次验收 fail，verdict 与 SHA 均同 = 同签名 | sig_count 写为 2；**不发生第三次自动回投** |
| 3 | 升级 HITL：进入等待三件套（chat 提问卡带 `waiting` 指针 + `PUT metadata/waiting` JSON 字符串 + deferred） | UI 会话行徽章「等你回答」/横幅出现；deferred 不占并发 | `GET metadata` 见 `waiting` 键值 `{who,what,ref}` 完整；queue 无新 run |
| 4 | 有效回答：用户在该会话发一条 member/user 消息 | 指针后第一条用户消息 = 有效回答；deferred 提升；清除 `waiting` 键 | `DELETE metadata/waiting` 已执行；只恢复对应 lane；改派/改票由 coordinator 在唤醒点决策，平台不自动推进 |
| 5 | 变体（新签名）：改判据或让 worker 产出新 SHA 后再次失败 | (verdict, SHA) 任一变化 = 新签名 | sig_count 重置为 1，允许再次自动回投；签名计数按 (verdict, SHA) 独立 |

## 通过总判据

- 演练 0 全链路无人工干预完成闭环；演练 A/B/C 每行判据全过。
- 任一判据不过：记录 (演练, 步骤, 观察值, 期望值) 回标到对应实现票，不带病推进。
