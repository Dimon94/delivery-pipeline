# 模型角色路由

本文件是 CLI/Herdr 主干的配置 schema、agent adapter 与验证规则的唯一文档定义点。
worker 调度只读本配置；Coordinator 是当前调用会话，不在配置中。

## 配置

路径：`~/.config/delivery-pipeline/model-roles.json`。

schema version 2 仍然受支持；六个角色全部必填，每个角色都必须具有非空 `agent`、`model`、`effort`。
version 3 是显式执行计划扩展：它保留相同六角色和三字段，并新增 `execution`。旧 version 2
配置只沿原有一次启动行为运行，不隐式开启分阶段，也不迁移已有 lane。

```json
{
  "version": 2,
  "roles": {
    "planning": { "agent": "<pi|codex|claude>", "model": "<native-model-id>", "effort": "<native-effort>" },
    "design":   { "agent": "<pi|codex|claude>", "model": "<native-model-id>", "effort": "<native-effort>" },
    "frontend": { "agent": "<pi|codex|claude>", "model": "<native-model-id>", "effort": "<native-effort>" },
    "backend":  { "agent": "<pi|codex|claude>", "model": "<native-model-id>", "effort": "<native-effort>" },
    "testing":  { "agent": "<pi|codex|claude>", "model": "<native-model-id>", "effort": "<native-effort>" },
    "review":   { "agent": "<pi|codex|claude>", "model": "<native-model-id>", "effort": "<native-effort>" }
  }
}
```

version 3 只为 implementation role（`design`、`frontend`、`backend`）提供分阶段选择；`planning`、
`testing`、`review` 继续使用 role triple。`execution` 的 key 必须精确为三个 worker agent，且每个
agent 都必须显式填写 `default_mode`（`staged` 或 `direct`）以及 `starting`、`execution`、
`direct` 三组 `model` + `effort`：

```json
{
  "version": 3,
  "roles": { "...": "沿用 version 2 的六角色对象" },
  "execution": {
    "pi": {
      "default_mode": "staged",
      "starting": { "model": "<native-model-id>", "effort": "<native-effort>" },
      "execution": { "model": "<native-model-id>", "effort": "<native-effort>" },
      "direct": { "model": "<native-model-id>", "effort": "<native-effort>" }
    },
    "codex": {
      "default_mode": "direct",
      "starting": { "model": "<native-model-id>", "effort": "<native-effort>" },
      "execution": { "model": "<native-model-id>", "effort": "<native-effort>" },
      "direct": { "model": "<native-model-id>", "effort": "<native-effort>" }
    },
    "claude": {
      "default_mode": "direct",
      "starting": { "model": "<native-model-id>", "effort": "<native-effort>" },
      "execution": { "model": "<native-model-id>", "effort": "<native-effort>" },
      "direct": { "model": "<native-model-id>", "effort": "<native-effort>" }
    }
  }
}
```

示例中的空对象只表示省略重复字段；实际配置不能省略 `model` 或 `effort`，也不能写
`Unknown`。setup 只有在每个模型、effort 命中本机 evidence 且对应 binary 存在时才写入并 readback。
Pi/Codex/Claude 的 staged 起步均通过 `delivery-pipeline-setup/scripts/model_config.py start`
进入既有 Herdr caller。停止现场完成 registry persist/readback 后，通过同一入口的
`resume --request <payload.json>` 复用现有 adapter：Pi 的 `scripts/pi_adapter.py` 生成原 session
`/model`、`/thinking` TUI 命令；Codex 的 `scripts/codex_cli_adapter.py` 生成精确 session resume；
Claude 使用下方的 staged continuation adapter。不得静默降级 direct。

Pi/Codex payload 精确包含 `runtime`、`checkpoint_path`、`request`、`observation`、`evidence`。
request 是已持久化的 canonical continuation request；observation 必须匹配 checkpoint 身份，
确认 ready/stop evidence、writer/coordinator 停止且原 session 可恢复；evidence 使用下方归一化格式。
入口读回 checkpoint/Git、核验停止现场与 intent，并验证目标能力，再返回原生计划。
Claude payload 继续遵循现有 adapter 合同。该入口不发送请求，不替代 coordinator 的 registry、
发送 lease 或 runtime readback；Pi 计划由原 pane 的 TUI apply 接缝应用并读回。

setup/dispatch 可把实时探测归一化为 `{ "pi|codex|claude": { "binary": true,
"models": { "<model>": ["<supported-effort>"] } } }`，交给
`model_config.py resolve ... --output-mode commit --evidence`。
缺 evidence、binary、model 或所选 model 不支持该 effort 时返回阻塞；没有 evidence 的计划只能解析，不能生成启动请求。version 2 的 `legacy-config`
仅保留 schema/一次启动兼容，实际 startup 同样必须传入当前 evidence。
`model_config.py freeze ...` 输出同一冻结 overlay，coordinator 将其写入既有 packet 与 lane registry 后
必须用 `verify_overlay` 精确 readback 校验；staged 完整包含 starting/execution/direct 三组
model/effort，缺项、空值或不匹配 fail-closed；它不是第二套配置或 registry truth。

skill 与 reference 不提供默认 agent/model/effort。有效 version 2 配置顶层只有 `version` 与 `roles`；
有效 version 3 配置再增加 `execution`；两者的 roles key 与六角色精确相等；每个 role object 只有
`agent`、`model`、`effort`；agent 属于
`pi|codex|claude`；三字段非空且命中本机 evidence。任一条件失败都阻塞 dispatch并在当前会话运行
`delivery-pipeline-setup`；不静默回落。

## 角色映射

