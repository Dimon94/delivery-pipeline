# Codex App Role Dispatch Packet

派发与 FINAL_REPORT 使用 `../../delivery-pipeline/references/lane-registry.md` §轻量交接的
固定模板。仅展开当前分支，输入省略不适用项；本壳只追加三个回传字段：

```text
Coordinator task：<原生 threadId>
Coordinator host：<原生 hostId>
Terminal 回传合同：<absolute codex-app-dispatch.md，读取 Terminal 回传节>
```

coordinator 先持久化完整 App overlay；公共模板的 Registry 指向本 lane，输入引用其
config_path、phase_plan/phase_targets/execution_target 和实施前置证据，传当前请求值。
Review 分支的输入包含 scope、fixed point、owner 三字段、两轴配置与 preflight 绝对路径。
初始 Execution Worktree 由 App 创建，startup 后补真实坐标，写入前完成隔离核验。

## 按分支加载

worker 从本节进入，每次调用的执行核验按当前 role/output_mode 与冻结 phase 选行；按标题读取
完整章节及子节，到下一个同级或更高标题结束。完整 Owner SKILL.md、repo instructions 和本票
业务输入另读。coordinator 的 core/壳入口、创建与归档合同由 coordinator 消费。

| 分支 | 必读章节 |
|---|---|
| 全部 | `../../delivery-pipeline/references/lane-registry.md` §Worker 共同行为；`../../delivery-pipeline/references/lane-registry.md` §终态模板；`../references/development-mode.md` §执行入口；`../references/development-mode.md` §参数与证据；`../references/codex-app-dispatch.md` §Terminal 回传 |
| commit | `../../delivery-pipeline/references/gate-state-machine.md` §实施前置检查 |
| staged | `../references/development-mode.md` §Prewalk 接续；`../references/development-mode.md` §机械核验入口 |
| planning | `../references/development-mode.md` §Planning 直接沟通与回传 |
| 内部委派 | `../references/development-mode.md` §工作分工；`../references/development-mode.md` §内部委派；`../references/development-mode.md` §内部辅助工作 |
| 正式 Review | `../references/development-mode.md` §Review 职责；`../references/development-mode.md` §正式 Review；`../../delivery-pipeline/references/code-review-evidence-preflight.md` §Code-review 只读子审查证据预检；`../references/codex-app-dispatch.md` §独立 Review 放行 |

staged 只适用于 implementation；planning 行只适用于 planning artifact。
内部委派、正式 Review 行在实际调用前加载；coordinator 管理正式 Review，实施 worker 准备
候选审查证据时只读 preflight，不能因此取得放行权。正式 Review 同时加载内部委派行。
其他 output mode 按完整 owner 与本项验收执行。
咨询与 sizing 再读开发模式对应章节；缺失、Unknown 或历史 legacy phase 时回到持久证据和对应
恢复分支，不能猜 direct。同一未压缩上下文只复用已读且未变化的合同，冷恢复重新读取必要章节。

## Worker 执行

kind: direct 使用 resolve 返回的 direct 请求，phase: executing，checkpoint: none；按冻结计划
完成 owner 流程，跳过起步与换模型步骤，测试、Review 与集成标准相同。需要重判方案时读开发模式
§Second opinion；模式升级由用户明确选择，沿同一 task 保存原因和现场证据。

1. 按上表执行公共模板的 Worker 共同行为与当前章节；用 registry 的 config_path 调用 `../scripts/prewalk.py`，
   内部辅助、second opinion 与 Review 参数走 subagent 入口，权限不超过本项。
2. 仅 staged：starting 按开发模式合同生成 checkpoint，PREWALK_READY 后停止，保留现场；executing 才
   继续实现。恢复沿原冻结计划和 checkpoint，不重新选择配置。
3. 正式 Review 由 coordinator 调用 resolved code-review owner：commit 用
   `review_scope: implementation`、Execution base；verdict 用 `review_scope: whole-change`、
   map registry base。执行 `../../delivery-pipeline/references/code-review-evidence-preflight.md`，
   preflight bundle 完成前不派生 Standards/Spec 子审查。
4. 实施 worker 只保存候选和修复证据；正式 reviewer 的取消、重派和放行归 coordinator。
   缺失、中断或待复核的独立 verdict 回传 blocked“实现已保存、审查待完成”，不写 completed；
   coordinator 按 Terminal 合同接手，不能把 blocked 当作无需处理。
5. completed 与 blocked 都在最终回复前按 Terminal 回传合同发送公共终态模板。
   工具成功后才声明 FINAL_REPORT 已回传；失败或 Unknown 保留报告、目标与恢复坐标。
