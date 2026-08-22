# Execution Worktree Integration via Cherry-pick

每个 execution worktree 的 terminal commit 必须通过 cherry-pick 集成到 integration worktree，
再删除 execution worktree。本文件描述完整的集成序列、冲突处理和清理逻辑。

## Integration Sequence

**触发：** execution worker 报告 terminal。`codex-thread` 从 `read_thread` 读取最终报告；
`herdr-codex-pane` / `herdr-claude-pane` 验证完整 final report markers。

**前置条件验证：**

1. 从 final report 提取 commit hash、ticket number、worktree path。
2. 验证 execution worktree 存在且 commit valid：
   ```bash
   test -d "$EXECUTION_PATH"
   git -C "$EXECUTION_PATH" rev-parse --verify "$COMMIT_HASH" >/dev/null 2>&1
   ```
3. 从 ticket registry 读取 `parent_integration_worktree_path`。
4. 验证 integration worktree 存在且 working tree clean：
   ```bash
   test -d "$INTEGRATION_PATH"
   [ -z "$(git -C "$INTEGRATION_PATH" status --short)" ]
   ```

**集成步骤：**

1. 切换到 integration worktree（如果不在）：
   ```bash
   cd "$INTEGRATION_PATH"
   ```

2. Cherry-pick execution commit：
   ```bash
   git cherry-pick "$COMMIT_HASH" 2>&1
   ```

3. 检测 cherry-pick 结果：
   ```bash
   # 成功：working tree clean，no CHERRY_PICK_HEAD
   if [ -z "$(git status --short)" ] && [ ! -f .git/CHERRY_PICK_HEAD ]; then
     echo "cherry-pick successful"
   
   # 冲突：working tree 有 "UU" 或 "AA" 文件
   elif git status --short | grep -qE "^(UU|AA) "; then
     echo "cherry-pick conflict"
     # 获取冲突文件列表
     CONFLICTING_FILES=$(git status --short | grep -E "^(UU|AA) " | awk '{print $2}')
   
   # 其他错误：cherry-pick 失败但无冲突标记
   else
     echo "cherry-pick failed"
   fi
   ```

4. 如果 cherry-pick 成功：
   - 运行 focused checks（基于 touched files）
   - Checks 通过后进入 cleanup 序列
   - Checks 失败时标记 ticket 为 `integration_checks_failed`，保留 execution worktree 供调试

5. 如果 cherry-pick 冲突：
   - 中止 cherry-pick：`git cherry-pick --abort`
   - 标记 ticket 为 `integration_conflict`，写入冲突文件列表到 registry
   - **不在这里调用** conflict resolution（用户可能需要更多上下文）
   - 保留 execution worktree，提示用户可手动解决或调用 `$resolving-merge-conflicts`
   - 报告格式：
     ```
     ticket #123 integration conflict:
     - file1.ts
     - file2.ts
     
     execution worktree 已保留：<path>
     手动解决后运行：/delivery-pipeline <map> --retry-integration 123
     ```

6. 如果 cherry-pick 其他错误：
   - 中止 cherry-pick：`git cherry-pick --abort`
   - 标记 ticket 为 `integration_failed`
   - 立即删除 execution worktree（已知坏状态）

**完成标准：** execution commit 已 cherry-pick 到 integration worktree，checks 通过，
registry 已更新为 `integrated` state。

## Focused Checks

**触发：** cherry-pick 成功后，在 integration worktree 运行。

**检查范围：** 只针对 touched files 运行相关 checks，不运行全量 test suite。

**检查类型：**

1. Type checking（如果 touched files 是 TypeScript/类型化语言）：
   ```bash
   # TypeScript 示例
   npx tsc --noEmit
   ```

2. Linting（针对 touched files）：
   ```bash
   # ESLint 示例
   npx eslint $TOUCHED_FILES
   ```

3. Unit tests（针对 touched files 的 test files）：
   ```bash
   # Jest 示例
   npx jest --findRelatedTests $TOUCHED_FILES
   ```

4. 格式检查（如果 repo 有格式化要求）：
   ```bash
   # Prettier 示例
   npx prettier --check $TOUCHED_FILES
   ```

**Checks 失败处理：**

- 保留 integration worktree 当前状态（commit 已 cherry-pick）
- 保留 execution worktree 供对比
- 标记 ticket 为 `integration_checks_failed`
- 报告具体失败的 check 和错误信息
- 用户需要手动修复 integration worktree，然后运行 `--continue-integration`

**完成标准：** 所有 focused checks 通过，working tree clean。

## Cleanup Sequence

**触发：** cherry-pick 成功且 focused checks 通过。

**删除步骤：**

1. 删除 execution worktree：
   ```bash
   # 先检查 worktree 是否 clean（防御性检查）
   if [ -z "$(git -C "$EXECUTION_PATH" status --short)" ]; then
     git worktree remove "$EXECUTION_PATH"
   else
     echo "警告：execution worktree 有未提交变更，跳过删除"
     # 标记为 cleanup_pending，不阻塞其他 tickets
   fi
   ```

2. 删除 execution branch：
   ```bash
   # 只在 worktree 成功删除后删除 branch
   if [ ! -d "$EXECUTION_PATH" ]; then
     git branch -D "$EXECUTION_BRANCH"
   fi
   ```