选择或配置 role 时读取 `frontier-lanes.md` 的 Role Binding 表；该表统一定义工作、role 与 output mode。

当前 coordinator 会话不属于任何 worker 角色；它使用启动时已经选择的 agent/model。

配置只绑定 lane 启动参数（见下文 Dispatch 验证）。解析入口必须明确传 `output_mode: commit` 才能
消费 implementation 阶段计划；缺失或其他 output mode 保留 role 的旧行为。新 implementation lane 的执行计划选择顺序为
本票 → map → 用户配置（分别读取本票明确选择、map 已持久化选择、version 3 用户配置）；解析出的 mode、source、agent、
starting/execution/direct model 与 effort 必须冻结到 packet 和既有 lane registry，再启动 worker。
ticket/map 缺项时继续按下一层选择；非法 mode、缺失计划或能力 evidence 不匹配直接阻塞。
已有 lane 只按 registry 恢复，不重新解析新配置。

配置只绑定 lane 启动参数。Lane 启动后用户在 worker pane 中改
model/effort 属正常操作：coordinator 不做运行中或 fan-in 的 pane model 对账，不把 pane 实际
model 与 registry 不符当作 setup 失败，不因此重建 lane、回写配置或拒收交付；fan-in 只验收持久
交付证据。

## Agent Adapter

### pi

- runtime：`herdr-pi-pane`
- model evidence：`pi --list-models`，记录 provider/model 与 thinking 支持；缺失 binary 或候选记 Unknown。
- 启动参数：

```bash
herdr agent start "$agent_name" --kind pi --pane "$pane_id" -- \
  --approve --model "$model" --thinking "$effort"
```

`--approve` 信任 fresh Execution Worktree 的 project-local files，纳入
`trusted_execution_bootstrap`；registry 写 `agent_permission_mode: approve`。

### Codex CLI

- runtime：`herdr-codex-pane`
- model evidence：`codex debug models` 的 `models[].slug` 与
  `supported_reasoning_levels[].effort`
- 启动参数：

```bash
herdr agent start "$agent_name" --kind codex --pane "$pane_id" -- \
  --model "$model" -c "model_reasoning_effort=\"$effort\"" \
  -s danger-full-access -a never
```

### Claude CLI

- runtime：`herdr-claude-pane`
- model evidence：`~/.claude/settings.json` 的 `env`：
  - 候选值：`ANTHROPIC_DEFAULT_FABLE_MODEL`、`ANTHROPIC_DEFAULT_HAIKU_MODEL`、
    `ANTHROPIC_DEFAULT_OPUS_MODEL`、`ANTHROPIC_DEFAULT_SONNET_MODEL`、
    `ANTHROPIC_MODEL`、`CLAUDE_CODE_SUBAGENT_MODEL`
  - 显示名：对应的 `*_MODEL_NAME`
  - effort：`CLAUDE_CODE_EFFORT_LEVEL`
- 启动参数：

```bash
herdr agent start "$agent_name" --kind claude --pane "$pane_id" -- \
  --model "$model" --effort "$effort" --dangerously-skip-permissions
```

Claude env 候选是本机可配置选项的证据。Setup 只允许从这些 `*_MODEL` / `ANTHROPIC_MODEL` /
`CLAUDE_CODE_SUBAGENT_MODEL` 候选中选择；字段不存在时不能把该 Claude model 分配给 role。

### Claude staged continuation adapter

`scripts/claude_adapter.py` 只消费已由 `continuation.py` 核验并持久化的 request，先读回
checkpoint 与当前 Execution Worktree 的 Git/dirty snapshot，再核对 runtime、原 session、旧
writer/coordinator 已停止、staged starting 阶段和 continuation intent。它还要求 TUI 探测明确为
`unavailable`/`unreliable`、Claude CLI effort 枚举含目标值，才生成 Claude 原生接续计划：使用
精确原生 session 的 `--resume <session-id>`，并传递冻结的 `--model` 与 `--effort`；计划明确禁止
`--fork-session`。它不把 requested model/effort 当作实际运行值，`tool_acceptance`、
`actual_model` 与 `actual_effort` 初始均为 `Unknown`，必须由原生新轮的接受、session、turn、
实际 model/effort 读回分别填充。Herdr/TUI 不可见时，只能使用这个有界原生 resume 接缝并保留
现场，不能猜最近会话、静默降级或替代 runtime。

配置仅作为新 lane 的前置 gate；既有 lane 的恢复与 replacement 使用
`dispatch-runtime-routing.md` 的“恢复与切换”。

## Dispatch 验证

1. 读取 role entry并验证三字段非空。
2. `command -v <pi|codex|claude>` 验证 agent binary。
3. 按对应 evidence 验证 model/effort；Codex 必须匹配 catalog，pi 必须匹配 list-models，
   Claude 必须匹配 settings.json env 候选与 CLI effort 枚举。
4. registry 在启动前写 role、output_mode、agent、model、effort、model_evidence、runtime 与 permission mode；
   精确 readback 后才能启动 worker。

直接启动参数按 agent 映射：pi 使用 `--approve --model <model> --thinking <effort>`，Pi staged
起步同样通过 `scripts/pi_adapter.py` 生成该参数；Codex 使用
`--model <model> -c model_reasoning_effort="<effort>" -s danger-full-access -a never`，Claude
使用 `--model <model> --effort <effort> --dangerously-skip-permissions`。这些参数由冻结的
`direct` 计划（或 version 2 legacy role triple）提供，不从 coordinator 模型推断。分阶段计划
在 adapter 具备前没有启动请求；不得把起步模型的请求回显当成执行模型已运行。
