# Orca 共享 registry overlay caller

由 `delivery-pipeline-orca` SKILL.md 的「共享 registry caller」节引入；本文件承载 payload
schema 与一致性检查细节。调用入口见 SKILL.md。

执行通过唯一 caller 脚本：

```bash
python3 scripts/registry_overlay.py apply --payload <json>
```

## Payload schema

```json
{
  "action": "<见下表>",
  "kind": "map|lane",
  "row": "<当前 registry row 完整对象>",
  "arguments": {"<action 对应字段>": "..."}
}
```

request 必须精确包含 `action`/`kind`/`row`/`arguments` 四键；脚本返回改写后的 row，registry
文件的写回与读回由 caller 完成（`persist_overlay` 提供乐观并发核对）。

| action | kind | arguments |
| --- | --- | --- |
| `bind_map_run` | map | `run_id`、`coordinator_host_id`、`coordinator_terminal_handle` |
| `rebind_map_coordinator` | map | `observed_run_id`、`coordinator_host_id`、`coordinator_terminal_handle`、`writer_active` |
| `bind_lane_task` | lane | `map_row`（map row 对象）、`task_id` |
| `bind_attempt` | lane | `dispatch_id`、`terminal_handle`、`worktree_selector`、`execution_host`、`attempt_index` |
| `record_native_coordinates` | map/lane | `run_id`/`task_id`/`dispatch_id`/`terminal_handle`/`worktree_selector`/`execution_host`/`attempt_index` 的子集 |
| `record_readback` | map/lane | `coordinates`（可选）、`source`、`observed_at`、`evidence_reference`、`replace`（可选） |
| `record_mutation` | map/lane | `operation`、`request_id`（可选）、`receipt_reference`（可选）、`replace`（可选） |
| `record_observation` | map/lane | `source`、`observed_at`、`evidence_reference`、`replace`（可选） |
| `recover_map` / `recover_lane` / `recover_attempt` | map/lane | 恢复期身份核对字段；只返回 `ready`/`blocked`，不改写 row |

字段以 canonical lane registry schema 为准；runtime-specific 内容只允许嵌套在 `orca`
opaque overlay 槽位，不改共享顶层 schema。

## 一致性检查

`registry_overlay.py` 校验：request 精确四键；action 已知且与 kind 匹配；row 带 canonical
markers；runtime-specific 身份坐标（Run/Task/Dispatch/terminal/worktree selector/execution host）
冲突即拒绝覆盖；`record_mutation` 先 intent 后补 request/receipt，同身份幂等、冲突 fail-closed；
`record_observation` 证据冲突保留旧证据；`bind_attempt` 要求 lane 已绑定 Run/Task；recover 系要求
registry 与 native 身份一致且旧 writer 已排除。不满足即失败，不写 registry。

本脚本不校验也不推进项目 state（`integrated`/`consumed`/`close_pending`/`closed`）；项目侧
final/cleanup 的顺序门禁由 `worker_lifecycle.py` 与 `project_lifecycle.py` 承载，coordinator
必须在门禁通过后才把 state 写入 registry。
