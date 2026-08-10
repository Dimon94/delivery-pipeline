# 05 — 修复被 2238745 打红的 validate 闸门，并让它拦住同类改写

Status: resolved
Type: wayfinder:grilling
Blocked by:

## Question

`python3 scripts/validate.py` 在当前 HEAD **失败**：

```
missing invariant in skills/delivery-pipeline/SKILL.md: /to-spec
```

已验证 `2238745~1` 时通过，所以是 `2238745` 打红的——它把 Codex 侧 SKILL.md 里的
`/to-spec` 改写成 `/mattpocock-skills:to-spec`，而 `validate.py` 的 `require()` 断言
（第 46-50 行）逐字检查 `/to-spec` 存在。那次 commit 的 message 却写着
"Verification: All skill references now point to mattpocock-skills plugin"、
"Risk: Low: purely reference updates"。闸门是红的，改动照样进了 main。

这是本 map 其余三张票能够无声上线的**同一个原因**：唯一的自动闸门被打红后没人看。
所以这张票排在其他票之前有意义——它恢复的是发现问题的能力本身。

要决定的点：

1. **`/to-spec` 这条 invariant 的正确形态**。它现在逐字匹配裸 skill 名。第 03 票要定
   plugin-namespaced locator 的允许边界，两者会互相影响：如果 Codex 侧一律禁止
   plugin locator，那这条 invariant 就该保持裸名并对 Codex 侧强制；如果允许，
   invariant 要改成能同时接受两种写法。先定哪个、还是这张票只把闸门恢复成绿、
   把语义留给 03。

2. **闸门为什么能被绕过**。没有 pre-commit hook、没有 CI。要定是否引入
   （repo 里有 `skills/misc/setup-pre-commit` 这个现成 skill 可参考），
   还是靠约定——考虑到本 repo 是给 agent 用的 skill bundle，被 agent 批量改写正是
   常态，约定的可靠性值得怀疑。

3. **invariant 清单本身是否够**。`require()` 现在检查的是几个 skill 名字符串是否存在。
   它没能拦住"Codex 侧出现 Claude plugin locator"这类语义错误——第 03 票第 4 点要加的
   正是这种边界检查。要定两者是同一份清单还是分开表达。

4. **本次修复的顺序**。这张票是否必须先合、其他票的落地都在闸门恢复绿之后进行；
   还是允许并行、由各票自己保证收尾时闸门为绿。

## 落地

决策定下后直接改文件（本 map 授权 execution）：修复 invariant 使
`python3 scripts/validate.py` 恢复通过，按决策加防回归机制。

## Answer

拷问中查明的事实修正了票面前提，先记录：

- 红灯不是 1 条而是 **8 条**。`common` 元组的 5 个 token 里有 4 个
  （`/to-spec`、`/to-tickets`、`/implement`、`/code-review`）在**两棵树**都缺失；
  `require()` fail-fast 只报第一条，把 8 条错误伪装成 1 条。票面"是 Codex 侧被改写"
  不准确——`2238745` 同时改了两个 SKILL.md。
- 第 5 个 token `/wayfinder` 显示通过，是**假阳性**：它匹配的是文件路径
  `references/wayfinder-frontier-loop.md`，不是 skill 引用。把 5 个引用全删光它依旧绿，
  即这条 invariant 一直在空转。
- `2238745` 不是漂移的发起者。`references/test-decision-and-rebase.md` 等文件在
  `2238745~1` 时 Codex 侧**已有** plugin locator；该 commit 扩大了漂移面。
- `2238745` 尚未 push（本地 main 领先 origin/main 一个 commit），所以拦点必须在 commit
  而非 push。
- `setup-pre-commit` 那套（husky + lint-staged + npm scripts）对本仓不适用：无 `package.json`。
- `install.sh:73` 本来就会跑 validate.py，但本仓是软链安装，改文件不需要重装，
  这条路径实际拦不到任何东西。

### 决策

