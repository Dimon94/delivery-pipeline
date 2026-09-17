# Orca Phase 2A browser/automation operation gate

本文件是 delivery-pipeline 交付所需 browser/automation operation 的只读门禁合同。
不代理全部 Orca browser 产品能力，只覆盖 delivery 相关场景（测试页面操作/截图与
有限自动任务）；Phase 2 失败不破坏 Phase 1 本地链。共享 registry、checkpoint、
overlay、FIFO 与项目 authority 仍由既有合同持有，本门禁不新建第二套。

## 只读门禁

```text
python3 <Orca skill realpath>/scripts/browser_gate.py check <absolute-request.json>
```

返回始终包含 `authority: false`、`mutations: []`、`project_lane_transition: unchanged`
与 `scope: phase2-operation-only`。`ready` 仅表示 caller-declared 结构证据通过；
coordinator 必须验证 native source provenance、目标 host 当前性与同一 caller identity
后才沿原生命令执行。helper 不执行 Orca 命令、不写 registry、不保存 receipt/job 数据库。
`blocked` 只阻塞当前 Phase 2 operation，不回改已完成的 Phase 1 本地证据。

## 公共输入

每个 request 必须携带：

- `operation`：下表之一。
- `lane`：共享 registry latest row（markers + `orca` attempt 完整身份）。
- `binding`：`lane_id/work_item/run_id/task_id/dispatch_id/terminal_handle/execution_host`，
  与 lane 完全一致；browser action 的输入、authority、结果与 artifact 由此绑定 map/work
  item/lane。
- `capability`：执行前的版本匹配检查。
  - `command`：本次 native 命令（如 `click`、`tab create`、`automations run`）。
  - `schema`：目标 host 上 `orca agent-context --json` 的完整捕获（含 `schemaVersion`
    与 `commands`）；命令必须出现在其中，缺失即 operation-scoped blocked。
  - `host_readback`：目标 host 的 `orca status --json` native envelope；
    `_meta.runtimeId` 必须等于 `runtime_id`。不能用本地 capability 宣布代替目标证据。
  - `runtime_id`：目标 runtime 身份。
  - `reference`：已读取的版本匹配 guide 名（当前 binary 的 `orca skills get orca-cli`）。
  - `require`（可选）：声明后，`host_readback` 的 `result.runtime.capabilities` 必须
    包含该版本 capability（如 screenshot 用 `browser.screencast.v1`，automation
    create 用 `automation.create-idempotency.v1`）。

coordinator 必须保证 `schema`/`host_readback` 确实捕获自目标 host；helper 只验证
结构与身份一致性，文件存在本身不证明 provenance。

## Operation 表

| operation | 命令闭集 | 额外输入 | 结果边界 |
| --- | --- | --- | --- |
| `browser-read` | 只读：`snapshot`/`screenshot`/`get`/`is`/`find`/`tab list`/`tab show`/`tab current`/`tab profile list`/`tab profile show`/`automations list`/`automations runs`/`automations show` | `screenshot` 必须声明 `artifact.path`（绝对）与 `artifact.kind` | 只读 browser 不增设确认 |
| `browser-navigate` | `tab create`/`goto`/`reload`/`back`/`forward`/`wait`/`tab switch`/`tab close`/`scroll`/`scrollintoview`/`hover`/`focus`/`set device`/`set offline`/`set headers` | `tab create`/`goto` 必须声明 `target.url`；幂等合同 | 导航是外部只读 GET，不新增确认 |
| `browser-write` | `click`/`dblclick`/`fill`/`type`/`inserttext`/`select`/`check`/`uncheck`/`clear`/`upload`/`eval`/`keypress`/`drag`/`mouse *` | `authorization` + 幂等合同；可选 `target.url` | 外部数据写入/发消息才核对明确授权 |
| `automation-create` | `automations create` | `authorization`、`automation.name/schedule`、`dedupe.list_readback` | 有界 schedule；同名去重 |
| `automation-run` | `automations run` | `authorization`、`automation_id`、`dedupe.runs_readback` | 在途 job 去重 |
| `automation-pause` | `automations edit` | `authorization`、`automation_id`、`state_readback` | 仅 active 状态可暂停 |
| `verify-result` | 上述全部 | `evidence` 结果束 | 绑定结果/artifact/readback 到 lane |

