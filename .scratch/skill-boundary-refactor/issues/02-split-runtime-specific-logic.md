# 02 — runtime 相关文件的拆分目标

Status: open
Type: wayfinder:grilling
Blocked by: 01

## Question

01 票合并了 runtime 无关的文件后，剩下的 runtime 相关文件要决定拆到哪里去。
当前的派发机制已经有了正确的拆分范式：`pane-dispatch`（Claude 侧）是独立 skill，
不试图与 Codex 侧同步。现在要把同样的逻辑应用到 `delivery-pipeline` 内部的
runtime 相关逻辑。

已知的 runtime 相关文件（来自 07 票的漂移分析）：

- `references/child-monitoring.md`（82/33 行 diff，基本重写）
  - Claude 侧：Herdr pane listener（`herdr agent wait`）
  - Codex 侧：`Agent` tool 后台 subagent 的完成通知
- `SKILL.md` 的派发段落（158/107 行 diff 中的一部分）
  - Claude 侧："通过 `/pane-dispatch` 创建 pane"
  - Codex 侧："通过 `send_message_to_thread` 创建 thread"（如果有的话）

要决定的点：

1. **拆分粒度**。runtime 相关逻辑是：
   - (a) 拆到独立的派发 skill（`pane-dispatch` / 未来的 `thread-dispatch`）
   - (b) 保留在 `delivery-pipeline` 里，但分成 runtime-specific 的 reference 文件
     （`references/child-monitoring-claude.md` / `references/child-monitoring-codex.md`）
   - (c) 混合：派发机械拆到独立 skill，但监听/恢复逻辑保留在编排器里（按 runtime 分文件）

2. **`child-monitoring.md` 的归属**。这个文件讲的是"如何监听 child 的 terminal 状态"，
   但 Claude 和 Codex 的监听机制完全不同（pane listener vs Agent tool 通知）。要定：
   - 是否把 pane listener 逻辑移到 `pane-dispatch/references/`
   - 是否把 Agent tool 通知逻辑移到 `delivery-pipeline/references/`（因为它是 runtime 无关的）
   - 还是保持现状，只是明确标注哪些是 runtime 相关的段落

3. **Codex 侧的 thread-dispatch**。当前只有 `pane-dispatch`（Claude 侧），
   Codex 侧的 thread-based dispatch 还没有独立 skill。要定：
   - 是否在本 map 内创建 `thread-dispatch` skill
   - 还是先记录为已知债务，等 Codex app 的跨线程调度需求明确后再做
   - 如果是后者，`delivery-pipeline` 的 Codex 侧如何引用尚未存在的 `thread-dispatch`

4. **`SKILL.md` 的派发段落**。编排器的入口文件（`SKILL.md`）里有"如何派发"的说明，
   这部分是 runtime 相关的。要定：
   - 是否在 `SKILL.md` 里只写"通过 `<runtime-specific-dispatch-skill>` 派发"，
     具体机制留给派发 skill 自己描述
   - 还是在 `SKILL.md` 里分别写 Claude 和 Codex 的派发方式（但这会导致 `SKILL.md` 分叉）

## 落地

决策定下后直接改文件（本 map 授权 execution）：按决策拆分 runtime 相关的文件或段落，
移动到正确的归属位置，跑 `python3 scripts/validate.py`。
