# Owner Skill Resolution

Stage owners may be user-invoked skills and therefore absent from a delegated child’s active skill
catalog. A bare `$implement` or `$to-spec` string is not proof that the skill was attached.

## Resolve

Before entering a stage, resolve its owner to a real `SKILL.md`:

1. Use the exact locator from the current session’s available-skills catalog when present.
2. Otherwise use the absolute path the dispatching packet already resolved for you — a Codex
   pane is not required to hold a local copy of the owner.
3. Otherwise check `${CODEX_HOME:-$HOME/.codex}/skills/<name>/SKILL.md`.
4. Otherwise check `${AGENTS_HOME:-$HOME/.agents}/skills/<name>/SKILL.md`.
5. Resolve symlinks to an absolute path. coordinator 只解析 realpath、frontmatter name 和 direct reference paths，
   coordinator 不把 owner body 加载进上下文；packet 负责把真实路径交给 worker。

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

child 完整读取 owner 与所需 direct references；coordinator 的 dispatch packet、resolved realpath 与
frontmatter readback 证明 owner 坐标，worker 的 terminal evidence 证明 contract 消费。缺失或不匹配时
该 lane blocked；startup 不为等待 owner 复述而持续读取 worker 输出。
