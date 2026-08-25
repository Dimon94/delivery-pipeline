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
