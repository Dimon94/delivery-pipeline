# Owner Skill Resolution

Stage owners may be user-invoked skills and therefore absent from a delegated child’s active skill
catalog. A bare `$implement` or `$to-spec` string is not proof that the skill was attached.

## Resolve

Before entering a stage, resolve its owner to a real `SKILL.md`:

1. Use the exact locator from the current session’s available-skills catalog when present.
2. Otherwise check `${CODEX_HOME:-$HOME/.codex}/skills/<name>/SKILL.md`.
3. Otherwise check `${AGENTS_HOME:-$HOME/.agents}/skills/<name>/SKILL.md`.
4. Resolve symlinks to an absolute path, read the file completely, and verify frontmatter
   `name: <name>`.

Resolve only the owner needed by the current gate. Missing or mismatched owner path blocks that
gate; do not silently replace its contract with generic behavior.

## Dispatch Contract

Every child packet must include:

```text
Owner skill name：<name>
Owner skill SKILL.md：<absolute resolved path>
Owner skill invocation label：$<name> | /<name>
```

The child must read the passed `SKILL.md` completely before task actions and follow it as the stage
contract. The invocation label is descriptive only; availability of that label in the child catalog
is not a prerequisite and must not trigger a fallback workflow.

The startup probe verifies that the child reports the same owner name and resolved path. A child
that starts work without reading the file is setup blocked and may be replaced once.
