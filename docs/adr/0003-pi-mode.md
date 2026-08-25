# ADR-0003: pi Mode as In-Tree Delta Skill

**Status:** Accepted
**Date:** 2026-08-25
**Decider:** User (Dimon)

## Context

ADR-0002 made dispatch runtime-aware across `codex-app`, `codex-cli`, and `claude-cli`. pi is a
fourth Coordinator Runtime: it can host the orchestrator and, through Herdr, host workers with
per-role model selection (`pi --model provider/id:<thinking>`). The question was where pi mode
lives. Three options were weighed:

- **A. In-repo, third face `pi/skills/`** — mirrors the dual-tree layout.
- **B. Standalone wrapper repo `delivery-pipeline-pi`** — leaves this repo untouched but splits
  the canonical source and forces cross-repo sync of CONTEXT/ADR language.
- **C. No face at all** — only add a lane runtime to existing docs, leaving "pi as coordinator"
  without an entry skill.

A variant of A was selected: the pi face is a single skill directory `skills/delivery-pipeline-pi`
living beside the existing skills, not a new top-level tree.

## Decision

1. pi mode ships as `skills/delivery-pipeline-pi`, a thin delta skill. It reads the
   `delivery-pipeline` SKILL.md body as the orchestration contract and overrides exactly four
   cells: Coordinator Runtime (`pi-cli`, fixed Herdr Dispatch), worker kind (`herdr-pi-pane`),
   model routing, and the pi semantics of Trusted Execution Bootstrap.
2. Model routing: explicit instruction wins; otherwise frontend/design lanes (including HITL)
   start with `--model junbo/kimi-k3:max`, backend/other lanes with
   `--model openai-codex/gpt-5.6-sol:xhigh`. Workers never switch models themselves.
3. Explicit worker kind still wins over the pi default: a user-named Codex or Claude pane keeps
   the ADR-0002 branches and packets.
4. All ADR-0001/0002 invariants are unchanged: ready frontier, one writer per ticket,
   Execution Worktree isolation, maximal safe batch, Dispatch Handoff, Integration, and remote
   closeout.

## Consequences

- `skills/` is no longer purely the Codex face: it now also hosts the pi entry. The `$name`
  sigil rule applies to the pi tree unchanged; cross-face locators remain forbidden.
- pi coordinator runs always use Herdr Dispatch; there is no pi native thread transport.
- pi-side project-local trust (whether `--approve` is needed in fresh Execution Worktrees) is
  Unknown and recorded as such in the delta skill.
- The bundle manifest, installer, and validator gain a third target; `delivery-pipeline`
  remains the single source of orchestration prose.
