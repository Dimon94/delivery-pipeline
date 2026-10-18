# Code-review 只读子审查证据预检

当前 worker 直接运行 `code-review` owner，或 `implement` owner 在 `commit` lane 内嵌套调用
`code-review` 时读取。父 worker 在派生 Standards/Spec 子审查前完成本预检。

## 权限边界

父 worker 是本轮 Git 证据 owner；其子 reviewer 可以只有 read/search 权限。只读是预期边界，
Git diff、历史与 staged state 由父 worker 先物化为文件，再把绝对路径传给所有子 reviewer。
`code-review` owner 仍拥有审查维度、finding 质量与聚合格式；本文件只拥有证据 transport。

## 派发前的规定检查

implementation packet 创建前回读 repo/module instructions、manifest 的 check 命令和 CI，用本 skill
realpath 下的 `scripts/review_evidence.py checks` 核验 JSON stdin。输入保存到既有 repo 外工件，
packet 的“输入”引用其绝对路径；不扩展 lane 状态或交接模板：

```json
{
  "worktree": "<Git 顶层绝对路径>", "head_commit": "<当前完整 HEAD SHA>",
  "checks_source": "<repo/module/manifest/CI 回读来源与时间>",
  "required_checks": [
    {"command": "<完整规定命令，含 TZ 等环境参数>", "cwd": "<本 repo 内绝对目录>", "source": "<规定此命令的来源>"}
  ]
}
```

返回当前 `candidate_sha256`（HEAD、staged/unstaged/dirty 内容与模式）和完整清单；仅表示命令
列齐，不表示已 PASS。无规定命令时显式 `[]` 并在 source 说明回读结论；coordinator 核对清单
是否完整，helper 不从任意自然语言自动推断要求。双时区规定必须分别列出两条命令。
Evidence current 显式选择 checkpoint 的 `include_ignored=False`，只采 Git 输入，不枚举或读 ignored。
该视图的 ignored 为 Unknown＋空清单/指纹，表示策略未采集，不是物理无 ignored，也不作为可恢复
checkpoint；`required_ignored` 非空时拒绝该策略。checkpoint 默认完整采集与其原 fail-close 判据不变。
候选改变后沿同一规定清单回读新 candidate；旧 Head 或旧 dirty 输入的结果不能直接套新候选。
当前 candidate 已有真实 PASS 时只回读原终态，不因新报告或时间戳重跑。精确输入映射见下节。

提交 Review 前输入同清单及 `check_results`；每个结果保留 command/cwd/source，并包含
head_commit、candidate_sha256、status（终态为 completed）、exit_code（整数 0）、stdout_log
和 stderr_log（repo 外可读绝对文件，允许空日志）。实际执行 owner 保存原命令、exit 和日志，
coordinator 验证来源真实性；helper 不执行命令，不以路径存在证明日志真实。
缺项/非终态明确 pending，FAIL、skip、Unknown 或版本不匹配非零，先指出违规字段与下一动作，
再按原 gate 保留现场。外部 CI 无授权时完成本地部分并保留 pending，不用本地结果代替 CI。

完成标准：派发前命令清单可读；进入两轴前规定命令对当前输入的真实终态齐备。

## 固定审查边界

| 调用分支 | Review fixed point | Worktree 边界 |
|---|---|---|
| implementation `commit` lane 内嵌 review | packet 的 Execution `Base commit` | 当前 Work item 的 staged、unstaged 与 untracked 变更；允许预期 dirty |
| whole-change `review` + `verdict` lane | map registry `role: map` 行的 `base_commit` | Map Integration Worktree 的完整集成变更；review Execution Worktree 必须 clean |

1. 验证 packet 的 Review fixed point 与上表一致并可解析为唯一 commit；记录当前 `HEAD`。
2. 沿 `code-review` owner 选择的精确 diff 关系生成 patch；fixed point、HEAD 与 diff 关系只解析一次，
   两个审查轴共用。
3. `commit` 分支把 untracked 路径写入清单，并把每个 untracked 文件作为 `/dev/null` 到当前内容的
   addition patch纳入 `diff.patch`；`verdict` 分支确认 worktree clean。
4. ref 无效、diff 为空、存在 Work item 外的 dirty 路径，或 `verdict` worktree 不 clean 时在
   子审查 fan-out 前阻塞。

完成标准：fixed point、HEAD、diff 关系唯一，审查范围完整覆盖当前 Work item 或整个 map Integration。

## Review Evidence Bundle