1. **invariant 形态 = 分树（选项 C）。** Codex 侧断言 `$name`，Claude 侧断言
   `/mattpocock-skills:name`。这不是新政策：`validate.py` 自己第 210 行就写着
   `"$to-spec" if root == CODEX_ROOT else "/to-spec"`，两棵树的 packet 也早已分别用
   `$to-spec` 与 `/to-spec`。本票把它从个别断言提升为全仓规则。断言 sigil 而非裸名
   顺带消灭了 `/wayfinder` 假阳性——`$wayfinder` 不可能出现在文件路径里。
   代价自觉：这等于替 03 票第 1 点定了 plugin locator 的允许边界，03 只余契约层。

2. **防回归 = pre-commit hook + CI（选项 d）。** 不采用"靠约定"：`2238745` 的 commit
   message 写着 "Verification: ..."、"Risk: Low" 而闸门是红的——约定刚刚以
   "声称已验证" 的方式失败过，且本仓是给 agent 用的 bundle，被批量改写是常态。
   hook 源码放 `scripts/hooks/pre-commit`（进版本库），由 `install.sh` 软链到
   `.git/hooks`；CI 为新 clone 与 `--no-verify` 兜底。

3. **34 处写法替换归本票（选项 a）。** 禁则一旦生效这些行立刻全红，而本票收尾必须绿。
   实际执行时发现并行票已把它们改成**裸名**（不是 `$` 形态），故按决策 1 统一转成
   `$name`，实测 38 处。

4. **严格度 = 分树精确断言 + 一次报全部错（选项 c）。** `require()` 改为收集后统一报。
   本票之所以要先查一轮才知道真实规模，就是 fail-fast 造成的。

5. **并发 = 与 03 并行、分工（选项 c）。** 05 拿写法层（sigil 替换 + validate.py +
   hook/CI），03 拿契约层（绝对路径传递、packet 强制字段、Codex 侧依赖供给），互不碰。

6. **禁则扫描范围 = 只扫 `skills/`（选项 a）。** 禁则要精确对应它防的 bug——"Claude 写法
   越界进 Codex 树"，不是"仓库里出现 Claude 写法"。`docs/adr/0001` 那 2 处保持原样
   （ADR 记录历史，且不分树）；`.scratch/` 天然排除——票文件本身就要引用
   `/mattpocock-skills:xxx` 来描述问题，扫到那里等于写票即犯规。扫得比语义宽只会
   制造假红灯，而假红灯正是让人不看闸门的原因。

### 落地结果

- Codex 树 38 处 skill 引用 → `$name`（11 个文件）。`$resolving-merge-conflicts` 是
  真实可解析的（`~/.agents/skills` 下存在）；其余 5 个 owner 对 Codex 不可见，
  只能靠绝对路径传递——属 03 票。
- `validate.py`：新增 `ERRORS`/`record()` 收集器与终局汇总报错；`skill_ref()` 分树
  返回应有 sigil；`require()` 改为 whitespace-insensitive（不再被换行折断）；
  `check_runtime_boundaries()`（并行票已建）改用 `record()`，未另建重复扫描器。
- `scripts/hooks/pre-commit`：对 `git checkout-index` 导出的**暂存树**跑校验，
  避免未暂存的修改掩盖或背书一个红的暂存改动。
- `.github/workflows/validate.yml`：push/PR 跑同一校验器。
- `install.sh`：新增 `install_hooks()` 与 `--no-hooks`，默认装 hook。
- README / README.zh-CN：记录 hook、CI 与分树写法规则。

反向验证（临时副本，非本仓）：重放 `2238745` 的改写 → 同时报出 missing invariant
与 locator 越界 2 条；恢复 → 回绿；删光 5 个引用 → 报 5 条，旧假阳性不再漏过。
hook 实测拒绝红灯 commit，且确认无新 commit 产生。

### 交给别人的发现

Claude 侧 3 个 packet 的 `Owner skill invocation label` 仍是裸名
（`GATE_CHILD:17` `</to-spec | /to-tickets | /code-review | /research>`、
`WAYFINDER_TICKET:17`、`WAYFINDER_GRILLING:24`）。这些 owner 由插件供给，
`~/.claude/skills` 下不存在，裸名 label 解析不了。按决策 5 属契约层，留给 03。
（`CODEX_PANE_DISPATCH_PACKET.md:14` 的 `$implement` 是对的——它描述的是 Codex pane。）
