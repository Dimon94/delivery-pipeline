# 模型角色路由

本文件是 CLI/Herdr 主干 version 3 配置 schema、六角色定义、Bootstrap Gearshift Policy、agent adapter 与验证规则的唯一定义点。worker 调度只读本配置；Coordinator 是当前调用会话，不在配置中。

## 配置

路径：`~/.config/delivery-pipeline/model-roles.json`。

六个角色全部必填，每个角色都必须具有非空 `agent`、`model`、`effort`。`frontend`、`backend` 在 `agent: pi` 时可以额外声明 `bootstrap.model/effort`；普通 `model/effort` 始终是 Role Model，也是 Bootstrap Handoff 的 Target Model。

```json
{
  "version": 3,
  "gearshift": {
    "mode": "opt_in",
    "optInLabel": "bootstrap-handoff"
  },
  "roles": {
    "planning": { "agent": "pi", "model": "provider/planning", "effort": "high" },
    "design":   { "agent": "pi", "model": "provider/design", "effort": "high" },
    "frontend": { "agent": "pi", "model": "provider/frontend-fast", "effort": "high" },
    "backend":  {
      "agent": "pi",
      "model": "provider/backend-fast",
      "effort": "high",
      "bootstrap": { "model": "provider/bootstrap-high", "effort": "high" }
    },
    "testing":  { "agent": "pi", "model": "provider/testing", "effort": "high" },
    "review":   { "agent": "pi", "model": "provider/review", "effort": "high" }
  }
}
```

严格 schema：

- 顶层 key 精确为 `version`、`gearshift`、`roles`；version = 3。
- `gearshift` key 精确为 `mode`、`optInLabel`。
- `mode` 只允许 `off | opt_in | all_eligible`；label 为 1–50 字符且不含控制字符。
- role key 与六角色精确相等。
- 每个 role 有且只有 `agent/model/effort`；只有 frontend/backend 可额外有 `bootstrap`。
- `bootstrap` 有且只有非空 `model/effort`，要求 role agent = pi，且 Source Model 不等于普通 Target Model。
- `opt_in` 或 `all_eligible` 至少存在一个 eligible bootstrap。
- design/planning/testing/review 与非 pi role 禁止 bootstrap。

skill 与 reference 不提供默认 agent/model/effort/bootstrap。任一条件失败都阻塞 dispatch 并在当前会话运行 `delivery-pipeline-setup`；不静默回落。

## Bootstrap Gearshift Policy

| mode | 新 implementation lane 行为 |
|---|---|
| `off` | 所有 role 直接使用普通 `model/effort`；忽略已保存的 bootstrap entry。 |
| `opt_in` | 只有带 `optInLabel` 的 eligible ticket 使用 Bootstrap Handoff。 |
| `all_eligible` | 所有 agent=pi 且具有 bootstrap 的 frontend/backend ticket 使用。 |

Policy 是确定性配置，不调用 LLM 判断风险。`opt_in` 的 ticket label 必须从 tracker 持久状态读回；registry 写 `gearshift_eligibility: ticket-label`，并把原 label 作为独立的 JSON-quoted `gearshift_opt_in_label` 保存，不拼进 YAML scalar。对话中的口头意图不算。配置只绑定首次创建的新 work-item lane。既有 lane 与 replacement 始终按 `lane-registry.md` 恢复，不因 mode、schema 或配置变化迁移；legacy v2 row 的 Gearshift 保持 disabled/none。

Eligible lane 启动时：

1. Source Model = `bootstrap.model/effort`。
2. Target Model = role `model/effort`。
3. Trigger Adapter = `delivery-pipeline/bootstrap-slice`。
4. Adapter 文件由当前 canonical skill realpath 解析为 `adapters/bootstrap-trigger.ts`，只在本 lane 用 `-e` 加载。
5. Pi Gearshift Core 必须已全局安装；`pi --help` 必须暴露 `--gearshift-profile`、`--gearshift-target`、`--gearshift-target-thinking`、`--gearshift-adapter` 与 `--gearshift-arm-authority`。缺失即 `setup_blocked`，不改用首次 edit 或人工模型猜测。
6. Startup Probe 从 `GEARSHIFT_ARMED <json>` 读回完整 Shift ID、`gearshift-shift:<shiftId>` evidence reference、Source/Target、profile 与 Adapter；恢复时可用 `GEARSHIFT_STATUS <json>` 精确对账。截断 ID 或自然语言猜测不算 readback。
7. Bootstrap Checkpoint 通过后 Core Shift 到 Target Model；失败时保留 Source Model、session state、worktree 与 blocker。
8. 恢复同一 Worker session 时，启动命令中的 Source `--model` 不得覆盖已完成 Shift 的 Target，且不得创建第二个 Shift。Gearshift 实际重申 terminal Shift Record model 时必须从 `GEARSHIFT_RESUMED <json>` 对账；若 Shift 后存在明确持久化的 branch-local `model_change`，该意图优先且 Gearshift 不发 `GEARSHIFT_RESUMED`，恢复对账改用 branch model intent + `GEARSHIFT_STATUS <json>` + 既有 Shift Record。

