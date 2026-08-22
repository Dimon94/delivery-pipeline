# 03 — validate.py 的断言改造

Status: open
Type: wayfinder:grilling
Blocked by: 01, 02

## Question

01 和 02 票决定了哪些文件合并、哪些拆分后，`validate.py` 的断言要跟着改。
当前 `validate.py` 的断言是基于双树结构的：分树断言 sigil（Codex `$name` / Claude plugin locator）、
检查两棵树的平行文件都存在、检查两棵树的 packet 都符合契约。

按 invocation 拆分后，这些断言的形状要变：

1. **单树断言**。如果 `skills/delivery-pipeline/` 成为唯一的编排器（Claude 和 Codex 共用），
   那分树断言 sigil 的规则要改：
   - 单树里允许哪种 sigil？（`$name` 还是 `/mattpocock-skills:name`，还是两者都允许）
   - 还是单树里只允许一种，另一种由 `install.sh` 在安装时转换？

2. **派发 skill 的独立断言**。`pane-dispatch` 是 Claude-only 的单树 skill，
   它的断言规则与 `delivery-pipeline` 不同：
   - 是否允许 plugin locator？（当前允许，因为它是 Claude-only）
   - 是否要求 `--kind` 参数？（01 票已决定 packet 模板内嵌 `--kind`，fail closed）
   - 未来的 `thread-dispatch` 是否有自己的断言规则？

3. **跨 skill 引用检查**。`delivery-pipeline` 的 `SKILL.md` 会引用 `pane-dispatch`
   （Claude 侧）或 `thread-dispatch`（Codex 侧），`validate.py` 是否检查：
   - 引用的 skill 存在
   - 引用的 skill 的 frontmatter 符合预期（`disable-model-invocation` 等）
   - 引用的 skill 的契约字段（owner skill name / SKILL.md 路径 / invocation label）

4. **与 05 闸门的关系**。05 已定"禁则只扫 `skills/`"，但现在 `pane-dispatch` 在
   `claude/skills/` 下。要定：
   - 禁则扫描范围是否扩到 `claude/skills/`
   - 还是 `pane-dispatch` 有自己的禁则规则（比如允许 plugin locator）
   - 未来的 `thread-dispatch` 放在哪（`skills/` 还是 `codex/skills/`）

5. **`skill-bundle.json` 的 entrypoint**。当前是双 entrypoint（`codex` / `claude`），
   按 invocation 拆分后：
   - 是否改成单 entrypoint（`skills/delivery-pipeline/`）
   - 还是保持双 entrypoint，但指向同一个文件
   - 还是改成三 entrypoint（`delivery-pipeline` + `pane-dispatch` + `thread-dispatch`）

## 落地

决策定下后直接改文件（本 map 授权 execution）：按决策改造 `validate.py` 的断言，
更新 `skill-bundle.json` 和 `install.sh`，跑 `python3 scripts/validate.py` 和
`./scripts/install.sh --target all`。
