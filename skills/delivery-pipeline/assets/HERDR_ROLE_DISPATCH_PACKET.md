# Herdr Configured Role Dispatch Packet

所有 CLI/Herdr worker 共用本 packet。Coordinator 从 version 2 兼容配置或 version 3 执行计划解析 role、agent、model、
effort并在启动前写入 registry。implementation lane 还要冻结 mode 与 source。配置的 model/effort 只是派发时的初始化值：用户可在 lane 运行中手动切换，
worker 被动接受，照常交付并在 final report 如实记录 runtime 实际值与 evidence；worker 不自行切换
agent/model/effort。

```text
Coordinator task：
Lane ID：<lane_id>
Herdr session/workspace/tab/pane：
Role：<planning | design | frontend | backend | testing | review>
Output mode：<commit | artifact | checks | verdict>
Agent：<pi | codex | claude>
Model：<configured native model id>
Effort：<configured native effort>
Model evidence：<pi-list-models | codex-catalog | claude-env>
Execution mode：<legacy | staged | direct>
Execution source：<role-config | ticket | map | user-config>
Checkpoint：<repo-external absolute checkpoint path | none>
Checkpoint helper：<absolute delivery-pipeline/scripts/checkpoint.py | none>
Starting model/effort：<frozen pair | none>
Execution model/effort：<frozen pair | none>
Direct model/effort：<frozen pair | role triple>
Owner skill name：<owner frontmatter name>
Owner skill SKILL.md：<absolute resolved path>
Owner skill invocation label：<runtime-specific label; metadata only>
Work item：<id/title/url | gate coordinate>
Parent spec：<id/url | none>
实施前置合同：<absolute canonical gate-state-machine.md>
实施前置证据：<absolute repo-external gate evidence JSON path | none for non-commit>
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
- `commit` 写入前读取实施前置合同与证据，核对本票的 to-spec、to-tickets、ticket-sizing 产物和用户确认；缺失则 blocked 回传。
- 确认 cwd 位于 Execution Worktree（not Integration Worktree，not Source Worktree）。
- 先完整读取 Owner skill SKILL.md，回报 frontmatter name 与 resolved path，再按其 contract
  处理本 Work item。invocation label 只用于说明，不依赖 pane catalog。
- 当前 owner 直接或嵌套调用 `code-review` 时，完整读取 Review evidence preflight；`commit` mode
  的 Review fixed point 等于本 Execution Worktree 的 Base commit，`verdict` mode 等于 map registry
  base commit。preflight bundle 完成前不派生 Standards/Spec 子审查。
- 只处理本 Work item，不领取 sibling/dependent item，也不进入下一 gate。
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
  照常交付并在 final report 记录 runtime 实际值与 evidence。
- `starting` implementation 先完成首处有意义修改与最小检查，再用 checkpoint helper 采集完整
  Execution Worktree/Git dirty snapshot，向 repo 外同目录原子写入 checkpoint，并在持久读回后发送
  `PREWALK_READY <lane_id> <checkpoint_path>` 独立完整行（不加引号、反引号或说明前缀，path 为绝对路径）；
  watcher 在本进程内对同一完整 marker 只唤醒一次 coordinator 核验 checkpoint/停止证据，继续监听 LANE_DONE。
  发送后立即结束本回合，保留 dirty 现场，不得继续实现、
  审查、commit、接续或 fan-in。该信号只表示 checkpoint 待核验，不能触发 Terminal fan-in、cherry-pick
  或归档；checkpoint 更新必须使用新的 repo 外 artifact 路径，不覆盖旧阶段意图。
- Coordinator 必须再从原 runtime 读回真实停止证据，且 observation 的 runtime、原生 session 与
  coordinator thread/host 必须和 checkpoint 完全一致；`WORKER_STOPPED <lane_id> <checkpoint_path>`
  之前不得继续。active、Unknown、身份不匹配、ignored 路径、工具拒绝、关键设计 Unknown、过期或不完整
  checkpoint 均 fail-closed；helper
  只返回 `wait`/`blocked`/`ready-for-coordinator`，不发送接续请求。
- `WORKER_STOPPED` 通过后，coordinator 只能使用 canonical `scripts/continuation.py` 复用既有 lane
  registry：先持久化并 readback 唯一 intent，再持久化 `dispatching` request marker 与一次性
  `send-authorized` lease，最后发送 runtime-neutral request。请求、tool acceptance、
  新轮和实际 model/effort 分开留证；send Unknown、旧 coordinator 活性不明、session 不可恢复、用户
  改码/手动换模、模型拒绝、重入或重复 terminal/fan-in 均保留现场、去重或 fail-closed，不得新建 writer。
- 直接检查可复跑为 `python3 skills/delivery-pipeline/scripts/checkpoint.py snapshot <Execution Worktree>`、
  `validate <checkpoint> --worktree <Execution Worktree>` 与 `signal <checkpoint> <signal-line>
  <runtime-observation-json>`；这些命令只读或写 checkpoint，不写 registry。
- `staged` 计划在阶段 adapter 未具备时必须保持 blocked；不得把它静默改成 `direct`。`direct` 与
  `legacy` 才能生成既有三 CLI 启动请求。

完成标准：
- Work item acceptance 已满足，或已有精确 blocker。
- final report 包含 role、output mode、agent/model/effort、对应 evidence、dirty state 与 touched files；
  `commit` 与 `verdict` 还包含 review branch、Review fixed point、HEAD 与 bundle readback。
- 到达终态（completed 或 blocked）后在 final report 之外，额外在终端输出单独一行
  `LANE_DONE <lane_id>`，该行不得包含其他内容。这是 coordinator watcher 的唯一完成信号；
  遗漏会导致 lane 完成后无法自动唤醒 fan-in。

FINAL_REPORT_BEGIN
Work item：
Role：
Output mode：
Agent/model/effort：
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
