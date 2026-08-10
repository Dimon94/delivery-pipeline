# 03 — Codex pane 收到的 owner 指令必须是 Codex 能解析的

Status: resolved
Type: wayfinder:grilling
Blocked by:

## Question

Codex pane 被送进 `/implement`（或 `/mattpocock-skills:implement`）后回答"Codex 不认
/implement"。两层原因叠加：

- **表层**：commit `2238745` 把全 repo 的 `/implement` 改写成
  `/mattpocock-skills:implement`，**包括 Codex 侧的 `skills/` 树**。
  `/mattpocock-skills:*` 是 Claude Code plugin 的 locator，只在 Claude Code 里解析；
  `~/.codex/skills/` 下根本没有 `implement`。当前受影响的关键行：
  `references/frontier-lanes.md:33`（"Codex pane 只运行该 ticket 的
  `/mattpocock-skills:implement`"）、`references/gate-state-machine.md:49`、
  `references/wayfinder-frontier-loop.md:45-46`，以及 Codex 侧同名文件。
- **深层**：`references/owner-skill-resolution.md` **已经**规定了正确契约——把 owner
  解析成绝对 `SKILL.md` 路径传过去，invocation label 只作说明、不得触发 fallback。
  派发路径没有遵守它。`dispatch-to-codex/SKILL.md:22,187,387` 直接
  `send-text "/implement <url>"`，属于同一 bug 的平行实例。

要决定的点：

1. **plugin-namespaced locator 的允许边界**。`/mattpocock-skills:*` 是否只准出现在
   Claude 侧文档里、Codex 侧一律禁止？还是全 repo 都改回裸名 + 绝对路径，只在说明
   owner 归属时才写 plugin 名？这决定要不要给 `validate.py` 加一条禁则。

2. **owner 传递的唯一形式**。`owner-skill-resolution.md` 的三段式契约（name /
   绝对 SKILL.md 路径 / invocation label）是否成为**所有** packet 的强制字段，派发前
   必须完成解析并 readback。以及解析失败时该 gate 是否 fail closed。

3. **Codex 侧 owner 从哪来**。已验证：`install.sh` 声明的 9 个依赖
   （wayfinder、grilling、domain-modeling、prototype、research、to-spec、to-tickets、
   implement、code-review）在 `~/.codex/skills` 与 `~/.agents/skills` 下**全部缺失**，
   `./scripts/install.sh --target codex` 今天会直接失败退出。要定：Codex 侧是否本来就
   不该依赖这些 Claude 生态 owner、还是应当把它们暴露进 `CODEX_HOME`
   （`expose_codex_dependencies()` 就是干这个的，但源目录不存在所以无从暴露）。
   这一条与 map 里"Codex 侧 owner 依赖的供给方式"那片 fog 同源，本票只定契约，
   供给面等契约定下后 graduate 成新票。

4. **防回归**。`2238745` 是一次全 repo 批量改写，越过了 Codex/Claude 边界。要定
   `validate.py` 是否增加边界检查（例如 Codex 侧文件不得出现 plugin locator），
   使同类批量改写下次直接被闸门拦住。

## 落地

决策定下后直接改文件（本 map 授权 execution）：修正受影响行，双树都改，
按决策给 `validate.py` 加禁则，跑 `python3 scripts/validate.py`。

## Answer

### 1. plugin-namespaced locator 的允许边界 —— 混合，按 runtime 分

`/mattpocock-skills:*` **只准出现在 Claude 树**（`claude/skills/`）。Codex 树
（`skills/`）一律禁止，由 `validate.py` 的新禁则机械拦住。

理由：在 Claude Code 里 plugin locator 是这些 owner **唯一真能解析**的调用形式
（`~/.claude/skills/` 下没有 `implement`，只有 plugin 里有），把 Claude 侧也改回裸名
是用假信息换一致性。反过来 Codex 侧那个 locator 永远解析不了。

修正范围比 ticket 原文点名的 3 个文件大：Codex 树实际有 **26 处 / 11 个文件**，全部剥回
裸名。其中 `resolving-merge-conflicts` 那批**早于 `2238745`** 就已污染 Codex 树
（`2238745~1` 已可查到），说明这不是单次事故，边界从来没有闸门。

### 2. owner 传递的唯一形式 —— 三段式已是强制，补的是闸门

查清后修正一个前提：8 个 packet 的三段式字段（name / 绝对 SKILL.md 路径 /
invocation label）**本来就全齐**，fail-closed 也**已经写在**
`owner-skill-resolution.md`（"Missing or mismatched owner path blocks that gate;
do not silently replace its contract with generic behavior"）。真实缺口只有一个：
`validate.py` 只对 4/8 个 packet 断言 owner 字段，漏掉两树的 `WAYFINDER_TICKET` 和
`WAYFINDER_GRILLING`；fail-closed 那句话完全没有断言保护。

