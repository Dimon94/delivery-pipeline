# Git hook GIT_DIR 泄漏污染 fixture 与共享仓库配置

## Symptom

# 124 commit 时 pre-commit hook（validate.py 在 staged 树临时副本上运行）中的 recovery_check fixture 执行 git init/config/commit 失败（exit 128），且泄漏把 user=probe、core.bare=true 写进 Source 共享 .git/config，导致所有 worktree 报 fatal: this operation must be run in a work tree。

## Root cause (confirmed)

git 调用 hook 时导出 GIT_DIR/GIT_INDEX_FILE 等环境变量；fixture 在新临时 repo 中运行 git 子进程未剥离 GIT_*，init/config 操作落到了 GIT_DIR 指向的真实仓库（配合 extensions.worktreeConfig 写进 commondir 共享 config）。

## Lesson

任何在 git hook 触发链下运行的脚本，凡是要在自建临时 repo 中执行 git 子进程，必须显式剥离 GIT_*环境变量（env scrub）。修复见 skills/delivery-pipeline-orca/scripts/recovery_check.py（GIT_* env scrub）。事故与修复证据：lane-114-124 artifacts source-git-config-before-repair.txt。

## Recall condition

修改/新增在 validate.py 或 git hook 链路下执行 git 子进程的脚本；或 worktree 突然报 must be run in a work tree。

## Recurrence key

hook-git-env-leak-into-fixture-repo
