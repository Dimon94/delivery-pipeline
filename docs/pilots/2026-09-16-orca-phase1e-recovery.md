# #124 Phase 1E recovery 验收记录

结论：代码候选可复审；**#124 / Phase 1 仍 blocked**，不是完整功能验收通过。
本次只新增 Orca readback 薄层，复用共享 registry/checkpoint/continuation；未提交、未推进
Integration、未关闭 issue。基线 `3781612c57c6ee83725b91642f16331445061ece`。

## 触达与实现

- `skills/delivery-pipeline-orca/scripts/recovery.py`：retry、response-lost、restart、cancel、
  question 与 staged prepare/lease 的只读门禁，所有返回 `authority: false`、`mutations: []`。
- `recovery_check.py`：最小模拟合同矩阵，复用 canonical continuation 的 Git/checkpoint fixture。
- 真机补测发现 native ask 的 sender 为 `dispatch:<id>`：同步修正 recovery 与既有
  `worker_lifecycle._message`，只接受当前 fleet 中唯一 binding；检查先红后绿。
  checkpoint evidence 按实际路径核对，接受 `/tmp`、`/private/tmp` 与 `./` 的同文件别名，
  不接受带说明后缀的假路径；该检查也先红后绿。
- Orca SKILL、dispatch reference、worker packet 与 `orca-recovery.md` 接入同一 owner；
  `scripts/validate.py` 纳入可执行检查。
- 没有新 registry、dispatcher、project retry counter 或 native capability matrix。

## 可运行检查

```text
PYTHONDONTWRITEBYTECODE=1 python3 skills/delivery-pipeline-orca/scripts/recovery_check.py
python3 scripts/validate.py
git diff --check
PYTHONDONTWRITEBYTECODE=1 python3 /tmp/delivery-pipeline-124-evidence/native-checks.py
```

最小检查先红（新增检查时 helper 尚不存在，`red.log`），后绿；完整 validator 输出
`bundle: pass`。模拟测试覆盖正面 failed/stopped 条件、circuit-break、身份/placement 不一致、
同 worktree 第二 writer、Unknown/host loss、保留 ownership、稀疏 startup receipt、
request completed/pending/absent、原 Run 恢复、question/reply/过期 Dispatch、staged
persist/readback/send lease 重入和过期 checkpoint。
模拟通过**不证明**真实 retry、pending、runtime restart 或 staged 成功。

原始证据目录：`/tmp/delivery-pipeline-124-evidence`；复审/交接时保留该目录。

## Native 与模拟严格分开

固定 binary 为当前 `orca`；runtime `47a2461a-b48d-4a52-9f19-9e578220c19d`。

| 验收项 | 本轮真实观察 | 证据 / 剩余边界 |
| --- | --- | --- |
| 正面失败 | 真实 `worker_done outcome=failed`，fleet worker/dispatch 均 failed | `native-wait-1.json`、`native-fleet-1.json` |
| 同 Task retry | **真实成功**：独立取消探针在同一 Task 先 stopped/exited→retry，再 failed/released/exited→两次 retry，native retryOf 链一致 | `native-stop-probe-stop-1.json`、`native-stop-retry-1.json`、`native-retry-show-1.json`、`native-failure-2-start.json`、`native-failure-3-start.json`、`native-stopped-gate-result.json`；原 user-owned 场地未动 |
| 三次 circuit-break | **Unknown**：同 Task 三次 worker_done failed 均已真实捕获，但每个 native dispatch.failureCount 都是 0，未取得 circuit-break 触发证明 | `native-retry-failed-show.json`、`native-failure-2-show.json`、`native-failure-3-show.json`；不自行增加 project counter，不发第四次 retry 试图绕过 |
| 取消 | **真实成功**：owned/working 时 worker-stop 返回 stopped、closed_agent_terminal、ptyKilled=true，fleet exited/source=worker_stop | `native-stop-probe-stop-1.json`、`native-stop-probe-show-after.json`；原 user-owned worker 的 stop 仍为 alreadySettled/processAction=none，不能把它算作成功 |
| response-lost completed | 原生 workerStart request-show completed，helper 消费原 receipt；coordinator takeover 后仍可读该 receipt | `native-request-completed.json`、`native-request-after-takeover.json`；没有故意破坏网络或伪称丢失响应 |
| request-show absent | 未记录 ID 的只读查询真实返回 absent，不据此重发 | `native-request-absent.json`；不是“原 worker-start 未执行”的证据 |
| pending / 同 retry-request join | **未捕获 / Unknown** | 补测 worker-start 使用 60000ms timeout，但本轮 request ID 在 ready/completed receipt 返回后才可读，未取得 pending 证据；未自造 ID、未伪造响应丢失 |
| coordinator terminal restart | **已证明原 Run 接管**：关闭专用测试 coordinator，创建新 terminal，run-use 同 Run，generation 1→2，原 Task/Dispatch 仍在 | `native-coordinator-close.json`、`native-coordinator-closed-readback.json`、`native-run-use.json`、`native-*-after-restart.json` |
| runtime/app restart | **not-run/Unknown** | `native-environments.json` 没有可用的独立环境；不重启用户 runtime，coordinator terminal restart 不冒充 app restart |
| question / escalation / reply | 本 worker 与 coordinator 原生往返已执行；ask timeout 后按同 message ID resume，最终收到原问题 answer | `question.json`、`question-resume.json`、`question-answered.json`；checkpoint/Task/Dispatch 联合门禁只做了模拟检查，不伪称完整 staged 问题验收 |
| idle / timeout / unverifiable 零 mutation | 模拟矩阵通过；真实 live/user-owned 现场拒绝 retry/cancel，helper 不修改请求、不发 mutation | `native-gate-results.json`、`native-fleet-after-checks.json`；真实 host 失联/unverifiable 注入 **not-run** |
| staged 起步（codex） | **真实完成**：共享模式 gpt-5.6-sol/high 起步、首改/最小检查、canonical 原子 checkpoint、真实 provider session 与 session_meta/turn_context 交叉核验，中间信号后结束当前轮、没有 worker_done | `native-codex-start.json`、`native-codex-checkpoint-v3.json`、`native-codex-binding-v2.json`；session=`01a0a9c4-122b-74c0-b768-f632c8d2cce8`；v1/v2 保留，v3 修正 runtime 与精确 evidence 路径，机械 binding/Git/hash 已通过 |
| staged 同 session 换模 | **Unknown / AC12 边界**：尚未执行 gpt-5.6-luna/max 接续，不以起步成功替代 AC11 | pi transcript 为 provider_unsupported、launch model/effort=null；codex 可证明起步，但 Orca inventory 只有通用 terminal.send，没有专用同 session model/effort/resume 合同，须独立 provider CLI/TUI transport 与 send lease/native request 映射；`native-codex-stage-gate-result.json` 如实 blocked |

