# Codex App Role Dispatch Packet

Codex App 壳的所有 delegated roles 共用本 packet。App task 的 model/effort 由 App 环境拥有；
role 与 output mode 仍由 canonical gate contract 决定。

```text
Coordinator task：
Role：<planning | design | frontend | backend | testing | review>
Output mode：<commit | artifact | checks | verdict>
Agent/model/effort：codex-app / app-owned / app-owned
Source owner projectId：
Owner skill name：<owner frontmatter name>
Owner skill SKILL.md：<absolute resolved path>
Owner skill invocation label：<runtime-specific label; metadata only>
Work item：<id/title/url | gate coordinate>
Parent spec：<id/url | none>
Wayfinder map：<id/url | none>
Repo：
Integration worktree：<integration-worktree-path>
Integration branch：feature/map-<map-issue>
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
- 确认 cwd 位于 App-managed Execution Worktree，common dir 属于 Repo，HEAD 包含 Base commit。
- 先完整读取 Owner skill SKILL.md，回报 frontmatter name 与 resolved path，再按其 contract
  处理 Work item。invocation label 只是元数据。
- 当前 owner 直接或嵌套调用 `code-review` 时，完整读取 Review evidence preflight；`commit` mode
  的 Review fixed point 等于本 Execution Worktree 的 Base commit，`verdict` mode 等于 map registry
  base commit。preflight bundle 完成前不派生 Standards/Spec 子审查。
- 只处理本 Work item，不领取 sibling/dependent item，也不进入下一 gate。
- `commit`：实现变更；owner 调用 `code-review` 时先按 Review evidence preflight 物化当前 dirty
  worktree 证据，再创建单一 local commit并报告 hash。
- `artifact`：完成 tracker/artifact坐标；无必要 repo 变更时保持 clean。
- `checks`：运行 whole-change checks并报告精确命令/结果；保持 clean。
- `verdict`：按 Review evidence preflight 一次物化 Git/path/staged 证据，再运行 review owner；
  所有只读子 reviewer 共用 bundle并报告 verdict/findings；保持 clean。
- 保留 tracker fan-in、cherry-pick、Integration 与 remote actions 给 coordinator。

FINAL_REPORT_BEGIN
Work item：
Role：
Output mode：
状态：completed | blocked
Task/worktree/branch：
Commit：<hash subject | none>
Artifacts/checks/verdict：
Review evidence：<fixed-point/head/bundle-readback | none>
Dirty state：
Touched files：
Blocker：
FINAL_REPORT_END
```
