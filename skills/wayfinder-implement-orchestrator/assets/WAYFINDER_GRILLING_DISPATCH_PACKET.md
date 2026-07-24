# Wayfinder HITL Worker Packet

当 wayfinder map issue 走到未阻塞的 `wayfinder:prototype`、`wayfinder:grilling`、
HITL `wayfinder:task` child issue，或任何需要实时用户判断的 discovery child issue
时，填写这个 packet。一个 HITL child issue 对应一个用户运行的 fresh task，承载
完整真人反馈会话；不要每个问题开一个线程。

```text
项目：
Coordinator task：
Wayfinder map issue：
Ticket issue：
Ticket title：
Ticket label：wayfinder:prototype | wayfinder:grilling | wayfinder:task
Ticket mode：HITL
基线分支：
基线提交：
Source owner projectId：
Source worktree：
HITL 目标：
需要解决的决策/反馈分支：
-
进度快照：<当前门禁；discovery 已完成/运行/阻塞/待派发数量；本 ticket 为什么需要用户判断；下一门禁或 blocker>

路由：
- 使用该 map issue 和 ticket issue 调用 /wayfinder。
- 只解决这个 child issue。
- Wayfinder 默认是 planning；除非 map Notes 明确授权 execution，产出 decisions、
  evidence 和 linked artifacts，不交付 Destination 本身。
- 把 /grilling 作为一个连续会话使用；当术语需要钉住时使用 /domain-modeling。
- 一次只问一个问题并等待用户反馈，然后继续问下一个依赖问题，直到这个 ticket
  resolved 或 blocked。
- 每个问题都给出你的推荐答案；推荐答案不是用户回答，不能用来替用户确认。
- 不要在第一个回答之后就结束 owner task。
- 如果某个 fact 可以通过探索代码库或已链接 artifacts 回答，就先探索，不要问用户。
  决策、偏好、scope tradeoff 和 risk acceptance 必须由用户回答。
- 如果这是 `wayfinder:prototype`，先做最小可反应 artifact，再请用户反馈；只有用户
  反馈足够支持 resolution 后才 close。
- 如果这是 HITL `wayfinder:task`，给出精确 checklist 或执行可自动部分；需要用户
  执行/确认的步骤不能由 agent 代答。
- ticket resolved 后返回 coordinator；不要进入下一 gate、`/to-spec`、
  `/to-tickets` 或 `/implement`。

真相源：
- Map issue：<title/link>
- Ticket issue：<title/link>
- Wayfinding operations：docs/agents/issue-tracker.md | local-markdown fallback
- 既有产物：
-

允许范围：
- 这个 ticket issue 的 body/comments/labels/assignee/close state
- Map issue 的 Destination、Decisions-so-far、Not yet specified 和 Out of scope 行
- 如果 /domain-modeling 需要，可以修改 domain glossary 或 ADR 文件
- 禁止范围：

执行规则：
- 需要分支时，只在本 worktree 目录内创建/切换；不要切换主目录/source worktree 的分支。
- 如果 ticket 仍 open 且 unassigned，先 assign 给自己并读回确认；如果已分配给
  别的 session/dev，停止并报告 blocker。
- HITL ticket 只能通过真人反馈 resolved；不要让 agent 自问自答或把推荐答案写成
  resolution。
- resolved 后，把 answer 写成 ticket 的 resolution comment，close ticket，并给
  map Decisions-so-far 追加 title link + gist；不要把完整 answer 粘贴进 map。
- 如果 answer 让 Not yet specified 中的 fog 变得可成票，创建/连线 child issues，并从
  Not yet specified 删除对应 fog；如果发现某个 ticket 或 fog 已越过 Destination，close
  ticket 或删除 fog，并在 Out of scope 追加 title link + gist + ruled-out reason，不要写入
  Decisions-so-far。

Terminal：
- resolved 或 blocked 后输出 final report，并向 coordinator 发送
  `TERMINAL: <ticket> completed|blocked <一句原因>`。
- 不发送 routine progress。

Final report：
Ticket：
状态：resolved | blocked
线程：
Worktree：
分支：
Commit：<hash subject> | none
Tracker 变更：
-
Docs 变更：
-
新增或解除阻塞的 child issues / Not yet specified / Out of scope：
-
Coordinator 下一步建议：
-
阻塞：
-
下一门禁建议：spec | more-discovery | ask-user | blocked

```
