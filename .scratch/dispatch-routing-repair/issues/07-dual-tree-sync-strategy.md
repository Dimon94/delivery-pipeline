# 07 — 两棵树的长期同步策略：哪些文件该单源生成、哪些该各写各的

Status: claimed
Type: wayfinder:grilling
Blocked by:

## Question

05 已定下闸门形态（`validate.py` 分树断言 sigil + pre-commit hook 校验暂存树 + CI 兜底），
所以 map 里"两棵树的长期同步策略"这片 fog 现在可判断了：**05 的闸门只拦写法漂移，
不拦内容漂移。** 它保证 Codex 树不出现 plugin locator、两棵树各自含有应有的 sigil，
但两棵树的正文说了不同的事时，它一句话都不会说。

已实测的漂移分布（16 个平行 `.md`，`diff` 行数 / Codex 侧行数）：

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

这不是一个均匀的问题：`toc-thinking-processes.md` 是纯复制品，维护两份没有任何收益；
`child-monitoring.md` 两侧讲的是不同 runtime 的监听机制（`Agent` tool 后台 subagent
vs Herdr pane listener），本来就该不同。一刀切"全部生成"或"全部手写"都是错的。

`2238745` 之所以能一次污染两棵树，正是因为它把两棵树当成同一堆文本做批量替换——
而仓库没有任何东西声明"这两个文件应该一致"或"这两个文件必须不同"。

要决定的点：

1. **分类标准**。按什么判定一个平行文件属于"该单源"还是"该分叉"？候选：diff 比例阈值、
   人工在文件里声明（front-matter 或注释标记）、按目录（`references/` vs `assets/`）。
   阈值方案的问题是文件会自然演化、阈值会不断需要调整。

2. **单源文件的机械**。选定"该一致"的文件后，用哪种机械：
   (a) 生成——一份源文件 + 构建步骤产出两份，(b) 校验——两份都手写，`validate.py`
   断言二者一致（或仅在允许的差异清单内不同），(c) 软链——两棵树指向同一文件。
   (c) 最省但会改变 bundle 的物理形状（`skill-bundle.json` 的 entrypoint 语义、
   `install.sh` 的软链安装是否还成立）。(a) 引入构建步骤，本仓目前无构建。

3. **分叉文件的意图声明**。对"本来就该不同"的文件，是否要求显式记录**为什么**不同，
   以及差异边界在哪。否则下一次批量改写仍然无从判断哪些行不该跨树复制。

4. **与 05 闸门的关系**。这套检查是否并入 `validate.py`（与既有分树断言同一份清单），
   还是独立脚本。考虑到 05 已定"禁则只扫 `skills/`"的范围原则，跨树一致性检查天然要
   同时读两棵树，范围语义与既有禁则不同。

5. **优先级**。本 map 剩余的 02/04 都要改双树，先定这套机械能少改两遍；但它也可能是
   过度工程——真正的漂移事故目前只有 `2238745` 一次，且已被 05 的闸门覆盖住写法面。
   要定这张票是现在做、还是记录为已知债务等下一次漂移再做。

## 落地

决策定下后直接改文件（本 map 授权 execution）：按决策实现分类标记与检查/生成机械，
跑 `python3 scripts/validate.py`。若决策是"记录为债务、暂不实现"，则只落文档，
不加机械。
