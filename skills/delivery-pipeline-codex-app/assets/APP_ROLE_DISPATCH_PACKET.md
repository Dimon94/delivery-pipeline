# Codex App Role Dispatch Packet

派发与 FINAL_REPORT 使用 `../../delivery-pipeline/references/lane-registry.md` §轻量交接的
固定模板。仅展开当前分支，输入省略不适用项；本壳只追加三个回传字段：

```text
Coordinator task：<原生 threadId>
Coordinator host：<原生 hostId>
Terminal 回传合同：<absolute codex-app-dispatch.md，读取 Terminal 回传节>
```

coordinator 先持久化完整 App overlay；公共模板的 Registry 指向本 lane，输入引用其
config_path、phase_plan/phase_targets/execution_target 和实施前置证据，传当前请求值。
Review 分支的输入包含 scope、fixed point、owner 三字段、两轴配置与 preflight 绝对路径。
初始 Execution Worktree 由 App 创建，startup 后补真实坐标，写入前完成隔离核验。

## Worker 执行

1. 执行公共模板的 Worker 共同行为。每次调用的执行核验按
   `../references/development-mode.md`；用 registry 的 config_path 调用 `../scripts/prewalk.py`，
   内部辅助、second opinion 与 Review 参数走 subagent 入口，权限不超过本项。
2. starting 按开发模式合同生成 checkpoint，PREWALK_READY 后停止，保留现场；executing 才
   继续实现。恢复沿原冻结计划和 checkpoint，不重新选择配置。
3. 正式 Review 由 coordinator 调用 resolved code-review owner：commit 用
   `review_scope: implementation`、Execution base；verdict 用 `review_scope: whole-change`、
   map registry base。执行 `../../delivery-pipeline/references/code-review-evidence-preflight.md`，
   preflight bundle 完成前不派生 Standards/Spec 子审查。
4. 实施 worker 只保存候选和修复证据；正式 reviewer 的取消、重派和放行归 coordinator。
   缺失、中断或待复核的独立 verdict 回传 blocked“实现已保存、审查待完成”，不写 completed；
   coordinator 按 Terminal 合同接手，不能把 blocked 当作无需处理。
5. completed 与 blocked 都在最终回复前按 Terminal 回传合同发送公共终态模板。
   工具成功后才声明 FINAL_REPORT 已回传；失败或 Unknown 保留报告、目标与恢复坐标。
