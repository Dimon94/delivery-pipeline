# Alma Task Native Dispatch Adapter

仅 `delivery-pipeline-alma` 加载。本文件拥有 Alma Task tool transport、Alma registry
overlay、外层 Task fan-in 与内部 gate Tasks；canonical CLI/Herdr 主干不读取它。

## Capability

Task tool 内置于 Alma，必须可用：
- `Task(...)`：启动前台或后台 subagent，`model` 参数格式 `"<providerId>:<providerModelId>"`
- `TaskOutput(task_id)`：读取 Task 状态与输出
- `resume` 参数：恢复已有 Task，**但 resume 不保留上下文（ADR-0015）**

缺一项就不能声称 native Dispatch 可用。

## Role Coverage

| Role/work | Execution | Output mode | Fan-in |
|---|---|---|---|
| planning / design HITL | Alma Task | `artifact` | artifact/tracker readback → consumed |
| design/frontend/backend implementation | Alma Task | `commit` | Integration Task + focused checks → integrated |
| testing | 配置的 testing Task | `checks` | check evidence readback → consumed |
| review | code-review 双轴 Tasks | `verdict` | verdict/findings readback → consumed |

外层 Task roles 使用 `../assets/ALMA_ROLE_DISPATCH_PACKET.md`；内部 Testing、Review 与 Integration
由 coordinator 组装同等范围、证据和权限 handoff packet。没有 role 可以回落到不存在的 CLI config。
模型选择与首次建图入口读取本文件§配置查询；用户 gate 判断由 coordinator 核验确认与持久产物。

## Alma Registry Overlay

Alma lane 在 canonical role/state 字段之外增加：

```yaml
runtime: alma-task
agent: alma
development_mode: <配置 modes 中的 key | none；恢复沿持久值>
mode_source: <ticket | map | default | existing lane>
config_path: <absolute resolved config/models.json>
execution_kind: direct  # ADR-0015：Alma 只支持 kind: direct
direct_target: <frozen direct model + effort + source + scope>
requested_model: <配置查询返回的 model>
requested_effort: <配置查询返回的 effort>  # effort 只记录请求值（ADR-0015），Task 无此参数
model: Unknown
effort: Unknown
model_evidence: Unknown
agent_permission_mode: alma-owned
task_id: <Alma Task ID>
coordinator_thread_id: <coordinator thread ID>
alma_thread_id: <worker thread ID | same as coordinator | none>
```

这些字段只定义在本 Alma reference，不进入 canonical Herdr registry schema。
requested 字段保存配置查询返回值；model/effort 保存宿主实际 readback，model_evidence 保存来源与时间。
工具接受请求不代表已验证模型；缺 readback 保持 Unknown。**Alma Task 无 effort 参数**，effort 只记录不落实（ADR-0015）。

## 配置查询

本壳使用 `scripts/alma_gate.py` 与 `config/models.json`：

- `echo '{"work":"planning"}' | alma_gate.py model` → 返回 target（model/effort/source/scope）与 Task request（只含 model）
- `echo '{"task":"backend","output_mode":"commit","ticket_mode":"standard"}' | alma_gate.py resolve` → 返回 direct_target 与 overlay
- `echo '{"work":"review","review_scope":"implementation","active_count":0,"read_only":true}' | alma_gate.py subagent` → 返回两轴 review_models 与 requests

所有查询从 stdin 读 JSON，stdout 输出 JSON。配置校验：`python3 -I setup/scripts/model_config.py validate config/models.json --transport alma`。

新 lane 调用 `resolve` 前先完成 `gate-state-machine.md` 的实施前置检查；返回 `action: create` 时冻结 overlay 写入 registry，
`request.model` 传给 Task tool 的 `model` 参数。Subagent 入口在真实调用前执行；返回 `action: wait` 时保持 blocked。

## 创建

先从宿主读取当前 thread 的实际 model/source，用 `alma_gate.py coordinator` 记录；
推荐配置允许用户覆盖，Unknown 或偏离推荐值本身不阻断创建或恢复。

1. implementation 新 lane 先回读 canonical gate-state-machine 的实施前置证据，再按上节调用 `resolve`；
   非零退出不得创建 Task，把通过后的 overlay（含配置路径、direct_target 和来源）持久化到 registry，handoff packet 传其
   绝对路径/字段与当前请求值。解析并持久化 coordinator thread ID。
   packet 填入真实 coordinator 坐标、repo 外 lane registry 绝对路径与本文件绝对路径作为 Terminal 回传合同。
   非 implementation artifact 根据工作内容调用 `model`（planning/research/prototype），保存 target/config_path 与模型请求。
2. **Execution Worktree 由 coordinator 创建**（coordinator cwd 默认继承给 Task，但 Execution Worktree 隔离更可靠），
   从当前 Integration HEAD 创建，branch prefix 与 task type 一致。packet 传绝对路径，worker 所有命令显式指向该路径。
   派发前核对 Source/Integration Worktree clean，记录快照 `{worktree, head, dirty}`。
