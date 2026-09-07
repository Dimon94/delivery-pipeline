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
Development mode：<astra-luna | astra-sol | sol-direct | none; 按开发模式合同解析>
Mode source：<ticket 用户选择 | map 持久选择 | default | existing lane>
Execution phase：<starting | switching | executing | none>
Checkpoint：<absolute checkpoint artifact path | none>
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
Wayfinder map：<id/url | none>
Repo：
Integration worktree：<integration-worktree-path | none for initial map creation>
Integration branch：<feature/map-<map-issue> | none for initial map creation>
Execution worktree：<由 Codex App 创建，startup 后 readback 实际路径>
Execution branch：codex/issue-<ticket-number-or-coordinate>
Base commit：<integration-branch-HEAD-at-creation>
Review fixed point：<execution-base-commit | map-registry-base-commit | none>
Review evidence preflight：<absolute delivery-pipeline/references/code-review-evidence-preflight.md | none>
允许编辑：
-
禁止范围：
-

执行：
- 你是当前 task/worktree 的实现或验收 worker；Coordinator task 是回传目标，不是你的身份。
  直接执行本票，不承担 coordinator 的任务监控。
- 先读取开发模式合同：完成“每次调用的执行核验”。内部辅助、second opinion 和
  Review 前调用执行 helper 的 subagent 入口；子代理权限不超过本 Work item。
- 确认 cwd 位于 App-managed Execution Worktree，common dir 属于 Repo，HEAD 包含 Base commit。
- 先完整读取 Owner skill SKILL.md，回报 frontmatter name 与 resolved path，再按其 contract
  处理 Work item。invocation label 只是元数据。
- 当前 owner 直接或嵌套调用 `code-review` 时，完整读取 Review evidence preflight；`commit` mode
  的 Review fixed point 等于本 Execution Worktree 的 Base commit，`verdict` mode 等于 map registry
  base commit。preflight bundle 完成前不派生 Standards/Spec 子审查。
- 只处理本 Work item，不领取 sibling/dependent item，也不进入下一 gate。
- `commit`：先按 Development mode 与 Execution phase 执行开发模式合同；starting 时按机械核验入口生成并保存 checkpoint snapshot，PREWALK_READY 后停止，只有 executing 继续下面的最终交付步骤。实现变更；owner 调用 `code-review` 时先按 Review evidence preflight 物化当前 dirty
  worktree 证据，再创建单一 local commit并报告 hash。
- `artifact`：完成 tracker/artifact坐标；无必要 repo 变更时保持 clean。
- `checks`：运行 whole-change checks并报告精确命令/结果；保持 clean。
- `verdict`：按 Review evidence preflight 一次物化 Git/path/staged 证据，再运行 review owner；
  所有只读子 reviewer 共用 bundle并报告 verdict/findings；保持 clean。
- 保留 tracker fan-in、cherry-pick、Integration 与 remote actions 给 coordinator。
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
Dirty state：
Touched files：
Blocker：
FINAL_REPORT_END
```
