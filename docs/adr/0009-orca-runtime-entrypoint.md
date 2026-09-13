# ADR-0009: 独立 Orca runtime 入口与 fail-closed preflight

**Status:** Accepted
**Date:** 2026-09-13
**Decider:** User (Dimon；Spec #129 与确认 comment 5646715861)

## Decision

1. `skills/delivery-pipeline-orca` 是与 canonical CLI/Herdr 主干和 Codex App 壳并列的独立
   entrypoint。它严格绑定当前 Orca runtime；不完整执行 canonical SKILL 的 Herdr startup，
   也不修改既有两个入口的运行行为。
2. 每次 capability-sensitive operation 只解析并固定一个 Orca executable。入口读取该
   binary 的 version-matched `orca-cli`、`orchestration` guide 与本次所需 reference，记录固定
   executable 和精确读取命令，并从 `agent-context`、`status` 的 target + runtimeId、terminal
   identity 和 operation-specific capability readback 判定是否可执行。request 的目标 host 必须
   与该原生 status identity 精确匹配；选定 binary 失败后不尝试其他 binary。
3. Orca 入口复用 version 4 Worker Task Configuration、既有 mode 解析/冻结、model evidence
   和 owner 三字段合同。没有 Orca override、agent 映射、第二套配置或 dispatcher；Herdr
   `startup_request`/`continuation_request` 不作为 Orca transport。
4. bundle manifest 与既有软链 helper 暴露新入口。`skills installed --json` 的 exact
   id/name/providers/sourceKind/sourceLabel 和目标 agent owner 的绝对 `SKILL.md` realpath 必须可读；Orca 原生
   `skills install` 不被当作自定义 bundle installer。
5. 缺 CLI/runtime/reference/discovery/capability、shared agent/model/effort、native
   same-session 或 identity 证据时，该 operation 返回可见 `blocked` / `dispatch unavailable`；
   不 fallback 到 Herdr/Codex App。机械 helper 只能校验 caller-declared readback 的字段、绑定与
   可读绝对 source path，不能证明原生 provenance；结构成功仅为 `preflight-ready` 且
   `authority: false`，coordinator 读回 native source 后才可授权。Unknown 不授权 mutation。
6. 本决策只交付入口与 preflight。Run/Task/Dispatch、fan-in/recovery、provider、remote 与
   closeout 生命周期分别留给 #121–#128，不在入口中提前实现。

## Consequences

- 安装成功与静态 validator 通过不证明 Orca runtime 可运行；真机未执行的能力保持
  `not-run/Unknown`。
- capability requirements 由当次 native guide/request 提供，仓库不维护静态 version 或
  capability matrix。
- canonical CLI/Herdr 主干继续 runtime-neutral；Codex App transport 内容继续只在其壳内。
