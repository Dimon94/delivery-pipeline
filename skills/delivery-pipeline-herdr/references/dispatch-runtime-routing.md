# CLI/Herdr 调度运行时路由

创建、恢复或替换 worker lane 前读取。Coordinator 是当前 pi/Codex CLI/Claude CLI 会话；
新 worker 都经 Herdr，worker kind 完全由 version 5 work config 的 `agent` 决定：
pi → `herdr-pi-pane`，codex → `herdr-codex-pane`，claude → `herdr-claude-pane`。

恢复既有 lane 直接进入“恢复与切换”，不运行新 lane 的配置 gate。

## 新 lane

implementation lane 先按 `gate-state-machine.md` 实施前置检查运行 `scripts/implementation_gate.py`。
随后每条 lane：

1. 从当前 Integration HEAD 建 Execution Worktree；packet 按 `assets/HERDR_ROLE_DISPATCH_PACKET.md`
   写到 repo 外 `~/.config/delivery-pipeline/packets/<lane_id>.md`。
2. 运行本壳 `scripts/dispatch.py`（参数见 `--help`），capability evidence 按 `model-role-routing.md`
   探测。它一次完成：Coordinator Pane 坐标 readback（`herdr pane current --current` 与
   `HERDR_WORKSPACE_ID`/`HERDR_TAB_ID`/`HERDR_PANE_ID` 一致）、计划解析与冻结、registry
   先于 worker 写入、worker tab 落位与 readback、agent start、packet 单行投递、working 确认
   （重投一次）、lane watcher、registry `running`。成功只回一行 JSON 坐标；失败写 `setup_blocked`
   并回原因。
3. 同批 lane 并发运行 dispatch；默认复用 coordinator 当前所在的 Herdr Workspace，
   只有用户显式要求新 Workspace 才创建。整批成功/失败项都完成 startup readback 后才到达 Dispatch Handoff。

配置或 evidence 校验失败时阻塞并运行 setup，不替换成 coordinator 自身 agent。trusted execution
bootstrap 覆盖已配置 worker 在精确 Execution Worktree 内的 kind-specific startup permission；
不覆盖 remote publication。Herdr unavailable 时输出完整 durable packet 并报告 `dispatch unavailable`。

## 恢复与切换

- 各 kind 按 registry 的 agent/model/effort 与 `herdr` overlay 恢复；配置变化不迁移 running lane。
- replacement 先按 `lane-registry.md` 排除 active writer，再沿原 lane runtime/model/effort。
  replacement 验证 stored agent/model/effort 的实时可用性，不要求当前配置一致；失败时保留
  `setup_blocked`。用户明确选择改配时才经 setup 验证新配置。
- cleanup 只关闭本 lane pane 与本 lane Execution Worktree/branch；保留 Coordinator Pane 及其 Workspace。
