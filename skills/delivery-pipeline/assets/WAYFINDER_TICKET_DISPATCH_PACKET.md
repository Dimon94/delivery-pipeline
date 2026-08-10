# Wayfinder Ticket Subagent Packet

用于派发一个 Wayfinder decision ticket 后台 subagent。不要发送半截 packet。

```text
项目：
Lead session：
Wayfinder map issue：
Ticket issue：
Ticket title：
Ticket label：wayfinder:research | wayfinder:task
Ticket mode：AFK
基线分支：
基线提交：
Owner skill name：<research | wayfinder>
Owner skill SKILL.md：<absolute resolved path>
Owner skill invocation label：<$research | $wayfinder>
执行目标：
Source worktree：
Research branch：research/<ticket-name> | n/a
进度快照：<当前门禁；discovery 已完成/运行/阻塞/待派发数量；本 batch；下一门禁或 blocker>

路由：
- 先完整读取 Owner skill SKILL.md，回报 frontmatter name 与 resolved path，再执行对应
  contract；invocation label 只用于说明，不依赖 catalog。
- `wayfinder:research`：按 `research` owner 执行研究工作流，
  不再调用 `$wayfinder` 或嵌套派发另一个 research subagent。
- `wayfinder:task`：按 `wayfinder` owner处理该 map issue 和 ticket issue。
- 只解决这个 child issue。
- Wayfinder 默认是 planning；除非 map Notes 明确授权 execution，产出 decisions、
  evidence 和 linked artifacts，不交付 Destination 本身。

真相源：
- Map issue：<title/link>
- Ticket issue：<title/link>
- Wayfinding operations：docs/agents/issue-tracker.md | local-markdown fallback
- 既有产物：
-

允许范围：
- 这个 ticket issue 的 body/comments/labels/assignee/close state
- Map issue 的 Destination、Decisions-so-far、Not yet specified 和 Out of scope 行
- Artifact paths：
- Research context pointer：<ticket comment + research/<name> branch + Markdown path | n/a>
- 禁止范围：

外部可写目标：
- Tracker map/ticket issues：
- Artifact paths：

执行规则：
- 本 subagent 作为独立后台 agent 运行（不是 Herdr pane 或 Codex thread）。
- 需要分支时，只在本 worktree 目录内创建/切换；不要切换主目录/source worktree 的分支。
- 如果 ticket 仍 open 且 unassigned，先 assign 给自己并读回确认；如果已分配给
  别的 agent/dev，停止并报告 blocker。
- 能查到的 fact 自己查；任何 product、architecture、preference 或 risk judgement
  都是 human decision，停止并回报 `ask-user`，不要替用户回答。
- 不要解决 sibling child issues。
- 不要派发后续 subagents。不要建议进入 `$to-spec`、`$to-tickets` 或 `$implement`；
  lead 会重查 map/frontier 再判断下一步。
- 不要进入 `$implement`。
- 如果 ticket 是 `wayfinder:task`，只执行让后续 decision 可判断的前置清障；不要把
  task 扩大成实现 Destination 的交付。
- 如果 ticket 是 `wayfinder:research`，在开始阅读前建立或复用
  `research/<ticket-name>` 临时分支；研究结果保存成一份引用一手来源的 Markdown
  artifact，并把 branch + path 作为 context pointer 写入 ticket。没有 artifact
  或 context pointer 不得 close ticket。
- research artifact 需要 repo write 时，必须先获得独立 research worktree；没有可写
  worktree 就报告 blocked，不得在 source worktree 切换 `research/<ticket-name>`。
- 如果 ticket 需要人为判断、prototype reaction 或 HITL task input，停止并报告问题。
- 把 answer 写成 ticket 的 resolution comment，close ticket，并给 map
  Decisions-so-far 追加 title link + gist；不要把完整 answer 或 artifacts 粘贴进 map。
- 如果 answer 让 Not yet specified 中的 fog 变得可成票，创建/连线 child issues，并从
  Not yet specified 删除对应 fog；如果发现某个 ticket 或 fog 已越过 Destination，close
  ticket 或删除 fog，并在 Out of scope 追加 title link + gist + ruled-out reason，不要写入
  Decisions-so-far。
- 如果 `执行目标` 和 `Source worktree` 不同，只能修改上面列出的外部可写目标；
  其他 source-worktree 路径全部只读。
- 在本 subagent final answer 中输出完整 final report。

最终输出必须完整包含两个 marker：

FINAL_REPORT_BEGIN
Ticket：
状态：resolved | blocked
Agent：<agent-name>
Worktree：
执行目标：
Source worktree：
分支：
Commit：<hash subject> | none
Tracker 变更：
-
Artifacts：
-
Research context pointer：<branch + path | n/a>
新增或解除阻塞的 child issues / Not yet specified / Out of scope：
-
Lead 下一步提示：
-
阻塞：
-
下一门禁建议：spec | more-discovery | ask-user | blocked
FINAL_REPORT_END
```
