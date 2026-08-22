# Integration Worktree Management

本文件只拥有 Source Worktree、Map Integration Worktree 与 Execution Worktree 的创建、验证和
恢复。lane transport 归 `dispatch-runtime-routing.md`，terminal commit 的 Integration 与清理归
`execution-worktree-integration.md`，rebase/remote closeout 归 `test-decision-and-rebase.md`。

## Worktree hierarchy

```text
Source Worktree (main)
  └─ Map Integration Worktree (feature/map-<map>)
       ├─ Codex App-managed Execution Worktree (codex-thread)
       ├─ manual Execution Worktree (herdr-codex-pane)
       ├─ manual Execution Worktree (herdr-claude-pane)
       └─ ...
```

所有 Execution Worktree 都从 dispatch 时的 Integration branch HEAD 开始。Source Worktree
保持原 branch；每张 implementation ticket 只有一个 active writer。

## Map Integration Worktree

### Create

触发：用户从 Source Worktree 调用 `$delivery-pipeline`，目标 map 还没有有效的 Integration
Worktree。

```bash
SOURCE_ROOT=$(git rev-parse --show-toplevel)
SOURCE_HEAD=$(git rev-parse HEAD)
REPO_NAME=$(basename "$SOURCE_ROOT")
WORKTREES_ROOT=$(dirname "$SOURCE_ROOT")/worktrees
INTEGRATION_PATH="$WORKTREES_ROOT/${REPO_NAME}-map-${MAP_ISSUE}"
INTEGRATION_BRANCH="feature/map-${MAP_ISSUE}"
```

1. 验证 Source Worktree 的 repo、branch、HEAD 和 `git status --short`；dirty 时保留现场并请求
   用户处置。
2. 读取 map registry。路径或 branch 已存在时进入 Detect，不覆盖。
3. 从 `$SOURCE_HEAD` 创建：

   ```bash
   git worktree add -b "$INTEGRATION_BRANCH" "$INTEGRATION_PATH" "$SOURCE_HEAD"
   ```

4. 验证 path、Git registration、branch、HEAD、common dir 和 clean state。
5. map registry 写入 `integration_worktree_path`、`integration_branch`、`base_commit` 和当前
   `dispatch_runtime`；Codex App bridge 同时写 `herdr_session_name`、`herdr_session_owned` 与
   `bootstrap_authority`，随后精确 readback。
6. coordinator 在 Integration Worktree 继续。只有首条 Herdr lane 需要时才通过
   Herdr Control Route 懒创建 map workspace。

完成标准：Integration Worktree 唯一、clean、基于预期 Source HEAD，registry 与 Git 一致。

### Detect and recover

1. 从 map latest registry 读取 path、branch、base commit 与 lifecycle state。
2. 用 `git worktree list --porcelain` 验证 registration 和 common dir。
3. 验证实际 branch 等于 registry branch；detached 或不匹配写 `Unknown` 并停止自动写入。
4. dirty 时报告精确文件并保留；clean 时从最早未完成 gate 继续。
5. `dispatch_runtime` 只决定新 lane。existing lanes 按各自 registry 的 `runtime` 恢复。
6. map 存在 `herdr_workspace_label` 时只为仍属 Herdr runtime 的 lane 验证 workspace；
   `codex-thread` map 不创建 Herdr workspace。

完成标准：coordinator 已定位唯一有效 Integration Worktree，所有 existing lane 已完成 active
writer 去重。

### Input routing

| 输入 | 当前位置 | Map Integration Worktree | 行为 |
| --- | --- | --- | --- |
| map | Source Worktree | absent | create |
| map | Source Worktree | valid | recover |
| map/spec/tickets | matching Integration Worktree | valid | continue |
| spec/tickets | Source Worktree | map 可追溯 | create or recover map worktree |
| any | other map Integration Worktree | mismatch | stop and report expected/actual |

当前位置优先用 branch 判定，detached HEAD 才用 path + common dir + registry 组合判定；单独路径名
不是证据。

## Execution Worktree provisioning

触发：ready frontier 已选择 maximal safe batch，且每张票均已排除 existing active writer。

