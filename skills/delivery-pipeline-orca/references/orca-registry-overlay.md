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
  "action": "record_dispatch_intent|record_native_coordinates|record_readback|record_final_state|record_cleanup_state",
  "registry_path": "<abs path>",
  "lane_id": "<stable lane id>",
  "map_id": "<map id>",
  "runtime": "orca",
  "dispatch_runtime": "orca",
  "coordinator_runtime": "orca-terminal",
  "role": "<planning|design|frontend|backend|testing|review|map>",
  "task_type": "<configured task type>",
  "output_mode": "<commit|artifact|checks|verdict|none>",
  "agent": "<pi|codex|claude>",
  "model": "<configured>",
  "effort": "<configured>",
  "worktree": "<abs path|none>",
  "branch": "<branch|none>",
  "native": {
    "source": "<native command or artifact>",
    "terminal": "<Orca terminal id>",
    "task": "<task id|none>",
    "receipt": "<verbatim receipt summary|none>"
  },
  "state": "<registry state>",
  "evidence": "<commands and outputs|none>"
}
```

action 固定五个；意图与 native 坐标分步记录；每次写后 readback，持久化后才继续。
字段以 canonical lane registry schema 为准；runtime-specific 内容只允许嵌套在 `orca`
opaque overlay 槽位，不改共享顶层 schema。

## 一致性检查

`registry_overlay.py` 校验：registry 路径可读可写；lane_id/map_id 非空；`runtime: orca`
与 `dispatch_runtime: orca` 一致；`record_native_coordinates` 的 terminal/task/receipt 字段
非空并与 preflight 的固定 executable、target_host、terminal identity 一致；
`record_readback` 的 evidence 可读回；`record_final_state` 的 state 属于
`integrated|consumed|close_pending|closed|stale|blocked`；`record_cleanup_state` 只允许
`closed|close_pending` 持久态。不满足即失败，不写 registry。
