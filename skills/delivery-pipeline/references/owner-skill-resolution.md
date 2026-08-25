# Owner Skill Resolution

Stage owners may be user-invoked skills and absent from a delegated worker catalog. Invocation text
is never proof that an owner is installed; the absolute resolved `SKILL.md` path is authoritative.

## Resolve

Before entering a stage, resolve only that stage's owner:

1. Use the exact locator from the current session available-skills catalog when present.
2. Otherwise check runtime homes: `${PI_HOME:-$HOME/.pi}/agent/skills/<name>/SKILL.md`,
   `${CODEX_HOME:-$HOME/.codex}/skills/<name>/SKILL.md`,
   `${CLAUDE_HOME:-$HOME/.claude}/skills/<name>/SKILL.md`, and
   `${AGENTS_HOME:-$HOME/.agents}/skills/<name>/SKILL.md`.
3. Include provider/plugin caches only when repo instructions name their exact root.
4. Resolve symlinks; verify frontmatter `name`; record the absolute path and direct reference paths.

Coordinator只解析 realpath、frontmatter name 与 direct reference paths，不预加载 owner body。路径缺失
或 name 不匹配时阻塞该 gate，不用 generic behavior 代替。

## Dispatch Contract

每个 packet 包含：

```text
Owner skill name：<name>
Owner skill SKILL.md：<absolute resolved path>
Owner skill invocation label：<runtime-specific label; metadata only>
```

label 按 worker runtime 记录：Codex 常用 `$name`，Claude 常用 plugin/skill label，pi 常用
`/skill:name`；label 不参与文件查找。Worker 在动作前完整读取 passed SKILL.md及所需 direct
references并回报 frontmatter name + resolved path。不匹配时 lane blocked；不得触发 fallback workflow。