3. 构造 Task tool handoff packet（structured JSON）：
   ```json
   {
     "goal": "实现 ticket #123 的登录功能",
     "context": [
       "当前 Integration HEAD: abc123",
       "Execution Worktree: /path/to/worktree（所有命令显式指向该路径）",
       "完整读取 /path/to/ALMA_ROLE_DISPATCH_PACKET.md 并按 output_mode 执行对应章节"
     ],
     "constraints": [
       "只修改 Execution Worktree 内的文件",
       "不修改 Source 或 Integration Worktree",
       "Commit message 使用中文"
     ],
     "deliverable": "一个可 merge 的 commit，实现了 spec 要求的功能",
     "acceptanceCriteria": [
       "所有测试通过",
       "代码符合项目风格",
       "最终回复包含 LANE_DONE <lane_id> 标记"
     ],
     "artifactRefs": [
       "/path/to/ALMA_ROLE_DISPATCH_PACKET.md",
       "/path/to/spec.md",
       "/path/to/execution/worktree"
     ]
   }
   ```
4. 同批 lanes 并发调用 Task tool（**前台模式为默认**，多个 Task 在同一 message 中并发）：
   ```python
   Task(
     agent_id="developer",  # 或 planner/researcher/designer
     description="实现 #123",
     prompt="完整读取 handoff packet 中的 ALMA_ROLE_DISPATCH_PACKET.md 并严格执行。",
     handoff=handoff_packet,
     model="<providerId>:<providerModelId>",  # 来自 resolve/model 的 request.model
     run_in_background=False  # 前台：等待完成；后台：返回 task_id 后需 TaskOutput 轮询
   )
   ```
5. 聚合 readback：前台模式立即获得结果，后台模式记录 task_id。
   模型请求被拒绝时写 setup_blocked 并保留错误；不静默换模型。模型 readback 写 model_evidence（含 self-report 标记），
   Unknown 不冒充请求已落实。
6. 写 base registry + Alma overlay 并精确 readback；Task 已接受 packet 后写 running/awaiting_human。
7. 整批 startup 完成后：
   - 前台模式：等待所有 Task 完成，直接读取结果
   - 后台模式：记录 task_id，用 TaskOutput 轮询或阻塞等待
   已终态的 lane 立即 fan-in，其余在确认 packet 包含回传合同后 Dispatch Handoff。

Testing 和 Review gate 不进入本节创建流程。coordinator 先持久化 gate fixed point 与不可变证据，
再通过 `subagent` 查询取得显式模型参数；Testing 单独读取 work.testing，Review
传 review_scope 取得 review_models，再把参数与 `implementation` 或 `whole-change` scope 交给 owner。两者都只读并在回传后由 coordinator
核验结果。逐票 Integration 也走 subagent 入口，但要求父 Task 可写、active_count 为 0，并只允许
写指定 Integration Worktree；完成后 coordinator 重新读取 HEAD、commit、worktree 状态与 checks。

## Terminal 回传

worker 对 completed 与 blocked 都执行，所有 output mode 共用：

1. 完成持久交付证据，按 canonical `../../delivery-pipeline/references/lane-registry.md` §轻量交接
   组装完整 `FINAL_REPORT_BEGIN` / `FINAL_REPORT_END` 报告；完整指当前分支必需信息与可读证据，
   不复制 packet、检查日志或已知坐标。
2. **最终回复包含 `LANE_DONE <lane_id>` 标记**，coordinator 通过读取 Task output 检测该标记。
   前台模式直接获得结果；后台模式通过 TaskOutput 读取。
3. coordinator 收到标记后，按 registry 核对 worker Task、work item 与 output mode。通知可能早于
   worker 最终回复：此时直接核验报告与 Git/artifact 持久证据。重复通知以 registry 的
   integrated/consumed/closed 状态去重，避免重复 cherry-pick；close_pending 仅恢复 cleanup。
   blocked 进入受阻分支，其余 ready lanes 继续推进；若原因为"实现已保存、审查待完成"，
   coordinator 验证候选 commit 后立即按独立 Review 放行流程接手，不等待用户重复要求。

**完成判据以 Task 状态为准**：`TaskOutput.status == completed` + 持久证据（Git/artifact/registry）才进入 fan-in；
`LANE_DONE` 文本只作辅助定位，单独不构成完成（ADR-0015 实测：worker 可能在真正完成前输出完成字样）。

报告中的 `completed` 是 FINAL_REPORT outcome，不是 registry state，禁止写入 `state: completed`。
核验成功后先写 `terminal`，再按 output mode 写 `integrated` 或 `consumed`；报告为 `blocked` 才写
`blocked`。这样所有成功 lane 都进入下面同一次 fan-in，不会绕过状态机。

## Role-aware Fan-in

### 独立 Review 放行

