# Code-review 只读子审查证据预检

运行 `code-review` owner 的 worker 在派生 Standards/Spec 子审查前读取并完成本预检。
父 worker 拥有 Git 证据；子 reviewer 只需 read/search。`code-review` owner 拥有审查维度与
finding 格式，本文件只拥有证据 transport。

## 固定审查边界

| 调用分支 | Review fixed point | Worktree 边界 |
|---|---|---|
| whole-change `review` + `verdict` lane | map registry `role: map` 行的 `base_commit` | Map Integration Worktree 的完整集成变更；review Execution Worktree 必须 clean |
| 所属壳仍启用逐票 review 时 | packet 的 Execution `Base commit` | 当前 Work item 的 staged、unstaged 与 untracked 变更 |

fixed point 解析为唯一 commit 后记录 HEAD；ref 无效、diff 为空或越界 dirty 时在 fan-out 前阻塞。

## Review Evidence Bundle

在 repo 外临时目录一次生成，生成后不改写，所有子 reviewer 共用：

- `fixed-point.txt`：fixed point 原值、resolved SHA、HEAD SHA 与 diff 关系。
- `diff.patch`：精确 diff；逐票分支用 `/dev/null` addition 纳入 untracked 文件。
- `changed-paths.txt`：同边界 name-status 清单，每行 `<status>\t<path>\t@<diff.patch 起始行号>`。

三个文件都非空。commit 列表、worktree 状态等其余事实 reviewer 用 read/search 自行查。

## 子审查 Fan-out

轮次与处置归 `gate-state-machine.md` §Review 预算；父 worker 拿到各轴 verdict 后运行
`scripts/review_gate.py`，不自行判定通过。

- prompt 传 bundle 绝对目录、当前轴、「第 N 轮，共 3 轮」和 spec source（spec、ticket、相关 ADR
  的绝对路径或 tracker URL）；R2/R3 另传上轮 finding 与修复 diff 路径，只审修复及其影响。
- 子任务标记 review-only/no-acceptance；交付物是 findings/verdict，Git 与测试命令留在父 worker。
- bundle 缺项属于 preflight failure，fan-out 前补齐。

完成标准：两轴从同一 bundle 开始，只用 read/search 完成并返回可聚合结果。