在 repo 外的临时目录生成一个 bundle；同一轮所有子 reviewer 共用以下文件：

- `fixed-point.txt`：packet 值、resolved SHA、HEAD SHA、调用分支与精确 diff 关系。
- `diff.patch`：精确 diff 内容及 hunk 行号；`commit` 分支同时包含 untracked additions。
- `commits.txt`：fixed point 到 HEAD 的 commit 列表；没有 commit 时明确记录 `none`。
- `changed-paths.txt`：与 `diff.patch` 同边界的完整 name-status 路径清单，包含 untracked 路径；
  每行附该文件在 diff.patch 起始行号（`<status>\t<path>\t@<line>`），reviewer 直接跳到对应 hunk。
- `fixed-point-added-paths.txt`：resolved fixed-point commit 新增路径的
  `git diff-tree --root --no-commit-id --diff-filter=A --name-status -r` 输出；无新增时明确记录 `none`。
- `worktree-state.txt`：带标题的 `git status --short`、`git diff --cached --name-status -- .`，以及
  明确的 `NO_STAGED_FILES=true|false`。
- `commands.txt`：生成上述证据的完整命令，包括 untracked addition patch 命令。

每个文件都必须存在且可读；`diff.patch`、`changed-paths.txt` 和 `fixed-point.txt` 必须非空。
`changed-paths.txt` 是完整路径级清单，子 reviewer 可用 read/search 按任意目录前缀筛选，
无需再次执行 Git。bundle 只作上下文 transport，不写入 repo；生成后不再改写，并保留到
coordinator 完成对应 lane fan-in。

### 机械生成与 readback

同一 helper 的 `bundle` / `preflight` 命令分别生成新 bundle / 只读校验原 bundle。沿上节 JSON
补 base_commit（packet fixed point）、target_commit（调用方批准的本轮目标 ref 或完整 SHA）、
review_scope（implementation 或 whole-change）、bundle_path
（repo 外绝对目录）、check_results；implementation 另给 allowed_dirty_paths 精确票内路径清单。
`bundle` 只写不存在的新目录，七文件来自同一次 Git snapshot，原 bundle/FAIL 不被改写。
`preflight` 逐文件与当前真实 Git 比较，成功返回七文件路径、字节数和原 bytes 哈希。
两命令都先核规定检查终态；缺命令、错误 Head、name-only、错路径集合、错 base additions 或
票外 dirty 在 fan-out 前非零。whole-change 使用固定 base 到当前 HEAD；前候选独有而 base/head
均不存在的路径不属于这次 diff，不能标作 base 删除。实现 diff 同时纳入 staged/unstaged 的
当前内容和 untracked additions，worktree-state 单列 index 状态。

机械比较只容许证据输出 framing 的单个末尾 LF 差异；Git blob 正文仍按原 bytes 比较。
source mode 以文件种类和执行位比较：tar 0664/Git 100644、tar 0775/Git 100755 各自等价，
非执行与执行不等价；这些规范化不修改原记录或原 FAIL。

无继承时每轴完整审查全部路径。确需复用历史覆盖时，额外输入 coverage，键恰为 standards/spec；
每轴给 fresh_paths 和 inherited 列表。每个 inherited 原结论含 axis、source、completed/pass、
base_commit、head_commit、paths，以及 inputs（逐路径 content_sha256 和 mode）。helper 核对
同轴、固定 base、前/现候选精确正文与执行位及本轴完整路径集合；正文末尾 LF 不被吞掉。
历史输入缺失、跨轴借用、重复或未覆盖路径均非零，回到该轴补审；旧 Spec PASS 不代新 Head。
原结论真实性与判断质量仍由 coordinator/code-review owner 核对。继承另须满足下节有效输入合同；
旧 receipt 缺这些证据时补审，不把历史 notes 映射为 PASS。两轴必须对新 Head 各自返回独立结论。

### 固定候选与有效输入复用

最终 testing/review 前，coordinator 在授权内完成必要主线合流，再冻结 base/head/target。
helper 每次预检只解析一次 target，写入 fixed-point.txt；target 不是 head 祖先时非零，保留原 cause，
明确由 coordinator 获授权合流后重冻结，不 force/rewrite 或循环追 main。后续只用完整 SHA；
新 target 必须重新预检，兼容祖先可重建新 bundle 而不重跑同输入已 PASS 的命令。
preflight 返回 base_commit/head_commit/target_commit、target_reason、check_decisions 与 coverage_decisions；
它们是本轮恢复证据，不是新的 registry 或 reviewer PASS。

