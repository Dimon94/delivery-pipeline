# ADR-0016: Lody Transport Shell

**Status:** Proposed（决策待用户逐项确认；Unknown 待 tracer 实测后改 Accepted）
**Date:** 2026-10-29
**Decider:** User (Dimon)

## Context

Lody 通过宿主内置 MCP 工具（`lody_session_create`、`lody_session_chat`、`lody_session_status_many`、
`lody_session_history`、`lody_session_archive`、`lody_operation_*` 等）编排会话。子 session 可带
Lody-managed git worktree，跨 session 工作是 durable Operation，结果在调用方轮次释放后或随下一条
用户输入投递。被其他 session 发起的轮次禁止反向 chat 回发起方（`REVERSE_CHAT_FORBIDDEN`）。
这套 worktree、结果投递与恢复语义与 Herdr pane、Codex App task、T3 task、Orca 都不同。

## Decision

1. 新增平级 transport 壳 `skills/delivery-pipeline-lody/`，依赖方向只从壳指向核心。结构沿
   ADR-0015 的 T3Code 壳，承接 Codex App 壳的“宿主原生任务 + 宿主管理 worktree”思路。
2. 核心 `lane-registry.md` 只扩共享枚举：`runtime` 加 `lody-session`，`dispatch_runtime` 与
   `coordinator_runtime` 加 `lody`，`model_evidence` 加 `lody-run-config`，新增与 `t3code` 平级的
   `lody` opaque overlay 槽位；coordinator 宿主 agent 记在 overlay 内。
3. 派发原语：新 lane 一律 `lody_session_create(operationId: <lane_id>, useCurrentSessionAsParent: false,
   workContext: {kind: local, projectId, worktree: true})`；同批在同一轮并行调用，用 lane_id 作
   Operation 去重键。不用 `lody_session_create_many`：单批一个 Operation id 不能逐 lane 恢复。
4. Execution base 对齐：沿 ADR-0015 决策 5。coordinator 留在 Source Worktree；worker 首步
   `git switch -c <agent>/issue-N <base_sha>`（非 commit mode 为 `--detach`），不依赖 Lody `branch` 参数。
5. 模型配置：复用 CLI 实例 `~/.config/delivery-pipeline/model-roles.json`，schema 与 setup 不变。
   `agent` 按 `agentType` 映射到 coordinator machine 上唯一可用的 Lody agent config；model 须与
   `runConfig.models[].id` 完全一致，effort 属于该 model 的 `reasoningEffortValues`。不采用 Codex App
   壳的独立 `config/models.json`：Lody 承载的仍是 pi/codex/claude，worker kind 与 CLI 配置同义。
6. Terminal 信号改为 Lody Operation 结果投递：worker 最终回复首行 `LANE_DONE <lane_id>`，其后为
   canonical 终态模板；coordinator 在 Dispatch Handoff 结束本轮，不轮询。worker 不调用
   `lody_session_chat` 回传（与 Codex App 壳的 `send_message_to_thread` 回传不同）。
7. HITL：worker 以 `LANE_WAITING <lane_id>` 结束本轮，使 Operation 完成并唤醒 coordinator；用户在子
   session 回答，或在 coordinator 对话给出答案并同意转发后由 `lody_session_chat` 代交。
8. v1 只支持 direct 单轮。`lody_session_chat` 无逐轮 model 参数，staged lane 保持 `blocked`。
9. testing（checks）与 whole-change review（verdict）各为一条 Lody lane；Integration 由 coordinator
   在 Map Integration Worktree 亲自执行，沿 ADR-0015 决策 9。
10. worker 子审查只用宿主原生 subagent；Lody session 与 Operation 工具只由 coordinator 调用，lane 树保持一层。
11. Cleanup 六步：`lody_session_archive` → `git worktree remove`（不加 `--force`）→ 删 worker 分支与
    Lody 初始分支 → readback → 失败 `close_pending` → 成功 `closed`。独立票模式 2–6 步推迟到 deployed。
12. 并发：不设壳级上限，按 canonical ready frontier 一批派发。

Unknown（待 tracer 实测）：
- Lody `agentType` 对 codex/claude 的实际取值（本机当前只读到 `pi`）。
- `lody_operation_get` 在子 session 首轮结束前能否读回 target sessionId 与 worktree 路径。
- Lody worktree 的基点、分支命名，以及 `lody_session_archive` 是否删除 worktree。
- 用户直接在子 session 回答 HITL 后，该轮结果是否也投递给 coordinator。
- Lody local project 报 `isGit: false` 的仓库（如 bare repo + 外部 worktree 布局）无法建子 worktree；
  v1 在 preflight 报 `dispatch unavailable`，是否补 coordinator 自建 worktree 的回落另开票。

## Consequences

- registry 可解析 Lody lane；现有四个壳行为不变。
- Lody 工具调用只存在于 `delivery-pipeline-lody` 树，`scripts/validate.py` 强制。