3. 更新 ticket registry：
   ```yaml
   state: integrated
   integrated_commit: <integration-worktree-commit-hash>
   cleanup_at: <ISO-8601-timestamp>
   ```

4. 按 registry runtime 收口 transport：
   - `codex-thread`：确认 task 已 terminal；保留 task 历史，registry 清除 active writer 状态。
   - `herdr-codex-pane` / `herdr-claude-pane`：通过 `$herdr` 关闭 pane 并更新 tab label；失败时标记
     `close_pending`，不阻塞其他 tickets。

**完成标准：** Execution Worktree 已删除、branch 已删除、registry 已更新，runtime transport
已 terminal 或关闭。

## Failed Worktree Cleanup

**触发条件：**

1. Startup probe 失败两次（task/pane 未正确启动或未读取 owner file）
2. Worktree 路径冲突（路径已存在但不是该 ticket 的 worktree）
3. Worktree 状态 invalid（branch 不匹配、不在 Git worktree list 中）
4. Cherry-pick 非冲突失败（其他 Git 错误）

**立即删除序列：**

```bash
# 仅删除已验证属于该 lane 且没有用户变更的 worktree
if [ -d "$EXECUTION_PATH" ]; then
  git worktree remove --force "$EXECUTION_PATH"
fi

# 删除 branch（如果存在）
git branch -D "$EXECUTION_BRANCH" 2>/dev/null

# Herdr runtime 再通过 $herdr 关闭已验证 pane；codex-thread 保留 task 历史
```

**标记 ticket 状态：**

- `setup_blocked`（startup probe 失败）
- `path_conflict`（路径冲突）
- `worktree_invalid`（worktree 状态不一致）
- `integration_failed`（cherry-pick 非冲突失败）

已知坏的 Execution Worktree 与 branch 清理；task/pane 依 runtime 收口，tracker/Git 证据保留。

**报告格式：**

```
ticket #123 setup blocked: startup probe failed after 2 retries
- task/pane 未读取 owner file
- execution worktree 已删除：<path>

需要手动检查 runtime transport 或 worktree 权限。
```

## Conflict Retry Flow

**触发：** 用户手动解决 integration conflict 后，运行 `--retry-integration <ticket>`。

**Retry 序列：**

1. 从 registry 读取 ticket 的 `execution_worktree_path` 和 conflict details。
2. 验证 ticket state 是 `integration_conflict`。
3. 切换到 integration worktree。
4. 用户已手动修改 integration worktree 来解决冲突（或调用了 conflict resolution skill）。
5. 验证 working tree clean（冲突已解决）。
6. 重新运行 focused checks。
7. Checks 通过后进入 cleanup 序列。

**不重新 cherry-pick**（用户已手动应用了变更）。

## Dependency Order Integration

**触发：** 多个 execution tickets terminal，需按 dependency order 集成。

**排序规则：**

1. 读取所有 terminal tickets 的 dependency edges（从 tracker 或 spec）。
2. 拓扑排序：dependents 必须在 dependencies 之后集成。
3. 同一层级的 tickets 可并发集成（无相互依赖）。
4. 某个 ticket integration 失败或冲突时，标记其 dependents 为 `blocked_by_dependency`。

**集成顺序示例：**

```
ticket #201 (no dependencies) → integrate first
ticket #202 (no dependencies) → integrate first (parallel with #201)
ticket #203 (depends on #201) → integrate after #201 succeeds
ticket #204 (depends on #202, #203) → integrate after both #202 and #203 succeed
```

**Blocked by dependency 处理：**

- 如果 #201 integration conflict，#203 和 #204 标记为 `blocked_by_dependency`。
- 用户解决 #201 conflict 后，#203 自动解锁并尝试集成。
- #203 成功后，#204 自动解锁。

**完成标准：** 所有 tickets 按正确的 dependency order 集成，或已标记明确 blocker。

## Registry Persistence

**每次状态变更都更新 ticket registry comment。**

**State transitions：**

```
running → terminal → integrating → integrated
                  → integration_conflict → (manual fix) → integrated
                  → integration_failed → (immediate cleanup)
                  → integration_checks_failed → (manual fix) → integrated
```

**Registry fields 更新：**

```yaml
state: integrated
integrated_commit: <integration-worktree-commit-hash>
integration_at: <ISO-8601-timestamp>
focused_checks: passed
execution_worktree_path: null  # 已删除
execution_branch: null  # 已删除
```

**Readback 验证：** 每次写入后立即 readback，验证字段正确持久化。

## Verification Checklist

每次 cherry-pick 和 cleanup 后验证：

- [ ] Integration commit exists: `git -C "$INTEGRATION_PATH" rev-parse HEAD`
- [ ] Working tree clean: `git -C "$INTEGRATION_PATH" status --short` 空输出
- [ ] Execution worktree deleted: `! test -d "$EXECUTION_PATH"`
- [ ] Execution branch deleted: `! git rev-parse --verify "$EXECUTION_BRANCH" 2>/dev/null`
- [ ] Worktree unregistered: `git worktree list --porcelain` 不包含 `$EXECUTION_PATH`
- [ ] Registry updated: readback `state: integrated`
- [ ] Runtime transport terminal: thread terminal，或 `$herdr` 验证 pane closed/tab updated

验证失败时，报告具体失败项（expected vs actual），标记为 partial cleanup，不继续后续 tickets。
