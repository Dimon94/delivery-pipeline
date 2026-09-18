# HANDOFF 落实核对（2026-09-07）

完整来源：/tmp/delivery-pipeline-handoff.Q6wz0A/HANDOFF.md。以用户后续明确选择为优先：正式实现默认由 Sol 改为 astra-luna；astra-sol/sol-direct 可覆盖；Prewalk 主执行始终同任务接续。

| 要求 | 当前落点与结果 |
|---|---|
| 外层 App task 与内层 subagent 分开 | App SKILL、开发模式、packet、registry overlay 已落实；无 Herdr 配置 gate |
| Sol high 调度/独立调查/whole-change 测试 | 工作分工表保留；当前会话是已有开发维护会话，宿主为 Astra low，不冒充已切为 Sol coordinator；新 map 启动前按合同核对 |
| Astra low 地图/拷问/spec/拆票/原型 | App artifact lane 与直接用户沟通入口已落实；首次无 map 的临时 registry/base 已定义 |
| 用户确认与回传 | packet 携带 coordinator task/host；完成报告不等于用户确认，既有确认复用，缺确认不推进 gate |
| Sol/Astra 可直接用 Luna high 辅助 | 合同明确双方直接按需委派，父会话分配文件边界并负责验收；只读父任务不扩权 |
| 内部默认配置 | 本次新增本仓 .codex/config.toml：agents.enabled=true、并发3、默认Luna/high；无自定义角色覆盖声明；不修改全局或其他repo |
| 双轴 Astra low Review | my-skills 原始 code-review 已明确两轴模型/effort、同一证据包、只读、修复后复核；本次真实使用两轴审查 |
| Second opinion | 开发模式合同同时覆盖 coordinator/implementation，包含触发、输入、输出及只读边界 |
| 原始 Skill 归属 | .agents 的 code-review/git-commit 分别软链到 my-skills 原始目录；my-skills 当前clean，已有29662c3/d97b7c5提交，无需再复制或重改 |
| 请求与运行证据分开 | App 请求/Unknown/readback 分开；旧lane恢复不换模型，Prewalk 也不 fork |
| 实际试跑 | #94三种模式已做隔离App测试，详见RESULTS.md；自动回传与空闲唤醒两阶段检查已通过；完整地图互动确认与集成仍未端到端试跑 |

## 本轮验证

- 完整读取 HANDOFF，核对本仓规则、当前diff、原始Skill和软链归属。
- TOML解析及四个默认字段断言：通过。
- Codex 0.153.0：`--strict-config` 不支持 debug 子命令，改用只读 exec 探针。加载全局配置时发现既有 disable_response_storage 字段不被严格schema接受；未修改全局文件。
- `codex exec --ignore-user-config --strict-config --ephemeral --json -m gpt-5.6-sol -c model_reasoning_effort=high` 只读 CONFIG_OK 探针：退出0，返回CONFIG_OK。证明隔离用户配置后的加载/请求可执行，不证明当前App已重新加载项目默认值或默认spawn运行值。
- `python3 scripts/validate.py`：prewalk dispatch: pass，bundle: pass。
- `git diff --check`：通过。

字段依据：OpenAI 子智能体及配置参考（2026-09-07读取）：
https://learn.chatgpt.com/zh-Hans/docs/agent-configuration/subagents
https://learn.chatgpt.com/zh-Hans/docs/config-file/config-reference

本仓配置不随软链自动应用于其他业务repo，外层task与关键spawn仍显式传模型/effort。Luna fast和其他模型非fast没有本轮运行保证。原HANDOFF保持为历史输入，没有改写其旧结论。未新增Git提交或推送。

## 后续调用闭环补强

- App SKILL 启动与worker packet强制进入“每次调用的执行核验”；使用安装Skill realpath，不读取execution worktree旧副本或scratch报告代替合同。
- 新增prewalk.py subagent入口：assistance显式Luna/high，second-opinion显式Astra/low，review预留两轴容量后交resolved owner。读取live active_count，超过每父会话并发3就返回wait/null request。只读父任务不能请求可写辅助。
- 这是每父会话工作流约束，不声称改写宿主硬配额；宿主更低限制优先。配置不随symlink传播的问题不再依赖其他repo安装配置解决；其他repo/全局文件保持未修改。
- 真机Sol工作会话已调用上述入口完成Luna辅助与Astra咨询，宿主子会话元数据分别读回gpt-5.6-luna/high、gpt-6-astra/low。报告中的Unknown已由协调器独立证据补充，记录在app-evidence/subagent-policy-host.json。
- worker按Terminal合同调用send_message_to_thread成功，当前协调任务已实际收到FINAL_REPORT；随后校验worker文件SHA256与报告一致。此证明活跃协调任务收到了回传，不推论空闲唤醒或完整map Integration已验证。
- 发现helper无执行权限：实际调用先permission denied，补可执行位后同入口直接执行通过；validate.py加入权限回归检查。
- 新入口CLI检查先失败后通过；最新代码通过独立Astra low Standards/Spec复核，0项新增阻断。README增加实际调用方式与跨repo配置边界。
- 最终python3 scripts/validate.py与git diff --check通过。既有三模式App探针继续适用，新增内部策略另有真实回传证据。

- 后续 idle-wake-94 已补证空闲协调任务自动唤醒、同 worker 第二阶段自动派发及最终回传；详见 RESULTS.md 与 app-evidence/idle-wake-*。READY/active 竞态已修复并通过红绿检查及双轴复核。
