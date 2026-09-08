# Codex App Native Dispatch Adapter

仅 `delivery-pipeline-codex-app` 加载。本文件拥有 Codex App task/thread transport、App registry
overlay、外层 task fan-in 与内部 gate subagents；canonical CLI/Herdr 主干不读取它。

## Capability

`list_projects`、`create_thread`、`list_threads`、`read_thread`、`wait_threads`、
`send_message_to_thread`、`set_thread_title`、`set_thread_archived` 与
`list_archived_threads` 必须全部可用；缺一项就不能声称 native Dispatch 可用。

## Role Coverage

| Role/work | Execution | Output mode | Fan-in |
|---|---|---|---|
| planning / design HITL | App task | `artifact` | artifact/tracker readback → consumed |
| design/frontend/backend implementation | App task | `commit` | Integration subagent + focused checks → integrated |
| testing | Luna / max subagent | `checks` | check evidence readback → consumed |
| review | code-review 双轴 subagents | `verdict` | verdict/findings readback → consumed |

外层 task roles 使用 `../assets/APP_ROLE_DISPATCH_PACKET.md`；内部 Testing、Review 与 Integration
由 coordinator 组装同等范围、证据和权限 prompt。没有 role 可以回落到不存在的 CLI config。
模型选择与首次建图入口读取 `development-mode.md`；用户 gate 判断由 coordinator
核验确认与持久产物。

## App Registry Overlay

App lane 在 canonical role/state字段之外增加：

```yaml
runtime: codex-thread
agent: codex-app
development_mode: <sol-luna | sol-sol | sol-direct | none; legacy astra-* only on recovery>
mode_source: <ticket | map | default | existing lane>
execution_phase: <starting | switching | executing | none>
checkpoint: <absolute artifact path | none>
requested_model: <development-mode current phase selection>
requested_effort: <development-mode work selection>
model: Unknown
effort: Unknown
model_evidence: Unknown
agent_permission_mode: app-owned
project_id: <Source-owner-projectId>
host_id: <host-id>
thread_id: <id>
thread_archived: true | false | unknown
coordinator_thread_id: <coordinator-task-id>
coordinator_host_id: <coordinator-host-id>
```

这些字段只定义在本 App reference，不进入 canonical Herdr registry schema。
requested 字段保存当前阶段请求，切换前的请求及证据保存在 checkpoint；model/effort 保存宿主实际 readback，model_evidence 保存来源与时间。
工具接受请求不代表已验证模型；缺 readback 保持 Unknown。旧 lane 的 app-owned 值保留为
历史记录，不反推 requested 值、不静默换模型或 transport；继续按 registry 和产物恢复。

## 创建

先从宿主读取当前 task 的实际 model/effort/source，用 `scripts/prewalk.py coordinator` 记录；
推荐配置允许用户覆盖，Unknown 或偏离推荐值本身不阻断创建或恢复。

1. implementation 新 lane 先回读 canonical gate-state-machine 的实施前置证据，再按开发模式合同
   调用 `scripts/prewalk.py resolve`；非零退出不得创建任务，把通过后的模式与
   当前阶段请求写入 packet/overlay；recover 只恢复、不新建。解析并持久化 Source owner projectId 与 coordinator task/host；project/path 未变化时复用。
   packet 填入真实 coordinator 坐标、repo 外 lane registry 绝对路径与本文件绝对路径作为 Terminal 回传合同；新建与接管 packet
   都保留该入口。完成回传属于本 lane 的调度授权。
2. 按 `task-coordinate-title.md` 生成 role-aware title；同批 lanes 并行调用 `create_thread`，显式
   设置 title、project、Integration branch `startingState` 及 requested_model → `model`、
   requested_effort → `thinking`。先确认用户已明确要求新任务；仅维护 skill 不满足该条件。
   首次无 map 的临时 base 按开发模式合同处理。App 拥有 Execution Worktree。
3. 只返回 `clientThreadId` 时用 `list_threads` 按 title/project/lane 找 ready task；不能把
   clientThreadId 当 threadId。