这些结果不授权删减 #124 的完整 AC；只证明已经实测的分支及其 fail-closed 行为。
coordinator 已通过原问题 `msg_c0065da3125a` 的 reply 明确选择“按 AC12 收口 Unknown，不临时拼接
未经验证的续传执行器”，见 `native-continuation-boundary-answer.json`。provider normalized
negative evidence 是 caller projection，不是原生 receipt；原始 CLI/provider 证据分开保存。

## 按 issue #124 body 的 AC 收口

| AC | 当前状态 |
| --- | --- |
| 1 | 正面 stopped/failed 同 Task retry 已真实证明；Task、retryOf、agent、Worktree、local host 坐标留证 |
| 2 | 未添加 project counter；三次 failed 的原生 failureCount=0，circuit-break 触发 **Unknown** |
| 3 | completed 消费原 receipt、absent inspect 已核验；pending join 与真实 response lost **Unknown** |
| 4 | 原 Run coordinator 接管已证；完整 runtime/app restart 与现场 registry 接管 **Unknown**，冲突不覆盖 |
| 5 | 机械绑定检查绿，native question/reply 往返与 Dispatch sender 已证；checkpoint 绑定的完整真实问题链 **not-run** |
| 6 | no-mutation 负向矩阵绿；原生 user-owned/live 不重试，真实 host loss/unverifiable 注入 **not-run** |
| 7 | 真机、模拟与 Unknown 分开记录，没有以模拟结果冒充原生成功 |
| 8 | 原生 completed/absent 已证；pending、同 retry-request join **未捕获/Unknown**，ID 丢失路径不盲重发 |
| 9 | codex starting 首改/检查/原子 checkpoint/真实 provider session/Orca evidence/中间停止已证；没有最终 worker_done |
| 10 | checkpoint/Git/hash 与绑定真机核验通过，canonical lease 模拟检查绿；同 session 换模执行 **Unknown**，未滥用 worker-start --terminal |
| 11 | 同 Task retry、取消、coordinator 接管、question 往返已补；至少一条完整共享 staged 成功仍缺，**Phase 1 blocked** |
| 12 | 独立 continuation 协议边界已由 coordinator 确认；下方子票草案已交接，实际建票由 coordinator 负责，未删减本票 AC |

## 隔离场地与保留资源

按 coordinator 明确授权，在 #123 的专用临时 Git repo
`/tmp/dp123-native-CFMF7ki0/repo` 中建立独立测试场地；没有改绑生产 worker，也没写真实
Source/Integration。测试不是重置失败预算：首个 user-owned 场地遇阻即停止；随后 coordinator
明确授权独立取消/重试与 codex staged 探针，仍在同一个测试 Run 中，每条 retry 链始终复用自己的
长期 Task，不用新 Task 恢复原 user-owned lane。

