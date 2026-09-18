# Herdr → Orca 改造可行性调研

调研日期：2026-09-12

> 调研范围：以本仓库当前 Herdr/CLI 能力为基线，评估 Orca 原生交付编排的可行性。下文保留初期候选方案供追溯；最终已确认三 transport 长期共存，具体设计以 [canonical Orca spec](../specs/2026-09-12-delivery-pipeline-orca.md) 为准，不迁移既有 lane。事实、代码观察、推断与 Unknown 分开记录。

## 结论摘要

**可行，但不是无适配迁移。** Orca 当前公开能力覆盖 worktree、终端、多 agent、浏览器/Design Mode、GitHub/Linear 集成、评论/状态与 CLI 自动化；这些足以承载 Herdr 的“启动—观察—交接—收口”外壳。最大缺口是 Herdr 的 pane/session 生命周期、可靠等待/事件语义、持久 registry/checkpoint、权限边界和可验证 fan-in 并非 Orca 公共材料已证明的等价物。

建议先做一个 **Orca adapter**，保留现有 registry、证据和 gate machine；不要把 Orca UI 状态直接当作完成事实。

## 现有 Herdr 语义

以下是本仓库代码和 skill 定义的直接观察：

1. **Coordinator 拥有调度与 Integration。** 新 lane 需要记录 `coordinator_runtime`、`dispatch_runtime: herdr`，并绑定每个 work item 一个 lane、owner、Execution Worktree/branch、active writer。来源：`skills/delivery-pipeline/SKILL.md:10-26,40-55,82-83`。
2. **完成不是“agent idle”。** `skills/delivery-pipeline/scripts/lane-watch.sh` 使用 `herdr pane read ... --source visible`，匹配 `PREWALK_READY` / `LANE_DONE`；脚本明确说明 CLI agent 回到 idle 不触发 done 事件。来源：`skills/delivery-pipeline/scripts/lane-watch.sh:3-5,16,38-50`。
3. **Watcher 只负责唤醒，不负责授权。** 看到 `LANE_DONE` 后，仍要求 coordinator 从 registry、Git、tracker、artifact 验证持久证据，然后才允许 fan-in、Integration、cleanup；pane 消失和超时进入异常处理，而不是自动视为完成。来源：`skills/delivery-pipeline/scripts/lane-watch.sh:33-50`。
4. **恢复以项目侧 registry/checkpoint 为准。** 现有规则要求 checkpoint 记录 Execution Worktree 的 Git/dirty/index snapshot；没有停止证据、身份不一致、Unknown 或过期 checkpoint 都要保留现场。来源：`skills/delivery-pipeline/SKILL.md:40-50`。

**推断：** Herdr 不是这个交付系统的事实源，而是当前的 dispatch/observation runtime。迁移 Orca 时，最应该复用的是 lane 状态机、registry、checkpoint 和 gate，而不是把 Herdr 命令逐条替换成 Orca 命令。

## Orca 一手能力证据

本机 Orca 版本与运行状态：

- `orca status --json`：app running，runtime `ready` / `reachable`，本机版本 `1.4.200`。
- `orca --help`：存在 `open`、`serve`、`status`、`agent-context`、worktree、terminal、tab、snapshot、browser automation 等命令面。
- `orca agent-context --json`：输出机器可读命令 schema，适合 adapter 做能力探测，而不是硬编码未知命令。
- `orca skills get orchestration --json`：版本匹配的官方运行指南明确把 Orca orchestration 定义为结构化协调层：`Run` 是持久命名空间和 coordinator inbox，`Task` 是工作，`Dispatch` 是一次权威尝试；`worker-start` 可创建 Task 与 attempt，`check --wait` 可等待 `worker_done` / `escalation` / `question`。
- 同一指南明确：heartbeat、可见活动和 TUI idle 只是 liveness，不是 completion；只有 worker 自己发送一次 `worker_done`，或获得正面的 `exited` 证据，才允许 settlement、stop、abandon、retry 或 release。`unverifiable` 是缺失证据，不得按退出处理。
- `orca skills get orchestration --reference references/recovery-and-cleanup.md --json` 进一步定义了 `worker-show`、`worker-read`、`worker-stop`、`worker-abandon`、`worker-retain`、`worker-release` 和 `--retry-request` 的恢复/幂等边界。
- 运行时 capability 列表包含：`orchestration.federation.v1`、`orchestration.contract.v1`、`terminal.binary-stream.v1`、`terminal.multiplex.v1`、`agent-session.structured.v1`、`agent-session.status-feed.v1`、`agent-session.background-task-stop.v1`、`workspace-ports.v1`、`browser.clientHost.automation.v1`、`automation.*` 等。上述 capability 只能证明当前运行时宣称支持这些能力；不自动证明它们与项目 lane 合同等价。

