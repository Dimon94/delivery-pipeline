# 01 — runtime 无关文件的识别与合并

Status: claimed
Type: wayfinder:grilling
Blocked by:

## Question

当前双树有 16 个平行 `.md` 文件，漂移分布从 0/100（纯复制品）到 158/107（基本重写）不等。
要决定哪些文件是 runtime 无关的，应该合并成单树（`skills/delivery-pipeline/`），
哪些是 runtime 相关的，应该保留在各自树里或拆到派发 skill。

已实测的漂移分布（来自 07 票）：

| 形态 | 文件 | diff/总行 |
|---|---|---|
| 完全相同 | `references/toc-thinking-processes.md` | 0 / 100 |
| 近乎相同 | `references/execution-worktree-integration.md` | 2 / 296 |
| | `references/test-decision-and-rebase.md` | 6 / 611 |
| 局部分叉 | `references/gate-state-machine.md` | 14 / 66 |
| | `assets/WAYFINDER_TICKET_DISPATCH_PACKET.md` | 14 / 105 |
| | `references/owner-skill-resolution.md` | 15 / 36 |
| 大幅分叉 | `references/integration-worktree-management.md` | 123 / 448 |
| | `references/child-monitoring.md` | 82 / 33（基本重写） |
| | `SKILL.md` | 158 / 107（基本重写） |

要决定的点：

1. **判定标准**。按什么判定一个文件是 runtime 无关的？候选：
   - diff 比例阈值（< 10% 视为 runtime 无关）
   - 语义分析（文件内容是否涉及 pane/thread/Herdr 等 runtime 概念）
   - 人工声明（在每个文件头部加 front-matter 标记）

2. **合并的机械**。选定 runtime 无关的文件后，用哪种机械合并：
   - (a) 软链：`claude/skills/delivery-pipeline/` 软链到 `skills/delivery-pipeline/`
   - (b) 物理删除 `claude/skills/delivery-pipeline/`，只保留 `skills/`
   - (c) 反向：只保留 `claude/skills/`，`skills/` 软链过去
   - 考虑因素：`skill-bundle.json` 的 entrypoint 语义、`install.sh` 的安装逻辑、
     `validate.py` 的断言、未来 Codex app 是否会有不同的编排逻辑

3. **`SKILL.md` 的特殊处理**。`SKILL.md` 是 skill 的入口，frontmatter 里有
   `disable-model-invocation` 等 runtime 相关配置。即使内容 runtime 无关，
   frontmatter 可能必须不同。要定 `SKILL.md` 是单源 + 条件 frontmatter，还是各自维护。

4. **验证**。合并后如何验证没有破坏：
   - `python3 scripts/validate.py` 仍然通过
   - `./scripts/install.sh --target all` 仍然工作
   - Claude Code 和 Codex CLI 都能正常调用 `delivery-pipeline`

## 落地

决策定下后直接改文件（本 map 授权 execution）：合并 runtime 无关的文件，
删除或软链重复副本，跑 `python3 scripts/validate.py` 和 `./scripts/install.sh --target all`。
