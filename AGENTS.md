<identity>
每次开始工作先读 repo://CONTEXT.md。使用其中的统一语言(Source Worktree、Map Integration Worktree、Execution Worktree、Integration、Herdr Workspace、Dispatch Model)。
交互、文档和注释使用简明中文。证据不足时写 Unknown,推断显式标注"推断"。
</identity>

<project>
定位:delivery-pipeline 多 runtime skill bundle —— 一条可恢复的交付链(idea/map → discovery → spec → tickets → 配置驱动的 CLI/worktree 分派 → integration → testing/review → 汇总 PR/MR)。
Canonical CLI/Herdr 主干是 repo://skills/delivery-pipeline/,由 pi、Codex CLI、Claude CLI 共用;Codex App 特殊 transport 只在 repo://skills/delivery-pipeline-codex-app/;首次配置在 repo://skills/delivery-pipeline-setup/。ticket-sizing 粒度判据在 repo://skills/ticket-sizing/,主干树外不再有 runtime 副本。软链安装即生效;安装与用法见 repo://README.md 和 repo://README.zh-CN.md。
事实优先级:运行证据 > 代码与 scripts/validate.py > repo://CONTEXT.md 与 accepted ADR > 推理。
</project>

<workflow>
改前读取 repo://CONTEXT.md、相关 ADR(repo://docs/adr/)和目标文件的直接调用者。
一次变更只解决一个可独立验证的语义目标。保留用户的无关改动。
</workflow>

<constraints>
Canonical 主干保持 runtime-neutral:owner 以 name + absolute SKILL.md path + runtime-specific invocation label 三字段传递;主干正文不写 Codex `$name` 或 Claude plugin locator。Runtime-specific transport 内容与其壳/helper 共置;`codex-thread` 只存在于 delivery-pipeline-codex-app 树。
提交前必跑 `python3 scripts/validate.py`;pre-commit hook 与 CI(.github/workflows/validate.yml)强制执行。
Git 只 stage 语义相关路径,不用 git add .。
提交、推送、建 PR 需要用户明确要求。
</constraints>

<forge>
Issue、代码和 CI 归 GitHub,项目坐标 `Dimon94/delivery-pipeline`,操作走 `gh` CLI。约定见 repo://docs/agents/issue-tracker.md。
</forge>

<done_definition>
完成前说明触达坐标、实际改动、验证命令和结果。validate.py 必须绿。
修复缺陷时,同一最小检查必须先失败后通过。
</done_definition>

## Agent skills

### Issue tracker

Issue 归 GitHub(`Dimon94/delivery-pipeline`),操作用 `gh` CLI;`.scratch/` 只是 feature 工作区。详见 `docs/agents/issue-tracker.md`。

### Triage labels

五个 canonical 标签:`needs-triage`、`needs-info`、`ready-for-agent`、`ready-for-human`、`wontfix`。详见 `docs/agents/triage-labels.md`。

### Domain docs

单上下文:根目录 `CONTEXT.md` + `docs/adr/`。详见 `docs/agents/domain.md`。
