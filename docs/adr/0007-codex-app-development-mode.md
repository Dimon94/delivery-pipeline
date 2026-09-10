# ADR-0007: Codex App 工作分工与模型证据

**Status:** Accepted
**Date:** 2026-09-07
**Decider:** User (Dimon)

## Decision

用户选定的开发模式由 App 壳 `references/development-mode.md` 拥有；coordinator 仍是
当前调用会话，implementation 外层仍用独立 App task 与 App-managed Execution Worktree。
Testing、Review 与 Integration 由 coordinator 在原 gate/owner 边界内显式委派内部子代理。
所有模型、思考档位与 fast 设置都是参考默认值，用户明确选择优先，可按任务、阶段或 map 覆盖。
coordinator 推荐值读取 App 专用模型配置；运行观测 Unknown 或偏离推荐值本身不停止编排。
实际值与用户请求分别记录；不以 prompt 自述或 registry 请求值代替运行证据。

App task 的模型请求与宿主运行 readback 分开保存；旧 lane 沿原 registry 恢复。地图沟通
移到用户直接参与的 planning/artifact 会话；coordinator 核验确认及持久证据后推进 gate。
首次无 map 时先以输入 artifact 和 Source HEAD 登记建图 lane，map 建立后回填 Integration
坐标；正式实现始终从 Integration HEAD 分派。

正式双轴由 resolved code-review owner 执行；Pipeline 从 App 配置解析两轴模型/effort，
作为用户选择参数连同 `review_scope: implementation | whole-change` 与证据 transport 传给 owner。Review 生命周期
和最终放行由 coordinator 管理，实施 worker 只能提交候选代码与修复说明，不能以自评、测试通过
或中断的审查替代独立两轴 verdict。技术咨询
与内部辅助规则同时传给 coordinator 和 worker。此决定补充 ADR-0004 的 App 例外，CLI 的
六角色显式配置、owner、权限、Integration、archive 与远程授权边界不变。

2026-09-10 用户要求统一 App 模型配置，Prewalk 默认选择 astra-sol。
唯一模型值来源为 App skill 的 `config/models.json`；模式、各阶段 model/effort、工作分工和
两轴 Review 参数均由 helper 读取。SKILL、packet、dispatch reference 查询配置，不复制模型值。
新分派按本票 → map → config.default_mode 选择；resolve 冻结阶段计划和来源到 packet/registry。
prepare 沿冻结目标与 canonical checkpoint 精确核验，配置变更不迁移既有 lane。
旧 canonical checkpoint 以持久 phase_plan 恢复；无计划的 legacy App 格式使用配置中的
legacy_execution，显式标记历史兼容与 Unknown。该配置段只用于旧格式恢复，不当作新票模式。

配置位于 skill realpath 内，软链安装即可使用；可显式传另一份完整配置的绝对路径，记录到
packet/registry。缺配置或非法配置阻塞新分派，不回落到 CLI 或宿主模型默认。
项目 `.codex/config.toml` 只保存能力和并发；模型经 App task/spawn 参数显式传递。
Testing 只读，Integration 要求父任务可写且无其他活跃子代理，二者串行执行。
service tier 沿宿主默认；不改变宿主或其他仓库的配置。

## Consequences

App Prewalk 新检查点复用 canonical checkpoint 的 Git 隔离、ignored/staged/unstaged 指纹、整体
SHA-256、原子持久读回与阶段信号判定；旧 App 检查点只能在 registry 已持久化旧模式、格式与
exact path 同时匹配且 ignored 交付输入为 none 时显式走 legacy 兼容，不补造指纹。

2026-09-08 补充：正式两轴 Review 的生命周期与最终放行归 coordinator，实施 worker 只能提交
候选代码和修复说明。中断、超时或测试成功不能替代独立 verdict；集成前核对宿主原始结论、
代码版本与阻断项。模型默认可覆盖，审查豁免只能来自用户明确指令并单列记录。

无运行 readback 时只报告 Unknown；静态验证不证明真实模型分派。修改本模式不创建业务
任务、不覆盖全局配置。回退时还原 App 合同，已存在 lane 继续使用持久坐标与证据。
