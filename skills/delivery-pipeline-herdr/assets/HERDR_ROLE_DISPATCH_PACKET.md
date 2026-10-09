# Herdr Configured Role Dispatch Packet

派发与 FINAL_REPORT 使用 `../../delivery-pipeline/references/lane-registry.md` §轻量交接的
固定模板。仅展开当前分支，输入省略不适用项；本壳只追加两个 transport 字段：

```text
Coordinator pane：<session/workspace/tab/pane>
Worker pane：<session/workspace/tab/pane>
```

coordinator 从 version 5 配置冻结 agent/model/effort、implementation mode/source 与阶段计划，
写入原 registry 后再启动。公共模板的输入引用冻结计划、实施前置证据；Review 时补 scope、
fixed point、两轴配置与 preflight 路径。用户在 pane 换模时记录实际证据，继续按交付验收。

## Worker 执行

1. 执行公共模板的 Worker 共同行为；只在已核验的 Execution Worktree 写入。
   JS commit 提交前运行 `pnpm install --frozen-lockfile`；assets 变更加对应 app 的 asset-inventory。
2. commit/verdict 的双轴 review 由 worker 按 resolved code-review owner 执行；调用前读取
   `../../delivery-pipeline/references/code-review-evidence-preflight.md`。implementation fixed point
   为 Execution base，whole-change 为 map registry base；preflight bundle 完成前不派生
   Standards/Spec 子审查，完成原始独立结论后才交付。
3. 仅 staged：按公共 registry 的 Prewalk Checkpoint / Continuation Overlay 生成并核验完整
   checkpoint，snapshot 重定向落盘。首改与最小检查后输出独立完整行
   `PREWALK_READY <lane_id> <checkpoint_path>` 并立即结束本轮、保留 dirty；该信号不授权 fan-in。
   原 runtime 的 `WORKER_STOPPED <lane_id> <checkpoint_path>` 核验通过后才由 coordinator
   接续；checkpoint helper 不发送接续请求，staged 不可用时 blocked，不降级 direct。
4. API 400/5xx/网络错误按原重试继续；402 额度错误停止，回传 blocked 与原错误工件。
   output_mode 不符停止写入；运行中 model/effort 变化记录来源，不替用户切换配置。
5. completed 或 blocked 都填公共终态模板，再在报告外输出独立一行 `LANE_DONE <lane_id>`。
   coordinator 按 `../references/pane-lifecycle-rules.md` 建立 watcher，阶段 marker 的持久去重与
   终态监听沿该合同执行。

## 设备与构建分支

设备/截图/构建 lane 的输入引用本节；其他 lane 不复制：截图、二进制和 dump 只落盘，视觉
对照交人检；逐页截图每 3–4 页保存 commit。大 JSON 定位修改；adb/logcat/构建输出截断到
200 行以内，构建用后台与轮询。每次 adb input 前核目标包在前台，抢占或不符停止并报告 STOLEN。
