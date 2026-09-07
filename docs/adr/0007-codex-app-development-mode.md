# ADR-0007: Codex App 工作分工与模型证据

**Status:** Accepted
**Date:** 2026-09-07
**Decider:** User (Dimon)

## Decision

用户选定的开发模式由 App 壳 `references/development-mode.md` 拥有；coordinator 仍是
当前调用会话，外层仍用独立 App task 与 App-managed Execution Worktree。内部子代理只在
父任务授权内辅助，不承担独立 lane 的 Integration。

App task 的模型请求与宿主运行 readback 分开保存；旧 lane 沿原 registry 恢复。地图沟通
移到用户直接参与的 planning/artifact 会话；coordinator 核验确认及持久证据后推进 gate。
首次无 map 时先以输入 artifact 和 Source HEAD 登记建图 lane，map 建立后回填 Integration
坐标；正式实现始终从 Integration HEAD 分派。

正式双轴模型规则归 resolved code-review owner；Pipeline 只负责证据 transport。技术咨询
与内部辅助规则同时传给 coordinator 和 worker。此决定补充 ADR-0004 的 App 例外，CLI 的
六角色显式配置、owner、权限、Integration、archive 与远程授权边界不变。

实施票支持 astra-luna（默认）、astra-sol 与 sol-direct；前两种由 Astra 起步，在同一
App task 下一轮显式请求接续模型。packet/registry 持久化选择及检查点；模式不改变 owner、
Review 或 Integration gate。该决定是用户选定的流程合同；App 接续已有隔离运行证据。
Luna 使用 max 且不启用 fast，service tier 沿宿主默认值，运行 readback 缺失时仍记 Unknown。

本仓内部子代理默认值落在项目级 Codex 配置，外层 App task 仍显式传 model/effort。
该配置不随 Skill 软链扩散到其他 repo，不覆盖用户全局配置或自定义角色。

## Consequences

无运行 readback 时只报告 Unknown；静态验证不证明真实模型分派。修改本模式不创建业务
任务、不覆盖全局配置。回退时还原 App 合同，已存在 lane 继续使用持久坐标与证据。
