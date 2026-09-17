# #125 Phase 2A browser/automation operation gate 验收记录

结论：代码候选可复审；**#125 / Phase 2A 仍 blocked**，不是完整功能验收通过。
本次只新增 Orca readback 薄层，复用共享 registry/markers/attempt 身份核验；未提交、
未推进 Integration、未关闭 issue。基线 `45c7b6c717058d1f8c91ddfba616ffbbe77ef969`。

## Follow-up 补充验收（2026-09-16，dispatch ctx_bf2b67654f87 / task_cf103a9db66e）

授权证据：`lane-114-125-dispatch/followup-packet-send.json`（协调者明确授权 /tmp 隔离场地

+ 本机 Orca local runtime 的有界测试 automation job 创建/触发/暂停/删除与 screenshot 重试）。

+ **bounded automation mutation 已真机验收**：门禁 ready 后创建
  `issue-125-followup-probe`（job `5a7c3e3a-207c-4a55-9b3d-24726388e17d`，daily 03:00
  一次性探针语义，取证窗口内不会触发，且已删除）；手动触发 run `40f4d43c` 状态
  dispatching → dispatched → completed；pause（`edit --disabled`）读回 `enabled=false`；
  remove 后 `automations list`/`runs` 均为空，无残留。每步 readback 均绑定
  job ID/状态/时间。证据：`req-aut2-*.json`/`req-aut2-*-result.json`、
  `native-aut2-*.json`（list-before/create/show-active/runs-before-run/run/
  runs-after-run/pause/show-paused/runs-final/remove/list-after/runs-after-remove）。
+ **真实缺陷（已先红后绿修复）**：`browser_gate.py` 的 `IN_FLIGHT` 不含 Orca 原生在途状态
  `dispatching`/`dispatched`，真机 readback 下重复触发去重不生效
  （修复前 `req-aut2-run-dup-result.json` 误返回 ready）。修复：IN_FLIGHT 增加两个状态，
  `browser_gate_check.py` 新增原生状态断言；红 `red-inflight.log`（exit=1）→ 绿
  `green-inflight.log` + 修复后 `req-aut2-run-dup-result-fixed.json` 正确 blocked（exit=1），
  `scripts/validate.py` bundle: pass。reference 文档同步。
+ **screenshot 重试仍 fail-closed**：更简单页面（`site/simple.html`）+ `tab switch` 聚焦后
  png 一次、jpeg 一次，均为同一 CDP `Page.captureScreenshot` timeout（窗口可见性/焦点，
  CLI 无 timeout 参数）；verify-result outcome=unknown 门禁 blocked
  （`native-shot-1.json`、`native-shot-2.json`、`req-verify-screenshot-retry-unknown*.json`）。
  测试 tab 已关闭（`native-tab-list-final.json` 为空），http.server 已停止。
+ remote host capability 仍 Unknown（仅 local），不绕过、不关闭。#125 AC 不全过，issue 保持打开。

## 触达与实现

+ `skills/delivery-pipeline-orca/scripts/browser_gate.py`：browser-read/navigate/write、
  automation-create/run/pause 与 verify-result 的只读门禁，所有返回 `authority: false`、
  `mutations: []`、`project_lane_transition: unchanged`、`scope: phase2-operation-only`。
+ `browser_gate_check.py`：最小模拟合同矩阵（capability 闭集/版本 schema/host runtime/
  require capability、授权、幂等 readback-first、有界 schedule、去重/resume、fail-closed
  outcome、请求不可变）。
+ `references/orca-browser-automation.md`：operation 表、命令闭集、授权复用、幂等合同、
  fail-closed 与验收边界；SKILL.md 接入；`scripts/validate.py` 纳入可执行检查。
+ 没有新 registry、dispatcher、receipt/job 数据库或第二套状态机。

## 可运行检查

```text
PYTHONDONTWRITEBYTECODE=1 python3 skills/delivery-pipeline-orca/scripts/browser_gate_check.py
python3 scripts/validate.py
git diff --check
python3 skills/delivery-pipeline-orca/scripts/browser_gate.py check /tmp/issue-125/req-browser-write.json
```

