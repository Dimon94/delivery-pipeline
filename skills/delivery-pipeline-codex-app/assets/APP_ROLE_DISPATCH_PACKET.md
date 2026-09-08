# Codex App Role Dispatch Packet

Codex App 壳的所有 delegated roles 共用本 packet。App 拥有执行配置，请求值与运行证据分开；
role 与 output mode 仍由 canonical gate contract 决定。

```text
Coordinator task：
Coordinator host：<coordinator hostId>
Lane registry：<absolute existing repo-external lane registry path>
Terminal 回传合同：<absolute delivery-pipeline-codex-app/references/codex-app-dispatch.md，读取 Terminal 回传节>
Role：<planning | design | frontend | backend | testing | review>
Output mode：<commit | artifact | checks | verdict>
Agent：codex-app
Development mode：<sol-luna | sol-sol | sol-direct | none; legacy astra-* 仅恢复>
Mode source：<ticket 用户选择 | map 持久选择 | default | existing lane>
Execution phase：<starting | switching | executing | none>
Checkpoint：<absolute checkpoint artifact path | none>
Checkpoint format/hash：<canonical-v1 + checkpoint_sha256 | legacy-app-v0 + Unknown，仅恢复>
Requested model：<development-mode work selection>
Requested effort：<development-mode work selection>
开发模式合同：<absolute resolved delivery-pipeline-codex-app/references/development-mode.md>
执行 helper：<absolute resolved delivery-pipeline-codex-app/scripts/prewalk.py>
Source owner projectId：
Owner skill name：<owner frontmatter name>
Owner skill SKILL.md：<absolute resolved path>
Owner skill invocation label：<runtime-specific label; metadata only>
Work item：<id/title/url | gate coordinate>
Parent spec：<id/url | none>
实施前置合同：<absolute canonical gate-state-machine.md>
实施前置证据：<absolute repo-external gate evidence JSON path | none for non-commit>
Wayfinder map：<id/url | none>
Repo：
Integration worktree：<integration-worktree-path | none for initial map creation>
Integration branch：<feature/map-<map-issue> | none for initial map creation>
Execution worktree：<由 Codex App 创建，startup 后 readback 实际路径>
Execution branch：codex/issue-<ticket-number-or-coordinate>
Base commit：<integration-branch-HEAD-at-creation>
Review fixed point：<execution-base-commit | map-registry-base-commit | none>
Review scope：<implementation | whole-change | none>
Review evidence preflight：<absolute delivery-pipeline/references/code-review-evidence-preflight.md | none>
允许编辑：
-
禁止范围：
-

执行：
- `commit` 写入前读取实施前置合同与证据，核对本票的 to-spec、to-tickets、ticket-sizing 产物和用户确认；缺失则 blocked 回传。
- 你是当前 task/worktree 的实现或验收 worker；Coordinator task 是回传目标，不是你的身份。
  直接执行本票，不承担 coordinator 的任务监控。
- 先读取开发模式合同：完成“每次调用的执行核验”。内部辅助、second opinion 和
  Review 前调用执行 helper 的 subagent 入口；子代理权限不超过本 Work item。
- 确认 cwd 位于 App-managed Execution Worktree，common dir 属于 Repo，HEAD 包含 Base commit。
- 先完整读取 Owner skill SKILL.md，回报 frontmatter name 与 resolved path，再按其 contract
  处理 Work item。invocation label 只是元数据。
- 正式 Review 由 coordinator 调用 resolved code-review owner；packet 只传 owner triple、
  Review scope 与 Review evidence preflight，不替 owner 选择模型或 effort。`commit` mode 传
  `review_scope: implementation`，fixed point 等于 Execution Base commit；`verdict` mode 传
  `review_scope: whole-change`，fixed point 等于 map registry base commit。preflight bundle 完成前不派生
  Standards/Spec 子审查。
- 只处理本 Work item，不领取 sibling/dependent item，也不进入下一 gate。
- `commit`：先按 Development mode 与 Execution phase 执行开发模式合同；starting 时通过
  `scripts/prewalk.py checkpoint` 生成 canonical checkpoint，PREWALK_READY 后停止，只有 executing
  继续。实现变更并创建单一候选 local commit；不启动、取消或替代正式 Review。缺 coordinator
  直接回读的独立两轴 verdict 时按 blocked 回传“实现已保存、审查待完成”，不写 completed。
- `artifact`：完成 tracker/artifact坐标；无必要 repo 变更时保持 clean。
- `checks`：运行 whole-change checks并报告精确命令/结果；保持 clean。
- `verdict`：只按 coordinator 传入的 resolved owner 与 whole-change scope 运行 review owner；
  按 Review evidence preflight 一次物化证据，所有只读子 reviewer 共用 bundle并报告原始
  verdict/findings；保持 clean，最终放行仍由 coordinator 直接回读。
- 保留 tracker fan-in、cherry-pick、Integration 与 remote actions 给 coordinator。
- 正式 reviewer 由 coordinator 管理；worker 不得取消审查或用自评替代独立 verdict。
  不得调用 interrupt_agent 中断正式 reviewer、催促其直接通过、删减审查范围规避 finding，
  或以测试通过/“已修复”自行豁免验收。需要取消或重派时向 coordinator 说明原因；等待不是通过。
  可以保存候选 commit，但独立审查缺失、中断或待复核时回传 blocked，注明“实现已保存、审查待完成”，
  不写 completed；由 coordinator 按 Terminal 合同接收并补审，不能把 blocked 当作无需处理。
- completed 与 blocked 都在最终回复前执行 Terminal 回传合同，将下面的完整报告发送给
  Coordinator task；工具成功后才声明 FINAL_REPORT 已回传，失败则报告回传受阻与恢复坐标。

FINAL_REPORT_BEGIN
Work item：
Role：
Output mode：
状态：completed | blocked
Task/worktree/branch：
Commit：<hash subject | none>
Model evidence：<host model/effort readback + source/time | Unknown>
用户确认：<decision + confirmation source + unresolved questions | none>
Artifacts/checks/verdict：
Review evidence：<fixed-point/head/bundle-readback | none>
Review owner/scope：<resolved owner triple + review_scope | none>
Dirty state：
Touched files：
Blocker：
FINAL_REPORT_END
```

`状态` 是报告 outcome，不是 registry state。coordinator 核验 `completed` 后按
`terminal → integrated/consumed → closed|close_pending` 推进，禁止持久化 `state: completed`。
`blocked` 仍是 coordinator 必须处理的恢复状态，不能把 blocked 当作无需处理。
