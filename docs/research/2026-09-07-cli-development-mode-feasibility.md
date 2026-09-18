# CLI 开发模式可行性调研（Pi、Claude Code、Codex CLI）

调研日期：2026-09-07（本机 CLI 版本与官方文档均以此日为准）

## 结论

可以实现与 Codex App #94 相同的“同一流程内调度、按阶段切换模型、可恢复续跑”能力，但三种 CLI 的接入面不同：

- **Pi：可行度高。** 原生保存 session，支持精确 session ID、恢复、fork；TUI 内 `/model` 和 `/thinking` 可即时切换，且有 `--mode json` 与 `--mode rpc` 供外部编排。
- **Claude Code：可行度高。** 原生保存 session，`--resume <session-id>` 或 `/resume` 续接同一 session；`/model`、`/effort` 支持当前会话切换，`-p --output-format stream-json` 可用于无 TTY 编排。
- **Codex CLI：可行度中高。** `codex resume` / `codex exec resume` 能以 session ID 续跑，`--model` 与 `model_reasoning_effort` 能为续跑显式指定模型和 effort；`codex exec --json`、`app-server` 提供事件/协议接口。但 JSONL 的 `thread.started` 当前只保证给出 thread ID，实际生效模型和 effort 的可回读、事件 schema 稳定性需要在实现时封装并验证。

因此，建议开一个**小型决策地图**，只收口三个跨 runtime 的不可逆边界：

1. 各 runtime 的模型/effort 政策是由本地 CLI 配置驱动，还是由调度器在每次启动/续跑时显式覆盖。
2. session ID、恢复命令和 TUI/后台 transport 如何映射为统一 lane identity。
3. 如何产生“请求模型、实际模型、effort、runtime 版本、session ID、终态事件”的持久 receipt。

不建议重做已有 Herdr 调度主干，也不应直接扩展旧的 Pi watcher；先以当前 #50 的真实实现基线为首个地图决策项。#50 当前候选代码基线在本 checkout 与远程分支中均为 **Unknown**，不能把 issue 描述当作已落地实现。

## 本机版本与 help 证据

在仓库根目录执行以下只读命令，未启动模型推理：

```text
pi --version       -> 0.85.0
claude --version   -> 2.1.259 (Claude Code)
codex --version    -> codex-cli 0.153.0
```

关键本机 help：

- `pi --help`：`--model`、`--thinking`、`--models`、`--continue`、`--resume`、`--session`、`--session-id`、`--fork`、`--mode json|rpc`。
- `claude --help`：`--model`、`--effort`、`--continue`、`--resume`、`--session-id`、`--fork-session`、`--print`、`--input-format stream-json`、`--output-format stream-json`、`--bg`、`attach`、`logs`、`stop`。
- `codex resume --help`：按 UUID/名称恢复，`--last`，`--model`，可附带 prompt。
- `codex exec resume --help`：同样支持 UUID/名称、`--last`、`--model`、`--json`；`codex exec --help` 另有 `--ephemeral`、`--output-last-message`、`--thread-source`。

这些命令仅读取版本和帮助文本；未使用 API key、OAuth 或订阅额度执行任务。

## 能力矩阵