正式两轴由 coordinator 调用 resolved code-review owner 管理；Alma 壳只传 owner triple、
`review_scope: implementation | whole-change` 与 Review Evidence Bundle；两轴模型从配置读取并作为 review_models 传给 owner。implementation worker 不拥有取消、改写 verdict 或豁免的权限，可保存候选 commit，但
缺独立结论时按 blocked 回传"实现已保存、审查待完成"。修复回原 worker，完成后冻结新 head
并复核；旧 head 的 PASS 不覆盖新代码。

cherry-pick、integrated、关闭实施票之前，coordinator 必须直接读取 reviewer 宿主记录，调用
`scripts/alma_gate.py review`。输入 worktree、worker_id、base_commit、head_commit、resolved owner
triple、review_scope 与 reviews；reviews 必须包含 standards/spec 两轴，每轴包含 reviewer_id、
source（宿主任务/轮次与时间）、status、verdict、verdict_text（原始最终结论）、
blocking_findings（未解决阻断项数）、review_scope、base_commit、head_commit。只有 completed + pass
零阻断项、两轴身份独立且版本匹配才可放行。source 和 verdict 必须由 coordinator 直接核对，
不能复制 worker 提供的"通过凭证"；helper 校验结构和当前 Git 现场，不验证宿主来源真实性，
不是宿主权限沙箱。中断、超时、缺结果、自评和旧版本结论都不能替代 PASS。
用户明确豁免须单列原话、来源、代码版本和 scope，不伪造 helper PASS。

需取消时由 coordinator 记录原因并恢复或重派；已有合适 reviewer 可复用，无需重复建任务。
whole-change Review 同样执行本门禁；旧 lane 已有两轴结果可直接回读核验，无有效结果则补审。

### Output-mode 验收

外层 Task terminal 后读取最终 output（TaskOutput 或直接 Task 返回值）；内部 Testing、Review、Integration 则读取 Task
回传与持久证据。随后按 output mode 验证：

- `commit`：先回读 canonical gate-state-machine 的实施前置证据，缺失则保留现场并阻塞 Integration；要求候选 commit、`implementation` scope、resolved owner、Review fixed point 等于 lane base commit、
  独立两轴 Review Evidence Bundle readback 与 clean/declared dirty state，按 dependency order cherry-pick；
  focused checks 通过后写 integrated。
- `artifact`：验证 tracker/artifact 坐标；无必要 repo 变更时 worktree 必须 clean，写 consumed。
- `checks`：验证 testing 命令/结果且 worktree clean，写 consumed；失败阻塞 review。
- `verdict`：验证 Review fixed point 等于 map registry base commit、Review Evidence Bundle readback、
  resolved owner、`whole-change` scope 与 review verdict/findings 且 worktree clean，写 consumed；
  blocking finding 阻塞 closeout。

非 commit lane 不要求 commit，也不 cherry-pick；unexpected file changes fail closed。

### Worktree 隔离核验

**Task 无 cwd 参数**（ADR-0015 实测：子代理运行在 coordinator cwd），fan-in 前调用 `scripts/alma_gate.py isolation`
核对派发前登记的 Source/Integration Worktree 未被 worker 改动：

```bash
echo '{"guarded":[{"worktree":"/path/to/source","head":"abc123","dirty":{}}]}' | alma_gate.py isolation
```

返回 `action: blocked` 且 `violations` 非空时，fail closed 并保留现场与证据。

## 恢复、Cleanup

- running Task 依靠 Terminal 回传唤醒 coordinator；恢复时先做一次 TaskOutput 快照（非阻塞），
  补收旧 packet 或发送失败遗留的终态报告。显式 monitor/wait 使用阻塞 TaskOutput；快照结束后仍 running 的 lane 按回传合同等待真实通知。
- 旧 running lane 缺回传合同或 coordinator 已更换时，先更新 overlay，再通过 Task resume 发送新的
  coordinator 坐标与 Terminal 回传合同入口；**resume 不保留上下文**（ADR-0015），只复用 task_id，
  coordinator 需在新 prompt 中重新传递全部输入。完成补发后才交接，沿用原 worktree。
- active lane 用 task_id 恢复；Task 消失但持久 evidence 存在时沿 evidence fan-in。
- integrated/consumed 不是 Alma Task 的停靠状态：在同一次 fan-in 内立即标记 lane 为 closed（Alma 无需显式 archive Task）。
  成功写 closed；失败写 close_pending 并保留坐标。关闭 tracker 或派发下一 ready lane 前，
  必须已完成该 close，或已持久化 close_pending 与失败证据；不得静默留下已验收的 active Task。
- commit lane focused checks 失败时 Task 保持未关闭；artifact/checks/verdict lane 证据失败同样保留 Task。

完成标准：外层 roles 有 Task transport 与 close 路径；内部 Testing/Review/Integration 有
Task 请求、运行 readback、output-mode fan-in 与持久证据。Alma overlay、Task/worktree 与
持久证据一致。