沿既有 required_checks/check_results/coverage 扩展，不增加检查清单或取消模块强制全量。
需要跨 Head 复用时，repo/module 原 owner 必须提供可复核的 Git-only 有效输入合同 reuse_contract：
source 是合同来源；paths 为检查/审查直接输入根；production_closure 与 runtime_assembly 为完整
生产导入闭包和运行装配的字面 Git 路径根列表。两个列表必须显式提供；确无该类输入可为 []，
source 必须给出依据。使用目录根时包含其完整子树和新增文件，不用 test 文件名推断依赖。
命令的脚本、manifest、配置、合同来源文件也属于输入。外部环境、生成输入、submodule/symlink、
动态装配或闭包完整性无法核实时为 Unknown，重新执行/本轴补审；不得由模型声称闭包已证明。
合同来源真实性和闭包完整性由 coordinator 按原 owner 核实，helper 只确定性核声明输入，不能推断语言依赖。

原终态同时保存 reuse_contract 和 input_snapshot（展开后的每个文件对应 {mode: Git mode, blob: OID}）。
helper 读取前/现候选完整声明子树，要求两版本与原 snapshot 的路径集合/mode/blob 全等、原 Head 为
当前祖先。合同改变或输入缺失/新增/删除/正文/执行位变化均拒绝，诊断给出字段/路径和下一动作。
coverage.inherited 每条沿用本轴原结论，继续核 inputs 的正文哈希/执行位，并要求 paths 全含于 snapshot；
两轴 fresh＋本轴 inherited 必须各自等于整个 whole-change 集合。

检查映射在当前 check_results 条目保留 command/cwd/source，增加 inherited_from 指向完整原结果对象，
不改原 Head/candidate/exit/日志。required_checks 同条另声明当前 reuse_contract，必须与原合同完全相同。
只支持原/现 clean 候选，原 candidate 必须等于该 Head 的 clean 指纹；原 command/cwd/source、completed、
exit 0 与可读日志仍逐项核验。普通结果仍按当前 Head/candidate 严格比较。FAIL/skip/Unknown/pending、
旧 dirty 或合同缺失一律不映射；保留历史，不以新 PASS 覆盖原失败，也不把映射当作真实重跑。

完成标准：当前唯一恢复坐标指向本轮 bundle/preflight，历史版本/FAIL/skip/Unknown 仅追加保留。
active 状态只按最新 cursor 取一次增量快照；已 complete 不再轮询。大日志先读定向摘要与原坐标，
判定需要时再读完整正式报告；失败类别可回放不代表历史具体 actor/cause 已知。

完成标准：七个文件一次生成、bundle 绝对目录已写入每个子 reviewer prompt，`preflight` exit 0，
生成后 fixed point、HEAD 与 worktree snapshot 未变化；完整 JSON/exit/日志保存到原 lane 工件。

## 子审查 Fan-out

- 每个子 reviewer prompt 传 bundle 绝对目录、fixed point/HEAD、当前轴和 standards/spec source；
  spec source 全部以绝对路径或 tracker URL 给出（spec、ticket body、相关 ADR），reviewer 不搜索定位；
  七个文件名沿上表恢复。先读 fixed-point.txt、changed-paths.txt、worktree-state.txt，再按当前轴读取
  diff.patch 的相关 hunk、commits.txt、fixed-point-added-paths.txt 与 commands.txt；完整审查范围
  保持不变，各轴仍须覆盖其职责内的全部变更，再读源码补充上下文。
- 子任务显式标记 review-only；交付物是 findings/verdict，不承担 Git 命令、测试命令或 staged-state 自证。
- runtime 若自动附加 child acceptance/evidence gate，父 worker 选择其 review-only/no-acceptance
  形式；`noStagedFiles` 等 shell-derived 字段以 `worktree-state.txt` 为父级证据，不向子 reviewer 索取。
- bundle 缺项属于 preflight failure，在 fan-out 前补齐；正常路径不产生索取 Git/path 输出的
  supervisor 往返。

父 worker 在 final report 的 `Review evidence` 中记录调用分支、fixed point、HEAD、bundle 目录与
七文件存在/可读/必需项非空的校验结果；完整 readback 留在原证据，不逐文件复述路径与正文。

完成标准：Standards 与 Spec 子审查从同一 bundle 开始，均可只用 read/search 完成，并返回可聚合结果。
