# Lody Configured Role Dispatch Packet

派发与 FINAL_REPORT 使用 `../../delivery-pipeline/references/lane-registry.md` §轻量交接的
固定模板。仅展开当前分支，输入省略不适用项；本壳只追加 transport 字段：

```text
Coordinator session：<coordinator_session_id>（<coordinator_agent>）
Worker target：<agent_config_id> / <model> / reasoningEffort=<effort>
Base：<base_sha>；分支 <prefix>issue-<coordinate> | detached
```

packet 全文作为 `lody_session_create` 的 `prompt`；Worker 合同指向本文件绝对路径，读取 §Worker 执行。
Review 时公共模板的输入补 scope、fixed point、两轴配置与 preflight 路径。

## Worker 执行

从本节进入；公共合同只读 lane-registry 的 Worker 共同行为与终态模板，完整 owner 另读。
commit 加载 gate-state-machine 的实施前置检查；Review 分支在适用时再读。

1. 先对齐 Lody 给的 worktree，再执行 Worker 共同行为：
   - 记录 `git rev-parse --show-toplevel` 作为 worktree 路径，`git branch --show-current` 作为 Lody 初始分支。
   - commit mode：`git switch -c <prefix>issue-<coordinate> <base_sha>`；其他 mode：
     `git switch --detach <base_sha>`。
   - 读回 HEAD 等于 `base_sha`、worktree clean、`git rev-parse --git-common-dir` 等于 Source repo。
     任一不符即 blocked。
2. commit/verdict 的双轴 review 由 worker 按 resolved code-review owner 执行；调用前读取
   `../../delivery-pipeline/references/code-review-evidence-preflight.md`。implementation fixed point
   为 Execution base，whole-change 为 map registry base；preflight bundle 完成前不派生
   Standards/Spec 子审查。子审查用宿主原生 subagent，本轮内同步完成、只读同一 bundle。
   本 lane 的其余工作由 worker 亲自完成；Lody session 与 Operation 工具只由 coordinator 调用，
   需要更多并行时在终态报告写明，由 coordinator 决定。
3. 只有用户能回答的问题：保留现场，以独立一行 `LANE_WAITING <lane_id>` 开头结束本轮，其后写问题、
   已知选项与恢复坐标。Lody 把这条回复投递给 coordinator；回答到达后在本 session 继续。
4. API 400/5xx/网络错误按原重试继续；402 额度错误停止，回传 blocked 与原错误工件。
   output_mode 不符停止写入。
5. completed 或 blocked 都以独立一行 `LANE_DONE <lane_id>` 开头作为最终回复，其后填公共终态模板；
   「现场」写入 worktree 路径与 Lody 初始分支。这条最终回复就是回传：Lody 把它作为 Operation 结果
   投递给 coordinator。
