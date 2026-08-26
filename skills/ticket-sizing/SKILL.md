---
name: ticket-sizing
description: Size implementation tickets by token budget — estimate the work's total tokens, divide by the smart zone (~150k tokens), and cut at least that many tickets. Use when deciding how many tickets to split work into, or evaluating whether existing tickets are too coarse.
---

# Ticket Sizing

拆票粒度由 token 预算决定：每张 ticket 的全部工作（读码、改动、测试、迭代）必须装进一个 smart zone。

**Smart zone：** SOTA agent 保持清晰推理的上下文区间，约 150k tokens。单票超出它，执行中途推理质量劣化。

## 步骤

1. **估总量。** 想清楚任务规模，估算完成它一共要花多少 token。估高不估低：估高只是多拆几票，估低会让单票超出 smart zone。
2. **算下限。** 总 token ÷ 150k，向上取整，得到票数下限。
3. **对照现有拆分。** 已经拆得更细就维持细票；有票超出一个 smart zone 就继续拆细，直到每张票都装得下。

完成标准：票数不少于下限，且每张票的估算工作量都装进一个 smart zone。

本 skill 只提供粒度判据；拆票流程的 owner 是 `to-tickets`。
