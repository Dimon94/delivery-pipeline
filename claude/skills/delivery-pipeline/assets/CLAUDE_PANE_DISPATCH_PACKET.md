# Claude Implementation Pane Packet

每张前端/设计 ready implementation ticket 填写一个 packet，并派给一个独立 execution worktree 的 fresh Claude pane。

**Agent kind**：`claude`（前端/设计 implementation tickets 使用 Claude Code 引擎执行）

**Tab placement**：X tab（execution）

```text
Lead pane：
Pane location：<由 /pane-dispatch skill 管理>
Owner skill name：implement
Owner skill SKILL.md：<absolute resolved path>
Owner skill invocation label：/implement
Ticket：<id/title/url>
Parent spec：<id/url>
Wayfinder map：<id/url | none>
Repo：
Integration worktree：<integration-worktree-path>
Integration branch：feature/map-<map-issue>
Execution worktree：<execution-worktree-path>
Execution branch：claude/issue-<ticket-number>
Base commit：<integration-branch-HEAD-at-creation>
允许编辑：
-
禁止范围：
-

执行：
- 确认 cwd 位于 execution worktree（not integration worktree，not source worktree）。
- 先完整读取 Owner skill SKILL.md，回报 frontmatter name 与 resolved path，再按其 contract
  实现 Ticket。invocation label 只用于说明，不依赖 pane catalog。
- 只处理这张 ticket，不领取 sibling 或 dependent tickets。
- 运行 ticket/repo 要求的 focused checks 与 review（在 execution worktree）。
- 有文件变更时创建一个仅含本 ticket 的 local commit（在 execution worktree）。
- 保留 tracker writes、cherry-pick、integration 和 remote actions 给 lead。

完成标准：
- ticket acceptance 已满足，或已有精确 blocker。
- final report 包含 commit、checks、review、dirty state 和 touched files。

最终输出必须完整包含两个 marker：

FINAL_REPORT_BEGIN
Ticket：
状态：completed | blocked
Pane/worktree/branch：
Commit：<hash subject | none>
Checks：
Review：
Dirty state：
Touched files：
Blocker：
FINAL_REPORT_END
```