| Runtime | 调度/自动化入口 | session 身份与恢复 | 会话内模型/effort | 事件与恢复证据 | 主要限制 |
|---|---|---|---|---|---|
| Pi 0.85.0 | `pi -p`；`--mode json`；`--mode rpc`；外部可包在 Herdr pane | session 文件按工作目录保存；`--session <path|id>`、`--session-id <id>`、`--continue`、`--resume`；`--fork` 新建 session | `/model` 换模型；`/thinking` 换 thinking level；启动参数为 `--model`、`--thinking`；`--models` 限制 Ctrl+P 候选 | 官方 usage 明确 session 自动保存、`/session` 展示文件和 ID、`/tree`/`/compact` 可恢复上下文；RPC 文档是 stdin/stdout 控制面 | Pi 核心刻意不内置 sub-agent、后台 bash、权限弹窗和 MCP；多角色/后台调度需扩展或 Herdr；实际 RPC 事件和“切换后生效模型”尚未在本机启动验证 |
| Claude Code 2.1.259 | 交互 TUI；`-p`；`--output-format stream-json`；`--bg` + `attach/logs/stop` | session 绑定项目目录并持续写本地 JSONL；`--continue` 最近会话；`--resume <id/name>`；`--session-id` 指定新会话；`--fork-session` 恢复时复制为新 ID | `/model [model]` 当前 session 换模型；`/effort` 或 `--effort` 设置 effort；支持 `low/medium/high/xhigh/max`（具体可用级别按模型降级） | 官方 sessions 文档明确恢复沿用同一 session ID 并追加消息；`stream-json`、partial message、hook event flags 可供编排；`--no-session-persistence` 会关闭恢复 | 切换模型会导致下一请求重读完整历史并失去该模型的 prompt cache；`max` 为当前 session 级别；同一 session 在两个终端同时恢复会交错写 transcript；stream-json 完整 schema 与实际模型回读尚未本机验证 |
| Codex CLI 0.153.0 | `codex exec`；`codex exec --json`；实验性 `codex app-server`（stdio/unix/ws） | `codex resume [SESSION_ID]`、`--last`；`codex exec resume [SESSION_ID]`、`--last`；官方 app-server 为 `thread/start`、`thread/resume`；thread ID 是持续身份 | 新建/续跑均可 `--model`；官方 config 的 `model_reasoning_effort = minimal|low|medium|high|xhigh`；TUI 也支持模型/effort 操作（CLI 文档首页显示 model 行） | `exec --json` 事件含 `thread.started`、`turn.started`、`item.*`、`turn.completed`、`turn.failed`、`error`；`thread.started.thread_id` 可用于后续恢复；app-server resume 默认可恢复 persisted model/effort，显式 model/config override 会覆盖 | 当前 `exec --json` 的官方源码定义中 `thread.started` 只保证 `thread_id`；模型和 effort 不一定随 JSONL 事件回传；事件 schema 没有统一版本标记，消费者需防升级；`app-server` 仍标为 experimental |

## Pi：官方能力

官方 [Pi usage 文档](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/usage.md) 明确：

- `/model` 切换模型，`/thinking` 切换 thinking level；启动参数对应 `--model`、`--thinking`，`--models` 可限制循环候选。
- session 自动保存到 `~/.pi/agent/sessions/`，按工作目录组织；`--continue` 继续最近 session，`--resume` 选择 session，`--session` 指定文件或 ID，`--session-id` 指定精确项目 session ID，`--fork` 派生新 session。
- `/session` 展示 session 文件和 ID，`/tree` 可在 session 树中跳转，`/compact` 可压缩历史。
- `--mode json` 输出 JSON lines，`--mode rpc` 通过 stdin/stdout 运行 RPC；这给外部 coordinator 一个无需模拟键盘的入口。

官方文档还明确 Pi **不内置** sub-agents、后台 bash、权限弹窗、plan mode、to-dos 或 MCP；这些行为放在扩展/包或外部 tmux 等工具中。因此 Pi 适合作为 Herdr 的 worker transport，但“多角色调度”仍由现有主干/扩展负责，不应假设 Pi 自己拥有 #94 的 coordinator 能力。

来源：

- [Pi usage](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/usage.md)
- [Pi RPC mode](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/rpc.md)
- [Pi model documentation](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/models.md)

## Claude Code：官方能力

