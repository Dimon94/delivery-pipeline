# Integration Worktree Management

每个 Wayfinder map 自动获得独立的 integration worktree，discovery/spec/tickets 在其中运行，
execution tickets 再从 integration worktree 分支出独立 execution worktrees。source worktree 保持
main 分支不变。

## Two-Tier Worktree Hierarchy

```text
source worktree (main)
  └─ integration worktree (feature/map-<issue>)
       ├─ execution worktree 1 (codex/issue-<ticket-1>)
       ├─ execution worktree 2 (codex/issue-<ticket-2>)
       └─ ...
```

**为什么需要两层：**
- discovery/spec 的变更需要对所有 execution tickets 可见。
- execution tickets 可以依赖彼此的变更（通过 cherry-pick 到 integration worktree）。
- integration worktree 提供 whole-change checks 的运行位置。
- source worktree 始终在 main 上，多个 map 可并行运行。

## Integration Worktree Lifecycle

### Creation

**触发：** 用户在 source worktree 运行 `/delivery-pipeline <map-issue>`，
且该 map 还没有 integration worktree。

**路径计算：**

```bash
# 1. 获取 source worktree 信息
SOURCE_ROOT=$(git rev-parse --show-toplevel)
SOURCE_HEAD=$(git rev-parse HEAD)
REPO_NAME=$(basename "$SOURCE_ROOT")

# 2. 计算 integration worktree 路径
WORKTREES_ROOT=$(dirname "$SOURCE_ROOT")/worktrees
INTEGRATION_PATH="$WORKTREES_ROOT/${REPO_NAME}-map-${MAP_ISSUE}"
INTEGRATION_BRANCH="feature/map-${MAP_ISSUE}"
```

**创建序列：**

1. 验证 source worktree 在 main/stable 分支上且 working tree clean。
2. 检查 `$INTEGRATION_PATH` 不存在，或已存在且是该 map 的有效 worktree。
3. 创建 worktree：
   ```bash
   git worktree add -b "$INTEGRATION_BRANCH" "$INTEGRATION_PATH" "$SOURCE_HEAD"
   ```
4. 验证创建结果：
   ```bash
   git -C "$INTEGRATION_PATH" rev-parse --show-toplevel  # 应返回 $INTEGRATION_PATH
   git -C "$INTEGRATION_PATH" branch --show-current       # 应返回 $INTEGRATION_BRANCH
   git -C "$INTEGRATION_PATH" status --short              # 应为空（clean working tree）
   ```
5. 从 map issue title 提取关键词，生成 workspace label：
   ```text
   例：issue title "重构用户登录模块" → workspace label "用户登录重构-map-101"
   ```
6. 委托 `/pane-dispatch`：
   ```bash
   cd "$INTEGRATION_PATH"
   /herdr workspace create --label "<map-title>-map-<issue>"
   # 或 workspace rename 如果已存在
   ```
7. 将 integration worktree metadata 写入 map issue 的 lane registry comment。
8. 切换到 integration worktree：`cd "$INTEGRATION_PATH"`。

**完成标准：** integration worktree 已创建、branch 正确、working tree clean、workspace 已创建、
registry 已 readback、orchestrator `cwd` 位于 integration worktree。

### Detection (Session Restart)

**触发：** 新会话启动，输入是 map issue，需要检测是否已有 integration worktree。

**检测序列：**

1. 读取 map issue 的最新 lane registry comment，查找 `integration_worktree_path` 字段。
2. 如果 registry 存在：
   ```bash
   # 验证路径存在
   test -d "$INTEGRATION_PATH"
   
   # 验证 worktree 已在 Git 注册
   git worktree list --porcelain | grep -F "worktree $INTEGRATION_PATH"
   
   # 验证 branch 正确
   ACTUAL_BRANCH=$(git -C "$INTEGRATION_PATH" branch --show-current)
   test "$ACTUAL_BRANCH" = "$INTEGRATION_BRANCH"
   
   # 检查 working tree 状态
   DIRTY=$(git -C "$INTEGRATION_PATH" status --short)
   ```
3. 如果 worktree valid 且 clean：提示用户确认 resume（显示 integration worktree 路径和当前 gate），
   用户确认后切换到 integration worktree 并继续。
4. 如果 worktree valid 但 dirty：报告 uncommitted changes，询问用户是 stash/commit/abort。
5. 如果 worktree invalid 或路径不存在：报告 "integration worktree missing or invalid"，
   询问用户是否重新创建。

**Herdr workspace 恢复：**

从 registry 读取 `herdr_workspace_id` 或 `herdr_workspace_label`，验证 workspace 存在。
不存在时重新创建。

**完成标准：** orchestrator 已切换到 valid integration worktree，gate state 已从 registry 恢复，
workspace 已确认存在，用户已确认 resume。

### Routing Logic

**输入类型与位置决定行为：**

