# Orca 版本匹配 CLI 与 capability contract 调研

调研日期：2026-09-12
关联 Wayfinder：[#114](https://github.com/Dimon94/delivery-pipeline/issues/114)
研究票：[#116](https://github.com/Dimon94/delivery-pipeline/issues/116)

> 目标：为 `delivery-pipeline-orca` 定义版本匹配 skill/reference、Orca CLI schema、capability/readback 和 agent/worktree/恢复边界。本文件只把本机 Orca 1.4.200 的直接 readback 作为事实；设计建议标记为“推断”，未验证内容标记为 Unknown。

## 运行时身份

本机 readback：

```text
orca --version
→ 1.4.200

orca status --json
→ runtime.state: ready
→ runtime.reachable: true
→ runtime.connectionState: connected
→ runtime.runtimeId: 3122f52b-673d-4732-9e80-a066649a5650
→ runtime.appVersion: 1.4.200
```

本机 capability 列表直接宣布了与 delivery-pipeline 相关的项目，包括：

```text
orchestration.contract.v1
orchestration.federation.v1
orchestration.federation-control-mail.v1
orchestration.federation-lifecycle-settlement.v1
orchestration.worker-stop-verdict.v1
orchestration.worker-launch-preferences.v1
orchestration.federation-structured-read.v1
orchestration.federation-fleet-snapshot.v1
orchestration.federation-release-archive.v1
terminal.binary-stream.v1
terminal.multiplex.v1
workspace-ports.v1
worktree.create-idempotency.v1
worktree.linked-work-item-context.v1
browser.clientHost.automation.v1
network.browserTunnel.executionHosts.v1
github.markPRReadyForReview
gitlab.updateMR.readyForReview.v1
```

事实边界：runtime 宣布 capability 只证明本机 runtime 支持或暴露该能力，不证明目标 execution host、当前 worker 或项目交付场景已经满足更高层的 delivery-pipeline gate。远程 worker 必须按 Orca guide 使用 host-scoped readback；不能把本地 capability 列表当成远程能力证明。

## 版本匹配 skill/reference 合同

当前 CLI schema：

```bash
orca skills get <topic> [--full | --reference <name>] [--json]
```

Orca 1.4.200 的 orchestration topic 宣布 references：

```text
coordinator-loop
legacy-contract-migration
low-level-topology
messaging-and-gates
placement-and-remote
recovery-and-cleanup
worker-contract
```

`orca-cli` topic 的 reference 包含 worktree、terminal、browser、automations、publishing 等执行边界。Orca CLI guide 明确：在执行对应 action 前，先读取当前 binary 匹配的 skill/reference；CLI schema 是执行接口，未声明的 flag、field 或 command 不得从旧版本、公开文章或记忆补齐。

**设计建议（推断，按已确认的即时加载决策收口）：** 进入壳先读 compact `orca-cli` / `orchestration` guide；根据当前操作只加载 guide 指定的 reference。同一任务未变化的合同不重复读取。expanded DAG/review 时读 coordinator-loop，消息处理读 messaging-and-gates，失败恢复读 recovery-and-cleanup，远程 placement 才读 placement-and-remote。低层 terminal、browser、automation、publishing 同理。

不要复制这些 reference 的完整正文到项目 skill；Orca skill 应写“先读取版本匹配 reference，再调用 CLI”的入口合同。

## CLI 命令与生命周期事实

### Run / Task / Dispatch

直接 help readback：

```text
orca orchestration run-create --objective <text> [--from <handle>] [--retry-request <id>] [--json]
→ Run 是 namespace/home inbox，不调度、不 placement worker。

orca orchestration task-create --spec <text> [--task-title <text>] [--deps <json_array>] [--parent <task_id>] [--run <run_id>] ...
→ 创建 Task，可挂到已有 Run 和 dependency DAG。

orca orchestration worker-start
  (--task <task_id> | --spec <text>)
  [--on <saved-environment>]
  [--worktree <current|selector|new-child|new-top-level>]
  (--agent <agent> | --terminal <handle>)
  [--model <id>] [--effort <level>] [--retry-of <dispatch_id>]
  [--repo <selector>] [--base-branch <ref>] [--setup <run|skip|inherit>]
  [--run <run_id>] [--retry-request <id>] [--json]
```

Orca orchestration guide 进一步规定：

- `worker-start --spec` 一次创建 Task 和 attempt；
- 规划 fan-out、依赖或已知 Task retry 使用 `task-create` + `worker-start --task`；
- `--retry-of` 必须配合同一 Task 的 `--task`，不会静默继承 placement；
- retry 必须重复明确 `--on`、`--worktree`、`--agent`/terminal；
- `--model` 和 `--effort` 只在使用新 agent terminal 时传递，`--effort` 依赖 `--model`；
- 不能用模型/effort 参数推断实际生效配置，必须比较 receipt 的 `launch.requested` 与 `launch.effective`；
- `worker-start` 返回非零时先读 receipt 的 `failedStage`、`residualResources`、`recovery`，不能盲目重新执行。

### Agent 支持

`orca-cli --full` guide 当前列举已知 TUI agent id，包括：

```text
claude, codex, omp, pi, grok，以及其他已安装 TUI agent
```

但 `worker-start --help` 暴露的是开放的 `--agent <id>`，没有给出稳定、版本独立的完整枚举。实际 receipt 会同时返回：

```json
{
  "launch": {
    "requested": {"agent": "codex", "model": null, "effort": null},
    "effective": {"agent": "codex", "model": null, "effort": null}
  }
}
```

**项目决策：** 不建立 Orca agent 映射表、不将 pi 替换成 codex/claude、不提供 Orca override。启动前用当前 Orca/目标 host 的能力与 agent evidence 验证共享配置；启动后比对 `launch.effective` 与独立 provider readback。新 terminal 的 `--model/--effort` 在原生 coordinator-loop 中只明确讨论 Claude/Codex/Cursor，不能从 TUI agent 列表推出 pi/omp 也支持全部 launch preferences。不能证明所选参数可用时 blocked。

### Worktree / terminal / host

`worker-start --worktree` 的直接 schema 支持：

```text
current | selector | new-child | new-top-level
```

- `current`/existing workspace 仍创建新 terminal，除非显式传 `--terminal`；
- new worktree 默认走 agent-first 创建，并受 `--setup run|skip|inherit` 控制；
- `--on` 只选择 worker execution server，Run 和 coordinator command 仍在当前 server；
- remote `current` 和 `new-child` 无效，必须使用 exact remote selector 或 `new-top-level` + exact repo selector；
- follow-up、read、stop、cleanup 均按 Dispatch ID 路由，不能改用 remote terminal handle；
- execution host 拥有 process、filesystem、transcript、stop 和 cleanup 事实；连接丢失只产生 `unverifiable`，不生成 synthetic exit。

### Wait / message / gate

直接 help readback：

```text
orca orchestration check
  [--terminal <handle>] [--run <run_id>] [--ack <delivery_id>]
  [--unread | --peek | --all] [--types <type,...>]
  [--wait] [--timeout-ms <n>] [--retry-request <id>] [--json]
```

合同：

- `check --wait --types ...` 的 type filter 只决定唤醒条件；返回完整 FIFO Delivery；
- 未 ack 前重复返回同一 Delivery；必须处理整批后再 `--ack`；
- worker address 使用稳定 `dispatch:<dispatch_id>`，不能替换成 terminal handle；
- `send` 的 durable enqueue 不证明对方已读、已开始或已接受；
- worker `ask` 的 timeout 会留下 durable question，coordinator 用 `reply` 恢复；
- gate 仅用于 coordinator-owned Task DAG decision，不拿 gate 替代普通 worker ask。

### Liveness / settlement / cleanup

`worker-list --run <run_id>` 是 fleet liveness / next action 枚举权威；`worker-show` 的 PTY status 只是终端观察。两者不一致时遵循版本匹配 recovery reference 的证据优先级。关键状态不能由 idle、heartbeat、空 read tail、timeout 或连接缺失推断。

安全动作矩阵：

| 观察证据 | 项目可做的 Orca 动作 |
| --- | --- |
| `ready` / positive `live` | 继续 wait 或 bounded read |
| positive `exited` / `failed` / `stopped` | inspect；按项目 gate 决定 retry/stop/abandon |
| accepted `worker_done` | 先持久化消息、待 fan-in 与 terminal ownership 决策并 readback，再 ack；项目 Git/artifact/Integration gate 后才 release/cleanup |
| `outcome_unknown` | 先 inspect，再显式 stop 或 abandon |
| `unverifiable` / host contact loss | 保留现场；不得 stop、abandon、retry、release |
| mutation response 丢失 | `request-show`；`completed` 读 receipt，`pending` 用同一 `--retry-request`，`absent` 先 inspect，不把 absent 当作未执行 |

三次连续失败后 Orca Task dispatch context circuit-break；不能通过新 Run 或无关 Dispatch 绕过。项目侧不再增加第二个 retry counter。

## Phase 1 capability gate

Phase 1 只需要并必须证明：

- 当前本地 Orca runtime `ready` / `reachable` / `connected`；
- 当前 version-matched `orchestration` 与 `orca-cli` guide/reference 可读取；
- 共享 agent/model/effort/mode policy 能转成有效 `worker-start` 参数；
- 每个 worker 的 receipt/readback 证明 Run、Task、Dispatch、effective launch、Execution Worktree、terminal 坐标；
- coordinator 能进行 FIFO wait/ack、worker-list/read/show、项目侧 fan-in；
- cleanup 前能按证据执行 worker-release 和 worktree cleanup；
- capability 不足、字段 Unknown、host 不可达时 fail-closed，不 fallback 到 Herdr/Codex App。

以下是后续阶段能力：browser/automation、Orca 原生 GitHub/Linear 联动、artifact publication、remote federation/SSH、多执行主机、PR/MR ready/merge/remote closeout。Phase 1 仍通过项目既有 `gh` 合同完成必需的 map/spec/ticket 创建与状态转换；不能把这些基础 tracker 动作延期。

## 安装与 discovery 的补充只读证据

收口时重新执行 `orca --version` 仍为 1.4.200。`orca agent-context --json` 宣布：

- `skills install`/`update` 只操作 bundled skill registry，经 community skills CLI 执行；不据此假设任意自定义 skill 都可用 `--skill` 安装。
- `skills installed --json` 返回已发现 skill selectors，不读取内容；`skills share` 使用 exact selector 且要求原生分享权限。
- 实际 `skills installed --json` 的 `.result` 内条目包含 `id`、`name`、`providers`、`sourceKind`、`sourceLabel`。本机发现已有 delivery-pipeline、App、setup，以及 orca-cli/orchestration；来源包括 Codex home 与 Agent skills home。

设计推断：扩展既有软链 installer 并以 exact installed selector + agent owner realpath 双重回读，足以作为新入口 discovery 验收接缝；新 Orca 壳尚未创建，实际安装验证仍为 Unknown。跨 host version pin 也未验证。没有执行 install/update/share 或发布。

## Unknown

- Orca 当前完整 capability 版本兼容矩阵；
- worker-start 对所有 agent id 的稳定闭集；
- `launch.effective` 是否总能返回完整 model/effort，尤其是远程 host；
- `worker_done` payload 是否允许可靠承载项目 artifact/checks/verdict 字段；
- 远程 capability negotiation 的最小实现字段；
- runtime restart 后 Run binding 的自动恢复边界；
- skill install/discovery 在不同 Orca host 的持久化和版本 pin 语义；
- GitHub/Linear、artifact、browser 和 PR/MR 相关 mutation 的项目侧证据合同。

## 一手证据命令

```bash
orca --version
orca status --json
orca agent-context --json
orca skills get orchestration --full
orca skills get orca-cli --full
orca orchestration run-create --help
orca orchestration task-create --help
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

本研究没有创建或修改 canonical skill、manifest 或项目 lane registry。除 #115 明确标记的原型外，不把未执行命令、公开文档推断或 capability 宣布伪装成项目交付证据。