## 角色映射

| 角色 | 管辖工作 |
|---|---|
| `planning` | AFK discovery、research、to-spec、to-tickets 等 gate worker |
| `design` | design implementation、grilling、prototype 等 HITL lane |
| `frontend` | frontend implementation；pi role 可选 Bootstrap Handoff |
| `backend` | backend 与无法归入 design/frontend 的 implementation；pi role 可选 Bootstrap Handoff |
| `testing` | execution graph 清空后的 whole-change checks / test lane |
| `review` | testing 通过后的 fresh code-review lane；永不使用 Bootstrap Handoff |

当前 coordinator 会话不属于任何 worker 角色；它使用启动时已经选择的 agent/model。

配置绑定 lane 启动与已授权 Gearshift route。Lane 启动后用户仍可手动改 model/effort；coordinator 不因 pane model 与 registry 不符重建 lane，但 worker final report 必须记录实际模型历史。只有匹配 registry 的 Gearshift Shift Record 才能声称 Bootstrap Handoff 完成。

## Agent Adapter

### pi（普通 lane）

- runtime：`herdr-pi-pane`
- model evidence：`pi --list-models`
- 启动：

```bash
herdr agent start "$agent_name" --kind pi --pane "$pane_id" -- \
  --approve --model "$model" --thinking "$effort"
```

### pi（Bootstrap Handoff lane）

```bash
herdr agent start "$agent_name" --kind pi --pane "$pane_id" -- \
  --approve --model "$bootstrap_model" --thinking "$bootstrap_effort" \
  -e "$bootstrap_adapter" \
  --gearshift-profile delivery-bootstrap \
  --gearshift-target "$model" \
  --gearshift-target-thinking "$effort" \
  --gearshift-adapter delivery-pipeline/bootstrap-slice \
  --gearshift-arm-authority user
```

`--approve` 信任 fresh Execution Worktree 的 project-local files，纳入 `trusted_execution_bootstrap`；registry 写 `agent_permission_mode: approve`。Gearshift Core 是全局 package，`-e` 只加载 Delivery Pipeline Adapter。显式 `--gearshift-target` 创建以当前 CLI model 为 Source 的 ephemeral route，不继承同名持久 profile 的 `source`。

### Codex CLI

- runtime：`herdr-codex-pane`
- model evidence：`codex debug models`
- 启动：

```bash
herdr agent start "$agent_name" --kind codex --pane "$pane_id" -- \
  --model "$model" -c "model_reasoning_effort=\"$effort\"" \
  -s danger-full-access -a never
```

### Claude CLI

- runtime：`herdr-claude-pane`
- model evidence：`~/.claude/settings.json` 的 `env`
- 启动：

```bash
herdr agent start "$agent_name" --kind claude --pane "$pane_id" -- \
  --model "$model" --effort "$effort" --dangerously-skip-permissions
```

Claude 候选仍来自 `ANTHROPIC_DEFAULT_{FABLE,HAIKU,OPUS,SONNET}_MODEL`、`ANTHROPIC_MODEL`、`CLAUDE_CODE_SUBAGENT_MODEL` 与 `CLAUDE_CODE_EFFORT_LEVEL`。字段不存在时不能发明 ID。

## Dispatch 验证

1. 从 realpath 运行 setup 的 `scripts/model_config.py validate <config>`。
2. 按对应 catalog 验证普通 model/effort；存在 bootstrap 时同时验证其 pi model/effort。
3. 根据 mode、ticket label、role、agent 与 bootstrap 是否存在，确定本 lane `gearshift_enabled`。
4. enabled 时验证 Gearshift Core flags、Adapter 文件 realpath、Source/Target 不相同，并固定 profile 为 `delivery-bootstrap`。
5. registry 在启动前写 role、output mode、agent、普通 model/effort、bootstrap fields、Gearshift Projection 初始字段、runtime 与 permission mode；精确 readback 后才能启动。
6. disabled lane 不加载 Adapter、不传 Gearshift flags。
