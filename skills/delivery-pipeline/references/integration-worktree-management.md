# Integration Worktree Management

只拥有 Source Worktree、Map Integration Worktree 与手工 Execution Worktree 的创建、验证和恢复。
lane transport 归所属壳的 dispatch 合同，terminal Integration/cleanup 归
`execution-worktree-integration.md`。

## Hierarchy

```text
Source Worktree (main)
  └─ Map Integration Worktree (feature/map-<map>)
       ├─ manual Execution Worktree (herdr-pi-pane)
       ├─ manual Execution Worktree (herdr-codex-pane)
       └─ manual Execution Worktree (herdr-claude-pane)
```

Map 集成模式下所有 Execution Worktree 从 dispatch 时 Integration HEAD 开始（独立票模式见下节）；Git mutation显式使用
`-C <target>`，Coordinator Pane的 cwd与 checked-out branch保持不变；每个 work item只有一个
active writer。

## 独立票模式（Ticket Release Mode）

map 或用户明确要求逐票上线时启用，写入 map registry `delivery_mode: ticket_release` 并 readback；
未写明时沿用 Map 集成模式。本节是该模式的唯一规则，其他合同只指向这里。

- **建树。** 每票 dispatch 前 `git fetch` 目标仓远端，从远端默认分支（如 `origin/main`）当时 SHA
  建本票 Execution Worktree/branch；分支命名、MR 目标与禁止直推遵守目标仓分支合同（如 App Studio
  `docs/agents/git-branching.md`）。不建、不恢复 Map Integration Worktree，旧 Integration HEAD
  不作 base。lane registry 记该 SHA 为 `base_commit`，它就是本票 Review fixed point。
- **交付。** 一票一 MR 到默认分支；不 cherry-pick、不开 summary MR。testing/review/CI 的范围是
  本票 diff。ready 只看本票真实 `Blocked by`；sibling 的 running/blocked 与 milestone 完成率不阻塞。
- **状态分段记录，不互相替代。** lane registry 另记 `release_stage`（不新增 lane state）：
  `candidate`（MR 已开、本票检查与独立 review 通过）→ `merged`（用户对当前 head SHA 授权后合入，
  读回 merge commit）→ `deployed`（按目标仓发布对象读回运行版本与业务验收；无部署对象写 `N/A`
  及理由）。lane 停在 `terminal` 直到 `deployed`，再走 cleanup → `closed`、关票、删树删分支。
  worker transport 可以在 `candidate` 后释放。
- 保留模型配置、checkpoint、单写者与独立 review 合同；不新增 gate 或框架。

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
dir、branch、HEAD与 clean state，在 map registry 的 `role: map` 行写
`base_commit: <SOURCE_HEAD>` 并 readback；该值是 whole-change Review fixed point。随后断言
Coordinator Pane 的 repo root/branch/HEAD未因创建而改变。Herdr Workspace选择与 Git worktree层级相互独立。

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
   dispatch target 按所属壳的容量管理规则放置 worker;不改变
   coordinator 当前目录的 cwd/branch。

## Recovery

逐 lane 验证 path/common dir/branch/base/head/dirty state及 kind-matched pane。transport 消失但
commit 存在时沿 Git 证据 fan-in；两者都不存在且排除 active writer 后才 replacement。
`integrated` lane 的残留 worktree clean 时重试 cleanup，dirty 时保留并报告。

任一验证失败均报告 expected/actual，不使用 force add、不覆盖目录、不创建第二 writer。
