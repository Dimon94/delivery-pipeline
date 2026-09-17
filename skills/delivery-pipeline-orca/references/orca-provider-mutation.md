# Orca Phase 2B provider mutation gate（tracker/artifact/PR-MR）

本文件是 delivery 相关外部 provider mutation 的只读门禁合同。不代理各 provider 的
全部产品能力，只覆盖已证实且获授权的 operation：GitHub/Linear work item 读取与
mutation、delivery artifact 的 publish/read/archive/delete、既有 PR/MR 的
ready-for-review 状态转换。Phase 2 provider 失败不破坏 Phase 1 本地交付链；
共享 registry、checkpoint、overlay、FIFO 与项目 authority 仍由既有合同持有，
本门禁不新建第二套。

## 只读门禁

```text
python3 <Orca skill realpath>/scripts/provider_mutation.py check <absolute-request.json>
```

返回始终包含 `authority: false`、`mutations: []`、
`project_lane_transition: unchanged` 与 `scope: phase2-operation-only`。
`ready` 仅表示 caller-declared 结构证据通过；coordinator 必须验证 provider
source provenance、登录身份与目标坐标当前性后才沿 provider CLI 执行。
helper 不执行 gh/Linear 命令、不写 registry、不保存 request/receipt 数据库。
`blocked` 只阻塞当前 Phase 2 operation，不回改已完成的 Phase 1 本地证据。

## 公共输入

每个 request 必须携带：

- `operation`：下表之一。
- `lane`：共享 registry latest row（markers + `orca` attempt 完整身份）。
- `binding`：`lane_id/work_item/run_id/task_id/dispatch_id/terminal_handle/execution_host`，
  与 lane 完全一致；provider mutation 的输入、授权、结果与 artifact 由此绑定
  map/work item/lane。
- `capability`：执行前的 provider-scoped 前置检查。
  - `provider`：`github` | `linear`。
  - `command`：本次 provider 命令，必须在该 provider 的命令闭集内，缺失即
    operation-scoped blocked。
  - `reference`：已读取的版本匹配 CLI reference 名。
  - `cli_version_readback`：provider CLI `--version` 输出的可读绝对路径。
  - `identity_readback`：登录身份 readback JSON（如 gh api user 的 `login`）的
    可读绝对路径。
  - `expected_identity`：期望的登录身份；与 readback 不一致即 blocked。

coordinator 必须保证 version/identity readback 确实捕获自当前 provider 会话；
helper 只验证结构与一致性，文件存在本身不证明 provenance。

## Operation 表

| operation | 命令闭集 | 额外输入 | 结果边界 |
| --- | --- | --- | --- |
| `tracker-read` | github：`gh issue view`/`gh issue list`/`gh pr view`/`gh api`（仅 GET）；linear：`linear issue view`/`linear issue list` | `target.repository` | 只读，不要求授权/幂等 |
| `tracker-mutate` | github：`gh issue comment`/`gh issue edit`/`gh issue close`/`gh api`；linear：`linear issue update`/`linear comment create` | `authorization`、`target`、`idempotency`、`dedupe.readback` | 幂等 marker 去重 |
| `artifact-publish` | 文件系统 copy（无 provider 命令） | `authorization`、`idempotency`、`artifact.path/kind/sha256`、`output_mode`（artifact/checks/verdict）、`destination.dir`、`dedupe.listing_readback` | 内容一致 dedup，同名异内容 fail-closed |
| `artifact-read` | 文件系统 read | `artifact.path/kind/sha256` | sha 必须匹配 |
| `artifact-archive` / `artifact-delete` | 文件系统 move/remove | `authorization`、`cleanup_gate.verdict/evidence`、`review_evidence.verdict` | 与 cleanup gate 与 review evidence 一致 |
| `pr-ready` | github：`gh pr ready`；linear：无 | `authorization`、`target.pull_request`、`idempotency`、`state_readback` | 仅 OPEN+draft 转换；已 ready 幂等 dedup |
| `verify-result` | 上述全部 | `evidence` 结果束 | 绑定 mutation/readback/artifact 到 lane |

