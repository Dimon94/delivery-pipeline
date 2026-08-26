# Herdr Configured Role Dispatch Packet

所有 CLI/Herdr worker 共用本 packet。Coordinator 从 version 2 配置解析 role、agent、model、
effort并在启动前写入 registry；worker 不自行切换 agent/model/effort。

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
允许编辑：
-
禁止范围：
-

执行：
- 确认 cwd 位于 Execution Worktree（not Integration Worktree，not Source Worktree）。
- 先完整读取 Owner skill SKILL.md，回报 frontmatter name 与 resolved path，再按其 contract
  处理本 Work item。invocation label 只用于说明，不依赖 pane catalog。
- 只处理本 Work item，不领取 sibling/dependent item，也不进入下一 gate。
- 按 Output mode 交付：
  - `commit`：实现变更并创建一个仅含本 Work item 的 local commit；
  - `artifact`：产出 tracker/artifact坐标，无必要 repo 变更时保持 clean；
  - `checks`：运行 whole-change checks并报告命令/结果，保持 clean；
  - `verdict`：执行 review owner并报告 verdict/findings，保持 clean。
- 保留 tracker fan-in、cherry-pick、Integration 和 remote actions 给 coordinator。
- 当前 Agent/Model/Effort/Output mode 与 packet 不符时停止写入并在 Blocker 中报告。

完成标准：
- Work item acceptance 已满足，或已有精确 blocker。
- final report 包含 role、output mode、agent/model/effort、对应 evidence、dirty state 与 touched files。
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
Dirty state：
Touched files：
Blocker：
FINAL_REPORT_END
```
