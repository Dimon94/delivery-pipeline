# Herdr Codex 派发

仅在派发已选中的 `maximal safe batch` 时使用。本文件只规定易出错的 Herdr 落点操作。

## Workspace 与 worktree

1. 从 tracker project 或显式 map key 得到稳定坐标。
2. 运行 `herdr workspace list`，选择 label 与该坐标匹配的已有 workspace。
3. 无匹配 workspace 时停止派发；本 skill 不创建 workspace。
4. 在 source repo 记录：

   ```bash
   git rev-parse --show-toplevel
   git rev-parse HEAD
   git rev-parse --path-format=absolute --git-common-dir
   git worktree list --porcelain
   ```

5. 每张票分配 branch `codex/issue-<number>` 和独立路径
   `<worktree-root>/<repo-name>-issue-<number>`。未传 `--worktree-root` 时使用 source repo
   的父目录。路径已经属于其他 worktree、存在未注册目录、被活跃 writer 使用或无法证明
   所属同一 repo 时，把该票记为 `deferred`，不得覆盖或清理。
6. 创建 worktree：

   ```bash
   # branch 不存在
   git worktree add -b codex/issue-<number> <lane-path> <base-commit>

   # branch 已存在但未挂载到其他 worktree
   git worktree add <lane-path> codex/issue-<number>
   ```

7. 已有 worktree 只有在没有活跃 writer、branch 正确且 working tree clean 时才能复用。
8. 创建或复用后必须全部通过：

   ```bash
   git -C <lane-path> rev-parse --show-toplevel
   git -C <lane-path> rev-parse --path-format=absolute --git-common-dir
   git -C <lane-path> branch --show-current
   git -C <lane-path> status --short
   ```

   `show-toplevel` 必须等于 `<lane-path>`，`git-common-dir` 必须与 source repo 相同，branch
   必须等于 `codex/issue-<number>`，`status --short` 必须为空。任一不满足就记为
   `deferred`，不创建 pane。
9. source worktree 保持当前 branch；所有 branch 操作都通过 source repo 的
   `git worktree add` 完成。

## X tab 容量

- 执行 tab label 以 `X-` 开头，只列当前活跃 ticket 编号，例如 `X-#957·#958`。
- 每个 X tab 最多 4 个 panes。优先使用当前有容量的 X tab，再扫描其他 X tabs；都满时
  用 `herdr tab create --workspace <workspace-id> --no-focus` 创建新 tab。
- 新 tab 自带的默认 shell pane 不承载 worker；Codex pane 验证成功后再关闭该空 pane。

## 原子派发

一张票完整走完以下步骤后再处理下一张：

1. 使用显式 workspace、tab 和 worktree cwd 启动 Codex：

   ```bash
   herdr agent start "codex-<issue-number>" \
     --workspace <workspace-id> \
     --tab <tab-id> \
     --cwd <lane-path> \
     --no-focus \
     -- codex -s danger-full-access -a never
   ```

2. 从结果读取 `pane-id`，投递并执行指令：

   ```bash
   herdr pane send-text <pane-id> '$implement <issue-url>'
   herdr pane send-keys <pane-id> Enter
   ```

3. 重命名 pane，并同步 tab label：

   ```bash
   herdr pane rename <pane-id> '#<issue-number> <标题摘要>'
   herdr tab rename <tab-id> 'X-#<active-issue>·#<active-issue>'
   ```

4. 运行 `herdr pane get <pane-id>`，确认 `workspace_id`、`tab_id`，并确认 `cwd` 精确等于
   `<lane-path>`；再读取 agent status，确认 Codex 已启动并收到指令。
5. 新 tab 若仍有默认空 shell pane，在 Codex pane 验证成功后运行
   `herdr pane close <default-pane-id>`。

所有创建命令必须显式带 `--workspace`、`--tab`、`--cwd` 和 `--no-focus`；用户当前聚焦
位置不是派发坐标。

## 失败隔离

- 任一步返回错误都停止该票的原子组。
- 已创建错误 pane 时先关闭它，再用重新解析的显式坐标重试一次。
- 两次失败后把该票记为 `deferred`，记录命令、错误与目标坐标，继续处理 batch 里的其他票。
- worktree 创建或验证失败时不启动 Codex，也不删除、重置或覆盖现有路径。
- 派发完成后不启动 wait、watchdog 或 terminal fan-in；调用方拥有后续生命周期。
