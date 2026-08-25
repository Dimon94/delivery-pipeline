# CLI/Herdr 调度运行时路由

创建、恢复或替换任何 worker lane 前读取。本文件是 canonical CLI 主干的 transport adapter；
Coordinator 是当前 pi/Codex CLI/Claude CLI 会话，所有新 worker 都通过 Herdr，worker kind
完全由 version 2 role config 的 `agent` 决定。

## 选择顺序

1. 记录当前宿主 `coordinator_runtime: pi-cli | codex-cli | claude-cli`；无法唯一识别时报告
   Unknown并让用户确认。当前宿主不改写 worker 配置。
2. 固定 `dispatch_runtime: herdr`。验证 `command -v herdr`、visible Herdr session 与
   `herdr agent start --help` 支持 `pi`、`codex`、`claude` kind。
3. 加载 `model-role-routing.md`，从 role entry 读取 agent/model/effort；三字段不完整或证据
   验证失败时阻塞并运行 setup，不替换成 coordinator 自身 agent。
4. agent 映射 runtime：pi → `herdr-pi-pane`，codex → `herdr-codex-pane`，claude →
   `herdr-claude-pane`。同一 role 可由用户重跑 setup 后改变，existing lane 仍按 registry 恢复。
5. `bootstrap_authority: trusted_execution_bootstrap` 覆盖已配置 worker 在精确 Execution
   Worktree 内的 kind-specific startup permission；不覆盖 remote publication。

## Herdr Session 与 Workspace

运行中的 user-visible `default` session 优先；没有 default 且恰有一个 running session 时使用该
session；其余情况在创建 lane 前让用户选择。记录 `herdr_session_name` 与
`herdr_session_owned: false`。所有 CLI 命令显式使用：

```bash
herdr --session "$herdr_session_name" <group> ...
```

每个 map 一个 Herdr Workspace，首次 lane 前懒创建；workspace label 对应 map 坐标。workspace
解析是 maximal safe batch 的唯一串行前置，readback 后同批 pane create/split、placement 验证、
agent start 与 packet delivery 并发发出。

## Dispatch Critical Path

1. 一次并行 preflight snapshot：ticket/claim/registry、Integration HEAD/clean state、worktree
   path/branch collision、Herdr session、role config 与 agent model evidence。
2. registry 先写 role、agent、model、effort、model_evidence、runtime、permission mode、pane/worktree
   计划坐标与 base commit，再精确 readback。
3. 从同一 Integration HEAD 创建各 lane Execution Worktree，branch prefix 与 agent kind 一致。
4. 填写 `assets/HERDR_ROLE_DISPATCH_PACKET.md`；按 `model-role-routing.md` 启动 kind-matched CLI。
5. 按 `pane-lifecycle-rules.md` 完成落点验证、投递、记账和聚合 Working 确认；单条失败隔离为
   `setup_blocked`，不影响 siblings。
6. 整批成功/失败项都完成 startup readback 后才到达 Dispatch Handoff；单 lane working 不提前 yield。

## 恢复与切换

- `herdr-pi-pane`、`herdr-codex-pane`、`herdr-claude-pane` 均按自己的 registry kind、model、effort
  恢复；配置变化不迁移 running lane。
- replacement 沿原 lane runtime/model/effort，除非用户先更新配置且确认原 active writer 不存在。
- cleanup 只关闭本 lane pane与 Execution Worktree/branch，保留 user-visible session 与 map workspace。
- Herdr unavailable 时输出完整 durable packet并报告 `dispatch unavailable`，不假装已经派发。
