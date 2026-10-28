# ADR-0015: T3 Code Transport Shell

**Status:** Proposed（决策 1–13 已逐项确认；Unknown 待 tracer 实测后改 Accepted）
**Date:** 2026-10-28
**Decider:** User (Dimon)

## Context

T3 Code 0.1.3 由宿主内置 MCP 工具（`orchestrator_capabilities`、`delegate_task`、`task_status`、
`task_cancel`、`t3_thread_*`、`t3_worktree_*`）加注入提示词驱动会话编排，不经 skill。
其 worktree、终态唤醒与线程恢复语义与 Herdr pane、Codex App task、Orca 都不同，
放进现有任一壳都会让该壳混入第二种 transport。

## Decision

1. 新增平级 transport 壳 `skills/delivery-pipeline-t3code/`，依赖方向只从壳指向核心。
2. 核心 `lane-registry.md` 只扩共享枚举：`runtime` 加 `t3-task`，`dispatch_runtime` 与
   `coordinator_runtime` 加 `t3code`，新增与 `orca` 平级的 `t3code` opaque overlay 槽位；
   coordinator 实际宿主 provider 记在 overlay 内。
3. `GLOSSARY.md` 的 Entrypoint Layering 列入本壳。
4. 派发原语：新 lane 一律 `delegate_task(mode:"async", isolation:"worktree")`，取其完成唤醒、
   `task_cancel` 级联与 `task_status` 读回；不用 `t3_thread_launch`/`create_threads`（顶层线程，
   无完成唤醒，且 T3 限定为用户要求新线程时使用）。T3 为每个子任务新建 worktree，
   基点固定为父线程 checkout HEAD，分支为临时 `t3/<hex>`。
5. Execution base 对齐：coordinator 留在 Source Worktree；packet 携带 `base_sha`（Integration HEAD，
   独立票模式为刚 fetch 的远端默认分支 SHA）。worker 首步 `git switch -c <agent>/issue-N <base_sha>`
   并读回 HEAD、clean、common dir；coordinator 在 startup readback 核对。registry `branch` 只登记
   worker 自建分支，T3 临时分支在 Cleanup 删除。不采用把 coordinator 绑到 Integration Worktree
   的方案：会结束当前会话、独立票模式仍对不齐、并切换 coordinator 目录。
6. 模型配置映射：复用 CLI 配置实例 `~/.config/delivery-pipeline/model-roles.json`。壳内映射
   `agent` → providerInstanceId（pi→`pi`，codex→`codex`，claude→`claudeAgent`）和
   `effort` → option name（pi→`thinking`，codex→`reasoningEffort`，claudeAgent→`effort`）。
   每批派发前用 `orchestrator_capabilities(search)` 核对 model id 完全一致、effort 在允许值内；
   不匹配就 blocked 并给候选列表，交 setup 改配置。不做 suffix 匹配或自动补前缀。
7. Terminal 信号改为 T3 原生完成唤醒：派发时记 `taskId`/`childThreadId`/`link`；完成后 T3 唤醒，
   coordinator 调用 `task_status(taskId)` 读 `summary`；换线程恢复用 `t3_thread_read(childThreadId)`。
   `summary` 首行保留 `LANE_DONE <lane_id>` 锚点，后跟 canonical 终态模板。无 watcher，不轮询。
   HITL lane 由用户在子线程完成对话，然后回 coordinator 触发 fan-in。
8. v1 只支持 direct 单轮。配置了 `execution` 的 staged lane 按核心合同保持 `blocked`。
   staged 适配（`t3_thread_configure` + `t3_thread_send` 接续）另开票。
9. testing（checks）与 whole-change review（verdict）各为 `delegate_task(isolation:"worktree")` lane；
   packet `base_sha` 为当前 Integration HEAD，worker `git switch --detach <base_sha>` 对齐，不建分支、
   不提交，交付前读回 clean；review fixed point 为 map registry base commit。Integration（cherry-pick）
   由 coordinator 在 Map Integration Worktree 亲自执行，不委派。不采用 Codex App 的
   `mode:"wait"` 串行委派：会阻塞 coordinator 并新增一套承载合同。
10. worker 子审查授权：packet 只授权 resolved owner 规定的内部子审查（当前为 `code-review` 的
    Standards/Spec 两路），用宿主原生 subagent 在本轮内同步完成、只读同一 bundle；worker 其余工作
    亲自完成。worker 不调用 `delegate_task`，lane 树保持一层，`task_cancel` 与 Cleanup 只覆盖
    registry 登记的 lane。

11. Cleanup 六步映射，由 coordinator 显式执行：（1）`t3_thread_organize(action:"archive")` 释放 transport；
    （2）`git worktree remove <registry.worktree>`，不加 `--force`，not-clean 时停下；（3）删 worker 自建分支
    和 T3 临时分支（名字以 `t3_thread_read` 读到的线程元数据为准）；（4）读回线程已归档、worktree 与两分支
    都不存在；（5）失败写 `close_pending` 并保留坐标，已完成的 Integration 不回滚；（6）成功写 `closed`
    并重算 ready frontier。独立票模式下 2–6 步推迟到 `release_stage: deployed` 读回之后。不依赖 T3
    自动清理策略：触发时机不归 coordinator 控制，默认值 Unknown。
12. HITL lane 问题处理：coordinator 发现 `hasPendingQuestion: true` 时，写 lane 为 `awaiting_human`，
    在聊天里给出 `link` 让用户去子线程回答。用户答完后子线程继续跑到终态，再唤醒 coordinator 做 fan-in。
    coordinator 不代替用户回答，除非用户在 coordinator 聊天里明确给了答案并确认转发。
13. 并发上限：不设壳级上限，完全依赖 T3 的 `maxBatchThreads: 20`。coordinator 按 canonical ready frontier
    计算可派发项，一批全部调 `delegate_task`，T3 自己排队。超过 20 个时前 20 个立即开始，其余排队。

Unknown（待 tracer 实测）：`delegate_task` 路径是否触发 T3 的临时分支自动改名；
T3 setup 脚本按父 HEAD 执行后，worker 切到 `base_sha` 是否需要重跑依赖安装。

## Consequences

- registry 可解析 T3 lane；现有三个壳行为不变。
