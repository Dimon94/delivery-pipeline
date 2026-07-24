# Wayfinder Implement Orchestrator

[English README](README.md)

一个可恢复的 Codex/Claude 交付链：

```text
idea/map -> discovery -> spec -> implementation tickets
  -> 自动分配 Codex worktrees -> integration -> summary PR/MR
```

新会话里给出链路中的任意 issue 即可。skill 会沿 tracker relationships 向上、向下重建
map/spec/ticket 状态，并从最早未完成的 gate 自动继续。

各阶段 owner 保持权威：`wayfinder` 负责 discovery，`to-spec` 负责 spec，`to-tickets`
负责发布 implementation tickets，`implement` 负责单张票。orchestrator 只验证持久链接和
状态转换，不再增加第二套票面判断。

执行自动分配：每张 ready ticket 对应一个隔离的 Codex worker 和一个 Git worktree。
dependency 与 mutable-resource 冲突只串行受影响的 tickets。
每个被派发的 child 都保存 pane/thread ID、worktree、branch、commit 和生命周期状态。
新会话会先恢复已有 child 并重挂 terminal listener。Claude 在集成与 focused checks 成功后
自动关闭对应 Codex pane。

## 安装

先安装 `skill-bundle.json` 中的依赖，然后运行：

```bash
./scripts/install.sh --target all
```

Codex 和 Claude 安装都会软链接到当前 checkout。

## 使用

Codex：

```text
使用 $wayfinder-implement-orchestrator 继续 <任意 map/spec/ticket issue>。
```

Herdr 中的 Claude：

```text
使用 /wayfinder-implement-orchestrator <任意 map/spec/ticket issue>。
```

## 校验

```bash
python3 scripts/validate.py
```
