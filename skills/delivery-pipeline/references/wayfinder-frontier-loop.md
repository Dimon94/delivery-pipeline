# Wayfinder Frontier Loop

Discovery gate 使用同一 role-configured lane contract，不再绕过配置创建无模型坐标的通用 subagent。

## 循环

1. 从 map children 与 dependency edges 计算 ready frontier；读取每张 decision ticket 的 owner、
   HITL/AFK 属性、claim 与 latest lane registry。
2. AFK research/evidence/automatic task 绑定 `planning` role；grilling/prototype/HITL 绑定
   `design` role。按 `model-role-routing.md` 解析 agent/model/effort，填写
   `HERDR_ROLE_DISPATCH_PACKET.md`。
3. 同一 maximal safe batch 的独立 tickets 并发派发；每张 ticket 独立 pane/worktree/registry。
   HITL startup 后写 `awaiting_human`；AFK lane 写 `running`。整批 Dispatch Handoff 后 yield。
4. terminal/user completion signal 唤醒时，以 tracker、artifact、Git 与 registry fan-in：写
   resolution comment、关闭 child、更新 Decisions-so-far / Out of scope gist 与 dependency blocker。
5. 每个 dependency layer 的独立 writes 并行，一次聚合 readback；随后自动重算并派发下一 ready
   frontier，不等待用户回复“继续”。

Coordinator 拥有 frontier、tracker transaction、fan-in 与下一 gate；worker 只拥有 packet 指定的
work item，不进入 to-spec、to-tickets 或 implement gate。

## Map Run Authority

用户启动或恢复 named map 后，`map_run_authority: canonical_tracker_transitions` 覆盖该 map 的
claim/registry、child resolution/close、map gist、dependency blocker、owner-required follow-up
decision ticket 与下一 ready frontier。它不覆盖 unrelated issue、destructive ambiguity、push、main、
PR/MR、merge 或 final publication。

完成标准：所有 in-scope children closed，resolution/artifact 可读回；每层 tracker transaction 的
expected/actual 一致，ready frontier 已重算。