## 授权复用

`authorization` 精确为 `{approved: true, scope, evidence}`：`scope` 是已知非空
文本（如 packet 中的隔离验收范围），`evidence` 是可读绝对路径（dispatch packet、
用户确认 artifact）。只读 operation 不要求授权；tracker mutation、artifact
publish/archive/delete 与 PR ready 必须核对对应明确授权。没有授权证据即
blocked，不扩大既有授权范围。

## 幂等合同

mutation request 必须携带稳定 idempotency key 并可关联到 map/work item/lane：

```json
{"idempotency": {"key": "map-<map>-lane-<lane>-<work-item>-<op>", "retry_rule": "readback-first", "prior_readback": null}}
```

写入型 tracker mutation 在 request 体中携带 marker `dp-idem:<key>`；retry 必须
readback-first：先在 provider 读回（`gh issue view --json comments` 等）查找该
marker。marker 已存在且非 response-lost 恢复即 blocked；`resume: true` 且唯一
命中时返回 `consume-existing-mutation`，消费已存在对象，不盲重发。没有
retry-request 的原生 provider 以已存在对象/稳定身份/readback 恢复，不套用
orchestration 的参数；超时后先 inspect。

`artifact-publish` 以 `dedupe.listing_readback`（destination 目录清单 JSON，
`artifacts[].name/sha256`）按 name+sha256 去重：同名同内容返回
`deduplicated`，同名不同内容 fail-closed，禁止盲覆盖。`pr-ready` 以
`state_readback`（`gh pr view --json state,isDraft`）证明当前 OPEN；已是
ready 状态返回 `deduplicated`，MERGED/CLOSED blocked，不盲操作。

## Fail-closed 与 verify-result

权限缺失、登录身份不一致、用户确认缺失、网络失败、timeout 与 response
Unknown 均返回 `blocked`，`authority: false`，不修改 project completion
state，不回滚 Phase 1 本地交付证据。GitHub/Linear/PR/MR 状态变化永不替代
project-side ticket、Integration、testing 或 review gate。operation 完成后用
`verify-result` 绑定证据束：

```json
{"evidence": {"outcome": "success", "mutation_receipt": "<可读的 mutation 命令记录>",
              "result_readback": "<mutation 后 provider readback JSON>",
              "idempotency_key": "<声明的 key>", "artifacts": ["<可读绝对路径>"],
              "captured_at": "<ISO 时间>"}}
```

`outcome` 非 `success`（failed/unknown/timeout/network-loss）一律 fail-closed；
声明了 `idempotency_key` 时 result readback 必须含对应 marker，否则证据无法
关联 request。没有真实 provider 证据的 operation 标记 `not-run/Unknown`，
不得以静态检查冒充 provider proof。

## 验收边界

`provider_mutation_check.py` 只证明机械合同与 no-mutation，模拟成功不等于
provider 成功。真实验收必须提供：专用测试 issue 上的真实 mutation + readback、
重复/失联/Unknown 的 fail-closed 证据；Linear 无凭据时记 `Unknown` 并保持
blocked，不关闭本票。禁止 push、真实 PR/MR 创建或 merge。

DRY record:

- scope：GitHub/Linear work item、artifact 与既有 PR/MR ready 状态的
  capability/identity/授权/幂等/readback 门禁。
- searched：browser_gate、worker_lifecycle、registry_overlay、preflight、
  gh CLI envelope。
- reused：`validate_markers`、`_known_text/_known_bool/_readable_absolute/_read_json_object/_at`、
  registry markers 与 attempt 身份核验。
- remaining duplication：provider 命令闭集是本 transport 边界的显式声明；
  不复制共享 registry/FIFO/continuation 状态机。
