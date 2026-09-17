# Orca Phase 4 remote publication gate（push/PR-MR/merge/remote closeout）

本文件是 remote publication 的只读门禁合同，覆盖已证实且获授权的 operation：
git push、PR/MR 创建/更新、merge（merge/squash/rebase）与 remote closeout
（remote branch 删除等收尾）。Phase 4 失败不破坏 Phase 1-3 已有证据；共享
registry、checkpoint、overlay、FIFO、项目 authority、provider mutation 与
fan-in/cleanup 合同仍由既有 owner 持有，本门禁不新建第二套。

## 只读门禁

```text
python3 <Orca skill realpath>/scripts/remote_publication.py check <absolute-request.json>
```

返回始终包含 `authority: false`、`mutations: []`、
`project_lane_transition: unchanged` 与 `scope: phase4-publication-only`。
`ready` 仅表示 caller-declared 结构证据通过；coordinator 必须验证 provider
source provenance、登录身份与目标坐标当前性后才沿 git/provider CLI 执行。
helper 不执行 git push、gh pr create/merge 或任何 cleanup 命令、不写
registry、不保存 request/receipt 数据库。`blocked` 只阻塞当前 Phase 4
operation，不回改已完成的 Phase 1-3 本地与 provider 证据。

## 公共输入

`operation`、`lane`（共享 registry latest row + `orca` attempt 完整身份）、
`binding`、`capability` 与 `authorization` 字段定义与
`references/orca-provider-mutation.md` 相同。差异仅两点：

- `authorization.operation_authority` 是额外必填文本：push、PR/MR 创建/更新、
  merge 与 closeout 的 authority 与 approval gate 明确分离，必须唯一指向本
  operation 的授权来源（packet 隔离范围、用户确认 artifact）。缺失即 blocked；
  不由 capability 或 spec 标签自动授予 push/merge 权限。无授权时 coordinator
  只报告唯一剩余 gate，不越权执行。
- `capability.provider` 目前仅 `github` 有命令闭集；`linear` 无 publication
  命令闭集，任何 publication operation 对该 provider 一律 blocked。

## Operation 表

| operation | 命令闭集（github） | 额外输入 | 结果边界 |
| --- | --- | --- | --- |
| `publication-read` | `git ls-remote`/`git status`/`git rev-parse`/`git log`/`gh pr view`/`gh pr list`/`gh api`（仅 GET） | `target.repository` | 只读，不要求授权/幂等 |
| `branch-push` | `git push` | `authorization`、`idempotency`、`local_state.branch/head/status_readback/rev_parse_readback`、`remote_readback`（`git ls-remote` JSON）；fast-forward 更新还需 `ancestry_readback` | 同 SHA `deduplicated`；non-fast-forward blocked，禁止盲 force-push |
| `pr-create` | `gh pr create` | `authorization`、`idempotency`、`branch.head/base`、`existing_pr_readback`（`gh pr list --json number,state,headRefName,body`）、`push_readback` | 同 head 已有 OPEN PR blocked；`resume: true` 且唯一命中且含幂等 marker 返回 `consume-existing-pr`，不重复创建 |
| `pr-update` | `gh pr edit`/`gh api` | `authorization`、`idempotency`、`branch.head/base`、`target.pull_request`、`pr_readback` | 仅 OPEN 可更新；marker 已存在且 `resume: true` 返回 `deduplicated`，否则 blocked |
| `pr-merge` | `gh pr merge` | `authorization`、`idempotency`、`branch.head/base`、`target.pull_request`、`merge_method`（merge/squash/rebase）、`pr_readback`（state/mergeable/headRefOid）、`pr_evidence.ci/review/conflict`、`fan_in` | MERGED 且 `resume: true` 返回 `deduplicated`（merge 成功但响应丢失的恢复）；CLOSED/MERGED 非恢复 blocked；mergeable 非 true blocked |
| `remote-closeout` | `git push`/`gh api` | `authorization`、`idempotency`、`branch.head/base`、`parity_readback`（local_head/remote_head）、`merge_readback`、`fan_in`、`closeout_cleanup`（worker_release/archive_output/worktree_cleanup/registry）、`remote_readback`、`delete_branch` | parity 未证实 blocked；merge readback 非 MERGED blocked；registry 仅 `close_pending`/`closed`；branch 已删 `deduplicated` |
| `verify-result` | 上述全部 | `evidence` 结果束 | 绑定 mutation/readback/artifact 到 lane |

