# Issue Implementation Dispatch Packet

每张 ready implementation ticket 填写一个 packet，并派给一个由 Codex App 创建独立
Execution Worktree 的 fresh Codex task。

**Agent kind**：`codex`（implementation tickets 使用 Codex 引擎执行）

```text
Coordinator task：
Source owner projectId：
Owner skill name：implement
Owner skill SKILL.md：<absolute resolved path>
Owner skill invocation label：$implement
Ticket：<id/title/url>
Parent spec：<id/url>
Wayfinder map：<id/url | none>
Repo：
Integration worktree：<integration-worktree-path>
Integration branch：feature/map-<map-issue>
Execution worktree：<由 Codex App 创建，startup 后 readback 实际路径>
Execution branch：codex/issue-<ticket-number>（worker 首次写入前创建或验证）
Base commit：<integration-branch-HEAD-at-creation>
允许编辑：
-
禁止范围：
-

执行：
- 确认 cwd 位于 Codex App 创建的 Execution Worktree（not Integration Worktree，not Source Worktree），
  common dir 属于 Repo，HEAD 包含 Base commit；首次写入前创建或验证 Execution branch。
- 先完整读取 Owner skill SKILL.md，回报 frontmatter name 与 resolved path，再按其 contract
  实现 Ticket。invocation label 只用于说明，不依赖 child catalog。
- 只处理这张 ticket，不领取 sibling 或 dependent tickets。
- 运行 ticket/repo 要求的 focused checks 与 review（在 execution worktree）。
- 有文件变更时创建一个仅含本 ticket 的 local commit（在 execution worktree）。
- 保留 cherry-pick、integration 和 remote actions 给 coordinator。

完成标准：
- ticket acceptance 已满足，或已有精确 blocker。
- final report 包含 commit、checks、review、dirty state 和 touched files。
- 用 send_message_to_thread 发送：
  TERMINAL: <ticket> completed|blocked <一句原因>

Final report：
Ticket：
状态：completed | blocked
Task/worktree/branch：
Commit：<hash subject | none>
Checks：
Review：
Dirty state：
Touched files：
Blocker：
```
