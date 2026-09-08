# ADR-0007: Codex App 工作分工与模型证据

**Status:** Accepted
**Date:** 2026-09-07
**Decider:** User (Dimon)

## Decision

用户选定的开发模式由 App 壳 `references/development-mode.md` 拥有；coordinator 仍是
当前调用会话，implementation 外层仍用独立 App task 与 App-managed Execution Worktree。
Testing、Review 与 Integration 由 coordinator 在原 gate/owner 边界内显式委派内部子代理。
所有模型、思考档位与 fast 设置都是参考默认值，用户明确选择优先，可按任务、阶段或 map 覆盖。
coordinator 推荐 `gpt-5.6-sol` / `high`；运行观测 Unknown 或偏离推荐值本身不停止编排。
实际值与用户请求分别记录；不以 prompt 自述或 registry 请求值代替运行证据。

App task 的模型请求与宿主运行 readback 分开保存；旧 lane 沿原 registry 恢复。地图沟通
移到用户直接参与的 planning/artifact 会话；coordinator 核验确认及持久证据后推进 gate。
首次无 map 时先以输入 artifact 和 Source HEAD 登记建图 lane，map 建立后回填 Integration
坐标；正式实现始终从 Integration HEAD 分派。

正式双轴模型规则归 resolved code-review owner；implementation 使用 Astra / low，whole-change
使用 Sol / xhigh。Pipeline 只负责证据 transport。技术咨询
与内部辅助规则同时传给 coordinator 和 worker。此决定补充 ADR-0004 的 App 例外，CLI 的
六角色显式配置、owner、权限、Integration、archive 与远程授权边界不变。

新实施票支持 sol-luna（默认）、sol-sol 与 sol-direct；前两种由 Sol / high 起步，在同一
App task 下一轮显式请求接续模型。旧 astra-luna/astra-sol 只用于恢复已持久化 lane。
packet/registry 持久化选择及检查点；模式不改变 owner、
Review 或 Integration gate。该决定是用户选定的流程合同；App 接续已有隔离运行证据。
Luna 使用 max 且不启用 fast，service tier 沿宿主默认值，运行 readback 缺失时仍记 Unknown。

原型使用 Sol / high。whole-change Testing 与逐票 Integration 分开串行请求 Luna / max；Testing
只读，Integration 要求父任务可写且无其他活跃子代理。coordinator 对二者的产物与 Git 现场负责。

本仓内部子代理默认值落在项目级 Codex 配置，外层 App task 仍显式传 model/effort。
该配置不随 Skill 软链扩散到其他 repo，不覆盖用户全局配置或自定义角色。

## Consequences

2026-09-08 补充：正式两轴 Review 的生命周期与最终放行归 coordinator，实施 worker 只能提交
候选代码和修复说明。中断、超时或测试成功不能替代独立 verdict；集成前核对宿主原始结论、
代码版本与阻断项。模型默认可覆盖，审查豁免只能来自用户明确指令并单列记录。

无运行 readback 时只报告 Unknown；静态验证不证明真实模型分派。修改本模式不创建业务
任务、不覆盖全局配置。回退时还原 App 合同，已存在 lane 继续使用持久坐标与证据。
