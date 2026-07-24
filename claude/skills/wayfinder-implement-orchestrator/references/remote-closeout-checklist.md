# PR/MR 收尾清单

只有当全部 execution lanes terminal、ready frontier 为空，或剩余 work 已明确 out of scope
时才读取本文件。

## Execution Result Audit

- 审计每条 lane 的 terminal final report、ticket checkpoints、commits、verification 和 dirty state；
  不要只相信 Herdr status 或 notification。
- 集成前检查每个 commit：`git show --stat --oneline <hash>` 和 focused diff。
- 拒绝包含无关文件、缺失验证、dirty worktree，或把 blocker 包装成 success 的 commits。

## Integration Audit

- 只集成已验证 lane commits，并遵循 dependency topology。
- frontier 清空后，运行能证明 spec acceptance 的最小 whole-change check。
- remote submission 前运行 `/code-review` 或 repo-native review gate。
- 如果 review gate 要并行 helpers，优先使用 pane-local Claude Agent Team 的
  `wayfinder-integration-reviewer`，并显式传入完整 review 包：base commit、
  integrated diff、spec、tickets、验证结果、只读要求和输出格式。
- 如果无法形成有效 helper 调用，就在当前 review pane 运行同等的 Standards 和 Spec
  diff review，并把 fallback 记录到 PR/MR evidence。

## Summary PR/MR Body

包含：

- Spec link 和 source map link。
- 已实现 issue links。
- lane IDs、runtimes、pane labels 和 terminal reports。
- Integrated commits。
- Verification commands and results。
- 被 blocked 或 skipped 的 tickets/issues，以及原因。
- 已知 residual risk。

remote publication authority 只在 push/open/update/comment 前检查；缺失时停在此 gate，不能
反向阻塞已经授权的本地 lanes、integration 或 checks。

## Remote Pass Gate

- 根据 remote host 选择正确对象：GitHub 用 PR，GitLab 用 MR。
- 打开或更新 PR/MR 后，从 tracker 或 host API 读取 remote CI/CD status。
- 读取 PR/MR comments，确认 automated review Agent verdict。
- `pending`、missing、failed 或 ambiguous CI/CD 都不算完成。
- review-agent requests、failures 或 absent verdict 都不算完成。
- 只有 CI/CD 通过，且 review Agent 明确说 PR/MR can pass，才算完成。

## Review-Agent Mistake

对每个 blocking review-agent comment：

1. 基于 code、tests、artifacts 和 PR/MR diff evidence，把它分类为 `valid`、`invalid`
   或 `Unknown`。
2. 如果是 `valid`，完成前先修复或派发 follow-up issue。
3. 如果是 `Unknown`，询问用户或收集最小缺失证据。
4. 如果是 `invalid`，在 PR/MR 里用简短反驳和直接证据回复。
5. 在 PR/MR 里留下 adaptation note，记录为什么可能触发该 review，以及未来
   review-agent behavior 应如何改变。

对 invalid review 使用这个中文评论形状：

```text
Review-agent 反驳：
- 评论：<link 或简短引用该 claim>
- 结论：invalid
- 证据：<file/test/artifact/API result>
- 原因：<为什么该 claim 不适用>

Review-agent 适配记录：
- 可能触发原因：<pattern, missing context, stale assumption, or heuristic>
- 期望后续行为：<review Agent 应该学习的具体规则>
```

不要因为已经反驳就把 PR/MR 标为完成。完成仍要求 passing review-agent verdict，或用户
明确指示带着 unresolved remote-gate risk 停止。
