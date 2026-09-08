---
name: delivery-pipeline
description: 通过 CLI/Herdr 启动或恢复从想法、map、spec 到集成验收与远程收尾的交付编排。
disable-model-invocation: true
---

# Delivery Pipeline

唯一 canonical CLI/Herdr 编排主干，供 pi、Codex CLI 与 Claude CLI 共用。
当前调用会话就是 coordinator；本 skill 拥有调度与 Integration，产物质量归各 owner。

## 启动或恢复

1. **识别输入与 gate。** 读取 repo instructions、tracker operations 与输入 artifact。
   输入可以是松散想法、Wayfinder map、spec 或 implementation ticket；裸编号须能从当前
   repo tracker 唯一解析。加载 `references/gate-state-machine.md`，按持久证据选择最早未完成 gate。
2. **恢复坐标。** 新 coordinator 或恢复 map 时加载 `references/fresh-session-boundaries.md`
   与 `references/lane-registry.md`，先枚举 active writers。恢复既有 lane 不依赖当前 worker 配置；
   按 stored runtime 与持久证据继续 fan-in/cleanup。创建或恢复 worktree 时加载
   `references/integration-worktree-management.md`；复用已登记的 Map Integration Worktree/branch，
   不存在时才创建。所有 Git 操作显式指向隔离 worktree，不切换 Coordinator Pane 当前目录的 branch。
3. **确认 Coordinator Runtime。** 记录 `coordinator_runtime: pi-cli | codex-cli | claude-cli` 与
   `dispatch_runtime: herdr`。新建 lane 前加载 `references/dispatch-runtime-routing.md`，验证当前
   Herdr session/workspace/tab/pane；只有用户显式要求新 Workspace 才创建。

完成标准：输入、当前 gate、Map Integration Worktree 与全部 active writers 已有可恢复坐标；
缺失或矛盾证据记 Unknown，保留现场并报告受阻动作。

## 当前 gate 的执行入口

Gate 顺序、owner 与通过证据统一在 `references/gate-state-machine.md`。仅加载当前分支：

| 分支 | 必读合同 | 完成后 |
| --- | --- | --- |
| discovery | `references/wayfinder-frontier-loop.md` | 重算 ready frontier 或进入 spec |
| 新建 lane | `references/model-role-routing.md`、`references/owner-skill-resolution.md`、`references/frontier-lanes.md`、`references/dispatch-runtime-routing.md`、`references/pane-lifecycle-rules.md` | 整批 Dispatch Handoff |
| terminal/user completion signal 或显式 monitor | `references/child-monitoring.md`、`references/execution-worktree-integration.md`、`references/frontier-lanes.md` | 验证交付，自动推进下一 ready frontier |
| testing/review 后收尾 | `references/test-decision-and-rebase.md` | 复用适用的测试选择，按授权收尾或报告剩余 gate |

同一 coordinator task 不因下一 lane 重读未变化的合同。

`starting` implementation lane 还必须先完成首处有意义修改与最小检查，再由
`scripts/checkpoint.py` 将 Execution Worktree 的 Git/dirty/index snapshot 写入 repo 外 checkpoint；
`PREWALK_READY <lane_id> <checkpoint_path>` 后立即结束本回合并保留 dirty，只触发 coordinator 读回，
不是继续实现、审查、commit、接续或 fan-in。只有原 runtime 返回 `WORKER_STOPPED <lane_id> <checkpoint_path>`，
且 observation 身份与 checkpoint 的 runtime/session/coordinator 坐标一致、停止证据可读回、单写者为
false、没有 ignored 路径时，才允许 coordinator 进入下一阶段；active、Unknown、身份不匹配、关键设计
Unknown、工具拒绝、过期或不完整 checkpoint 均保留现场。checkpoint 入口不发送接续请求，也不触发
Terminal fan-in。

Claude staged lane 在上述 registry persist/readback 后，调用 setup 的
`model_config.py resume --request <payload.json>` 取得原生 `--resume` 计划；该 caller 只做
Claude adapter 核验与计划翻译，不替代 registry、send lease 或 runtime readback。Herdr gate
不可用时保留 blocked 现场。

## 新建 lane 的配置与 Packet

按 `references/model-role-routing.md` 验证 version 2 配置或显式 version 3 执行计划
`~/.config/delivery-pipeline/model-roles.json`：从 setup skill realpath 运行
`scripts/model_config.py validate <config>`，再验证本机实时 evidence。缺失或非法时完整读取
`../delivery-pipeline-setup/SKILL.md` 并在当前会话执行初始化；通过后才创建新 lane，不静默回落。
已有 lane 的恢复按 registry；replacement 的条件与验证见 dispatch runtime 合同。

新 implementation lane 按本票 → map → 用户配置解析 execution mode 与阶段参数，并将 mode、source、
starting/execution/direct model 与 effort 冻结到 packet 和 lane registry。version 2 继续既有 direct
启动行为；只有 `output_mode: commit` 的 implementation lane 消费 staged/direct 计划，其他 output
mode 沿原 role 行为。staged adapter 尚未具备时必须保持 blocked，不静默退回 direct。

从 role 配置解析 `agent`、`model`、`effort`，使用 `assets/HERDR_ROLE_DISPATCH_PACKET.md`。
commit/review lane 创建 packet 时加载 `references/code-review-evidence-preflight.md`：
`commit` 写 `Review fixed point: <Execution Base commit>`；`verdict` 写 map registry 的 base commit。
两者都传 preflight 绝对路径；worker 在派生子审查前生成 Review Evidence Bundle。

完成标准：配置与 owner 已验证，registry 先于 worker，packet 的 work item、role/output mode、
隔离坐标和必要 review evidence 输入完整；启动与 bounded retry 按 pane lifecycle 合同执行。

## 权限与交付边界

- 每张 work item 一个 lane、一个 owner、一个 Execution Worktree/branch、一个 active writer；
  worker 只处理本项，coordinator 不亲自实现。Execution Worktree 从当前 Integration HEAD 创建。
- owner 使用 name、绝对 SKILL.md path、runtime-specific invocation label 三字段；绝对路径是
  执行真相源，label 只作说明。
- 本地 worktree、文件修改与 commit 使用 local execution authority；named-map tracker transitions
  使用 Map Run Authority；push、main、PR/MR、merge 与最终 publication 需要 remote publication authority。
- 运行中或 fan-in 发现 worker 模型变化时，读取 `references/model-role-routing.md` 的启动绑定
  边界，继续按持久交付证据验收。
- 自然语言面向用户、workers、tracker 和 PR/MR 时使用中文；skill/tool/status/path/hash 保持原样。

完成标准：map/spec/tickets 与各 lane 交付可追溯，execution graph 为空，whole-change testing/review
通过；远程获授权时 CI/CD、remote review 与 closeout 通过，否则报告唯一剩余 remote gate。
Dispatch Handoff 是等待真实唤醒的批级交接，不代表整个 map 完成。
