# #126 Phase 2B tracker/artifact/PR-MR provider mutation gate 验收记录

结论：代码候选可复审；**#126 / Phase 2B 仍 blocked**，不是完整功能验收通过。
本次只新增 provider mutation 只读门禁薄层，复用共享 registry/markers/attempt 身份
核验；按 dispatch packet 要求冻结 WIP（未提交）、未推进 Integration、未关闭
issue #126。基线
`016f0100f73bdb73d89cbf04e7a6115ade74a75a`（lane-114-126，dispatch
ctx_06c64ac54e30 / task_f1b25d3703d8）。

## 触达与实现

+ `skills/delivery-pipeline-orca/scripts/provider_mutation.py`：tracker-read/
  tracker-mutate/artifact-publish/artifact-read/artifact-archive/artifact-delete/
  pr-ready/verify-result 的只读门禁；所有返回 `authority: false`、`mutations: []`、
  `project_lane_transition: unchanged`、`scope: phase2-operation-only`。
  每种 provider operation 执行前核对命令闭集、版本匹配 CLI reference、登录身份
  readback 与目标坐标；mutation 以稳定 idempotency key（须可关联 map/work
  item）+ `dp-idem:<key>` marker 去重，retry 只接受 readback-first，
  response 丢失不盲重发；`resume: true` 且 readback 唯一命中 marker 时返回
  `consume-existing-mutation`。artifact publish 按 destination 清单 name+sha256
  去重，同名异内容 fail-closed；archive/delete 必须携带 cleanup gate verdict 与
  review evidence。`pr-ready` 只对 OPEN+draft 转换，已 ready 幂等
  `deduplicated`，MERGED/CLOSED blocked。
+ `provider_mutation_check.py`：最小模拟合同矩阵（命令闭集/身份不一致/幂等
  readback-first/盲重发 blocked/resume consume/artifact dedup/同名异内容
  fail-closed/archive-delete 边界/pr-ready 状态机/verify-result fail-closed/
  请求不可变）。
+ `references/orca-provider-mutation.md`：operation 表、provider 命令闭集、
  授权复用、幂等合同、fail-closed 与验收边界；SKILL.md 接入 Phase 2B 节；
  `scripts/validate.py` 纳入可执行检查。
+ 没有新 registry、dispatcher、request/receipt 数据库或第二套状态机；
  GitHub/Linear/PR/MR 状态变化不替代 project-side gate（返回值恒为
  `project_lane_transition: unchanged`）。

## 可运行检查

```text
PYTHONDONTWRITEBYTECODE=1 python3 skills/delivery-pipeline-orca/scripts/provider_mutation_check.py
python3 scripts/validate.py
git diff --check
python3 skills/delivery-pipeline-orca/scripts/provider_mutation.py check /tmp/issue-126/req-tracker-mutate.json
```

最小检查先红（基线 016f010 无 `provider_mutation_check.py`，`red.log` exit=2）
后绿（`green.log` exit=0）；完整 validator 输出 `bundle: pass`。

原始证据目录：`/tmp/issue-126`；复审/交接时保留该目录。

## Native 与模拟严格分开

provider CLI 为 `gh` 2.78.0（`gh-version.txt`），登录身份 `Dimon94`
（`gh-identity.json`，gh api user 真实 readback）。授权边界（dispatch
registry-checkpoint）：GitHub 验收限专用测试 issue，取证后关闭并标注 test；
禁止 push/真实 PR-MR/merge；Linear 无凭据记 Unknown。授权 evidence 为
`lane-114-126-dispatch/registry-checkpoint.md`。专用测试 issue：
[#131](https://github.com/Dimon94/delivery-pipeline/issues/131)（标题含
`[test]`，取证后已关闭并标注 test）。

| 验收项 | 本轮真实观察 | 证据 / 剩余边界 |
| --- | --- | --- |
| provider 身份/版本 readback | 真实 `gh --version` 2.78.0、`gh api user` login=Dimon94 | `gh-version.txt`、`gh-identity.json` |
| tracker-read | 门禁 ready（execute-readonly）后真实 `gh issue view 131` | `req-tracker-read.json`、`native-view-before.json` |
| tracker-mutate 真实 mutation | 门禁 ready（execute-idempotent-mutation）后真实 `gh issue comment 131`，comment URL 读回 | `req-tracker-mutate.json`、`native-comment-receipt.txt`（comment-5707078466） |
| 幂等 marker readback | mutation 后 `gh issue view --json comments` 含 `dp-idem:map-114-lane-114-126-126-accept-comment` | `native-view-after.json` |
| 重复 request 不盲重发 | 同一 key 再次请求：dedupe readback 命中 marker，非 resume → blocked | `req-tracker-mutate-dup.json`（exit=1） |
| response-lost 恢复 | `resume: true` + 唯一 marker 命中 → `consume-existing-mutation`，不重复创建 | `req-tracker-mutate-resume.json` / `-result.json` |
| verify-result | success（receipt+readback+marker+artifact）→ evidence-bound；outcome=unknown → fail-closed blocked | `req-verify-success*.json`、`req-verify-unknown*.json` |
| 测试场地收口 | issue #131 已关闭（close comment 标注 test），final readback state=CLOSED、2 条 comment | `native-close-receipt.txt`、`native-view-final.json` |
| artifact publish/read（/tmp 隔离） | **已实测**：空 listing → publish-artifact ready → 真实 copy 到 destination → listing readback（name+sha256）→ 重复 publish `deduplicated`；artifact-read sha 匹配 → ready | `req-artifact-publish*.json`、`native-listing-before/after.json`、`req-artifact-read*.json`、`dest/` |
| PR/MR ready（只读探测） | 真实 `gh pr list/view`：本 repo 无 OPEN PR；以 PR #6（MERGED）真实 readback 喂入门禁 → fail-closed blocked（不盲操作）；draft→ready 转换未实测 | `native-pr-list.json`、`native-pr-6-view.json`、`req-pr-ready-merged*.json` |
| Linear tracker | **Unknown**：无 linear CLI、无凭据（`LINEAR_API_KEY` 未设置）；相关 operation 保持 blocked，不关闭本票 | 无凭据即无证据 |
| PR/MR draft→ready mutation | **not-run**：授权边界禁止真实 PR/MR 创建/push/merge；合同仅经模拟矩阵验证 | `provider_mutation_check.py` |
| artifact archive/delete | **not-run（native）**：cleanup gate + review evidence 边界经模拟矩阵验证 | 同上 |

这些结果不授权删减 #126 的完整 AC；只证明已实测分支及其 fail-closed 行为。
未 push、未建真实 PR、未 merge、未修改真实 Source/Integration；测试 issue
已关闭，无残留。
