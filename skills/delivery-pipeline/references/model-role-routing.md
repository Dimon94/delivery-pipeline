# 模型角色路由

本文件是 CLI/Herdr 主干的配置 schema、六角色定义、agent adapter 与验证规则的唯一定义点。
worker 调度只读本配置；Coordinator 是当前调用会话，不在配置中。

## 配置

路径：`~/.config/delivery-pipeline/model-roles.json`。

schema version 2；六个角色全部必填，每个角色都必须具有非空 `agent`、`model`、`effort`：

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

skill 与 reference 不提供默认 agent/model/effort。有效配置必须同时满足：顶层只有 `version` 与
`roles`；roles key 与六角色精确相等；每个 role object 只有 `agent`、`model`、`effort`；agent 属于
`pi|codex|claude`；三字段非空且命中本机 evidence。任一条件失败都阻塞 dispatch并在当前会话运行
`delivery-pipeline-setup`；不静默回落。

## 角色映射

| 角色 | 管辖工作 |
|---|---|
| `planning` | AFK discovery、research、to-spec、to-tickets 等 gate worker |
| `design` | design implementation、grilling、prototype 等 HITL lane |
| `frontend` | frontend implementation |
| `backend` | backend 与无法归入 design/frontend 的 implementation |
| `testing` | execution graph 清空后的 whole-change checks / test lane |
| `review` | testing 通过后的 code-review lane |

当前 coordinator 会话不属于任何 worker 角色；它使用启动时已经选择的 agent/model。

配置只绑定 lane 启动参数（见下文 Dispatch 验证）。Lane 启动后用户在 worker pane 中改
model/effort 属正常操作：coordinator 不做运行中或 fan-in 的 pane model 对账，不把 pane 实际
model 与 registry 不符当作 setup 失败，不因此重建 lane、回写配置或拒收交付；fan-in 只验收持久
交付证据。

## Agent Adapter

### pi

- runtime：`herdr-pi-pane`
- model evidence：`pi --list-models`
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
  - 显示名：对应的 `ANTHROPIC_DEFAULT_*_MODEL_NAME`
  - effort：`CLAUDE_CODE_EFFORT_LEVEL`
- 启动参数：

```bash
herdr agent start "$agent_name" --kind claude --pane "$pane_id" -- \
  --model "$model" --effort "$effort" --dangerously-skip-permissions
```

Claude env 候选是本机可配置选项的证据。Setup 只允许从这些 `*_MODEL` / `ANTHROPIC_MODEL` /
`CLAUDE_CODE_SUBAGENT_MODEL` 候选中选择；字段不存在时不能把该 Claude model 分配给 role。

## Dispatch 验证

1. 读取 role entry并验证三字段非空。
2. `command -v <pi|codex|claude>` 验证 agent binary。
3. 按对应 evidence 验证 model/effort；Codex 必须匹配 catalog，pi 必须匹配 list-models，
   Claude 必须匹配 settings.json env 候选与 CLI effort 枚举。
4. registry 在启动前写 role、output_mode、agent、model、effort、model_evidence、runtime 与 permission mode；
   精确 readback 后才能启动 worker。
