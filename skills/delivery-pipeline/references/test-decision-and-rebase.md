# Test Decision, Rebase, and Cleanup

当所有 implementation tickets 已集成到 integration worktree，whole-change checks 通过后，
orchestrator 暂停在 test decision point，由用户选择测试策略，随后自动 rebase 到 main、
push、清理所有 worktrees/branches，并关闭 map。

## Test Decision Point

**触发：** execution graph 已清空（所有 tickets `integrated` 或明确 blocked/skipped），
whole-change checks 通过。

**暂停显示：**

```text
所有 tickets 已集成到 integration worktree，whole-change checks 通过。

Integration worktree: <path>
Integration branch: feature/map-<issue>
Base commit: <hash>
Current HEAD: <hash>
Main branch HEAD: <remote-main-hash>

测试策略选择：

1. 在 integration worktree 测试（隔离，不阻塞其他开发者）
   - 保留 integration worktree，用户可手动运行测试
   - 测试完成后回复 "继续" 进入 rebase
   
2. 先 rebase 到 main 再测试（在 main 上测试最终状态）
   - 立即 rebase integration branch 到最新 main
   - 在 main worktree 测试，可能阻塞其他开发者
   - 测试完成后回复 "继续" 进入 push
   
3. 跳过手动测试，直接 push（信任 automated checks）
   - 立即 rebase 到 main 并 push
   - 适用于：全量 test suite 已通过，无需手动验证

请选择：1/测试、2/合并测试、3/继续
```

**输入识别：**

```python
user_input = input.strip().lower()

if user_input in ["1", "测试"]:
    strategy = "test_in_integration"
elif user_input in ["2", "合并测试"]:
    strategy = "rebase_then_test"
elif user_input in ["3", "继续"]:
    strategy = "skip_test_and_push"
else:
    # 报告 invalid input，重新显示选项
```

**完成标准：** 用户输入已识别为三种策略之一，orchestrator 进入对应分支。

## Strategy 1: Test in Integration Worktree

**序列：**

1. 告知用户可在 integration worktree 手动测试：
   ```text
   请在 integration worktree 运行测试：
   cd <integration-path>
   <test-commands>
   
   测试通过后回复 "继续" 进入 rebase。
   测试失败需修复时，commit 修复后回复 "继续"。
   ```

2. 等待用户输入 "继续" 或 "cancel"。

3. 用户回复 "继续"：
   - 验证 integration worktree working tree clean（确保所有修复已 commit）
   - 进入 Rebase Sequence

4. 用户回复 "cancel"：
   - 报告 "map paused at test decision, integration worktree preserved"
   - 更新 map registry：`state: test_decision_paused`
   - 退出 orchestrator

**完成标准：** 用户确认测试通过，working tree clean，进入 rebase。

## Strategy 2: Rebase Then Test

**序列：**

1. 先执行 Rebase Sequence（见下文），rebase integration branch 到最新 main。

2. Rebase 成功后，切换到 source worktree 的 main：
   ```bash
   cd "$SOURCE_ROOT"
   git checkout main
   git rebase "$INTEGRATION_BRANCH"
   ```

3. 告知用户在 main 测试：
   ```text
   Integration branch 已 rebase 到 main。
   
   请在 main branch 运行测试：
   cd <source-root>
   <test-commands>
   
   测试通过后回复 "继续" 进入 push。
   测试失败需修复时，commit 修复到 integration worktree，然后重新 rebase。
   ```

4. 等待用户输入 "继续" 或 "cancel"。

5. 用户回复 "继续"：
   - 进入 Push and Cleanup Sequence

6. 用户回复 "cancel"：
   - 报告 "map paused, main branch updated but not pushed"
   - 退出 orchestrator

**完成标准：** main 已 rebase 到 integration branch，用户确认测试通过，进入 push。

## Strategy 3: Skip Test and Push

**序列：**

1. 执行 Rebase Sequence。
2. Rebase 成功后，执行 Push and Cleanup Sequence。

**完成标准：** 直接从 rebase 进入 push，无需用户等待。

## Rebase Sequence

**前置条件：** 当前在 integration worktree 或 source worktree，integration worktree working tree clean。

**序列：**

1. 切换到 integration worktree（如果不在）：
   ```bash
   cd "$INTEGRATION_PATH"
   ```

