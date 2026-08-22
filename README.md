# Delivery Pipeline

[中文说明](README.zh-CN.md)

A resumable Codex/Claude skill bundle for one durable delivery chain:

```text
idea/map -> discovery -> spec -> implementation tickets
  -> automatic worktree dispatch -> integration -> summary PR/MR
```

Start a fresh session with any issue from the chain. The skill follows tracker
relationships upward and downward, reconstructs map/spec/ticket state, and
continues from the earliest incomplete gate.

Stage-owning skills remain authoritative: `wayfinder` owns discovery,
`to-spec` owns the spec, `to-tickets` owns ticket publication, and `implement`
owns one ticket. The orchestrator verifies durable links and state transitions;
it does not add a second ticket-shaping policy.

Implementation dispatch first selects transport from the coordinator runtime:
Codex App uses native tasks/worktrees; Codex CLI and Claude CLI use Herdr. Inside
Herdr, an explicit worker kind wins; otherwise frontend/design uses Claude and
backend/other work uses Codex CLI. Dependencies and mutable-resource conflicts
serialize only the affected tickets.
Each dispatched child persists its pane/thread ID, worktree, branch, commit, and
lifecycle state. Fresh sessions recover children and reattach terminal listeners
first. Claude closes the matching worker pane after integration and focused checks
succeed.
Delegated children receive the owner skill's resolved `SKILL.md` path, so
user-invoked stage owners do not depend on the child task's active skill catalog.

## Dependencies

**Runtimes** — Claude Code, Codex, or both (dual-runtime bundle; single-side installs work).

**Owner skills** — all from [mattpocock-skills](https://github.com/mattpocock/skills). The machine-readable list lives in `skill-bundle.json` (`requires`); the installer diagnoses missing ones:

- Discovery: `wayfinder`, `grilling`, `domain-modeling`, `prototype`, `research`
- Delivery: `to-spec`, `to-tickets`, `implement`, `code-review`
- Integration/closeout: `resolving-merge-conflicts`

**Herdr** — the terminal multiplexer for Codex CLI and Claude CLI coordinator
scenarios (CLI + `herdr` skill), also available as an explicit Codex App override.
It is separate and not bundled; the native Codex App path does not require it.

## Install

1. Install the owner skills.
   - Claude Code: `/plugin install mattpocock-skills@claude-plugins-official`
   - Codex: clone the source repo and symlink each owner into the skills home:
     ```bash
     git clone https://github.com/mattpocock/skills && cd skills
     for s in wayfinder grilling domain-modeling prototype research to-spec to-tickets implement code-review resolving-merge-conflicts; do
       ln -s "$(find "$PWD/skills" -maxdepth 2 -type d -name "$s")" "${AGENTS_HOME:-$HOME/.agents}/skills/$s"
     done
     ```
2. Install this bundle — both sides symlink to this checkout, plus the pre-commit validator:
   ```bash
   ./scripts/install.sh --target all
   ```
   The installer ends with a dependency-availability diagnostic (owner skills + Herdr CLI/skill); a `MISSING` line names something still to install.
3. Before first use in a project repo, run the `setup-matt-pocock-skills` skill there once — it configures the issue tracker, triage labels, and domain docs the owner skills assume.

## Use

Invoke with any node of the chain — the skill rebuilds the link from tracker relationships and resumes at the earliest incomplete gate, so work joins at any stage:

1. **Discovery** — a loose idea becomes a Wayfinder map (map-creation grilling stays in the current session, never dispatched). Research tickets run as background subagents; grilling and prototype tickets get dedicated Claude panes.
2. **Spec → tickets** — `to-spec` publishes the spec; `to-tickets` publishes linked implementation tickets.
3. **Dispatch** — each implementation ticket gets one Execution Worktree and one
   lane. A Codex App coordinator uses a native task; Herdr coordinators create a
   Codex CLI or Claude CLI pane according to the worker-kind binding.
4. **Hand-off and fan-in** — dispatched sessions run autonomously (HITL tickets talk to the user directly). When one terminals, its listener wakes the dispatcher, which verifies the final report, integrates the commit, and dispatches the next batch.
5. **Closeout** — after the graph empties: rebase, push, and one summary PR/MR.

Codex App (native tasks/worktrees by default):

```text
Use $delivery-pipeline with <any-map-spec-or-ticket-issue>.
```

Codex CLI (Herdr-hosted Codex/Claude panes):

```text
Use $delivery-pipeline with <any-map-spec-or-ticket-issue>.
```

Claude CLI (`/pane-dispatch` manages Herdr panes):

```text
Use /delivery-pipeline <any-map-spec-or-ticket-issue>.
```

## Verify

```bash
python3 scripts/validate.py
```

`scripts/install.sh` also installs `scripts/hooks/pre-commit`, which runs the
validator against the staged tree and refuses a red commit. Pass `--no-hooks` to
skip, or commit with `--no-verify` to override deliberately. The same validator
runs in CI (`.github/workflows/validate.yml`) as a backstop for fresh clones.

Skill references are runtime-specific and enforced: the Codex tree (`skills/`)
uses `$name`, the Claude tree (`claude/skills/`) uses `/mattpocock-skills:name`.
Claude plugin locators are rejected inside the Codex tree, where they cannot
resolve.