官方 [model configuration 文档](https://code.claude.com/docs/en/model-config) 明确 `/model` 可在当前 session 选择模型，`/effort` 或 `--effort` 设置 effort。文档列出 `low`、`medium`、`high`、`xhigh`、`max`，并说明模型不支持某级别时会落到该模型支持的最高较低级别；`max` 只作用于当前 session（除非由环境变量设置）。

官方 [commands 文档](https://code.claude.com/docs/en/commands) 明确 `/model` 和 `/effort` 在交互 session 中可用，`/resume` 可按 ID 或名称恢复；模型切换在已有输出时要求确认，并从下一响应生效。

官方 [sessions 文档](https://code.claude.com/docs/en/sessions) 明确：

- session 绑定项目目录，持续写本地 transcript；`claude --continue` 恢复当前目录最近会话，`claude --resume <session-id>` 恢复精确 session。
- 恢复会在**同一 session ID** 下追加消息；`--fork-session` 或 `/branch` 才会创建新 ID。
- `claude -p` 或 Agent SDK 创建的 session 不出现在普通 picker，但仍可用 session ID 恢复。
- `--no-session-persistence` 会关闭落盘，从而不能恢复。
- 同一个 session 在两个终端同时恢复时，消息会交错进入同一 transcript；调度器必须对 lane 做单写者约束。

官方 [prompt caching 文档](https://code.claude.com/docs/en/prompt-caching) 说明切模型会让下一请求失去原模型的 cache 命中并重读整个 history；这不是 session 丢失，但必须进入模型切换的成本/事件记录。

`claude --help` 还提供 `--print`、`--input-format stream-json`、`--output-format stream-json`、`--include-partial-messages` 和 `--include-hook-events`，以及 `--bg` / `attach` / `logs` / `stop`，所以可以做非 TTY worker 和后台生命周期控制。当前研究没有启动 Claude 任务确认 stream-json 的完整事件字段和“provider 实际模型 ID”回读，记为 **Unknown**。

来源：

- [Claude Code model configuration](https://code.claude.com/docs/en/model-config)
- [Claude Code commands](https://code.claude.com/docs/en/commands)
- [Claude Code sessions](https://code.claude.com/docs/en/sessions)
- [Claude Code prompt caching](https://code.claude.com/docs/en/prompt-caching)
- [Anthropic CLI reference](https://docs.anthropic.com/en/docs/claude-code/cli-usage)

## Codex CLI：官方能力

本机 `codex resume --help` 和 `codex exec resume --help` 均显示按 session UUID/名称恢复、`--last` 选择最近 session，并允许 `--model` 显式覆盖。`codex exec --help` 提供 `--json` JSONL、`--ephemeral`、`--output-last-message`；`codex app-server --help` 提供 stdio、Unix socket 和 WebSocket transport，但仍标记为 experimental。

官方 [Codex config reference](https://developers.openai.com/codex/config-reference/) 定义：

- `model_reasoning_effort`：`minimal | low | medium | high | xhigh`。
- `models.new_thread.model` 与 `models.new_thread.model_reasoning_effort` 仅是新 thread 默认值，显式 `--model` 或 model/reasoning config override 优先。
- `notify` 可配置接收 JSON payload 的命令，可作为外部通知入口，但其 payload 与 `exec --json` 事件并非同一合同。

官方 [app-server README](https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md) 说明 `thread/start` 创建 thread、`thread/resume` 以 thread ID 续接；resume 默认沿用持久化的 model/reasoningEffort，传入 model 或相关 config override 会禁用该默认并采用显式值。这是实现“同一 session 内模型切换”的最清晰协议证据。

官方 `exec` 事件源码 [`exec_events.rs`](https://github.com/openai/codex/blob/main/codex-rs/exec/src/exec_events.rs) 当前定义：

- `thread.started` 首个事件，携带 `thread_id`，该 ID 可用于后续 resume。
- `turn.started` / `turn.completed` / `turn.failed`，以及 `item.started` / `item.updated` / `item.completed` 和顶层 `error`。
- 当前定义的 `ThreadStartedEvent` 只有 `thread_id`，没有 model 或 effort 字段。因此 coordinator 不能把“启动时请求了某模型”当成“实际使用模型”的证据，必须把请求配置、CLI 版本、终态事件和可获得的 provider 信息分别记录。

官方 [Codex CLI 页面](https://developers.openai.com/codex/cli/) 也把 `codex resume` 定位为返回已保存 chat 的入口，并把 CLI 同时定位为可脚本化、可在终端恢复的工作面。

限制与风险：

- `exec --json` 的事件 schema 随 CLI 版本演进；官方源码有事件定义，但当前没有看到稳定的 schema version 字段。适配器必须未知事件可保留、终态以 `turn.completed` / `turn.failed` 判定，并把 CLI 版本写入 receipt。
- app-server 是更适合长期集成的协议面，但官方仍标 experimental；不能把它当作与 Codex App 一致的稳定公共合同。
- 本研究未运行 Codex 推理，未确认当前账户/模型目录对指定 model 和 effort 的实际可用性，也未确认 `codex exec --json` 在当前版本是否回传 provider 实际模型 ID，均为 **Unknown**。

## 对 delivery-pipeline 的落地判断

### 仓库与 tracker 的实际边界

用户已确认：**相同流程，模型按 CLI 配置**。不要求 Claude Code 使用 Astra/Luna/Sol，也不做跨 runtime 会话迁移。模型策略应由显式配置选择，adapter 将已选值传给原生接口，不能静默写死 App 模型。

- [#94 最终验收](https://github.com/Dimon94/delivery-pipeline/issues/94#issuecomment-5568590669)：App 三模式同 task 接续与自动回传已验；完整业务 map Review/Integration 未验。当前源目录含尚未提交的实现。
- 当前 `CONTEXT.md`、`references/model-role-routing.md`、`references/lane-registry.md` 与 `assets/HERDR_ROLE_DISPATCH_PACKET.md` 明确 model/effort 仅启动绑定，worker 不自行换模；registry 缺 CLI 原生 session ID。`scripts/lane-watch.sh` 只处理 `LANE_DONE`，不处理 Prewalk 中间通知。这些路径均位于 `skills/delivery-pipeline/` 下（CONTEXT 除外）。
- [#50](https://github.com/Dimon94/delivery-pipeline/issues/50) 已承载 Herdr Plugin 的 journal/receipt/recovery；[最近审查](https://github.com/Dimon94/delivery-pipeline/issues/50#issuecomment-5550819996) 未通过，安装与诊断缺口由仍 open 的 [#93](https://github.com/Dimon94/delivery-pipeline/issues/93) 处理。其 registry 的 running 是历史记录，不证明当前进程存活。
- #50 记录的 `/Users/dimon/003Tech/worktrees/delivery-pipeline-map-50` 本机不存在，当前 `git worktree list` 未列出它，`git ls-remote --heads origin feature/map-50` 无结果。因此未定位候选代码，不代表代码已丢失或其他主机不存在。
- [#49 收口评论](https://github.com/Dimon94/delivery-pipeline/issues/49#issuecomment-5489435530) 已明确由 #50 取代 Pi Subagents 路线；不能按 #50 正文残留的旧 blocker 重开这条路线。[#47](https://github.com/Dimon94/delivery-pipeline/issues/47) 仍有 Gearshift/schema v3 的旧配置规划，与当前 checkout v2 不一致，需要收口关联，不视为现成能力。

复用既有 lane、owner、单写者、worktree、gate 与 Integration；只补原生 session 坐标、阶段检查点、请求参数和独立运行回读。App helper 含 threadId/hostId 专属字段，不能直接复制到 canonical 主干；通用 Git 检查只在实现时按真实接缝提取，不新建第二套状态机。

### 建议的最小地图

如果开地图，建议三张决策票：

1. **CLI baseline 与 transport**：先定位并验收 #50 的候选代码，确定本次扩展基线；未定位前保持 Unknown，不直接另建替代调度器。然后为三种 CLI 各选一个最小接口，明确 Herdr 可见交互与原生 session 接续的关系。
2. **session/model policy**：规定每个 role 的启动配置、续跑配置、切换时机和 override 优先级；将“请求值”和“运行值”分离，沿用现有事实优先级。
3. **receipt/recovery**：规定首事件、终态、超时、进程退出、重启后恢复和用户确认 gate；不能以进程 `completed` 或单一 `LANE_DONE` 替代用户核验。

完整业务地图的 Review→Integration 端到端验证、Claude/Pi/Codex 的真实账号权限、具体模型可用性、JSON/RPC schema 的当前运行回读，均应作为后续验证票，而不是在本调研中推断完成。

## 未实测清单

- 未启动任何模型推理，未消耗付费额度。
- Pi：未运行 RPC/JSON session，未验证 `/model` 切换后的事件和 session 文件字段。
- Claude Code：未运行 `-p --output-format stream-json`，未验证事件 schema、后台 `--bg` 回传和实际 provider model ID。
- Codex CLI：未运行 `exec --json` 或 app-server，未验证当前账户下模型/effort 的可用性、resume 后显式 override 的实际生效值。
- 未把 #50 的旧 issue 描述视为实现证据；当前候选代码基线为 **Unknown**。


## 本次交付与验证

只新增本调研文档，未改运行行为、配置或 tracker，未提交或推送。`python3 scripts/validate.py` 输出 `prewalk dispatch: pass` 与 `bundle: pass`；`git diff --check` 通过。静态通过不证明 CLI 换模已端到端可用。
