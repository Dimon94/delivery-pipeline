# ADR-0004: Config-driven Multi-runtime Routing

**Status:** Accepted
**Date:** 2026-08-25
**Decider:** User (Dimon)

## Context

ADR-0002 selected transport from Coordinator Runtime and bound frontend/design to Claude and
backend/other to Codex. ADR-0003 added a pi-specific delta with hard-coded model choices. That
layering made worker policy depend on the coordinator host, duplicated the Claude/Codex
orchestration body, and required repo edits whenever a user preferred a different model.

The desired invariant is the opposite: the current calling session is always the coordinator;
worker role configuration independently chooses pi, Codex CLI, or Claude CLI plus its model and
effort. Codex App remains exceptional because App tasks and App-managed Execution Worktrees are a
provider-native transport unavailable to the three CLI hosts.

Local probe evidence:

- pi exposes an authoritative catalog through `pi --list-models` and accepts `--model` plus
  `--thinking`.
- Codex CLI exposes JSON through `codex debug models`, including model slugs and supported
  reasoning levels; it reads `model_reasoning_effort`.
- Claude CLI accepts `--model` and `--effort`. `~/.claude/settings.json` `env` exposes configured
  candidates through `ANTHROPIC_DEFAULT_{FABLE,HAIKU,OPUS,SONNET}_MODEL`, their `*_MODEL_NAME`
  labels, `ANTHROPIC_MODEL`, `CLAUDE_CODE_SUBAGENT_MODEL`, and `CLAUDE_CODE_EFFORT_LEVEL`.

## Decision

1. `skills/delivery-pipeline` is the single canonical CLI/Herdr core installed unchanged for pi,
   Codex CLI, and Claude CLI. It is runtime-neutral and passes owners by name, absolute SKILL.md
   path, and descriptive runtime label; it contains no Codex/Claude owner sigils.
2. The current calling session is the coordinator. Coordinator agent/model is not configured.
3. `~/.config/delivery-pipeline/model-roles.json` version 2 defines exactly six worker roles:
   `planning`, `design`, `frontend`, `backend`, `testing`, `review`. Every role requires explicit
   `agent`, `model`, and `effort`; skills contain no built-in routing defaults and missing/invalid
   configuration blocks dispatch.
4. Agent selects transport: pi → `herdr-pi-pane`, codex → `herdr-codex-pane`, claude →
   `herdr-claude-pane`. Each adapter translates model/effort into its CLI-native arguments and
   kind-specific permission mode.
5. `delivery-pipeline-setup` probes local evidence, requires the user to choose all six role
   triples, writes version 2, and reads it back. Claude roles select from the model options exposed
   by `settings.json.env`; missing candidates block that Claude selection rather than inventing an ID.
6. `skills/delivery-pipeline-codex-app` is the only transport shell. It skips worker-role
   configuration, uses `codex-thread` + App-managed Execution Worktree, and co-locates every
   app-specific packet/reference under its own tree.
7. `skills/delivery-pipeline-pi` and the duplicate `claude/skills/delivery-pipeline` are retired.
   Claude-specific helpers may remain under `claude/skills`, but they do not own canonical
   orchestration.

## Consequences

- A role can switch agent/model/effort without changing repository docs; rerunning setup is the
  durable change path.
- All CLI users must initialize before first dispatch; there is no silent fallback.
- The canonical core cannot mention `codex-thread`, App thread tools, or App-managed worktrees;
  those live only inside `delivery-pipeline-codex-app`.
- Existing lanes recover from their registry values and are not migrated when configuration
  changes.
- This ADR supersedes ADR-0003 and the CLI worker-binding portions of ADR-0002. ADR-0001 worktree
  isolation and ADR-0002 Codex App native transport remain accepted.

## 2026-09-08：为 version 3 重开决策（#107）

原决策 3/5 只定义并写入 version 2，与 #95 的显式分阶段执行计划冲突。
重开理由：需要在原 session 中冻结起步、执行与直接执行的选择，且现有 Pi/Codex native
adapter 已实现，入口不能继续以 adapter 缺失拒绝 staged。放弃 #50 历史恢复；以当前实现为准。

- version 2 保留六角色 schema、role triple 与一次启动的 legacy 行为，不自动迁移配置或已有 lane。
  `legacy-config` 仅表示解析兼容；所有实际 startup（包括 v2）必须提供当前 binary、model 与
  对应 effort 的 capability evidence，无证据或不匹配一律 fail-closed。
- version 3 显式增加每个 agent 的 default_mode 与 starting/execution/direct 三组 model/effort。
  仅 commit output 的 implementation role 消费该计划，选择顺序为 ticket → map → user-config。
  staged 三组参数完整冻结到 packet/registry，缺项或读回不一致不得启动；不静默降级 direct。
- setup 可按用户选择写入 v2 或 v3，并校验当前能力。生产 startup/continuation 入口复用现有
  Pi TUI、Codex 精确 session resume 与 Claude adapter，不另建 dispatcher。
  接续计划不替代停止核验、registry、发送 lease 或实际 runtime readback。
- App transport、已有 lane 恢复语义与 worktree 隔离保持原决策；能力请求不是实际模型运行证据。