4. 聚合 readback：task 属于 owner project、worktree common dir属于 Source repo、base commit
   等于 dispatch 时 Integration HEAD、cwd 不在 Source/Integration Worktree。首次建图则核对
   临时 registry 的 Source base，map/Integration 为 none；仅消费 artifact，后续沿正式 Integration。
   模型请求被拒绝时写 setup_blocked 并保留错误；不静默换模型。模型 readback 按开发模式合同
   独立记录，Unknown 不冒充请求已落实。
5. 写 base registry + App overlay并精确 readback；task 已接受 packet后写 running/awaiting_human。
6. 整批 startup 完成后用 `wait_threads`（`timeoutMs: 0`，targets 带 threadId/hostId）读一次快照，
   保存返回 cursor；已终态的 lane 立即 fan-in，其余在确认 packet 包含回传合同后 Dispatch Handoff。

Testing 和 Review gate 不进入本节创建流程。coordinator 先持久化 gate fixed point 与不可变证据，
再通过 `scripts/prewalk.py subagent` 取得显式模型参数；Testing 单独请求 Luna / max，Review
调用 owner 并传 `implementation` 或 `whole-change` scope。两者都只读并在回传后由 coordinator
核验结果。逐票 Integration 也走 subagent 入口，但要求父任务可写、active_count 为 0，并只允许
写指定 Integration Worktree；完成后 coordinator 重新读取 HEAD、commit、worktree 状态与 checks。

## Prewalk 中间回传

收到 `PREWALK_READY` 时按 `development-mode.md` 的机械核验入口运行 prepare，先持久化
返回 overlay，再按 Prewalk 接续步骤向原 task
发送下一轮。通知可能早于起步轮停止：prepare 返回 wait-for-stop 时，对返回 target 调用
wait_threads（每次最多 60000 ms，沿用 cursor），读到停止后重新读取现场并 prepare。
超时且仍 active 时继续有界等待并按需报告进度；不把正常结束时序误判成 blocked 或直接
结束协调轮，避免起步结束后再无通知可唤醒。活动状态 Unknown 时保留现场并报告，不能
启动接续。只有 persist-before-send 才能写 switching 并发送；不进入 Terminal fan-in、archive 或 cherry-pick。恢复 starting/switching lane
先读原 task 与 checkpoint；原轮未停止或发送结果未知时不启动第二个执行者。

## Terminal 回传

worker 对 completed 与 blocked 都执行，所有 output mode 共用：

1. 完成持久交付证据，组装完整 `FINAL_REPORT_BEGIN` / `FINAL_REPORT_END` 报告。
2. 最终回复前调用 `send_message_to_thread`，`threadId` / `hostId` 使用 packet 的 Coordinator
   task / Coordinator host，`prompt` 携带完整报告并要求 coordinator 按 registry 验证后执行
   role-aware fan-in。子任务的最终回复本身不构成已发送通知的证据。
3. 工具确认发送成功后，在最终回复保留同一报告并声明已回传。发送失败或结果 Unknown 时，
   保留报告和目标坐标，明确“回传受阻”；不把工作完成冒充通知成功。

coordinator 收到报告后按 registry 核对 worker task、work item 与 output mode。通知可能早于
worker 最终回复：此时直接核验消息中的报告与 Git/artifact 持久证据。重复通知以 registry 的
integrated/consumed/closed 状态去重，避免重复 cherry-pick；close_pending 仅恢复 cleanup。
blocked 进入受阻分支，其余 ready lanes 继续推进；若原因为“实现已保存、审查待完成”，
coordinator 验证候选 commit 后立即按独立 Review 放行流程接手，不等待用户重复要求。
回传不扩大 tracker 或远程发布权限。

报告中的 `completed` 是 FINAL_REPORT outcome，不是 registry state，禁止写入 `state: completed`。
核验成功后先写 `terminal`，再按 output mode 写 `integrated` 或 `consumed`；报告为 `blocked` 才写
`blocked`。这样所有成功 lane 都进入下面同一次 fan-in 的 archive，不会绕过状态机。

## Role-aware Fan-in

### 独立 Review 放行