### `runtime: codex-thread`

1. 记录当前 Integration HEAD 作为 `base_commit`。
2. 按 `dispatch-runtime-routing.md` 调用 `create_thread`，target 为 Source owner project，worktree
   `startingState` 指向 Integration branch。Codex App 创建并拥有路径。
3. setup ready 后 readback 实际 path、HEAD、common dir 和 clean state。worker 首次写入前创建或
   验证 `codex/issue-<ticket>` branch。
4. registry 保存实际 worktree、branch、base commit、project/host/thread coordinates。

完成标准：App-managed Execution Worktree 与 task 一一对应，HEAD 包含 dispatch base，Source
Worktree 和 Integration Worktree 都未被 child 写入。

### `runtime: herdr-codex-pane | herdr-claude-pane`

```bash
INTEGRATION_ROOT=$(git rev-parse --show-toplevel)
INTEGRATION_BRANCH=$(git branch --show-current)
INTEGRATION_HEAD=$(git rev-parse HEAD)
REPO_NAME=$(basename "$INTEGRATION_ROOT" | sed -E 's/-map-[0-9]+$//')
MAP_ISSUE=$(basename "$INTEGRATION_ROOT" | sed -E 's/.*-map-([0-9]+)$/\1/')
WORKTREES_ROOT=$(dirname "$INTEGRATION_ROOT")
EXECUTION_PATH="$WORKTREES_ROOT/${REPO_NAME}-map-${MAP_ISSUE}-issue-${TICKET_NUMBER}"
if [ "$LANE_RUNTIME" = "herdr-claude-pane" ]; then
  EXECUTION_BRANCH="claude/issue-${TICKET_NUMBER}"
else
  EXECUTION_BRANCH="codex/issue-${TICKET_NUMBER}"
fi
```

1. 验证 Integration branch、clean state 与 `INTEGRATION_HEAD`。
2. 路径或 branch 已存在时先执行 Conflict detection；唯一匹配则恢复，否则阻塞该票。
3. 创建并验证：

   ```bash
   git worktree add -b "$EXECUTION_BRANCH" "$EXECUTION_PATH" "$INTEGRATION_HEAD"
   ```

4. registry 保存 worktree、branch、base commit，随后按 routing owner 创建 kind-matched pane 并补写
   workspace/tab/pane coordinates。

完成标准：手工 Execution Worktree 与 kind-matched pane 一一对应，branch/HEAD/registry 一致。

## Conflict detection

对任何已存在的 worktree path 或 branch 执行 bounded recovery：

1. path 必须出现在 `git worktree list --porcelain`。
2. common dir、work item、branch 和 registry 必须全部唯一匹配。
3. 唯一匹配且没有第二个 active writer 时恢复。
4. 零个或多个匹配标记 `path_conflict` 或 `Unknown`；保留已有目录、branch 和 task/pane。

不得用 force add、目录覆盖或第二个 lane 解决冲突。

## Recovery

1. 从 map/spec/tickets 枚举 latest lane registries。
2. 逐条验证 worktree path、common dir、branch、base/head commit 和 dirty state。
3. `codex-thread` 用原生 thread tools 恢复；两种 Herdr pane 都用 Herdr Control Route 恢复。
4. lane transport 消失但 commit 存在时从 Git 证据进入 terminal fan-in；两者都不存在且已排除
   active writer 时才允许 replacement。
5. `integrated` lane 应已清理 Execution Worktree；残留且 clean 时重试 cleanup，dirty 时保留并
   报告。

## Verification checklist

- [ ] `git worktree list --porcelain` 包含预期 path。
- [ ] common dir 属于 Source repo。
- [ ] branch 与 registry 一致。
- [ ] Execution HEAD 包含 dispatch `base_commit`。
- [ ] `git status --short` 符合当前 lifecycle 预期。
- [ ] lane runtime 与 task/pane coordinates 匹配。
- [ ] registry 精确 readback。

任一项失败时报告 expected/actual，保留可能含用户数据的 worktree，并停止该 lane 的后续 gate。
