# Orca 与共享 lane registry 合同调研

调研日期：2026-09-12
关联 Wayfinder：[#114](https://github.com/Dimon94/delivery-pipeline/issues/114)
研究票：[#117](https://github.com/Dimon94/delivery-pipeline/issues/117)

> 目标：定义 Orca Run / Task / Dispatch / worker / terminal / worktree 坐标如何映射到现有项目侧 lane registry。本文只记录本机 Orca 1.4.200、版本匹配 skill/reference 和仓库合同可证明的事实；设计建议标记为“推断”，无法从当前证据确定的内容标记为 Unknown。

## 结论

采用共享 lane registry，不建立 Orca 独立 registry：

```text
项目 work item / ticket → 一个 delivery lane → 一个长期 Orca Task
                                              └→ 一个或多个 Dispatch attempt
```

- `Task` 是同一个 work item 的 Orca 执行对象；失败后的 retry 不新建项目 ticket，也不新建语义相同的 lane。
- `Dispatch` 是一次具体执行尝试；每次 retry 都新增 Dispatch，并通过 `retry_of` 指向已证实失败或 stopped 的 attempt。
- `Run` 是当前 Orca coordinator 的命名空间和 inbox，不是项目交付状态机，也不替代项目侧 registry。
- `worker_done` 只结算 Orca Task/Dispatch；不能直接证明 Git、checkpoint、artifact、Integration、testing、review 或 cleanup 已完成。
- 每个活动 lane 最多一个 active writer。terminal、worktree、worker 和 Dispatch 的坐标必须一起持久化，不能由 pane label、聊天摘要或“当前焦点”推断。

## 已证实事实

### Orca runtime 与 capability

本机命令：

```text
orca --version
→ 1.4.200

orca status --json
→ runtime.state: ready
→ runtime.reachable: true
→ runtime.connectionState: connected
→ runtime.appVersion: 1.4.200
```

本次 readback 的相关 capability 包括：

- `orchestration.contract.v1`
- `orchestration.federation.v1`
- `orchestration.federation-control-mail.v1`
- `orchestration.federation-lifecycle-settlement.v1`
- `orchestration.worker-stop-verdict.v1`
- `orchestration.worker-launch-preferences.v1`
- `orchestration.federation-structured-read.v1`
- `orchestration.federation-fleet-snapshot.v1`
- `orchestration.federation-release-archive.v1`
- `terminal.binary-stream.v1`
- `terminal.multiplex.v1`
- `workspace-ports.v1`
- `browser.clientHost.automation.v1`
- `network.browserTunnel.executionHosts.v1`
- `worktree.create-idempotency.v1`
- `worktree.linked-work-item-context.v1`
- `github.markPRReadyForReview`
- `gitlab.updateMR.readyForReview.v1`

这只证明当前本机 runtime 宣布了这些 capability；不证明每个 capability 已经满足 delivery-pipeline 的完整交付合同。不同 execution host 的 capability 仍需在使用前 readback。

来源：本机 `orca --version`、`orca status --json`。

### Run、Task、Dispatch 和 worker

版本匹配命令：

```bash
orca skills get orchestration --references --json
```

返回 references：

```text
coordinator-loop
legacy-contract-migration
low-level-topology
messaging-and-gates
placement-and-remote
recovery-and-cleanup
worker-contract
```

Orca orchestration guide 明确：

- Run 是 durable namespace 和 coordinator inbox；Run 本身不调度、不 placement worker。
- Task 表示 work；Dispatch 是某个 Task 的 authoritative attempt。
- 普通 worker 应使用：

```bash
orca orchestration worker-start \
  --task <task_id> \
  --worktree <explicit-placement> \
  --agent <agent> \
  --json
```

- `worker-start --spec` 可以在一次调用中创建 Task 和 attempt；使用已规划 Task、依赖或 retry 时使用 `--task <task_id>`。
- `--retry-of <dispatch_id>` 必须配合原 Task 的 `--task <task_id>`；retry 不静默继承 placement，必须再次显式给出 `--on`、`--worktree` 和 agent/terminal 选择。
- 失败的 `worker-start` 不应盲目重发；应先读取 receipt 的 `failedStage`、`residualResources` 和 recovery command。

来源：本机 `orca orchestration --help`、`orca orchestration worker-start --help`、`orca skills get orchestration --json` 的版本匹配 guide。

### 等待、消息和 settlement

```bash
orca orchestration check \
  --wait \
  --types "worker_done,escalation,question" \
  --timeout-ms 900000 \
  --json
```

事实：

- `check --wait` 是对 coordinator inbox 的阻塞等待；`--types` 是唤醒条件，不会把返回 Delivery 截成只含这些类型。
- bound Run 会按 FIFO 返回 Delivery；未 `--ack` 前会重放同一批，因此 coordinator 必须先处理整批消息，再 acknowledge。
- worker 发送 `worker_done` 后，Orca guide 规定 Task 和 Dispatch 会自动 settled；不能再以项目“已完成”替代项目侧 fan-in。
- settled worker 必须由 coordinator 选择 reuse、retain 或 release；release 不是 cancellation。
- `worker-list` 的 `projection.liveness` 是 fleet liveness authority；`worker-show` 的 `observation.status` 只是 PTY liveness。二者不一致时不能把 PTY live 当成 worker live。
- `unverifiable` 是缺少证据，不是 stopped。缺少 status、host 不可达、旧 peer 不支持 fleet snapshot 等都不能授权 stop、abandon、retry 或 release。

来源：本机 `/tmp/delivery-orca-orchestration.md`、`/tmp/delivery-orchestration-recovery-and-cleanup.md`；文件由本机 `orca skills get orchestration` 取得。

### Worktree 与 terminal 坐标

`worker-start --help` 公开的 worktree placement 包括：

```text
current | selector | new-child | new-top-level
```

并支持 `--on <saved-environment>` 选择 execution host。新 worktree 默认会创建 agent terminal；`--terminal <handle>` 只用于明确复用已有 terminal。Orca guide 要求新建、复用和 remote placement 都使用明确 selector，不能依赖隐式迁移。

基础 readback 命令：

```bash
orca orchestration worker-list --run <run_id> --json
orca orchestration worker-show --dispatch <dispatch_id> --json
orca orchestration worker-read --dispatch <dispatch_id> --limit 50 --json
orca terminal show --terminal <handle> --json
orca worktree show --worktree <selector> --json
```

`orca worktree rm` 会从 Orca 和 Git 删除 worktree，并在能力允许时尝试删除本地 branch；对无法证明已合并或原先存在的 branch 会保留。该命令不能替代项目侧 cleanup gate。

来源：本机 `orca orchestration worker-start --help`、`orca terminal --help`、`orca worktree --help`。

## Registry 映射建议（推断）

### 保留现有 base，增加最小 runtime 枚举

现有 `skills/delivery-pipeline/references/lane-registry.md` 的 base schema 已有：

- `work_item`、`role`、`output_mode`、`lane_id`、`state`
- `agent`、`model`、`effort` 及其 evidence
- `checkpoint`、`continuation`
- `worktree`、`branch`、`base_commit`、`head_commit`、`integrated_commit`
- `active-writer` 相关的 Herdr 坐标字段
- `dispatch_runtime`、`coordinator_runtime`、`map_run_authority`

最小建议：

1. 共享 base 的 `runtime` / `dispatch_runtime` 允许 `orca` 值；这只是 transport 枚举扩展，不把 Orca 的 Task 状态复制进项目 state machine。
2. Orca 坐标作为独立 transport overlay，和 `skills/delivery-pipeline-orca/` 共置，不把所有 Orca 字段塞进 Herdr/base schema。
3. 采用嵌套 `orca:` overlay，避免 transport 字段散落。最终字段、coordinator 与 mutation 证据的写入时点见 [canonical spec](../specs/2026-09-12-delivery-pipeline-orca.md)，下列七项是研究时确定的最小坐标：

```yaml
orca:
  run_id: <id-or-none>
  task_id: <id-or-none>
  dispatch_id: <id-or-none>
  terminal_handle: <handle-or-none>
  worktree_selector: <selector-or-none>
  execution_host: <environment-id-or-none>
  attempt_index: <integer-or-none>
```

这是 schema 设计建议，不是当前已存在字段；正式形式已在 canonical spec 选定，旧 lane 仍沿原 transport 恢复。

### Cardinality

采用当前项目合同的最小关系：

```text
一个项目 work item / ticket → 一个 lane
一个 lane                  → 一个长期 Orca Task
一个 Orca Task              → 一个或多个 Dispatch attempt
一个 active lane             → 最多一个 active writer
一个 Dispatch attempt        → 一个 worker、一个 terminal、一个 Execution Worktree 坐标
```

retry 追加 attempt，不覆盖原始 attempt；同一个 lane 的 active writer 不因 terminal 暂时不可达而自动转移。

### 证据绑定

- checkpoint 绑定 `lane_id`、work item、runtime、Orca Task/Dispatch 坐标和 Git snapshot；不能只绑定 terminal。
- active writer 绑定当前 Dispatch、worker、terminal、worktree 四元坐标；terminal 消失不自动授权 replacement。
- Git 证据至少包括 worktree path/selector、branch、base commit、head commit、dirty state；项目侧重新读回后才允许 fan-in。
- artifact/checks/verdict 绑定 lane 和 attempt 的 output evidence；`worker_done` 只表示 Orca settlement，不替代 artifact 或 Git evidence。
- `integrated`、`consumed` 和 `closed` 仍由 delivery-pipeline state machine 控制，不直接镜像 Orca Task 状态。

## 恢复合同

| 事实 | 允许动作 |
| --- | --- |
| `live` / active | 继续等待或 bounded read；不新建 writer |
| `exited` 且已有 accepted settlement | 按项目证据决定 reuse、retain 或 release |
| `failed` / `stopped` | 使用同一 Task、显式 placement 和 `--retry-of` 创建新 attempt |
| `outcome_unknown` | 先 inspect，再显式选择 `worker-stop` 或 `worker-abandon` |
| `unverifiable` / host contact loss | 保留现场；不 stop、abandon、retry、release |
| mutation response 丢失 | `request-show`；`pending` 用同一 `--retry-request` 恢复，`absent` 先 inspect，不盲重发 |
| worker_done 已接受 | Orca Task/Dispatch settled；仍需项目侧 Git/checkpoint/artifact/Integration gate |

远程 host、Orca runtime 或本地 coordinator 重启后，先从项目 lane registry 读取稳定坐标，再用 `worker-list --run`、`worker-show --dispatch` 和 worktree/Git readback 对账；不通过当前焦点或最近终端推断坐标。

## Unknown

- 当前 Orca 1.4.200 的完整 JSON receipt schema、所有 status 枚举和每个 capability 的版本向后兼容矩阵：Unknown；实现必须以当前 CLI readback 为准。
- Orca `worker_done` 的最小 payload 与本地 selector/path/branch 已由 [#115 原型](2026-09-12-orca-worker-lifecycle-prototype.md) 验证；项目附加 artifact/checks/verdict 仍由项目 evidence 承担，通用完整 schema Unknown。
- remote/federation 场景的 active-writer 与 cleanup authority 交接：Unknown；留到远程阶段研究，不阻塞 Phase 1 本地链路。
- 是否需要为 Orca 单独增加 checkpoint 字段，还是现有 checkpoint 的 runtime/session 字段足够：Unknown；以消融实验和 prototype 结果决定。

## 证据命令

```bash
orca --version
orca status --json
orca skills get orchestration --references --json
orca orchestration run-create --help
orca orchestration worker-start --help
orca orchestration check --help
orca orchestration worker-list --help
orca orchestration worker-show --help
orca orchestration worker-read --help
orca orchestration request-show --help
orca terminal show --help
orca worktree show --help
orca worktree rm --help
```

## 研究边界

本票没有创建 Run、Task、Dispatch，也没有启动 worker；因此没有把未执行的生命周期字段伪装成运行证据。Prototype #115 负责验证真实 receipt 和 worktree 生命周期。