新增 `check_owner_dispatch_contract()`：对两树 `assets/*DISPATCH_PACKET.md`
**全部**断言三个字段 + "先完整读取 Owner skill SKILL.md，回报 frontmatter name 与
resolved path" 这句执行指令；并把 fail-closed 两句钉进断言。

### 3. Codex 侧 owner 从哪来 —— 契约上不需要本地副本

Codex pane **不需要**在 `~/.codex/skills/` 下持有这 9 个 owner 的副本。owner 由**派发方**
解析成绝对路径写进 packet，Codex 只负责 read 那个路径。这正是三段式契约的全部意义:
invocation label "must not trigger a fallback workflow"。

不采用"暴露进 `CODEX_HOME`"，因为它只服务于"Codex 自己按名字查找"这条**契约要取消**的
路径，且引入新失效模式：symlink 指向 plugin 目录，plugin 升级/卸载即断链，而
`expose_codex_dependencies()` 遇断链直接 `exit 1`（`install.sh:141-144`）——今天
`--target codex` 挂掉就是这个机理，被一个契约上不需要的东西卡死。

解析顺序补充（已落地）：
- Claude 树新增第 5 档 plugin marketplace 探测
  `${CLAUDE_HOME:-$HOME/.claude}/plugins/marketplaces/*/skills/*/<name>/SKILL.md`。
  选 `marketplaces/` 而非 `cache/1.2.0/`：前者是 git checkout 就地更新、路径不带版本号
  （实测 9 个依赖全在，`main` @ `9603c1c`）；后者升级即失效。
  **标为 best-effort**：这是 plugin 内部布局、不是公开契约，探测不到即 fail closed 报缺
  owner，不得猜路径。
- Codex 树新增第 2 档：直接用派发 packet 已解析好的绝对路径。

已验证 Codex 默认沙箱不限制读（`~/.codex/config.toml` 无 sandbox 段），传
`~/.claude/plugins/...` 绝对路径给 Codex pane 可读。

**供给面 graduate 成新票**：`install.sh` 的 9 个依赖硬门禁（今天令
`--target codex` 直接失败退出）本票不动，见 06。

### 4. 防回归 —— 独立函数，与 pruned policy 分开表达

新增 `check_runtime_boundaries()`，与 `check_pruned_policy()` 并列，只做 runtime 边界。
不塞进后者的 `forbidden` 元组：那个函数的 `active` 列表**同时含 `CLAUDE_ROOT`**，而
Claude 树按第 1 点是**允许**该 locator 的（现有 26 处），塞进去会直接打红闸门；且语义不同
——pruned policy 是全仓禁词，runtime boundary 是按树区分的运行时正确性，混在一起会让
下一个读代码的人误以为 Claude 侧也禁。

这就是 **05 票第 3 点问的"分开表达"**，且是它需要的那半的具体实现，05 可直接引用不必重做。

已用注入测试验证两条新检查真的会打红（注入 locator + 删 packet 字段 → 2 violations，
还原后 pass）。

### 5. `common` 元组归本票改（会话中新增的冲突面）

第 1 点落地后红灯从 Codex 侧移到 Claude 侧：`common`（原 `validate.py:174-184`）对两树都
断言裸名，Q1 之后已无法同时表达两树期望。决定由本票就地拆开，不留给 05——05 第 1 点原文
把语义决定权交给 03，而这里刚好定了；把已确定的语义留在红灯状态交给下一票，只是让闸门多
红一段时间，而"闸门红着没人看"正是这批 bug 的根因。

**注意**：落地期间 05 的 pane 正在并行重构同一文件（引入 `record()` 收集器一次报全部违规、
`skill_ref()` helper，并把 Codex 侧 sigil 统一成 `$name` 而非 `/name`）。两边改动已在工作区
自然合流，最终形态采用 05 的 `skill_ref()` + 我的两个新 check 函数。`$name` 与 `/name` 之争
以 05 的 `$name` 为准（Codex 实际用 `$` 前缀，且能避开 `/wayfinder` 被
`references/wayfinder-frontier-loop.md` 蹭中的假通过）。

### 落地结果

`python3 scripts/validate.py` → `bundle: pass`。

改动文件（本票范围）：Codex 树 11 个文件剥离 26 处 locator、两树
`owner-skill-resolution.md` 补解析顺序、`scripts/validate.py` 加两个 check + 拆 `common`。
