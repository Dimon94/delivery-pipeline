# Code-review 只读子审查证据预检

运行 `code-review` owner 的 worker 在派生 Standards/Spec 子审查前读取并完成本预检。
父 worker 拥有 Git 证据；子 reviewer 只需 read/search。`code-review` owner 拥有审查维度与
finding 格式，本文件只拥有证据 transport。

## 固定审查边界

| 调用分支 | Review fixed point | Worktree 边界 |
|---|---|---|
| whole-change `review` + `verdict` lane | map registry `role: map` 行的 `base_commit` | Map Integration Worktree 的完整集成变更；review Execution Worktree 必须 clean |
| 所属壳仍启用逐票 review 时 | packet 的 Execution `Base commit` | 当前 Work item 的 staged、unstaged 与 untracked 变更 |

fixed point 解析为唯一 commit 后记录 HEAD；ref 无效、diff 为空或越界 dirty 时在 fan-out 前阻塞。

## Review Evidence Bundle

在 repo 外临时目录一次生成，生成后不改写，所有子 reviewer 共用：

- `fixed-point.txt`：fixed point 原值、resolved SHA、HEAD SHA 与 diff 关系。
- `diff.patch`：精确 diff；逐票分支用 `/dev/null` addition 纳入 untracked 文件。
- `changed-paths.txt`：同边界 name-status 清单，每行 `<status>\t<path>\t@<diff.patch 起始行号>`。

三个文件都非空。commit 列表、worktree 状态等其余事实 reviewer 用 read/search 自行查。

## 子审查 Fan-out

轮次与处置归 `gate-state-machine.md` §Review 预算；父 worker 拿到各轴 verdict 后运行
`scripts/review_gate.py`，不自行判定通过。

- prompt 传 bundle 绝对目录、当前轴、「第 N 轮，共 3 轮」和 spec source（spec、ticket、相关 ADR
  的绝对路径或 tracker URL）；R2/R3 另传上轮 finding 与修复 diff 路径，只审修复及其影响。
- 子任务标记 review-only/no-acceptance；交付物是 findings/verdict，Git 与测试命令留在父 worker。
- bundle 缺项属于 preflight failure，fan-out 前补齐。

完成标准：两轴从同一 bundle 开始，只用 read/search 完成并返回可聚合结果。

## 冻结单模型 Review Plan

CLI whole-change 的 packet 携带 `review_plan` 和 `owner_calls`，由 canonical
`model_config.resolve_review_plan` 生成；`lane_registry.verify_review_packet` 读回核对。
resolved code-review owner 按 `owner_calls` 中每条 axis/requested 调用该轴，仅执行 required axes，
不得重新读取用户配置选模型；每轴遵守原 findings、bundle 和预算规则。standards lane 只是宿主
启动目标，spec-only 时也不额外执行 standards。每轴执行 readback 缺失写 Unknown；
`execution_evidence: null` 是未观测，不表示 matched，也不能复制 pane 身份填充。

Registry `review_plan` 是不可变 JSON flow value。`freeze_review_plan(path, lane_id, plan,
request_id)` 只更新已存在 row，`load_review_plan` 按同 lane/request 读回；计划冲突拒绝。
`collect_implementation_identities(rows, fixed_point)` 的输入必须包含该 Map 的 map row 与
全部贡献 lane 最新 row；只收集相同 map 的已集成 commit 输出，排除 testing/review/coordinator。
requested 来自冻结顶层 triple（包含已选 fallback）；只有 `implementation_execution` 中
`source: native_readback` 的 identity 可作为 executed，旧 lane 缺读回保持 null。
`config_hash` 为完整配置 canonical JSON（sort_keys、UTF-8、紧凑 separators）的 SHA-256，
不同于配置事务对原始文件字节的 base_hash。本路径不写配置、不迁移、不要求家族声明。
空 candidates 按字段判断，兼容后续 canonical schema 接受的空池版本；非空池交后续选序能力。