正式两轴由 coordinator 调用 code-review owner 管理，implementation worker 不拥有取消、
改写 verdict 或豁免的权限。原 worker 内嵌审查可作预审，不替代 coordinator 的最终放行。
worker 可保存候选 commit，但缺独立结论时按 blocked 回传“实现已保存、审查待完成”。
coordinator 收到候选提交后冻结 base/head，生成 Review Evidence Bundle，启动两轴只读审查。
修复回原 worker，完成后冻结新 head 并复核；不沿用旧 head 的 PASS。

cherry-pick、integrated、关闭实施票之前，coordinator 必须独立读取 reviewer 宿主记录，调用
`scripts/prewalk.py review`。输入 worktree、worker_id、base_commit、head_commit 和 reviews，
reviews 必须包含 standards/spec 两轴；每轴包含 reviewer_id、source（宿主任务/轮次与时间）、
status、verdict、verdict_text（原始最终结论）、blocking_findings（未解决阻断项数）、base_commit、
head_commit。只有 completed + pass + 零阻断项、两轴身份独立且版本匹配才可放行。
source 和 verdict 必须由 coordinator 直接核对，不能复制 worker 提供的“通过凭证”；
helper 校验结构和当前 Git 现场，不验证宿主来源真实性，不是宿主权限沙箱。
中断、超时、缺结果、自评和旧版本结论均不得替代 PASS，测试通过也不能替代审查。
需取消时由 coordinator 记录原因并恢复或重派；已有合适 reviewer 可复用，无需重复建任务。
用户明确豁免须单独记录原话、来源、代码版本和范围，人工放行单列，不伪造 helper PASS。
whole-change Review 同样执行本门禁；旧 lane 已有两轴结果可直接回读核验，无有效结果则补审。

外层 task terminal 后 `read_thread` 一次；内部 Testing、Review、Integration 则读取 subagent
回传与持久证据。随后按 output mode 验证：

- `commit`：先回读 canonical gate-state-machine 的实施前置证据，缺失则保留现场并阻塞 Integration；要求 terminal commit、内嵌 code-review 的 Review fixed point 等于 lane base commit、
  Review Evidence Bundle readback与 clean/declared dirty state，按 dependency order cherry-pick；
  focused checks通过后写 integrated。
- `artifact`：验证 tracker/artifact坐标；无必要 repo 变更时 worktree必须 clean，写 consumed。
- `checks`：验证 Luna / max 测试命令/结果且 worktree clean，写 consumed；失败阻塞 review。
- `verdict`：验证 Review fixed point 等于 map registry base commit、Review Evidence Bundle readback、
  `whole-change` scope、Sol / xhigh 两轴 review verdict/findings且 worktree clean，写 consumed；
  blocking finding阻塞 closeout。

非 commit lane 不要求 commit，也不 cherry-pick；unexpected file changes fail closed。

## 恢复、Archive 与 Cleanup

- running task 依靠 Terminal 回传唤醒 coordinator；恢复时先做一次 `wait_threads` 快照
  （`timeoutMs: 0`），补收旧 packet 或发送失败遗留的终态报告。显式 monitor/wait 使用有界
  等待并传已有 cursor；快照结束后仍 running 的 lane 按回传合同等待真实通知。
- 旧 running lane 缺回传合同或 coordinator 已更换时，先更新 overlay，再向原 task 发送新的
  coordinator 坐标与 Terminal 回传合同入口；完成补发后才交接，沿用原 worker 与 worktree。
- active lane 用 project_id/host_id/thread_id恢复；task 消失但持久 evidence存在时沿 evidence fan-in。
- integrated/consumed 不是 Codex task 的停靠状态：在同一次 fan-in 内立即调用
  `set_thread_archived({threadId, hostId, archived: true})`，再用 `list_archived_threads` readback。
  成功写 closed；archive失败写 close_pending并保留坐标。关闭 tracker 或派发下一 ready lane 前，
  必须已完成该 archive readback，或已持久化 close_pending 与失败证据；不得静默留下已验收的
  live task。
- commit lane focused checks失败时 task保持未归档；artifact/checks/verdict lane证据失败同样保留 task。

完成标准：外层 roles 有 task transport 与 archive 路径；内部 Testing/Review/Integration 有
subagent 请求、运行 readback、output-mode fan-in 与持久证据。App overlay、task/worktree 与
持久证据一致。