2. Fetch 最新 main：
   ```bash
   git fetch origin main
   ```

3. 检测 main 是否前进：
   ```bash
   MERGE_BASE=$(git merge-base HEAD origin/main)
   REMOTE_MAIN=$(git rev-parse origin/main)
   
   if [ "$MERGE_BASE" != "$REMOTE_MAIN" ]; then
     echo "检测到 main 有新提交，开始 rebase..."
   else
     echo "main 未变化，跳过 rebase"
   fi
   ```

4. Rebase integration branch 到 origin/main：
   ```bash
   git rebase origin/main 2>&1
   ```

5. 检测 rebase 结果：
   ```bash
   # 成功：working tree clean，no rebase-merge directory
   if [ -z "$(git status --short)" ] && [ ! -d .git/rebase-merge ]; then
     echo "rebase successful"
   
   # 冲突：working tree 有 "UU" 或 "AA" 文件
   elif git status --short | grep -qE "^(UU|AA) "; then
     echo "rebase conflict"
     CONFLICTING_FILES=$(git status --short | grep -E "^(UU|AA) " | awk '{print $2}')
   
   # 其他错误
   else
     echo "rebase failed"
   fi
   ```

6. 如果 rebase 成功：
   - 继续后续流程（根据 strategy）

7. 如果 rebase 冲突：
   - 报告冲突文件：
     ```text
     Rebase 冲突，需要解决以下文件：
     - file1.ts
     - file2.ts
     
     委托 $resolving-merge-conflicts 解决冲突...
     ```
   - 调用 `$resolving-merge-conflicts`，传递：
     - 当前 worktree path（integration worktree）
     - 冲突文件列表
     - Map issue context（map title、description）
     - Base commit 和 target commit（origin/main）
   - 等待 conflict resolution skill 完成
   - 验证 working tree clean：
     ```bash
     [ -z "$(git status --short)" ]
     ```
   - Conflict resolution 成功后继续 rebase：
     ```bash
     git rebase --continue
     ```
   - 如果又有冲突，重复调用 conflict resolution
   - 最多 3 次 retry，超过后报告 "rebase 冲突无法自动解决" 并退出

8. 如果 rebase 其他错误：
   - 中止 rebase：`git rebase --abort`
   - 报告错误：
     ```text
     Rebase 失败：<error-message>
     
     Integration worktree 已恢复到 rebase 前状态。
     请手动检查并重新运行 orchestrator。
     ```
   - 退出 orchestrator

**完成标准：** integration branch 已成功 rebase 到最新 origin/main，working tree clean，
没有冲突或冲突已解决。

## Push and Cleanup Sequence

**前置条件：** integration branch 已 rebase 到最新 main，working tree clean，
用户已确认测试通过（或选择 skip test）。

**序列：**

1. Push integration branch 到 remote：
   ```bash
   git push origin "$INTEGRATION_BRANCH" 2>&1
   ```

2. 切换到 source worktree：
   ```bash
   cd "$SOURCE_ROOT"
   ```

3. 验证 source worktree 在 main 分支且 working tree clean：
   ```bash
   CURRENT_BRANCH=$(git branch --show-current)
   if [ "$CURRENT_BRANCH" != "main" ]; then
     git checkout main
   fi
   
   [ -z "$(git status --short)" ]
   ```

4. Rebase source worktree 的 main 到 integration branch：
   ```bash
   git rebase "$INTEGRATION_BRANCH" 2>&1
   ```
   
   这一步应该是 fast-forward（因为 integration branch 基于 main），不应有冲突。
   如果失败，报告错误并退出。

5. Push main 到 remote：
   ```bash
   git push origin main 2>&1
   ```

6. 检测 push 结果：
   ```bash
   if [ $? -eq 0 ]; then
     echo "push successful"
   else
     # Non-fast-forward：另一个 map 并发 push 了
     echo "push failed: non-fast-forward"
   fi
   ```

