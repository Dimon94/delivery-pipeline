# ADR-0017: Review 预算

**Status:** Accepted（逐票 review 部分对 CLI 由 ADR-0020 取代）
**Date:** 2026-11-05
**Decider:** User (Dimon)

## Context

my-skills ADR-0005 已规定只有 P0/P1 阻断，但 coordinator 仍能绕开：DD-230 的 packet 写“P0/P1/P2 均阻断”，
DD-267 的 P2 被转成修复 lane。DD-179 在 r3 到 r14 共跑 12 轮，P0/P1 始终为 0。ADR-0012 的“不设修复轮次上限”
也被用于 Review finding。30 天 2673 条审查会话显示：Review 主要在替实现阶段补对账和反例。

用户决定：每票最多 3 轮，整体另有 3 轮，R3 后结束。R3 后仍有 P0/P1 视为实现链路故障，触发 retro。
Agent 用尽量少的审查次数找尽量多的 P0/P1，不做抽象的对抗性审查，把 token 投给实证验证和形式化验证。

## Decision

1. Review finding 与 checks 失败分开：后者继续适用 ADR-0012，前者适用预算。
2. 预算、轮次范围和处置归 `gate-state-machine.md` §Review 预算；严重度和审查内容归 code-review owner。
3. `review_gate.py` 由 P0/P1 计数推导结论，账本强制连续轮次与上限，并要求每条 P2 有 Issue 坐标。
4. R3 后仍有 P0/P1 时写 `REVIEW_EXHAUSTED`：不合并，不续轮，运行实现链路 retro，由用户决定重开新票或放弃。
5. whole-change 阶段的修复 lane 不跑内嵌 Review，避免绕过预算。

## Consequences

- 更多 P2 会进入 Issue 积压，分级准确度成为主要风险。实现者仍不能降级，P1 必须有可触发场景和可观察影响。
- 账本路径由 packet 给出，gate 无法发现换路径重开账本的行为；coordinator 恢复时以 registry 记录核对。
- 按 30 天旧数据估算，7% 到 13% 的票可能触顶。这是正则统计，且旧数据没有 R1 穷举和前置对账，新规则下应会降低。
