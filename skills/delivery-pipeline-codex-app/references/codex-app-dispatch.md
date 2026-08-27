# Codex App Native Dispatch Adapter

仅 `delivery-pipeline-codex-app` 加载。本文件拥有 Codex App task/thread transport、App registry
overlay 与六角色 fan-in；canonical CLI/Herdr 主干不读取它。

## Capability

`list_projects`、`create_thread`、`list_threads`、`read_thread`、`wait_threads`、
`send_message_to_thread`、`set_thread_title`、`set_thread_archived` 与
`list_archived_threads` 必须全部可用；缺一项就不能声称 native Dispatch 可用。

## Role Coverage

| Role/work | Output mode | Fan-in |
|---|---|---|
| planning / design HITL | `artifact` | artifact/tracker readback → consumed |
| design/frontend/backend implementation | `commit` | cherry-pick + focused checks → integrated |
| testing | `checks` | check evidence readback → consumed |
| review | `verdict` | verdict/findings readback → consumed |

所有 delegated roles 使用 `../assets/APP_ROLE_DISPATCH_PACKET.md`；没有 role 可以回落到不存在的
CLI config。Map creation与用户 gate判断留在当前 App coordinator。

## App Registry Overlay

App lane 在 canonical role/state字段之外增加：

```yaml
runtime: codex-thread
agent: codex-app
model: app-owned
effort: app-owned
model_evidence: app-owned
agent_permission_mode: app-owned
project_id: <Source-owner-projectId>
host_id: <host-id>
thread_id: <id>
thread_archived: true | false | unknown
```

这些字段只定义在本 App reference，不进入 canonical Herdr registry schema。

## 创建

1. 解析并持久化 Source owner projectId；project/path 未变化时复用。
2. 按 `task-coordinate-title.md` 生成 role-aware title；同批 lanes 并行调用 `create_thread`，显式
   设置 title、project 与 Integration branch `startingState`。App 拥有 Execution Worktree。
3. 只返回 `clientThreadId` 时用 `list_threads` 按 title/project/lane 找 ready task；不能把
   clientThreadId 当 threadId。
4. 聚合 readback：task 属于 owner project、worktree common dir属于 Source repo、base commit
   等于 dispatch 时 Integration HEAD、cwd 不在 Source/Integration Worktree。
5. 写 base registry + App overlay并精确 readback；task 已接受 packet后写 running/awaiting_human。

## Role-aware Fan-in

terminal 后 `read_thread` 一次并验证 output mode：

- `commit`：要求 terminal commit、内嵌 code-review 的 Review fixed point 等于 lane base commit、
  Review Evidence Bundle readback与 clean/declared dirty state，按 dependency order cherry-pick；
  focused checks通过后写 integrated。
- `artifact`：验证 tracker/artifact坐标；无必要 repo 变更时 worktree必须 clean，写 consumed。
- `checks`：验证测试命令/结果且 worktree clean，写 consumed；失败阻塞 review。
- `verdict`：验证 Review fixed point 等于 map registry base commit、Review Evidence Bundle readback、
  review verdict/findings且 worktree clean，写 consumed；blocking finding阻塞 closeout。

非 commit lane 不要求 commit，也不 cherry-pick；unexpected file changes fail closed。

## 恢复、Archive 与 Cleanup

- 默认不等待 running task；用户明确 monitor/wait 或 terminal signal 后才一次有界
  `wait_threads` snapshot。
- active lane 用 project_id/host_id/thread_id恢复；task 消失但持久 evidence存在时沿 evidence fan-in。
- integrated/consumed 后调用 `set_thread_archived({threadId, hostId, archived: true})`，再用
  `list_archived_threads` readback。成功写 closed；archive失败写 close_pending并保留坐标。
- commit lane focused checks失败时 task保持未归档；artifact/checks/verdict lane证据失败同样保留 task。

完成标准：六角色都有 task transport、output-mode fan-in与 archive路径；App overlay、task、
App-managed Execution Worktree 与持久证据一致。