这意味着：**Orca 的控制面比仅有 worktree/terminal 更完整，已经有可直接承接 Herdr watcher/worker 生命周期的原生协调层。** 但本项目的 registry、checkpoint、Git/artifact gate 仍然必须留在项目侧。

公开一手来源：

- [Orca 官方仓库](https://github.com/stablyai/orca/tree/main)：README/仓库说明将 Orca 定位为可运行 Claude Code、Codex、OpenCode、Pi 等 CLI agent 的 IDE，并说明 worktree、多 agent、内置浏览器/Design Mode、GitHub/Linear 等能力。
- 本机版本匹配 CLI 文档：`/usr/local/bin/orca skills get orca-cli --json`、`/usr/local/bin/orca skills get orchestration --json`、`/usr/local/bin/orca skills get orchestration --reference references/recovery-and-cleanup.md --json`。
- 本机 CLI：`/usr/local/bin/orca --help`、`/usr/local/bin/orca agent-context --json`、`/usr/local/bin/orca status --json`。
- 本仓库 Orca 操作规范：`/Users/dimon/.agents/skills/orca-cli/SKILL.md`。

### 目前可以确认的能力

| 能力 | 证据 | 判断 |
| --- | --- | --- |
| durable Run / Task / Dispatch | `skills get orchestration` 的版本匹配官方指南 | **直接可映射**到 coordinator、work item、attempt；仍需把项目 lane_id 绑定到 Dispatch ID |
| worker 启动与 fan-out | `orchestration worker-start`、`task-create`、`task-list --ready` | **直接可映射**；依赖只表达真实顺序，不替代项目 frontier/gate |
| worker 完成/等待 | `worker_done`、`check --wait`、明确的 settlement 规则 | **直接可映射**；仍需把 done 与 Git/artifact/registry 证据联合判定 |
| liveness 与异常恢复 | `worker-list`、`worker-show`、`worker-read`、`worker-stop/abandon/retry` | **直接可映射**；必须保留 `unverifiable`，不能因联系丢失而重试 |
| 幂等 mutation | `request-show`、`--retry-request <id>` | **直接可映射**；可替代 Herdr 侧盲重发保护 |
| worktree 管理 | `orca worktree create/rm/show/list` | **直接映射**，但仍需验证项目命名、基线、cleanup 和并发冲突 |
| terminal 管理 | `terminal create/read/send/wait/stop/close`；运行时 `terminal.*` capability | **直接映射**；`tui-idle` 仍不是完成证据 |
| structured/status feed | `agent-session.structured.v1`、`agent-session.status-feed.v1` | 可作为观察补充，但不能替代 worker_done/退出和项目证据 |
| 多 agent / federation | `orchestration.federation.*` capability | 有希望承载多 lane，但不能仅据 capability 推断远端恢复合同 |
| browser / automation | `browser.clientHost.automation.v1`、`orca snapshot/click/fill/goto/eval` | 可作为测试/验收增强，不是 Herdr 核心依赖 |
| workspace ports | `workspace-ports.v1` | 可帮助端口分配，但隔离和清理语义仍需实测 |
| GitHub/Linear / comments | 官方仓库公开说明与 CLI schema 中相关命令 | 可适配，但权限、字段和审计回读要单独固化 |

## Herdr → Orca 能力映射

| Herdr/交付能力 | Orca 映射 | 结论 |
| --- | --- | --- |
| 隔离 worktree/branch | `orca worktree create` + Git | **直接映射**；保留项目侧命名、基线、cleanup 约束 |
| terminal pane 启动 agent | Orca terminal + CLI agent/session | **适配**；需要稳定 ID 和创建幂等键 |
| prompt/交接 | Orca agent/session/terminal prompt 或 quick command | **适配**；需要 request-id、回读和重复发送保护 |
| pane read / 完成检测 | snapshot、terminal/status feed、退出状态、Git/registry | **重大适配**；不能只依赖 idle 或 UI 状态 |
| checkpoint / registry | 本仓库文件、Git、tracker、artifact | **保留本地实现**；不要把 Orca 内部状态当 canonical registry |
| browser / Design Mode | Orca built-in browser / automation | **可选增强**；默认不能自动执行破坏性动作 |
| PR / issue / comment / status | Orca GitHub/Linear 集成 + 项目现有 gate | **适配**；远程发布仍由独立 authority gate 控制 |
| fan-in / Integration / rebase | Git 原生命令 + 现有 coordinator | **可复用**；Orca 只提供执行容器和观察面 |
| crash/restart recovery | 项目 registry/checkpoint + Orca 状态回读 | **以项目侧恢复为主**；Orca 的完整恢复合同需验证 |

## 关键缺口与边界

### 1. 项目 lane 与 Orca Dispatch 的边界

Orca 的原生协调层已经覆盖 Run/Task/Dispatch、worker_done、等待、liveness、停止、放弃、保留、释放和幂等重试；因此“Orca 是否能做类似 Herdr 的 worker 编排”答案是 **能，且已有原生控制面**。

但它不自动替代本项目的 lane registry 和交付 gate。项目仍需把 `lane_id`、work item、output_mode、Execution Worktree、branch、base/head、checkpoint、artifact 和 active-writer 绑定到 Orca 的 Task/Dispatch 坐标，并以 Git、tracker、artifact、registry 证据决定 fan-in。

### 2. 事件、等待和完成语义

Orca 的版本匹配指南已经证明以下语义：

- `worker_done` 是结构化完成消息；`check --wait` 可等待 `worker_done` / `escalation` / `question`；
- heartbeat、可见活动、TUI idle 和空 wait 都只是观察/检查点，不是完成；
- 只有正面的 `exited`、worker 自己的进程退出观察，或符合规则的最终 transcript 证据，才允许 stop/abandon/retry/release；
- `unverifiable`、联系丢失、没有 status 或旧 peer 能力不足都不能提升为已退出；
- mutation 回执丢失时，应使用 `request-show` 和同一个 `--retry-request`，不能盲目重放。

因此 Orca 原生等待语义可以替代 Herdr 的部分 `lane-watch.sh`，但 **worker_done 仍不是项目交付完成**。项目 adapter 必须把 Orca settlement 与 Git、checkpoint、artifact、registry 的验证串起来。

### 2. 持久化与恢复

Orca 提供 durable Run/Task/Dispatch 和 worker transcript/readback，已比初始仅依据 UI 的判断更强。但公开/版本匹配指南仍不能证明它会持有本项目完整的 lane registry、checkpoint 内容、Git dirty/index 快照、跨版本的项目 gate 或远程发布审计链。

因此必须保留本仓库已有的 registry/checkpoint/artifact。Orca 重启、CLI 不可达或 UI 状态丢失时，系统应能仅凭项目侧坐标进入 `blocked` 或恢复流程；Orca 的 Dispatch ID 作为 transport 坐标，而不是唯一事实源。

### 3. 权限和安全

**Unknown：** Orca token、GitHub/Linear scopes、是否支持 per-agent 最小权限、桌面登录态如何参与 CLI 自动化，需要针对锁定版本进一步取证。

浏览器点击、Computer Use、远程评论、PR 状态修改、合并等都可能是破坏性操作。默认关闭自动发布/合并；所有 remote publication 保留独立 authority gate，并留下操作证据。

### 4. 并发和隔离

worktree 隔离已有公开声明，但以下边界仍 Unknown：

- 同一 repo 的共享文件、端口、缓存和临时目录；
- browser profile 与登录态；
- 同一 issue/PR 的并发评论和状态写入；
- 多 agent/federation 下的取消、重试和 active writer 互斥。

每个 lane 仍应显式分配 worktree、branch、端口和临时目录；active writer 规则不能交给 UI 自己保证。

### 5. 不能承诺的等价物

即使 Orca 原生控制面已覆盖大部分 Herdr worker 生命周期，也不能直接承诺以下项目语义已经等价：

- 项目 registry/checkpoint 与 Orca Dispatch 的一体化持久化；
- 项目级 fan-in、Integration、cleanup 六步与 Orca worker-release 的一体化；
- 完整审计和权限最小化；
- CI/PR 自动发布的独立 authority 语义；
- headless、多租户或远程运行时的全部隔离边界。

## 建议的最小改造路线

### MVP：先做 Orca transport adapter

1. 新增 runtime-neutral `orca` adapter，不改 canonical gate/state machine。
2. 将项目 `lane_id` 与 Orca `run_id` / `task_id` / `dispatch_id` 建立一一对应；registry 先写项目坐标和 Orca 坐标，再启动 worker。
3. 用 `orchestration worker-start`、`check --wait`、`worker-read`、`worker-show` 替换 Herdr 的启动、唤醒、读取和等待；将 `worker_done` 作为观察信号，不直接作为 fan-in 授权。
4. 将 `worker-list` 的 `live` / `exited` / `unverifiable` 与项目 lane 状态映射；`unverifiable` 只进入等待或 blocked，不触发 replacement。
5. 用 `--retry-request` 和 `request-show` 复用 Orca mutation 幂等性；保留本项目 checkpoint、artifact、Git dirty/index、active-writer 验证。
6. 只支持本地 worktree、terminal、orchestration、Git fan-in；暂不接 browser、Computer Use、远程发布。
7. 失败、超时、Orca 重启都进入 `blocked`/可恢复状态；禁止自动重试产生第二个 active writer。

### 分层路线

- **L1 执行：** worktree + terminal + agent CLI。
- **L2 协调：** Run/Task/Dispatch、worker_done、check wait、question/escalation、stop/abandon/retry/release。
- **L3 项目证据：** lane registry、checkpoint、Git/artifact、Integration/cleanup gate。
- **L4 交互：** browser/Design Mode，仅用于测试证据与人工确认。
- **L5 远程收尾：** GitHub/Linear、PR/comment/status；保留 publication authority。

### 最小 adapter 形态

不需要复制一套 Orca 调度器。建议只增加一层映射：

```text
项目 lane registry
  ├─ lane_id / work_item / output_mode / active_writer
  ├─ checkpoint / worktree / branch / base_commit
  └─ orca: run_id / task_id / dispatch_id / terminal_handle
          ↓
Orca orchestration CLI
  worker-start → check --wait → worker-read/show
  worker_done → 项目证据核验 → fan-in/blocked
```

Orca 已有原生 Run/Task/Dispatch 和恢复合同，重复实现 scheduler、message inbox、worker liveness 或 request-id 幂等层都属于不必要的重复。

## 最小验收清单

- 两个 lane 并发创建不同 worktree，确认 branch/base/active-writer 不交叉。
- `worker-start` 创建 Task/Dispatch 后，registry 能精确回读 `run_id`、`task_id`、`dispatch_id` 和 terminal handle。
- coordinator 重启后，仅凭 registry/checkpoint 恢复；`worker-list` 的 `unverifiable` 不会被误判为 exited。
- agent 正常完成、发送 `worker_done`、返回 idle、terminal 消失、超时、Orca 重启各测一次；不能误报 project done。
- `worker_done` 到达后仍必须检查 dirty/index、commit、artifact、comment/status 与 lane 状态。
- 丢失 mutation 回执时用同一 `--retry-request` 恢复，不能生成重复 Task/Dispatch/worker。
- 已停止/失败、Unknown、远程失联分别测试 stop/abandon/retry 的 fail-closed 规则。
- `worker-retain` / `worker-release` 与项目 cleanup 六步不互相越权；release 不能替代 project fan-in。
- 无 GitHub token 时本地执行仍可完成，远程 gate 明确 blocked。
- browser/Computer Use 默认禁用，需显式用户授权并留下操作证据。
- `python3 scripts/validate.py` 保持 canonical 文档门禁通过。

## 下一轮必须补的实测证据

针对锁定的 Orca 版本，至少补跑并保存输出：

```bash
orca --version
orca --help
orca agent-context --json
orca skills get orchestration --json
orca skills get orchestration --reference references/recovery-and-cleanup.md --json
orca worktree --help
orca terminal --help
orca agent --help
orca snapshot --help
orca status --json
```

随后用隔离测试 repo 验证：创建/删除 worktree、`worker-start`、Task/Dispatch 映射、`check --wait`、`worker_done`、`worker-read`、发送/提问/回复、取消、`--retry-request` 回执恢复、Orca 重启恢复、两个 lane 并发以及无远程 token 的降级路径。

## Sources

### 本地一手来源

- `skills/delivery-pipeline/SKILL.md:10-26,40-55,82-83`：coordinator、runtime 路由、registry/checkpoint、lane/active-writer/cleanup 约束。
- `skills/delivery-pipeline/scripts/lane-watch.sh:3-5,16,33-50`：Herdr pane 读取、marker、idle 不等于 done、超时/消失唤醒与证据边界。
- `/Users/dimon/.agents/skills/orca-cli/SKILL.md`：本机 Orca CLI 选择、`skills get orca-cli`、`--help` 和启动约定。
- 本机版本匹配 CLI 文档：`/usr/local/bin/orca skills get orca-cli --json`、`/usr/local/bin/orca skills get orchestration --json`、`/usr/local/bin/orca skills get orchestration --reference references/recovery-and-cleanup.md --json`；其中定义了 Run/Task/Dispatch、worker_done、check wait、liveness、request-id 幂等、worker stop/abandon/retain/release 和远程失联的 fail-closed 规则。
- 本机 CLI：`/usr/local/bin/orca --help`、`/usr/local/bin/orca agent-context --json`、`/usr/local/bin/orca status --json`；调研时版本为 Orca `1.4.200`。

### 官方一手来源

- [stablyai/orca 官方仓库](https://github.com/stablyai/orca/tree/main)：README、仓库源码与公开能力说明。

## 研究限制

本次调研没有修改运行代码，也没有提交或推送。公开材料和当前 CLI schema 对部分 lifecycle、权限、持久化、事件和远程隔离语义仍不充分；这些内容在文中明确标记为 Unknown，不应直接作为实现承诺。
