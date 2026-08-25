# Delivery Pipeline

[中文说明](README.zh-CN.md)

A resumable, configuration-driven multi-runtime delivery chain:

```text
idea/map -> discovery -> spec -> implementation tickets
  -> configured CLI/worktree dispatch -> integration -> testing -> review -> summary PR/MR
```

`skills/delivery-pipeline` is the single canonical CLI/Herdr core, installed unchanged for pi,
Codex CLI, and Claude CLI. The calling session is the coordinator; worker agent/model/effort comes
from user configuration. Codex App native tasks/worktrees are the sole transport exception,
exposed by `delivery-pipeline-codex-app` with all App-specific packets and references co-located
inside that shell.

## Worker Configuration

Before the first CLI dispatch, run `delivery-pipeline-setup`. It probes:

- pi: `pi --list-models`
- Codex CLI: `codex debug models`
- Claude CLI: model mappings and effort from `~/.claude/settings.json` `env`

The user explicitly chooses `agent + model + effort` for six roles:

```text
planning  design  frontend  backend  testing  review
```

The version 2 configuration is stored at `~/.config/delivery-pipeline/model-roles.json`. Skills
contain no default models. Missing, old, incomplete, or invalid configuration blocks dispatch and
re-enters setup. The coordinator is not configured: whichever agent/model invoked the skill remains
coordinator.

Agent selects lane kind:

- pi → `herdr-pi-pane`
- codex → `herdr-codex-pane`
- claude → `herdr-claude-pane`

## Dependencies

- At least one of pi, Codex CLI, or Claude CLI as coordinator; every worker CLI named in config must exist.
- Herdr CLI as the canonical core's terminal multiplexer.
- Owner skills: `wayfinder`, `grilling`, `domain-modeling`, `prototype`, `research`, `to-spec`,
  `to-tickets`, `implement`, `code-review`, and `resolving-merge-conflicts`.

The machine-readable list is `skill-bundle.json` (`requires`). The installer diagnoses owners and
all four CLIs without blocking installation.

## Install

```bash
./scripts/install.sh --target all
```

The installer symlinks the same `skills/delivery-pipeline` directory into Codex, Claude, and pi
skill homes and installs setup in all three. Codex additionally receives
`delivery-pipeline-codex-app`. The pre-commit validator is installed by default; pass `--no-hooks`
to skip it.

Before first use in a project repo, also run `setup-matt-pocock-skills` for tracker, triage, and
domain-doc configuration. That is separate from `delivery-pipeline-setup` worker routing.

## Use

### pi / Codex CLI / Claude CLI

Initialize once:

```text
Use delivery-pipeline-setup to initialize or reconfigure worker routing.
```

Then invoke the canonical `delivery-pipeline` with any map/spec/ticket issue. It reconstructs the
chain from tracker relationships and dispatches planning/design/frontend/backend/testing/review
lanes according to version 2 configuration.

### Codex App

```text
Use $delivery-pipeline-codex-app with <any-map-spec-or-ticket-issue>.
```

The App shell uses native tasks and App-managed Execution Worktrees and does not read the CLI worker
role configuration. To use Herdr from a Codex App session, exit the App shell and invoke canonical
`delivery-pipeline`.

## Invariants

- One Execution Worktree, lane, and active writer per work item.
- Ordinary repository path overlap is an Integration risk, not an implicit dispatch dependency.
- Same-batch startup readback completes before Dispatch Handoff; long workers do not occupy coordinator time.
- Terminal fan-in trusts Git, tracker, artifacts, and registry evidence.
- Push/main/PR/MR/merge/final publication requires separate remote authority.

## Verify

```bash
python3 scripts/validate.py
```

The same validator is enforced by the pre-commit hook and CI (`.github/workflows/validate.yml`).