7. 如果 push 失败（non-fast-forward）：
   - Fetch 最新 main：
     ```bash
     git fetch origin main
     ```
   - Rebase 到最新 main：
     ```bash
     git rebase origin/main
     ```
   - 如果 rebase 冲突：
     - 调用 `$resolving-merge-conflicts`（同 Rebase Sequence）
     - 解决后继续 rebase
   - Retry push：
     ```bash
     git push origin main
     ```
   - 最多 retry 3 次
   - 如果仍失败，报告：
     ```text
     Push 失败：main 有多个并发更新，无法自动解决。
     
     请手动执行：
     cd <source-root>
     git fetch origin main
     git rebase origin/main
     git push origin main
     ```
   - 退出 orchestrator，保留 integration worktree（用户可能需要手动处理）

8. Push 成功后，进入 Cleanup Sequence。

**完成标准：** integration branch 和 main 均已 push 到 remote，source worktree main 与 remote 一致。

## Cleanup Sequence

**触发：** push to main 成功。

**序列：**

1. 验证 push 成功：
   ```bash
   REMOTE_MAIN=$(git ls-remote origin main | cut -f1)
   LOCAL_MAIN=$(git rev-parse HEAD)
   
   if [ "$REMOTE_MAIN" != "$LOCAL_MAIN" ]; then
     echo "警告：remote main 与 local main 不一致，跳过 cleanup"
     exit 1
   fi
   ```

2. 删除 integration worktree：
   ```bash
   # 检查是否 dirty（防御性检查）
   DIRTY=$(git -C "$INTEGRATION_PATH" status --short)
   
   if [ -n "$DIRTY" ]; then
     echo "警告：integration worktree 有未提交变更"
     echo "Integration worktree 保留在：$INTEGRATION_PATH"
     echo "请手动检查后删除：git worktree remove $INTEGRATION_PATH"
     # 不删除，继续其他 cleanup
   else
     git worktree remove "$INTEGRATION_PATH"
     echo "已删除 integration worktree: $INTEGRATION_PATH"
   fi
   ```

3. 删除 integration branch：
   ```bash
   # 只在 worktree 成功删除后删除 branch
   if [ ! -d "$INTEGRATION_PATH" ]; then
     git branch -D "$INTEGRATION_BRANCH"
     # 可选：删除 remote branch
     git push origin --delete "$INTEGRATION_BRANCH" 2>/dev/null
     echo "已删除 integration branch: $INTEGRATION_BRANCH"
   fi
   ```

4. 扫描并删除残留的 execution worktrees：
   ```bash
   # 使用 git worktree list 查找所有该 map 的 execution worktrees
   git worktree list --porcelain | grep "worktree" | grep "-map-${MAP_ISSUE}-issue-" | while read -r line; do
     ORPHANED_PATH=$(echo "$line" | awk '{print $2}')
     echo "发现残留 execution worktree: $ORPHANED_PATH"
     
     # 检查是否 dirty
     DIRTY=$(git -C "$ORPHANED_PATH" status --short 2>/dev/null)
     if [ -n "$DIRTY" ]; then
       echo "警告：execution worktree 有未提交变更，保留：$ORPHANED_PATH"
     else
       git worktree remove "$ORPHANED_PATH" 2>/dev/null
       echo "已删除: $ORPHANED_PATH"
     fi
   done
   ```

5. 删除该 map registry 列出的所有 execution branches（`codex/issue-*` 或 `claude/issue-*`）：
   ```bash
   # 从 map registry 读取所有 implementation ticket numbers
   TICKET_NUMBERS=$(从 registry 提取所有 ticket IDs)
   
   for TICKET_NUM in $TICKET_NUMBERS; do
     EXEC_BRANCH=$(从该 ticket registry 读取 branch)
     if git rev-parse --verify "$EXEC_BRANCH" >/dev/null 2>&1; then
       git branch -D "$EXEC_BRANCH"
       echo "已删除 execution branch: $EXEC_BRANCH"
     fi
   done
   ```

6. map registry 存在 Herdr workspace 时，通过 `$herdr` 关闭所有 panes：
   ```bash
   # 从 map registry 读取 workspace_id 或 workspace_label
   WORKSPACE_LABEL="<map-title>-map-${MAP_ISSUE}"
   
   # 关闭 workspace 中所有 panes（LEAD + X/G/P tabs）
   # 通过 $herdr 执行 workspace close-all-panes "$WORKSPACE_LABEL"
   
   # 保留 workspace 本身（用于历史访问）
   echo "已关闭 workspace 所有 panes，workspace 已保留：$WORKSPACE_LABEL"
   ```