- 测试 Run：`run_efd8885eabcb`
- 测试 Task：`task_0dc0730dd8ab`
- 测试 Dispatch：`ctx_0274ea1adac7`
- Execution Worktree：`/Users/dimon/orca/workspaces/repo/dp124-native-worker`（无文件改动）
- worker terminal：`term_6062298b-1051-4f81-9b5d-760ed239e7a8`，原生标记 user-owned/retained；
  **未强关、未 abandon、未删除 worktree**。
- 原测试 coordinator：`term_8c6f9ab4-b7de-45a5-8566-8ac930acb0d6`，已原生关闭。
- 接管 coordinator：`term_08101711-5e73-4afc-a4f8-91d9136c722a`，已证明接管同 Run；
  验证后随专用 coordinator worktree 原生清理。
- coordinator worktree：`/Users/dimon/orca/workspaces/repo/dp124-native-coordinator`，已用原生
  `worktree rm` 删除；Git branch readback 仅剩 `dp124-native-worker`，未删 retained worker。
  证据：`native-coordinator-worktree-rm.json`、`native-coordinator-worktree-after-rm.json`、
  `native-branches-after-teardown.txt`、`native-worker-after-teardown.json`。

补测场地（当前保留，不隐瞒残留）：

- 取消/重试 Task：`task_60162fd7a1dd`，Dispatch 链
  `ctx_afe371d281e4 → ctx_802d49bee182 → ctx_3d1aaab44502 → ctx_c157b5a6004c`。
  首个 stopped，后三个真实报告 failed，均已正面 exited/released；Worktree
  `/Users/dimon/orca/workspaces/repo/dp124-native-stop-worker` clean。首个 stop 后 archive unavailable
  （`native-stop-initial-release.json`），因此保留现场，不用 force rm 掩盖 archive 缺口。
- codex staged Task：`task_5775063f5c1e` / Dispatch `ctx_dd41ebc26992` / terminal
  `term_33dc4afb-181f-4bc1-bdf5-c02df132b19e`，首段停止后保留同一上下文；Worktree
  `/Users/dimon/orca/workspaces/repo/dp124-native-codex-staged` 含首改文件，保留 checkpoint/dirty，
  不发最终 worker_done、不以 release 冒充阶段接续。
- 专用 coordinator worktree 随补测授权已重建，同 Run 接管 terminal 为
  `term_8aa07bad-50fc-483e-9d98-7d8d661a0936`；当前保留以维持未收口测试上下文。
- 补测共享配置快照：`native-shared-config-current.json`。没有把 codex 作为原 pi lane fallback，
  没有回写用户配置或把新配置应用到既有生产 lane。

生产坐标保持 `run_8f6cb8130244 / task_fa84b6a80577 / ctx_f8ef588af70f`；没有创建第二份生产
Task。另观察到原 lane artifact 的 `coordinator_runtime: pi-cli` 与既有 overlay 合同要求的
`orca-terminal` 冲突，已通知 coordinator，不静默修正外部 registry。

## 依赖子票草案（未建 issue）

标题：Orca Phase 1E continuation：共享 pi 的原生同 session model/effort readback 与 transport。

依赖/关系：本票依赖 #124 的 recovery/checkpoint/lease 薄层；作为 #124 / Phase 1 完整验收的
必需后续项，由 coordinator 统一建票与关联，不据此关闭 #124。

AC：

1. Orca/provider 给出可验证的原 provider session、原 Execution Worktree 与停止/无 writer 证据。
2. 共享配置 pi 起步后，原 session 应用 execution model/effort 并回读；不映射 agent、不降级
   direct、不使用 `worker-start --terminal` 加 model/effort 冒充换模。
3. 同 lane/Task/Dispatch 的请求、接受、新 turn、actual model/effort 各自绑定；复用 canonical
   send lease 与 event overlay，response lost 不盲重发、不另建 journal。
4. 在隔离真机完成 starting 首改/检查/原子 checkpoint/中间信号/停止 → 同 session 接续成功；
   至少一个共享 agent 成功；其余未知能力明确 blocked。
5. 可重复证明 request-show pending 的同 request join/recover 与 active/Unknown/取消零越权
   mutation；补齐 #124 尚未通过的 circuit-break/runtime 恢复证据，不能用模拟结论关闭。

## Review

implementation fixed point 与 HEAD 均为 `3781612c57c6ee83725b91642f16331445061ece`，审查覆盖
本票全部 tracked WIP 与 untracked additions。七文件 Review Evidence Bundle 由实施 worker
在 repo 外物化后交 coordinator；独立 Standards/Spec verdict **待出具**，测试绿不替代复审。