`fan_in` 精确为 `{integration, testing, review, artifacts, tracker, cleanup}`
六个可读绝对路径：merge/closeout 前必须能读回 Phase 1-3 的 Integration、
testing、review、artifact、tracker 与 cleanup 证据。helper 只验证存在性与
完整性，不判定、不回改既有结果；缺失或 Unknown 只阻塞当前 operation。

## 幂等与恢复合同

写入型 operation 携带稳定 idempotency key（`map-<map>-lane-<lane>-<work-item>-<op>`），
retry 一律 readback-first：

- `branch-push` 以 `git ls-remote` readback 判定：remote SHA 等于 local HEAD
  即 `deduplicated`；remote 是 local 祖先才允许 `push-fast-forward`；分叉
  blocked，禁止盲 force-push。
- `pr-create` 以 `gh pr list` readback 判定：同 head 已有 OPEN PR 且非
  response-lost 恢复 blocked；`resume: true` 且唯一命中且 body 含
  `dp-idem:<key>` marker 才消费既有 PR。未先 push 成功（push_readback 无
  head ref）不创建 PR。恢复时不得猜测 PR number。
- `pr-update` 以 `gh pr view` readback 中的 marker 去重，语义同
  tracker-mutate。
- `pr-merge` 先读 PR 状态：MERGED 且 `resume: true` 即恢复
  `deduplicated`，绝不重复 merge；仍 OPEN 时 resume blocked，先重新
  readback 再判定。CI/review/conflict 证据与 project-side fan-in 全部可读
  且 mergeable 为 true 才返回 `merge-<method>`。
- `remote-closeout` 先证 local/remote parity（`parity_readback` 的
  local_head == remote_head）与 MERGED，再核对 closeout_cleanup 的
  worker release、archive/output、worktree cleanup 与 registry
  `close_pending`/`closed` 合同。dirty/Unknown 保留现场，不盲删除；
  重复 closeout 只返回 `deduplicated`。

## Fail-closed 与 verify-result

权限缺失、登录身份不一致、授权缺失、网络失败、timeout 与 response
Unknown 均返回 `blocked`，`authority: false`，不修改 project completion
state，不回滚 Phase 1-3 证据。push、PR/MR 与 merge 状态变化永不替代
project-side ticket、Integration、testing 或 review gate。operation 完成后
用 `verify-result` 绑定证据束（字段与
`references/orca-provider-mutation.md` 相同）；`outcome` 非 `success`
一律 fail-closed，声明了 `idempotency_key` 时 result readback 必须含对应
marker。

本票交付不代表整张 map 完成；完整 Orca 目标须九票全部 assigned 验收通过。
没有真实 provider 证据的 operation 标记 `not-run/Unknown`，不得以静态检查
冒充 provider proof。

## 验收边界

`remote_publication_check.py` 只证明机械合同与 no-mutation，模拟成功不等于
provider 成功。真实验收必须提供：隔离测试 PR 上真实的
push/create/merge/closeout + readback、重复/失联/Unknown 的 fail-closed
证据、active writer 恢复与 final local/remote parity；未验证能力标记
Unknown 并保持 blocked，不关闭本票。

DRY record:

- scope：git push、PR/MR 创建/更新/merge 与 remote closeout 的
  capability/identity/授权/幂等/readback/fan-in 门禁。
- searched：provider_mutation、browser_gate、worker_lifecycle、
  project_lifecycle、recovery、preflight 的合同与 helper。
- reused：`validate_markers`、`_known_text/_known_bool/_readable_absolute/_read_json_object`、
  registry markers 与 attempt 身份核验、authorization/idempotency/verify-result
  结构与 provider 命令闭集模式；`consume-existing-*`、`deduplicated`、
  `readback-first` 语义沿用 Phase 2B。
- remaining duplication：publication 命令闭集与 fan-in/parity/closeout
  输入是本 transport 边界的显式声明；不复制共享 registry/FIFO/continuation
  状态机，不重复 provider mutation 的 tracker/artifact 合同。
