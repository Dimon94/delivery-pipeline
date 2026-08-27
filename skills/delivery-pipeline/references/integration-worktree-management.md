# Integration Worktree Management

只拥有 Source Worktree、Map Integration Worktree 与手工 Execution Worktree 的创建、验证和恢复。
CLI lane transport 归 `dispatch-runtime-routing.md`，terminal Integration/cleanup 归
`execution-worktree-integration.md`。

## Hierarchy

```text
Source Worktree (main)
  └─ Map Integration Worktree (feature/map-<map>)
       ├─ manual Execution Worktree (herdr-pi-pane)
       ├─ manual Execution Worktree (herdr-codex-pane)
       └─ manual Execution Worktree (herdr-claude-pane)
```

所有 Execution Worktree 从 dispatch 时 Integration HEAD 开始；Git mutation显式使用
`-C <target>`，Coordinator Pane的 cwd与 checked-out branch保持不变；每个 work item只有一个
active writer。

## Map Integration Worktree

先用 map registry + `git worktree list --porcelain` 恢复已登记且唯一匹配的 Integration
path/branch。Map Integration Worktree/branch 不存在时创建独立 worktree 与 branch；不在
coordinator pane 的 cwd 切换 branch，也不把该 cwd直接当作新的 Integration Worktree。

从 Source Worktree启动 map 时：

```bash
SOURCE_ROOT=$(git rev-parse --show-toplevel)
SOURCE_HEAD=$(git rev-parse HEAD)
REPO_NAME=$(basename "$SOURCE_ROOT")
WORKTREES_ROOT=$(dirname "$SOURCE_ROOT")/worktrees
INTEGRATION_PATH="$WORKTREES_ROOT/${REPO_NAME}-map-${MAP_ISSUE}"
INTEGRATION_BRANCH="feature/map-${MAP_ISSUE}"
git -C "$SOURCE_ROOT" worktree add -b "$INTEGRATION_BRANCH" "$INTEGRATION_PATH" "$SOURCE_HEAD"
```

创建前记录 Coordinator Pane 的 repo root/branch/HEAD，验证 Source repo/branch/HEAD/clean state
与 map registry；路径/branch已存在时 bounded recover，不覆盖。创建后验证 registration、common
dir、branch、HEAD与 clean state，写入 registry并 readback，再断言 Coordinator Pane 的 repo
root/branch/HEAD未因创建而改变。Herdr Workspace选择与 Git worktree层级相互独立。

恢复时以 registry + `git worktree list --porcelain` + common dir + branch + base commit 交叉验证；
dirty、detached 或多匹配时保留现场并停止自动写入。

## Execution Worktree

从 role config 得到 agent/runtime 后，branch prefix 对应 agent：`pi/`、`codex/`、`claude/`。

```bash
INTEGRATION_ROOT=$(git rev-parse --show-toplevel)
INTEGRATION_HEAD=$(git rev-parse HEAD)
EXECUTION_PATH="<worktrees-root>/<repo>-map-<map>-issue-<coordinate>"
EXECUTION_BRANCH="<agent>/issue-<coordinate>"
git -C "$INTEGRATION_ROOT" worktree add -b "$EXECUTION_BRANCH" "$EXECUTION_PATH" "$INTEGRATION_HEAD"
```

1. 验证 Integration branch 与 clean state。
2. path/branch 已存在时，用 work item、runtime、registry、common dir、base commit 证明唯一匹配；
   无法证明则记 `path_conflict` / Unknown。
3. 创建后验证 path、branch、HEAD、common dir、clean state。
4. registry 写 role、agent、model、effort、runtime、worktree、branch、base commit，readback 后才在
   dispatch target Workspace按 `pane-lifecycle-rules.md` 容量管理规则放置 lane pane;不改变
   Coordinator Pane cwd/branch。

## Recovery

逐 lane 验证 path/common dir/branch/base/head/dirty state及 kind-matched pane。transport 消失但
commit 存在时沿 Git 证据 fan-in；两者都不存在且排除 active writer 后才 replacement。
`integrated` lane 的残留 worktree clean 时重试 cleanup，dirty 时保留并报告。

任一验证失败均报告 expected/actual，不使用 force add、不覆盖目录、不创建第二 writer。