| 输入 | 当前位置 | Existing Integration Worktree | 行为 |
|------|---------|------------------------------|------|
| map issue | source worktree | 不存在 | 创建 integration worktree，从 discovery 开始 |
| map issue | source worktree | 存在且 valid | 提示用户确认 resume，切换到 integration worktree |
| map issue | integration worktree | 自己 | 直接继续当前 gate |
| map issue | integration worktree | 不匹配 | 错误：在错误的 integration worktree |
| spec/tickets | source worktree | 可追溯到 map | 追溯 map，创建/恢复 integration worktree，运行 |
| spec/tickets | source worktree | 无法追溯 | 错误：spec/tickets 必须在 integration worktree 或能追溯到 map |
| spec/tickets | integration worktree | 自己 | 直接继续 |

**检测当前位置是 source 还是 integration worktree：**

优先使用 branch 名称检测（最可靠）：

```bash
CURRENT_BRANCH=$(git branch --show-current)

if [[ "$CURRENT_BRANCH" =~ ^feature/map-[0-9]+$ ]]; then
  WORKTREE_TYPE="integration"
elif [[ "$CURRENT_BRANCH" = "main" || "$CURRENT_BRANCH" = "master" ]]; then
  WORKTREE_TYPE="source"
else
  # 后备方案：检查路径模式
  CURRENT_ROOT=$(git rev-parse --show-toplevel)
  if [[ "$CURRENT_ROOT" =~ /worktrees/.*-map-[0-9]+$ ]]; then
    WORKTREE_TYPE="integration"
  else
    WORKTREE_TYPE="source"
  fi
fi
```

Branch 名称检测失败或 detached HEAD 时才使用路径模式后备方案。

## Execution Worktree Lifecycle

### Creation (from Integration Worktree)

**触发：** dispatch gate，ready frontier 中的每张 ticket 创建一个 execution worktree。

**路径计算：**

```bash
# 当前必须在 integration worktree
INTEGRATION_ROOT=$(git rev-parse --show-toplevel)
INTEGRATION_BRANCH=$(git branch --show-current)  # feature/map-<map-issue>

# 从 integration worktree 路径提取 repo name 和 map issue
# 例：/Users/user/projects/worktrees/my-app-map-101 → my-app, 101
REPO_NAME=$(basename "$INTEGRATION_ROOT" | sed -E 's/-map-[0-9]+$//')
MAP_ISSUE=$(basename "$INTEGRATION_ROOT" | sed -E 's/.*-map-([0-9]+)$/\1/')

# 计算 execution worktree 路径
WORKTREES_ROOT=$(dirname "$INTEGRATION_ROOT")
EXECUTION_PATH="$WORKTREES_ROOT/${REPO_NAME}-map-${MAP_ISSUE}-issue-${TICKET_NUMBER}"
EXECUTION_BRANCH="codex/issue-${TICKET_NUMBER}"
```

**创建序列：**

1. 验证当前在 integration worktree（检查 branch 是 `feature/map-*`）。
2. 验证 integration worktree working tree clean。
3. 检查 `$EXECUTION_PATH` 不存在。
4. 从 integration worktree 的当前 HEAD 创建 execution worktree：
   ```bash
   git worktree add -b "$EXECUTION_BRANCH" "$EXECUTION_PATH" HEAD
   ```
5. 验证创建结果（同 integration worktree）。
6. 将 execution worktree metadata 写入 ticket issue 的 lane registry comment，
   包含 `integration_worktree_path` 指向 parent。
7. 委托 `/pane-dispatch`：在 workspace `<map-title>-map-<map-issue>` 中创建 pane，
   放入 X tab（执行 capacity management）。

**Herdr capacity management：**

- LEAD tab：只有 orchestrator coordinator，不放 execution panes。
- X tabs：execution tickets，每个 tab 最多 4 panes。
- tab 满时创建 X-2, X-3, ...
- pane 创建时：`herdr tab rename <tab-id>` 更新 label 包含活跃 issue 编号。
- pane 关闭时：`herdr tab rename <tab-id>` 移除该 issue 编号。

**完成标准：** execution worktree 已创建、branch 正确、pane 已创建、registry 已 readback。

### Integration (Cherry-pick)

**触发：** execution worker 报告 terminal with commit hash。

**集成序列：**

1. 验证 execution worktree commit 存在：
   ```bash
   git -C "$EXECUTION_PATH" rev-parse "$COMMIT_HASH"
   ```
2. 切换到 integration worktree（如果不在）：
   ```bash
   cd "$INTEGRATION_PATH"
   ```
3. Cherry-pick execution commit：
   ```bash
   git cherry-pick "$COMMIT_HASH"
   ```
4. 如果冲突：
   ```bash
   # 检测冲突
   git status | grep -q "both modified"
   
   # 报告 blocker，不在这里调用 conflict resolution（用户可能需要上下文）
   # 标记该 ticket 为 blocked，等待用户手动解决或调用 /resolving-merge-conflicts
   ```
5. 如果 cherry-pick 成功，运行 focused checks：
   ```bash
   # 根据 touched files 运行相关 type checks/lints/tests
   ```
