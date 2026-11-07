# ADR-0019: Herdr dispatch helper 与 merger lane

**Status:** Accepted
**Date:** 2026-11-07
**Decider:** User (Dimon)

## Context

最近 30 次编排会话复盘显示，coordinator token 主要花在两处：每条 lane 手工走 pane 落位、agent
start、packet 投递、working 确认、watcher、registry 写入与回读的十余次 Herdr 往返；以及每个
WAKE 后亲自做验证、cherry-pick、focused checks、cleanup 与 tracker 迁移，这些工作把 diff、
测试输出和冲突细节灌进 coordinator 上下文。implement-spec 的做法是派一个 merger subagent 收口，
coordinator 只看结果。

## Decision

1. Herdr 新 lane 由 `skills/delivery-pipeline-herdr/scripts/dispatch.py` 一次完成派发全流程，
   成功只回一行 JSON 坐标，失败写 `setup_blocked`。行为由 `dispatch_check.py`（fake Herdr）锁定，
   取代 pane-lifecycle-rules 的逐步命令与 tab label 编号。registry 的 `herdr` overlay 写
   workspace/tab/pane、agent_name 与 coordinator pane，不写 session_name/session_owned。
2. coordinator 不亲自 fan-in。terminal event 后派发 integration lane（merger，output_mode
   `integration`，task type `integration`，CLI 配置未定义时用 `backend` 项），在 Map Integration
   Worktree 按 execution-worktree-integration 对待收口 lane 逐条收口，终态
   `LANE_DONE <merger_lane> <integration HEAD>`。同一 Map Integration Worktree 同时只有一个
   merger，期间到达的 terminal 累积到下一批。
3. watcher 接受 `LANE_DONE <lane_id>` 后带一个空格分隔后缀的终态行。

## Consequences

- coordinator 每条 lane 只消耗一次 dispatch 调用与一次 registry 状态读取。
- 收口串行化到 merger：吞吐受单 merger 限制，换来 coordinator 上下文不承载 diff 与 check 输出。
- 新增 output_mode 与 role 枚举值 `integration`。
