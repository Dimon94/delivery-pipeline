---
name: wayfinder-implement-orchestrator
description: Dispatch existing implementation tickets to fresh Codex tasks as a verified maximal safe batch.
disable-model-invocation: true
---

# Wayfinder Implementation Dispatcher

把一组已经写好的 implementation tickets 自动分配给 fresh Codex tasks。这个 skill 的产物是
可核验的派发结果，不是实现结果。

## 输入

接受 tracker issue URL 或编号列表：

```text
$wayfinder-implement-orchestrator <issue1> [issue2 ...]
```

编号无法唯一解析到项目时，从当前 repo 的 tracker 配置解析；仍不唯一就把该项记为
`deferred` 并说明缺少的坐标。

## 派发流程

1. 读取 repo instructions、tracker 配置，以及每张输入票的标题、状态、依赖、assignee、
   acceptance、显式文件足迹和 labels。只读取现有票面；不改写票的范围。
2. 排除 closed、已被其他 owner claim、prerequisites 未完成或已经有活跃执行 task 的票。
   把每个排除项记为 `deferred` 并保留证据。
3. 从剩余票中计算 `maximal safe batch`：
   - dependency 相连的票按依赖顺序串行；
   - 显式文件或可变资源足迹重叠的票串行；
   - 无法证明写集合互不相交的票串行；
   - 其余票并发。
   按 tracker priority、再按输入顺序做确定性选择。
4. 找到源码仓库所属的 `Source owner projectId`。每张入选票都用同一个 projectId 创建
   独立 Codex worktree task；不得把两个 writer 放进同一个 worktree。
5. 为 batch 中每张票调用 `create_thread`，投递一个最小、自足的执行指令：

   ```text
   使用 $implement 实现 <issue-url>。
   只负责这一张票；以 ticket、repo instructions 和当前 worktree 为真相源。
   不处理 sibling tickets，不做远程发布。
   ```

6. 每个 task 创建后做一次 startup probe：确认 task 已收到指令、`projectId` 属于同一
   仓库、`cwd` 位于它自己的 worktree。错误落点立即停止使用；用同一 projectId 重建一次，
   第二次仍失败就记为 `deferred`。
7. 返回派发表。每张输入票必须恰好出现一次：

   ```text
   | ticket | result | task | worktree | reason |
   |---|---|---|---|---|
   | <url> | dispatched | <task id> | <path> | ready and conflict-free |
   | <url> | deferred | - | - | <dependency/conflict/setup reason> |
   ```

## 完成标准

每张输入票都已被验证派发，或以可核验原因记为 `deferred`。派发完成即结束；执行监控、
结果收敛、集成、tracker 更新和远程发布由调用方负责。

## 边界

- 只接收上游已经准备完成的 implementation tickets，并原样调度。
- 只根据现有 dependency 与写足迹做分配；信息不足时保守串行。
- 不实现 ticket，不 review，不 commit，不集成，不 push，不开 PR/MR。
- 不把 deferred 当失败；它是下一轮在前置解除或资源空闲后重新派发的输入。
