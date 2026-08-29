# CLI/Herdr 调度运行时路由

首次创建新 work-item lane，或对 existing/replacement lane 执行 transport recovery 前读取。本文件是
canonical CLI 主干的 transport adapter；Coordinator 是当前 pi/Codex CLI/Claude CLI 会话，所有 worker
都通过 Herdr。worker kind 完全由 registry 或 canonical config 的 `agent` 决定；Bootstrap Gearshift
Policy 只改变 eligible pi implementation lane 的启动模型与 Adapter，不改变 runtime kind。

## 选择顺序

1. 记录当前宿主 `coordinator_runtime: pi-cli | codex-cli | claude-cli`；无法唯一识别时报告
   Unknown并让用户确认。固定 `dispatch_runtime: herdr`，验证 Herdr binary、visible session 与 agent kind。
2. **先按 registry 判断 existing/replacement。** 命中 registry row 时按 `lane-registry.md` 的 marker
   分支恢复；existing active lane 直接使用持久 pane/worktree/route，replacement 继续使用持久
   agent/model/effort。v3 Gearshift-enabled replacement 使用持久 Gearshift Projection，legacy v2 缺失字段
   保持 disabled/none。这条路径不读取当前 Worker Role Configuration，禁止运行 setup；registry route
   或所需 runtime/model 不可用时记 `setup_blocked` 并保留现场，不改用 coordinator route。
3. **仅首次创建新 work-item lane** 才加载 `model-role-routing.md`，从 canonical config 读取 route 与
   Gearshift Policy，并验证 model evidence、Gearshift flags 和 setup readback；失败时运行 setup，不替换成
   coordinator 自身 agent。
4. 将 route-owned agent 映射为 runtime：pi → `herdr-pi-pane`，codex → `herdr-codex-pane`，claude →
   `herdr-claude-pane`。新 lane 的 route 可由用户重跑 setup 后改变；existing/replacement 不迁移。
5. `bootstrap_authority: trusted_execution_bootstrap` 覆盖已配置 worker 在精确 Execution
   Worktree 内的 kind-specific startup permission；不覆盖 remote publication。

## Herdr Session 与 Workspace

Coordinator Pane 的 caller context 是新 lane 的唯一默认落点。先验证 `HERDR_ENV=1`，且
`HERDR_WORKSPACE_ID`、`HERDR_TAB_ID`、`HERDR_PANE_ID` 非空；任一缺失即报告
`dispatch unavailable`，不改用其他 client 的 focused session/workspace。验证通过后执行：

```bash
herdr pane current --current
herdr workspace get "$HERDR_WORKSPACE_ID"
```

readback 的 workspace/tab/pane 必须与环境坐标一致。当前 CLI socket就是 Herdr Session Target；
将它与 `herdr session list` 的 socket 唯一匹配后记录 `herdr_session_name`，并记录
`herdr_session_owned: false`；无法唯一匹配时以 Unknown阻塞新 lane。使用裸 `herdr <group> ...`
继承当前 session；不通过 `--session` 搜索、切换或创建另一个 session。

默认复用 coordinator 当前所在的 Herdr Workspace，并把 `HERDR_WORKSPACE_ID` 记为本次新 lane 的
`workspace_id`。只有用户显式要求新 Workspace 才执行 `herdr workspace create` 并使用返回的真实
ID；不重命名当前 Workspace为 map label。workspace 解析是 maximal safe batch 的唯一串行前置，
readback 后同批 tab/pane creation、placement验证、agent start 与 packet delivery并发发出。
已有 active lane始终按 registry 中原 session/workspace恢复；后续新 lane按本次 Coordinator Pane
的 current-workspace 默认重新解析。

## 首次创建新 lane 的 Dispatch Critical Path

existing/replacement 走上述 registry recovery 分支，不进入本节的 config preflight 或 setup。

1. 一次并行 preflight snapshot：ticket/claim/registry、Integration HEAD/clean state、worktree
   path/branch collision、Coordinator Pane 的 current session/workspace/tab/pane、role config 与
   agent model evidence。
2. registry 先写 role、agent、ordinary model/effort、bootstrap route 或 none、Gearshift Projection、
   model evidence、runtime、permission mode、pane/worktree 计划坐标与 base commit，再精确 readback。
3. 从同一 Integration HEAD 创建各 lane Execution Worktree，branch prefix 与 agent kind 一致。
4. 填写 `assets/HERDR_ROLE_DISPATCH_PACKET.md`；按 `model-role-routing.md` 启动 kind-matched CLI。
   Eligible pi lane 从 canonical skill realpath 定向加载 Bootstrap Adapter 并传 Gearshift per-run route；
   disabled lane 不加载、不传相关 flags。
5. 按 `pane-lifecycle-rules.md` 完成落点验证、投递、记账和聚合 Working 确认；单条失败隔离为
   `setup_blocked`，不影响 siblings。
6. 整批成功/失败项都完成 startup readback 后才到达 Dispatch Handoff；单 lane working 不提前 yield。

## 恢复与切换

- `herdr-pi-pane`、`herdr-codex-pane`、`herdr-claude-pane` 均按自己的 registry kind、ordinary/bootstrap
  route 与 Gearshift Projection 恢复；配置变化不迁移 running lane。
- replacement 沿原 lane registry 的 runtime/model/effort；不应用当前配置。legacy v2 row 按
  `lane-registry.md` 解释缺失字段并保持 Gearshift disabled/none。
- cleanup 只关闭本 lane pane并按 `pane-lifecycle-rules.md` 同步 tab label,以及本 lane
  Execution Worktree/branch;保留 Coordinator Pane及承载它的 user-visible session/workspace。
- Herdr unavailable 时输出完整 durable packet并报告 `dispatch unavailable`，不假装已经派发。
