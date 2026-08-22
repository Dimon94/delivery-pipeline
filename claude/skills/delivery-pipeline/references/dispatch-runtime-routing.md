# Coordinator Runtime Routing

本 entrypoint 的 Coordinator Runtime 是 `claude-cli`，调度 transport 固定为 Herdr：

```yaml
coordinator_runtime: claude-cli
dispatch_runtime: herdr
```

通过 `/pane-dispatch` 管理 Herdr workspace、tab、pane、startup probe、listener 和 terminal
readback。worker kind 是独立的第二条轴：

1. 用户显式指定 Codex CLI 或 Claude CLI 时采用该 kind。
2. 否则按 `frontier-lanes.md`：frontend/design → `herdr-claude-pane`，backend/other →
   `herdr-codex-pane`。
3. 每条 existing lane 按 registry 的 `runtime` 恢复；本次选择只影响新 lane。
4. replacement 前必须排除 original active writer，不迁移 running pane。

Codex App 原生 thread tools 不属于本 entrypoint；需要 Codex App native Dispatch 时，应从
Codex App 使用 Codex entrypoint。

完成标准：map registry 已 readback Coordinator Runtime/dispatch transport，每条 lane 的 packet、
pane kind、worktree branch 和 registry runtime 一致。
