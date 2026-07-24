---
name: wayfinder-implement-orchestrator
description: Dispatch existing implementation tickets to fresh Codex panes as a verified maximal safe batch.
---

# Wayfinder Implementation Dispatcher for Claude

把一组已经写好的 implementation tickets 自动分配给 Herdr 中的 fresh Codex panes。
这个 skill 的产物是可核验的派发结果，不是实现结果。

## 输入

接受 tracker issue URL 或编号列表：

```text
/wayfinder-implement-orchestrator <issue1> [issue2 ...] [--worktree-root <path>]
```

## 派发流程

1. 读取 repo instructions、tracker 配置，以及每张输入票的标题、状态、依赖、assignee、
   acceptance、显式文件足迹和 labels。只读取现有票面；不改写票的范围。
2. 排除 closed、已被其他 owner claim、prerequisites 未完成或已有活跃 pane 的票，并把
   原因记为 `deferred`。
3. 从剩余票中计算 `maximal safe batch`：
   - dependency 相连的票按依赖顺序串行；
   - 显式文件或可变资源足迹重叠的票串行；
   - 无法证明写集合互不相交的票串行；
   - 其余票并发。
   按 tracker priority、再按输入顺序做确定性选择。
4. 确认 `HERDR_ENV=1`，然后完整读取
   `references/herdr-dispatch.md`。按其中规则为 batch 中的每张票创建或验证一个真实、独立
   的 Git worktree。worktree 创建或验证失败的票直接记为 `deferred`。
5. 以验证后的 worktree 作为 `--cwd`，为每张票启动一个 Codex pane，并投递：

   ```text
   $implement <issue-url>
   ```

6. 对每个 pane 核对 workspace、tab、cwd、pane label 和 agent status；`cwd` 必须精确等于
   该票的 worktree 根目录。落点错误时关闭错误 pane 并重试一次；第二次仍失败就记为
   `deferred`，继续派发其他票。
7. 返回派发表。每张输入票必须恰好出现一次：

   ```text
   | ticket | result | pane | workspace/tab | worktree | reason |
   |---|---|---|---|---|---|
   | <url> | dispatched | <pane id> | <coords> | <path> | ready and conflict-free |
   | <url> | deferred | - | - | - | <dependency/conflict/setup reason> |
   ```

## 完成标准

每张输入票都已被验证派发，或以可核验原因记为 `deferred`。派发完成即结束；执行监控、
结果收敛、集成、tracker 更新和远程发布由调用方负责。

## 边界

- 只接收上游已经准备完成的 implementation tickets，并原样调度。
- 只根据现有 dependency 与写足迹做分配；信息不足时保守串行。
- 每个 dispatched ticket 固定由 Codex 在独立 Git worktree 中执行。
- 不实现 ticket，不 review，不 commit，不集成，不 push，不开 PR/MR。
- 不创建 Herdr workspace；找不到匹配 workspace 时全部记为 `deferred`。
