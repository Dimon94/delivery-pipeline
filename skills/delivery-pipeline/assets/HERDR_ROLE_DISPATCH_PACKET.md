# Herdr Configured Role Dispatch Packet

所有 CLI/Herdr worker 共用本 packet。Coordinator 从 version 2 配置解析 role、agent、model、
effort并在启动前写入 registry。配置的 model/effort 只是派发时的初始化值：用户可在 lane 运行中手动切换，
worker 被动接受，照常交付并在 final report 如实记录 runtime 实际值与 evidence；worker 不自行切换
agent/model/effort。

```text
Coordinator task：
Lane ID：<lane_id>
Herdr session/workspace/tab/pane：
Role：<planning | design | frontend | backend | testing | review>
Output mode：<commit | artifact | checks | verdict>
Agent：<pi | codex | claude>
Model：<configured native model id>
Effort：<configured native effort>
Model evidence：<pi-list-models | codex-catalog | claude-env>
Owner skill name：<owner frontmatter name>
Owner skill SKILL.md：<absolute resolved path>
Owner skill invocation label：<runtime-specific label; metadata only>
Work item：<id/title/url | gate coordinate>
Parent spec：<id/url | none>
Wayfinder map：<id/url | none>
Repo：
Integration worktree：<integration-worktree-path>
Integration branch：feature/map-<map-issue>
Execution worktree：<execution-worktree-path>
Execution branch：<pi|codex|claude>/issue-<ticket-number-or-coordinate>
Base commit：<integration-branch-HEAD-at-creation>
Review fixed point：<execution-base-commit | map-registry-base-commit | none>
Review evidence preflight：<absolute delivery-pipeline/references/code-review-evidence-preflight.md | none>
允许编辑：
-
禁止范围：
-

执行：
- 确认 cwd 位于 Execution Worktree（not Integration Worktree，not Source Worktree）。
- 先完整读取 Owner skill SKILL.md，回报 frontmatter name 与 resolved path，再按其 contract
  处理本 Work item。invocation label 只用于说明，不依赖 pane catalog。
- 当前 owner 直接或嵌套调用 `code-review` 时，完整读取 Review evidence preflight；`commit` mode
  的 Review fixed point 等于本 Execution Worktree 的 Base commit，`verdict` mode 等于 map registry
  base commit。preflight bundle 完成前不派生 Standards/Spec 子审查。
- 只处理本 Work item，不领取 sibling/dependent item，也不进入下一 gate。
- 按 Output mode 交付：
  - `commit`：实现变更；owner 调用 `code-review` 时先按 Review evidence preflight 物化当前
    dirty worktree 证据，再创建一个仅含本 Work item 的 local commit；
  - `artifact`：产出 tracker/artifact坐标，无必要 repo 变更时保持 clean；
  - `checks`：运行 whole-change checks并报告命令/结果，保持 clean；
  - `verdict`：按 Review evidence preflight 一次物化 Git/path/staged 证据，再执行 review owner；
    所有只读子 reviewer 共用 bundle并报告 verdict/findings，保持 clean。
- 保留 tracker fan-in、cherry-pick、Integration 和 remote actions 给 coordinator。
- 当前 Output mode 与 packet 不符时停止写入并在 Blocker 中报告。
- 当前 Agent/Model/Effort 与 packet 不符（通常是用户在本 pane 改了模型）时不阻塞，继续执行，
  照常交付并在 final report 记录 runtime 实际值与 evidence。

完成标准：
- Work item acceptance 已满足，或已有精确 blocker。
- final report 包含 role、output mode、agent/model/effort、对应 evidence、dirty state 与 touched files；
  `commit` 与 `verdict` 还包含 review branch、Review fixed point、HEAD 与 bundle readback。
- 到达终态（completed 或 blocked）后在 final report 之外，额外在终端输出单独一行
  `LANE_DONE <lane_id>`，该行不得包含其他内容。这是 coordinator watcher 的唯一完成信号；
  遗漏会导致 lane 完成后无法自动唤醒 fan-in。

FINAL_REPORT_BEGIN
Work item：
Role：
Output mode：
Agent/model/effort：
状态：completed | blocked
Pane/worktree/branch：
Commit：<hash subject | none>
Artifacts/checks/verdict：
Review evidence：<fixed-point/head/bundle-readback | none>
Dirty state：
Touched files：
Blocker：
FINAL_REPORT_END
```