6. 如果 checks 通过，删除 execution worktree：
   ```bash
   git worktree remove "$EXECUTION_PATH"
   git branch -D "$EXECUTION_BRANCH"
   ```
7. 通过 `/pane-dispatch`：关闭 pane，rename tab 移除 issue 编号。
8. 更新 ticket registry：`state: integrated`。
9. 重算 ready frontier（可能有新 tickets 解锁）。

**完成标准：** execution commit 已 cherry-pick 到 integration worktree、checks 通过、
execution worktree 已删除、registry 已更新。

### Cleanup on Failure

**触发：** execution worktree 的 startup probe 失败两次，或 worktree 状态 invalid。

**删除序列：**

```bash
# 立即删除，不保留（已知是坏状态）
git worktree remove --force "$EXECUTION_PATH"
git branch -D "$EXECUTION_BRANCH"
```

标记 ticket 为 `setup blocked`，报告原因。用户需要手动检查或重新 dispatch。

## Rebase to Main and Cleanup

**触发：** 所有 tickets integrated 到 integration worktree，whole-change checks 通过，
用户完成 test decision。

**详见 `references/test-decision-and-rebase.md`**，包含：
- Test decision point（三种测试策略选择）
- Rebase sequence（自动 rebase 到最新 main，冲突委托 conflict resolution）
- Push and cleanup sequence（push 到 main，删除所有 worktrees/branches）
- Full recovery from registry（crash 恢复）

## Recovery from Registry

**触发：** 新会话启动，从 map issue registry 恢复状态。

**基础恢复序列（简化版，完整版见 test-decision-and-rebase.md）：**

1. 读取 map issue 的 latest lane registry comment，提取 `integration_worktree_path`。
2. 读取所有 implementation tickets 的 registries，提取 `execution_worktree_path`。
3. 对 integration worktree：
   ```bash
   # 验证存在且 valid（见 Detection 序列）
   # 恢复 Herdr workspace
   ```
4. 对每个 execution worktree：
   ```bash
   # 验证 path 存在
   test -d "$EXECUTION_PATH"
   
   # 验证 worktree 已注册
   git worktree list --porcelain | grep -F "worktree $EXECUTION_PATH"
   
   # 验证 branch
   ACTUAL_BRANCH=$(git -C "$EXECUTION_PATH" branch --show-current)
   test "$ACTUAL_BRANCH" = "$EXECUTION_BRANCH"
   
   # 从 registry 读取 thread_id 和 state
   # 如果 state = running，通过 thread tools 验证 task 存在
   # 恢复 /pane-dispatch pane listener
   ```
5. 对 `running` state 的 tasks：重新调用 `wait_threads`。
6. 对 `terminal` state：读取 final report，进入 fan-in。
7. 对 missing task but commit exists：从持久证据继续 fan-in。
8. 对 registry 与现实不一致：标记 stale，确认没有 active writer 后才能 replacement。

**完成标准：** 所有 valid worktrees 已恢复、running tasks 已重新 wait、
terminal tasks 已进入 fan-in。

## Path Conflict Detection

**在创建任何 worktree 前检查路径冲突：**

```bash
WORKTREE_PATH="$WORKTREES_ROOT/${REPO_NAME}-map-${MAP_ISSUE}-issue-${TICKET_NUMBER}"

if [ -e "$WORKTREE_PATH" ]; then
  # 路径存在，检查是否是该 ticket 的 valid worktree
  if git worktree list --porcelain | grep -q "worktree $WORKTREE_PATH"; then
    # 是 Git worktree，验证是否属于该 ticket
    ACTUAL_BRANCH=$(git -C "$WORKTREE_PATH" branch --show-current)
    if [ "$ACTUAL_BRANCH" = "codex/issue-${TICKET_NUMBER}" ]; then
      # 是该 ticket 的 worktree，可恢复
      echo "恢复现有 worktree"
    else
      # 是其他 ticket 的 worktree，冲突
      echo "错误：路径被其他 ticket 占用"
      # defer 该 ticket
    fi
  else
    # 不是 Git worktree，是其他文件/目录，冲突
    echo "错误：路径已存在且不是 worktree"
    # defer 该 ticket
  fi
fi
```

**Defer ticket 时：** 标记为 `path conflict blocked`，报告给用户，不覆盖现有文件。

## Verification Checklist

每个 worktree 操作后验证：

- [ ] Path exists: `test -d "$WORKTREE_PATH"`
- [ ] Worktree registered: `git worktree list --porcelain | grep "worktree $WORKTREE_PATH"`
- [ ] Branch correct: `git -C "$WORKTREE_PATH" branch --show-current`
- [ ] Working tree clean: `git -C "$WORKTREE_PATH" status --short` (空输出)
- [ ] Base commit correct: `git -C "$WORKTREE_PATH" merge-base HEAD main`
- [ ] Registry persisted: readback from tracker comment
- [ ] Herdr workspace/pane exists: verify via `/pane-dispatch` tools

验证失败时：报告详细错误（哪一步失败、实际 vs 预期），不继续后续 gate。
