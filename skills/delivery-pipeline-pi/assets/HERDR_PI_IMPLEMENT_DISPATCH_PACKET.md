# Herdr pi Implementation Dispatch Packet

pi 调度运行时（`coordinator_runtime: pi-cli`）下填写本 packet，派给一个独立
Execution Worktree 的 fresh pi pane；worker 模型已由 coordinator 按角色路由
（frontend/design → `junbo/kimi-k3:max`，backend/other → `openai-codex/gpt-5.6-sol:xhigh`）。

```text
Coordinator task：
Herdr workspace/tab/pane：
Worker model：<junbo/kimi-k3:max | openai-codex/gpt-5.6-sol:xhigh>
Owner skill name：implement
Owner skill SKILL.md：<absolute resolved path>
Owner skill invocation label：$implement
Ticket：<id/title/url>
Parent spec：<id/url>
Wayfinder map：<id/url | none>
Repo：
Integration worktree：<integration-worktree-path>
Integration branch：feature/map-<map-issue>
Execution worktree：<execution-worktree-path>
Execution branch：pi/issue-<ticket-number>
Base commit：<integration-branch-HEAD-at-creation>
允许编辑：
-
禁止范围：
-

执行：
- 确认 cwd 位于 Execution Worktree（not Integration Worktree，not Source Worktree）。
- 先完整读取 Owner skill SKILL.md，回报 frontmatter name 与 resolved path，再按其 contract
  实现 Ticket。invocation label 只用于说明，不依赖 pane catalog。
- 只处理这张 ticket，不领取 sibling 或 dependent tickets。
- 运行 ticket/repo 要求的 focused checks 与 review。
- 有文件变更时创建一个仅含本 ticket 的 local commit。
- 保留 tracker writes、cherry-pick、Integration 和 remote actions 给 coordinator。
- 不自行切换模型；当前模型与 Worker model 不符时在 final report 的 Blocker 中说明。

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
