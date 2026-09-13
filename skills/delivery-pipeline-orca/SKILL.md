---
name: delivery-pipeline-orca
description: 在 Orca runtime 中检查交付编排入口、原生 discovery 与当前操作能力；证据不足时明确阻塞，不切换其他 transport。
disable-model-invocation: true
---

# Delivery Pipeline（Orca）

本入口与 CLI/Herdr、Codex App 并列，严格绑定 Orca。当前 Orca terminal 是 coordinator；
外部会话不能冒充该身份。本入口只做 preflight，不创建 Run/Task/Dispatch 或 Execution
Worktree；dispatch 尚未交付时返回 `dispatch unavailable`，不调用其他入口代办。

## 复用边界

从本文件的 realpath 解析 canonical siblings，不从调用者 cwd 猜路径，也不完整执行
`../delivery-pipeline/SKILL.md` 的 Herdr startup。

- gate 与实施前置证据：`../delivery-pipeline/references/gate-state-machine.md`。
- owner 解析：`../delivery-pipeline/references/owner-skill-resolution.md`；保留 name、绝对
  SKILL.md path、runtime-specific invocation label 三字段。
- worker policy：`../delivery-pipeline/references/model-config-schema.md`；只读现有
  `~/.config/delivery-pipeline/model-roles.json`，复用 setup 的 `model_config.py`
  `resolve`/`freeze` 与 version 4 schema/model evidence。不创建 Orca override、第二份配置
  或 dispatcher。Herdr 的 `startup_request` / `continuation_request` 不用于 Orca。

## 每次进入操作前

1. 完整读取原生 `orca-cli` discovery stub；优先使用 `ORCA_CLI_COMMAND`，否则按 guide
   的 dev/Linux/默认规则只解析并固定一个 executable。后续所有命令使用该绝对路径；
   选择失败时保留原始错误，不尝试另一 binary。
2. 从该 executable 读取 `skills get orca-cli --full --json`、
   `skills get orchestration --full --json` 与 `--version`，记录版本、路径和读取来源。原生 guide 必须 version-matched；
   缺失时可用该 binary 的 `--help` 做只读诊断，不猜命令、不用旧 guide 代替。
3. 按本次 guide 的 `agent-context` / help 核对 runtime ready/reachable/connected、
   coordinator terminal 与目标 host identity；加载 guide 清单中当前 operation 所需的
   references。不能用本机 CLI 可执行替代 runtime readback，也不强制加载 browser/remote。
4. 用该 binary 的 `skills installed --json` 核对本入口的 exact id/name/providers/
   sourceKind/sourceLabel，并独立读回目标 agent 解析到的 owner SKILL.md realpath。
   同名或安装成功不等于 agent 可发现、身份匹配或可运行。复用既有软链 helper 安装到
   被选 agent 的原生 discovery 目录；`skills install` 只管理 bundled skills，不猜造
   自定义安装命令，不创建 lockfile、静态 capability/version matrix。
5. 按共享 schema 读取当前 work/两轴 review 与 implementation mode 的冻结计划，分别保存
   agent/model/effort/mode 请求和原生证据。shared agent 不可证明可用时不映射其他 agent；
   model/effort 必须由当前 binary 与目标 runtime 的证据支持。staged 还须证明 native
   同 session 能力，不降级 direct；参数回显不充当实际 model/effort。
6. 只验证当前操作的 capability；readback 缺失、Unknown、不一致或 runtime 不可达，
   均停止依赖该证据的操作，保留已持久 registry、Git 与 artifact 的只读恢复能力。

## 机械 preflight

先把本次操作证据写入 repo 外 request JSON，再运行：

```text
python3 <Orca skill realpath>/scripts/preflight.py run <absolute-request.json>
```

request 精确包含 `operation`、`skill_name`、`references`、`required_commands`、
`required_capabilities`、`config`、`model_evidence`、`task`、`output_mode`、`phase`、
`target_host`、`owner`、`agent_readback` 与 `same_session_readback`；可选 `ticket_mode`、`map_mode`、
`terminal_handle`。`skill_name` 固定为 `delivery-pipeline-orca`；`target_host` 精确匹配原生
`status` 的 target + runtimeId。owner 精确为 name、absolute SKILL.md path、invocation label。
agent readback 精确匹配解析后的 agent/model/effort 和 `status: ready`；staged 还要求
匹配同一 agent 的 `status: verified` same-session capability readback。二者的 `source` 必须是
可读绝对 evidence 文件，但仍是 caller-declared：helper 只校验字段、路径与绑定，不证明原生
provenance。coordinator 必须读回 source 的原始 native receipt 后才可授权。当前 coordinator
terminal identity 由 `terminal_handle` 与原生 `terminal show` 独立核对。operation requirements
来自刚读取的原生 guide，不在仓库维护 capability/version matrix。

helper 只调用 `--version`、`skills get`、`agent-context`、`status`、`terminal show` 和
`skills installed`，并复用 setup `model_config.py resolve/freeze`；required command 只与
`agent-context` 对照，不执行。结构和路径均通过时返回 `status: ready`、
`dispatch: preflight-ready`、`authority: false`；这不是 dispatch 授权。失败返回带具体 blockers
的 `blocked`，不产生 mutation。

## 结果与权限

preflight 报告必须包含 executable/version、operation、runtime/host/terminal identity、
带固定 executable 与实际读取命令的 guide/reference 来源、discovery 与 owner realpath、冻结
worker policy、capability readback 及证据时间。`preflight-ready` 只表示 caller-declared 结构齐全；
coordinator 必须核验原生 source provenance。它不授权 dispatch 或推进项目 gate。

缺 CLI/runtime/reference/discovery/capability、shared agent/model/effort、native 同 session
证据或 identity 不一致时，输出 `blocked` 与具体缺口；dispatch 请求输出
`dispatch unavailable` 与同一原因。不 fallback 到 Herdr 或 Codex App，不启动 worker。
真机未运行明确写 `not-run/Unknown`，静态 validator 通过不等于 Orca 能力已验证。