最小检查先红（`browser_gate` 尚不存在，`red.log`，exit=1），后绿（`green.log`）；
完整 validator 输出 `bundle: pass`。

原始证据目录：`/tmp/issue-125`；复审/交接时保留该目录。

## Native 与模拟严格分开

固定 binary 为当前 `orca` 1.4.203；runtime `47a2461a-b48d-4a52-9f19-9e578220c19d`；
host `local`（`accept-host-list.json`：本 runtime 只有 local）。
隔离场地：`/tmp/issue-125/site` 经 `python3 -m http.server 18125` 提供测试页；
授权 evidence 为真实 dispatch packet（`lane-114-125-dispatch/packet-send.json`，
scope 为 issue #125 的 /tmp 隔离验收边界）。

| 验收项 | 本轮真实观察 | 证据 / 剩余边界 |
| --- | --- | --- |
| 版本匹配 capability schema | 真实 `orca agent-context --json`：schemaVersion 1、234 命令，含全部 browser/automation 命令 | `agent-context.json` |
| 目标 host readback | 真实 `orca status --json`：runtime ready、78 项 capabilities（含 `browser.screencast.v1`、`browser.clientHost.automation.v1`、`automation.create-idempotency.v1`） | `status.json` |
| 只读 browser 链路 | 真实 tab create → tab show（URL/title 读回）→ snapshot（element refs）→ get url | `accept-tab-create.json`、`accept-tab-show`/`native-tab-show.json`、`accept-snapshot.json`、`accept-get-url.json` |
| 写链路 + 结果读回 | 真实 fill e2 → click e3 → eval 读回 `clicked:accept-125`（隔离 localhost 测试页） | `accept-fill.json`、`accept-click.json`、`accept-eval.json` |
| 幂等 readback-first | 重复 click 前先读回页面状态；两次 eval 读回一致，未盲目重发创建类操作 | `native-click-repeat.json`、`native-eval-readback-2.json` |
| 门禁原生验收 | 6 个真实 request 经 `browser_gate.py check`：read/write/verify-success/automation-create/run 均 ready（exit=0），screenshot unknown 被 fail-closed（exit=1） | `req-*.json`、`req-*-result.json` |
| screenshot artifact | **真实失败（含 follow-up 重试）**：CDP `Page.captureScreenshot` timeout（tab 不可见/窗口未聚焦），首轮两次 + 重试两次（简单页/聚焦/jpeg）一致；`verify-result outcome=unknown` 被门禁 blocked，不声称截图证据 | `accept-screenshot-unknown.json`、`req-verify-screenshot-unknown-result.json`、`native-shot-1.json`、`native-shot-2.json`、`req-verify-screenshot-retry-unknown-result.json` |
| automation 只读读回 | 真实 `automations list`/`runs`：空，可作为 create/run 的 dedupe 前置 | `native-automations-list.json`、`native-automations-runs.json` |
| automation create/run/pause mutation | **已实测通过（follow-up）**：create（daily 03:00 有界探针，已删除）→ 手动 run（状态 dispatching→dispatched→completed 全程读回）→ pause（`enabled=false` 读回）→ remove（list/runs 读回为空，无残留）；修复后发现的去重缺陷（见上） | `req-aut2-*.json`、`native-aut2-*.json`、`req-aut2-run-dup-result-fixed.json` |
| remote host browser capability | **not-run/Unknown**：`environment list` 为空、`host list` 仅 local；remote 目标证据缺失前相关 operation blocked | `accept-environment-list.json`、`accept-host-list.json` |

这些结果不授权删减 #125 的完整 AC；只证明已实测分支及其 fail-closed 行为。
tab 操作发生在 Orca embedded browser 的共享会话，测试 tab 已关闭（`accept-tab-close.json`、
`native-tab-list-after.json` tabs 为空），http.server 已停止；未修改真实 Source/Integration，
未 push、未建 PR、未关 issue。
