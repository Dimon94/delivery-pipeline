---
name: delivery-pipeline-herdr
description: 通过 Herdr 启动或恢复交付编排的 CLI transport 壳。
disable-model-invocation: true
---

# Delivery Pipeline（Herdr 壳）

本 skill 是 `../delivery-pipeline/SKILL.md` 核心链路的 transport 壳，供 pi、Codex CLI 与
Claude CLI 使用。先完整读取 canonical 主干的 Run 循环；本文件只声明哪些 Action 由本壳程序执行。

Epic 输入按 `../delivery-pipeline/references/epic-scheduling.md` 从 Issue 恢复各 MMF，使用本壳派发和等待终态。

## Run 循环

1. 当前调用会话就是 coordinator，记录 `coordinator_runtime: pi-cli | codex-cli | claude-cli`、
   `dispatch_runtime: herdr`。每次唤醒调 `scripts/driver_run.py run <map 目录>`：退出 0 结束本轮；
   退出 10 执行打印的一行 Action，按 canonical 用 `driver.py record` 交回后再调 run。
2. `dispatch` 由本壳程序执行：driver.json `dispatch` 提供 `config`、`evidence`，`transport.herdr` 提供
   `worktrees_root` 时，`driver_run.py` 建 Execution Worktree、渲染 packet 并调 `scripts/dispatch.py`
   一次完成落位、启动、投递、watcher 与 registry。缺配置或 dispatch 失败时 Action 交回，coordinator 按
   `references/dispatch-runtime-routing.md` 验证 Herdr session/workspace/tab/pane 后派发；只有用户显式要求新
   Workspace 才创建。worker kind 由 version 5 work config 的 `agent` 决定（pi → `herdr-pi-pane`、codex → `herdr-codex-pane`、claude → `herdr-claude-pane`、antigravity → `herdr-agy-pane`），
   packet 使用 `assets/HERDR_ROLE_DISPATCH_PACKET.md`。
3. 唤醒由 `scripts/lane-watch.sh` 负责：map 有 driver.json 时，watcher 见到终态行先调
   `driver_run.py watch`，wait 或程序已执行完时不唤醒 coordinator，需要宿主时带 Action 唤醒一次。
   终态信号与 role-aware outcome 见 `references/child-monitoring.md`。
4. replacement 按 `references/dispatch-runtime-routing.md` 的「恢复与切换」。
5. 当前会话明确选择 Codex App 或 Orca 时退出本壳，改用对应入口；同一 map 不静默混合新 lane
   transport。existing lane 始终按 registry runtime 恢复。无 driver.json 的旧 map 按
   `references/child-monitoring.md` 的旧 fan-in 合同推进，直到下一次 Plan Review。

完成标准：Driver 输出 `done`；Herdr pane、Execution Worktree、registry 与 Integration branch 一致，
其余完成标准沿用 canonical 主干。

## Coordinator 恢复

沿 canonical `../delivery-pipeline/references/fresh-session-boundaries.md` §Coordinator Recovery
在原 map registry 保存六项短记录；恢复再核验真实 pane、Git、active writers 与当前 gate 证据。
Pi coordinator 需要可控压缩且本机版本支持 `/compact [instructions]` 时，先完成该记录的
持久 readback，再将记录正文、未决约束和原证据指针交给 `/compact`；压缩后核对摘要。
自动压缩和其他宿主的能力以实际接口为准。

## References

- `scripts/driver_run.py`：Driver run 循环与 Herdr dispatch 执行器。
- `references/dispatch-runtime-routing.md`：新 lane 经 `scripts/dispatch.py` 派发、恢复与 replacement。
- `references/pane-lifecycle-rules.md`：worker tab 拓扑、terminal signal 与 watcher。
- `references/child-monitoring.md`：终态信号、role-aware outcomes、fan-in。
- `assets/HERDR_ROLE_DISPATCH_PACKET.md`：worker packet 模板。