## 授权复用

`authorization` 精确为 `{approved: true, scope, evidence}`：`scope` 是已知非空文本
（如 packet 中的隔离验收范围），`evidence` 是可读绝对路径（dispatch packet、用户确认
artifact）。只读 browser 与导航不要求授权；外部数据写入、发送消息、发布与
automation 创建/触发/暂停必须核对对应明确授权。没有授权证据即 blocked，
不扩大既有授权范围。

## 幂等合同

`browser-navigate` 与 `browser-write` 必须携带：

```json
{"idempotency": {"key": "<稳定 operation key>", "retry_rule": "readback-first",
                 "prior_readback": null}}
```

retry 必须 `readback-first`：先读回当前 tab/页面状态（`tab show`、`eval`、`get`），
确认前次 attempt 未生效才重发；`prior_readback` 必须是 ok envelope。不允许盲重发
（`tab create` 每次都会创建新 tab；重复 click 可能重复提交表单）。

`automation-create` 以 `dedupe.list_readback`（`automations list --json` envelope）
按 `name` 去重：同名已存在且非 response-lost 恢复即 blocked；`resume: true` 且唯一
同名时返回 `consume-existing-automation`，消费原对象，不重复创建。interval schedule
必须带 `ends_at` 或 `max_runs`；禁止无界 recurring scheduler。
`automation-run` 以 `dedupe.runs_readback`（`automations runs --json`）检查同一
automation 的在途 job（running/pending/queued/in_progress/dispatching/dispatched）；
重复触发先读回，
`resume: true` 且唯一在途时返回 `consume-existing-job`。`automation-pause` 以
`state_readback`（`automations show --json`）证明当前 active，已暂停不盲暂停。

## Fail-closed 与 verify-result

权限缺失、用户确认缺失、timeout、host loss 与结果 Unknown 均返回 `blocked`，
`authority: false`，不修改 project completion state。operation 完成后用
`verify-result` 绑定证据束：

```json
{"evidence": {"input_receipt": "<action 的 native envelope>",
              "result_readback": "<操作后 native readback envelope>",
              "artifacts": ["<可读绝对路径>"], "captured_at": "<ISO 时间>",
              "outcome": "success|failed|unknown|timeout|host-loss"}}
```

`outcome` 非 `success` 一律 fail-closed；`success` 要求 input receipt 与 result
readback 均为 ok envelope、`_meta.runtimeId` 与 capability 目标一致、artifact 可读。
记录 host、URL/job ID、artifact 与操作时间；不能以静态文档检查冒充真实
automation proof。

## 验收边界

`browser_gate_check.py` 只证明机械合同与 no-mutation，模拟成功不等于 Orca 成功。
真实验收必须提供：版本匹配 schema/host readback、隔离场地（/tmp 测试资源）的真实
tab/snapshot/fill/click/eval readback、真实失败路径（如 screenshot CDP timeout）
的 fail-closed 证据。automation create/run/pause 没有真实成功证据时保持
`not-run/Unknown` 与 blocked，不关闭本票。remote host browser capability 未证明前
同样 blocked（本 runtime `host list` 只有 local）。

DRY record:

- scope：Orca browser/automation operation 的 capability/readback/幂等/授权门禁。
- searched：worker_lifecycle、registry_overlay、recovery.py、preflight.py、原生
  agent-context/status/tab/automations envelope。
- reused：`validate_markers`、`_known_text/_known_bool/_readable_absolute/_read_json_object/_at`、
  registry markers 与 attempt 身份核验、native envelope 形态。
- remaining duplication：operation 命令闭集是本 transport 边界的显式声明；不复制共享
  registry/FIFO/continuation 状态机。
