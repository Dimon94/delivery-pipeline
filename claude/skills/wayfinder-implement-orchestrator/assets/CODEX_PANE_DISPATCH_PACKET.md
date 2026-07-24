# Codex Implementation Pane Packet

每张 ready implementation ticket 填写一个 packet，并派给一个独立 worktree 的 fresh
Codex pane。

```text
Lead pane：
Herdr workspace/tab/pane：
Ticket：<id/title/url>
Parent spec：<id/url>
Wayfinder map：<id/url | none>
Repo：
Base branch/commit：
Worktree：
Branch：
允许编辑：
-
禁止范围：
-

执行：
- 使用 $implement 实现 Ticket。
- 只处理这张 ticket，不领取 sibling 或 dependent tickets。
- 运行 ticket/repo 要求的 focused checks 与 review。
- 有文件变更时创建一个仅含本 ticket 的 local commit。
- 保留 tracker writes、integration 和 remote actions 给 lead。

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
