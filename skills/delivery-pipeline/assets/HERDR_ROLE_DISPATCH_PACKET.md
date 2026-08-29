# Herdr Configured Role Dispatch Packet

所有 CLI/Herdr worker 共用本 packet。Coordinator 从 version 3 配置解析 role、agent、ordinary route、
可选 bootstrap 与 Gearshift Policy。普通 lane 在 startup registry readback 后生成 packet；enabled Pi lane
先只启动 agent，验证 `GEARSHIFT_ARMED <json>` 并持久化 Armed Projection，最终 packet 仅在 Armed
Projection readback 后生成和投递。worker 不自行切换 agent/model/effort；enabled lane 只允许已配置的
Pi Gearshift 按 Bootstrap Checkpoint 执行 Source→Target Shift。用户仍可在 pane 手动切换，worker照常
交付并在 final report 如实记录实际模型历史与 evidence。

```text
Coordinator task：
Lane ID：<lane_id>
Herdr session/workspace/tab/pane：
Role：<planning | design | frontend | backend | testing | review>
Output mode：<commit | artifact | checks | verdict>
Agent：<pi | codex | claude>
Model：<ordinary Target Model id>
Effort：<ordinary Target effort>
Model evidence：<pi-list-models | codex-catalog | claude-env>
Gearshift mode：<off | opt_in | all_eligible | none>
Gearshift enabled：<true | false>
Gearshift eligibility：<off | ticket-label | all-eligible | ineligible | none>
Gearshift opt-in label JSON：<quoted-label | none>
Legacy packet rule：legacy v2 replacement 固定写 mode=none、enabled=false、eligibility=none，其他 Gearshift 字段为 none；不得从当前配置补值。
Gearshift profile：<delivery-bootstrap | none>
Bootstrap Source：<model + effort | none>
Ordinary Target：<model + effort>
Gearshift Adapter：<absolute bootstrap-trigger.ts + delivery-pipeline/bootstrap-slice | none>
Gearshift Shift ID：<full id from GEARSHIFT_ARMED json | none>
Owner skill name：<owner frontmatter name>
Owner skill SKILL.md：<absolute resolved path>
Owner skill invocation label：<runtime-specific label; metadata only>
Work item：<id/title/url | gate coordinate>
Parent spec：<id/url | none>
Wayfinder map：<id/url | none>
Repo：
Integration worktree：<integration-worktree-path>
Integration branch：feature/map-<map-issue>
Execution worktree：<execution-worktree-path>
Execution branch：<pi|codex|claude>/issue-<ticket-number-or-coordinate>
Base commit：<integration-branch-HEAD-at-creation>
Review fixed point：<execution-base-commit | map-registry-base-commit | none>
Review evidence preflight：<absolute delivery-pipeline/references/code-review-evidence-preflight.md | none>
允许编辑：
-
禁止范围：
-

执行：
- 确认 cwd 位于 Execution Worktree（not Integration Worktree，not Source Worktree）。
- 先完整读取 Owner skill SKILL.md，回报 frontmatter name 与 resolved path，再按其 contract
  处理本 Work item。invocation label 只用于说明，不依赖 pane catalog。
- 当前 owner 直接或嵌套调用 `code-review` 时，完整读取 Review evidence preflight；`commit` mode
  的 Review fixed point 等于本 Execution Worktree 的 Base commit，`verdict` mode 等于 map registry
  base commit。preflight bundle 完成前不派生 Standards/Spec 子审查。
- 只处理本 Work item，不领取 sibling/dependent item，也不进入下一 gate。
- Gearshift enabled 时按顺序调用 `bootstrap_check`：同一 focused command 先 red；red 后修改至少一个
  声明的 canonical-owner path；同一 command green并提供 owner paths、remaining work 与 evidence refs。
  Adapter 在 green 退出 0 后再次核对 owner digest；green command 撤销或覆盖该 mutation 不发 Ready。
  工具发出 Ready 后由 Gearshift Core 切到 Ordinary Target。不得用第一次 edit、手动 `/model` 或文字
  声称替代 Shift Record；disabled lane 不调用 `bootstrap_check`。
- 按 Output mode 交付：
  - `commit`：实现变更；owner 调用 `code-review` 时先按 Review evidence preflight 物化当前
    dirty worktree 证据，再创建一个仅含本 Work item 的 local commit；
  - `artifact`：产出 tracker/artifact坐标，无必要 repo 变更时保持 clean；
  - `checks`：运行 whole-change checks并报告命令/结果，保持 clean；
  - `verdict`：按 Review evidence preflight 一次物化 Git/path/staged 证据，再执行 review owner；
    所有只读子 reviewer 共用 bundle并报告 verdict/findings，保持 clean。
- 保留 tracker fan-in、cherry-pick、Integration 和 remote actions 给 coordinator。
- 当前 Output mode 与 packet 不符时停止写入并在 Blocker 中报告。
- 当前 Agent/Model/Effort 与 packet 不符（通常是用户在本 pane 改了模型）时不阻塞，继续执行，
  照常交付并在 final report 记录 runtime 实际值与 evidence；但不得把手动变化冒充 Bootstrap Handoff。

完成标准：
- Work item acceptance 已满足，或已有精确 blocker。
- final report 包含 role、output mode、agent/model/effort、实际模型历史、对应 evidence、dirty state 与
  touched files；Gearshift enabled 时还包含 Shift ID、Source/Target、Adapter、Shift state 与 Shift Record
  readback；`commit` 与 `verdict` 还包含 review branch、Review fixed point、HEAD 与 bundle readback。
- 到达终态（completed 或 blocked）后在 final report 之外，额外在终端输出单独一行
  `LANE_DONE <lane_id>`，该行不得包含其他内容。这是 coordinator watcher 的唯一完成信号；
  遗漏会导致 lane 完成后无法自动唤醒 fan-in。

FINAL_REPORT_BEGIN
Work item：
Role：
Output mode：
Agent/model/effort：
模型历史：
Gearshift Projection：<mode/enabled/eligibility/opt-in-label-json/shift-id/source/target/adapter/state/evidence-ref | none>
状态：completed | blocked
Pane/worktree/branch：
Commit：<hash subject | none>
Artifacts/checks/verdict：
Review evidence：<fixed-point/head/bundle-readback | none>
Dirty state：
Touched files：
Blocker：
FINAL_REPORT_END
```
