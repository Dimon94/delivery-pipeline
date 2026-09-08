# Map #95 / Issue #106 独立 Review → Integration pilot

## 固定范围

- 选用 runtime：Codex CLI；前置 canary 为 #105，不重复运行 Pi/Claude Code 整链。
- Execution Base / Review fixed point：`58e0f6abbfdc658d40ab8363108d5b647c4d4c77`。
- 适用用户确认：#97 Q1–Q6、#98 Q1–Q7 的“全按推荐”，由 Spec #99 固定范围与来源。
- 本票只交付本场景及 repo 外执行证据；不改 Source Worktree，不授权 push、PR/MR、merge main 或发布。

## 执行场景

1. worker 只修改本票 Execution Worktree，完成候选并回传；coordinator 为每轮冻结 base/head、完整路径清单、staged/worktree 状态和 Review Evidence Bundle。
2. coordinator 使用每轮 bundle 启动并管理 Standards/Spec 双轴 reviewer，直接保留 reviewer 身份、原始 verdict 和 blocking findings。
3. 受控 finding 仅放在本隔离场景中；reviewer 必须独立发现。coordinator 将 finding 回传 worker 修复，再冻结新 head/bundle 并取得覆盖新版本的独立复核结论后决定放行。
4. worker 发出一次 terminal 报告；coordinator 对同一 terminal 的重复通知或恢复重入只回读，不重复 fan-in/cherry-pick。
5. coordinator 验证用户确认、commit、Review 放行与 dirty state 后，仅一次集成到 `feature/map-95`，并运行 focused checks。

## 必留证据

- 四层前置版本：静态、模拟、Pi/Claude Code/Codex CLI canary、当前 pilot。
- 固定 Review 基点、每轮 head、不可变 bundle 路径与双轴最终结论。
- 受控 finding 的预登记、独立发现、修复 diff 和新版本复核。
- terminal/fan-in 去重读回、source/integrated commit、patch 等价与 focused checks。
- 实际用户确认版本/来源；任何 Unknown 不冒充通过。

## 失败条件

session 或 task 身份改变、双 writer、覆盖用户改动、提前 Integration、缺用户确认、Review 身份不独立、旧 verdict 覆盖新 head，任一发生即保留现场并停止。
