# Code-review 只读子审查证据预检

当前 worker 直接运行 `code-review` owner，或 `implement` owner 在 `commit` lane 内嵌套调用
`code-review` 时读取。父 worker 在派生 Standards/Spec 子审查前完成本预检。

## 权限边界

父 worker 是本轮 Git 证据 owner；其子 reviewer 可以只有 read/search 权限。只读是预期边界，
Git diff、历史与 staged state 由父 worker 先物化为文件，再把绝对路径传给所有子 reviewer。
`code-review` owner 仍拥有审查维度、finding 质量与聚合格式；本文件只拥有证据 transport。

## 固定审查边界

| 调用分支 | Review fixed point | Worktree 边界 |
|---|---|---|
| implementation `commit` lane 内嵌 review | packet 的 Execution `Base commit` | 当前 Work item 的 staged、unstaged 与 untracked 变更；允许预期 dirty |
| whole-change `review` + `verdict` lane | map registry `role: map` 行的 `base_commit` | Map Integration Worktree 的完整集成变更；review Execution Worktree 必须 clean |

1. 验证 packet 的 Review fixed point 与上表一致并可解析为唯一 commit；记录当前 `HEAD`。
2. 沿 `code-review` owner 选择的精确 diff 关系生成 patch；fixed point、HEAD 与 diff 关系只解析一次，
   两个审查轴共用。
3. `commit` 分支把 untracked 路径写入清单，并把每个 untracked 文件作为 `/dev/null` 到当前内容的
   addition patch纳入 `diff.patch`；`verdict` 分支确认 worktree clean。
4. ref 无效、diff 为空、存在 Work item 外的 dirty 路径，或 `verdict` worktree 不 clean 时在
   子审查 fan-out 前阻塞。

完成标准：fixed point、HEAD、diff 关系唯一，审查范围完整覆盖当前 Work item 或整个 map Integration。

## Review Evidence Bundle

在 repo 外的临时目录生成一个 bundle；同一轮所有子 reviewer 共用以下文件：

- `fixed-point.txt`：packet 值、resolved SHA、HEAD SHA、调用分支与精确 diff 关系。
- `diff.patch`：精确 diff 内容及 hunk 行号；`commit` 分支同时包含 untracked additions。
- `commits.txt`：fixed point 到 HEAD 的 commit 列表；没有 commit 时明确记录 `none`。
- `changed-paths.txt`：与 `diff.patch` 同边界的完整 name-status 路径清单，包含 untracked 路径。
- `fixed-point-added-paths.txt`：resolved fixed-point commit 新增路径的
  `git diff-tree --root --no-commit-id --diff-filter=A --name-status -r` 输出；无新增时明确记录 `none`。
- `worktree-state.txt`：带标题的 `git status --short`、`git diff --cached --name-status -- .`，以及
  明确的 `NO_STAGED_FILES=true|false`。
- `commands.txt`：生成上述证据的完整命令，包括 untracked addition patch 命令。

每个文件都必须存在且可读；`diff.patch`、`changed-paths.txt` 和 `fixed-point.txt` 必须非空。
`changed-paths.txt` 是完整路径级清单，子 reviewer 可用 read/search 按任意目录前缀筛选，
无需再次执行 Git。bundle 只作上下文 transport，不写入 repo；生成后不再改写，并保留到
coordinator 完成对应 lane fan-in。

完成标准：七个文件一次生成、绝对路径已写入每个子 reviewer prompt，生成后 fixed point、HEAD 与
worktree snapshot 未变化。

## 子审查 Fan-out

- 每个子 reviewer prompt 先列出七个 bundle 绝对路径，再列 standards/spec source；先读 bundle，
  后读当前源码补充上下文。
- 子任务显式标记 review-only；交付物是 findings/verdict，不承担 Git 命令、测试命令或 staged-state 自证。
- runtime 若自动附加 child acceptance/evidence gate，父 worker 选择其 review-only/no-acceptance
  形式；`noStagedFiles` 等 shell-derived 字段以 `worktree-state.txt` 为父级证据，不向子 reviewer 索取。
- bundle 缺项属于 preflight failure，在 fan-out 前补齐；正常路径不产生索取 Git/path 输出的
  supervisor 往返。

父 worker 在 final report 的 `Review evidence` 中记录调用分支、fixed point、HEAD、bundle 目录与
七个文件的 readback。

完成标准：Standards 与 Spec 子审查从同一 bundle 开始，均可只用 read/search 完成，并返回可聚合结果。