7. 关闭 map issue，写入 completion comment：
   ```markdown
   map-${MAP_ISSUE} 已完成并合并到 main。
   
   **Final merge commit:** <commit-hash>
   **Implemented tickets:** #<t1>, #<t2>, #<t3>, ...
   **Verification:** 
   - Whole-change checks: passed
   - Test strategy: <strategy-chosen>
   - CI/CD: <link-to-ci-run>
   
   **Integration summary:**
   - Integration worktree: <path> (已删除)
   - Integration branch: <branch> (已删除)
   - Execution worktrees: <count> created, all cleaned up
   
   **Timeline:**
   - Map started: <start-timestamp>
   - All tickets integrated: <integration-complete-timestamp>
   - Merged to main: <merge-timestamp>
   - Total duration: <duration>
   ```

8. 更新 map registry 为 `state: closed`。

**完成标准：** 所有 worktrees 已删除（除非 dirty），所有 branches 已删除；存在 Herdr
workspace 时其 panes 已关闭；map issue 已关闭，registry 已更新为 `closed`。

## Full Recovery from Registry

**触发：** 新会话启动，orchestrator crash 或中断后重新运行。

**恢复序列：**

1. 读取 map issue 的 latest lane registry comment，提取：
   - `integration_worktree_path`
   - `integration_branch`
   - `base_commit`
   - `coordinator_runtime`
   - `dispatch_runtime`
   - `herdr_workspace_label`
   - `state`（可能是 `test_decision_paused`、`rebase_in_progress` 等）

2. 读取所有 implementation tickets 的 registries，提取：
   - `execution_worktree_path`
   - `execution_branch`
   - `state`（`running`、`terminal`、`integrated` 等）
   - `runtime`
   - `pane_id`
   - `thread_id` / `host_id`（如果有）

3. 验证 integration worktree：
   ```bash
   # 检查路径存在
   if [ ! -d "$INTEGRATION_PATH" ]; then
     echo "错误：integration worktree 不存在: $INTEGRATION_PATH"
     echo "无法恢复，请从 source worktree 重新运行 orchestrator"
     exit 1
   fi
   
   # 验证 worktree 已注册
   if ! git worktree list --porcelain | grep -q "worktree $INTEGRATION_PATH"; then
     echo "错误：integration worktree 未在 Git 注册"
     exit 1
   fi
   
   # 验证 branch
   ACTUAL_BRANCH=$(git -C "$INTEGRATION_PATH" branch --show-current)
   if [ "$ACTUAL_BRANCH" != "$INTEGRATION_BRANCH" ]; then
     echo "警告：integration worktree branch 不匹配"
     echo "Expected: $INTEGRATION_BRANCH, Actual: $ACTUAL_BRANCH"
   fi
   
   # 检查 working tree 状态
   DIRTY=$(git -C "$INTEGRATION_PATH" status --short)
   if [ -n "$DIRTY" ]; then
     echo "警告：integration worktree 有未提交变更："
     echo "$DIRTY"
     echo "请 commit 或 stash 后重新运行 orchestrator"
     exit 1
   fi
   ```

4. `dispatch_runtime: herdr` 或存在 Herdr lanes 时通过 `$herdr` 验证 workspace；只有
   `codex-thread` lanes 时跳过 workspace 操作。

5. 对每个 execution worktree：
   ```bash
   # 检查 path 存在
   if [ ! -d "$EXECUTION_PATH" ]; then
     echo "execution worktree 不存在: $EXECUTION_PATH"
     
     # 检查是否有 commit（可能已 integrated 但 registry 未更新）
     if git rev-parse --verify "$HEAD_COMMIT" >/dev/null 2>&1; then
       echo "commit 存在，可能已 integrated，从持久证据继续"
       # 标记为 terminal，进入 fan-in
     else
       echo "commit 不存在，标记为 setup_blocked"
       # 标记该 ticket 为 blocked
     fi
     continue
   fi
   
   # 验证 worktree 已注册
   if ! git worktree list --porcelain | grep -q "worktree $EXECUTION_PATH"; then
     echo "错误：execution worktree 未在 Git 注册: $EXECUTION_PATH"
     # 标记为 invalid，需要手动清理
     continue
   fi
   
   # 验证 branch
   ACTUAL_BRANCH=$(git -C "$EXECUTION_PATH" branch --show-current)
   if [ "$ACTUAL_BRANCH" != "$EXECUTION_BRANCH" ]; then
     echo "警告：execution worktree branch 不匹配"
     echo "Expected: $EXECUTION_BRANCH, Actual: $ACTUAL_BRANCH"
   fi
   ```

