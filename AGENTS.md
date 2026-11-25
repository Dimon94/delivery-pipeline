<identity>
涉及领域术语或编排语义时读取 repo://GLOSSARY.md 对应概念，沿用其中的统一语言。
交互、文档和注释使用简明中文。证据不足时写 Unknown,推断显式标注"推断"。
</identity>

<project>
定位:delivery-pipeline 多 runtime skill bundle —— 一条可恢复的交付链(idea/map → discovery → spec → tickets → 配置驱动的 CLI/worktree 分派 → integration → testing/review → 汇总 PR/MR)。
Canonical 核心链路是 repo://skills/delivery-pipeline/,由五个平级 transport 壳共用;CLI/Herdr transport 在 repo://skills/delivery-pipeline-herdr/（供 pi、Codex CLI、Claude CLI）;T3 Code transport 在 repo://skills/delivery-pipeline-t3code/;Lody transport 在 repo://skills/delivery-pipeline-lody/;Codex App 特殊 transport 只在 repo://skills/delivery-pipeline-codex-app/;Orca 独立入口在 repo://skills/delivery-pipeline-orca/;首次配置在 repo://skills/delivery-pipeline-setup/。ticket-sizing 粒度判据由 my-skills 仓拥有，按运行时 Skill 名称解析；本仓不携带或安装它。软链安装即生效;安装与用法见 repo://README.md 和 repo://README.zh-CN.md。
事实优先级:运行证据 > 代码与 scripts/validate.py > repo://GLOSSARY.md 与 accepted ADR > 推理。
</project>

<workflow>
改变行为时检查目标文件的直接调用者；改变架构决策时读取相关 accepted ADR(repo://docs/adr/)。
纯措辞或格式修订只读取目标及必要引用，不要求全量领域文档。
一次变更只解决一个可独立验证的语义目标。保留用户的无关改动。
</workflow>

<constraints>
Canonical 核心链路保持 runtime-neutral:owner 以 name + absolute SKILL.md path + runtime-specific invocation label 三字段传递;核心链路正文不写 Codex `$name` 或 Claude plugin locator。Runtime-specific transport 内容与其壳/helper 共置;`codex-thread` 只存在于 delivery-pipeline-codex-app 树;Herdr pane transport 只存在于 delivery-pipeline-herdr 树;T3 工具调用只存在于 delivery-pipeline-t3code 树;Lody 工具调用只存在于 delivery-pipeline-lody 树。
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

## 强制规则

| 规则 | 强制入口 |
| --- | --- |
| 新 work lane 的模型、档位与有序备用来自 setup 和显式命名预设。 | T3 `work_dispatch.py`、Herdr `dispatch.py`、Driver 调用的 `scripts/delivery-dispatch`；`python3 scripts/validate.py` 回放错误配置覆盖。本仓外的调用方：my-skills `skills/herdr-autopilot/scripts/launch.js` 经 `model_config.py probe/resolve/start` 启动入口 lane，改 `start` 输出或 CLI 参数时同步核对它。 |
| commit 票派发前必带一份派发合同；空变更或合同验收不过不进集成分支，越出 `writable` 的文件记成偏差进 Merge Review 页（ADR-0028）。 | `driver.py` 的 `prepare_contract` 与 `exec_fan_in`；`driver.py self-test` 回放无合同派发、空变更、验收失败和越界记偏差。 |

## Agent skills

### Issue tracker

Issue 归 GitHub(`Dimon94/delivery-pipeline`),操作用 `gh` CLI;`.scratch/` 只是 feature 工作区。详见 `docs/agents/issue-tracker.md`。

### Triage labels

五个 canonical 标签:`needs-triage`、`needs-info`、`ready-for-agent`、`ready-for-human`、`wontfix`。详见 `docs/agents/triage-labels.md`。

### Domain docs

单上下文:根目录 `GLOSSARY.md` + `docs/adr/`。详见 `docs/agents/domain.md`。