6. 对 `running` state 的 execution tickets 按 lane runtime 恢复：
   - `codex-thread`：用 `list_threads` / `read_thread` 验证 task，再带 cursor 调用
     `wait_threads`。
   - `herdr-codex-pane` / `herdr-claude-pane`：通过 `$herdr` 验证 pane；pane 存在时重挂
     listener，pane 消失时检查 final marker 与 commit。

7. 对 `terminal` state 的 execution tickets：
   ```bash
   # 读取 final report（从 registry 或 terminal marker）
   # 进入 integration 流程（cherry-pick）
   ```

8. 对 `integrated` / `close_pending` state 的 execution tickets：
   ```bash
   # 验证 execution worktree 和 branch 已删除
   if [ -d "$EXECUTION_PATH" ]; then
     echo "警告：execution worktree 应该已删除但仍存在: $EXECUTION_PATH"
     # 可能是 cleanup 失败，尝试重新 cleanup
   fi
   
   if git rev-parse --verify "$EXECUTION_BRANCH" >/dev/null 2>&1; then
     echo "警告：execution branch 应该已删除但仍存在: $EXECUTION_BRANCH"
     # 尝试重新删除
   fi
   ```
   - `codex-thread`：用 `list_archived_threads` 验证 task；仍在 active tasks 或 registry 为
     `close_pending` 时重试 `set_thread_archived`，成功 readback 后写 `closed`。
   - `herdr-codex-pane` / `herdr-claude-pane`：验证 pane 已关闭；`close_pending` 时重试关闭。

9. 根据 map state 恢复到正确位置：
   - `test_decision_paused`：重新显示 test decision prompt
   - `rebase_in_progress`：验证 rebase 状态，继续或重新开始
   - `push_failed`：重新尝试 push
   - `cleanup_in_progress`：继续 cleanup
   - 其他：根据 execution graph 状态决定下一步

**完成标准：** 所有 valid worktrees 已验证，running tasks 已重新 attach listener 或标记为 blocked，
terminal tasks 已进入 integration 流程，orchestrator 恢复到正确的 gate。

## Error Handling

**Integration worktree missing：**
- 无法恢复，报告用户从 source worktree 重新运行
- 不自动重新创建（可能丢失未 push 的工作）

**Execution worktree missing but commit exists：**
- 从持久证据继续 fan-in
- 标记该 ticket 为 terminal，进入 integration

**Herdr pane missing but terminal marker exists：**
- 读取 terminal marker，进入 fan-in
- 不重新创建 pane

**Dirty worktree during cleanup：**
- 保留 worktree，报告路径给用户
- 不删除，继续其他 cleanup

**Push fails after multiple retries：**
- 保留所有状态（integration worktree、registry）
- 报告详细错误和手动步骤
- 不自动 cleanup

**Conflict resolution fails after 3 retries：**
- 中止 rebase，恢复到 rebase 前状态
- 保留 integration worktree
- 报告用户手动解决冲突

## Verification Checklist

每个操作后验证：

- [ ] Rebase: working tree clean, no rebase-merge directory
- [ ] Push: remote main matches local main
- [ ] Integration worktree deleted: `! test -d "$INTEGRATION_PATH"`
- [ ] Integration branch deleted: `! git rev-parse --verify "$INTEGRATION_BRANCH" 2>/dev/null`
- [ ] Execution worktrees deleted: `git worktree list --porcelain` 不包含 `-map-${MAP_ISSUE}-issue-`
- [ ] Execution branches deleted: registry 中该 map 的 execution branches 均不存在
- [ ] Runtime transport closed: Codex App execution tasks archived；存在 Herdr workspace 时 panes 为空
- [ ] Map issue closed: tracker API 确认 issue state = closed
- [ ] Registry updated: readback `state: closed`

验证失败时，报告具体失败项（expected vs actual），不继续后续 cleanup。
