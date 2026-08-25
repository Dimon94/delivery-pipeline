---
name: delivery-pipeline-pi
description: pi 模式的 delivery-pipeline 入口——pi 作为调度者，Herdr pane 中的 pi worker 按角色携带模型（frontend/design → junbo/kimi-k3:max，backend/other → openai-codex/gpt-5.6-sol:xhigh），其余编排与 delivery-pipeline 相同。
disable-model-invocation: true
---

# Delivery Pipeline（pi 模式）

本 skill 是 `$delivery-pipeline` 的薄 delta。先完整读取 `$delivery-pipeline` 的 SKILL.md，
并按当前 gate 加载它要求的 references/assets，把其中全部编排合同作为主体：gate 链、
worktree 拓扑、ready frontier、maximal safe batch、Dispatch Handoff、Integration、
tracker 权限与远程收尾全部不变。本文件只覆盖以下四格；未覆盖处一律以主体为准，
冲突处以本文件为准。

## 覆盖 1：Coordinator Runtime = pi-cli

- map registry 写 `coordinator_runtime: pi-cli`、`dispatch_runtime: herdr`。
- pi 没有 Codex App 原生 thread tools，主体 step 1 的 codex-app/codex-cli transport
  选择、Task Coordinate Title、Codex App Herdr Bridge 与 `codex-thread` lane 整支跳过。
  主体的 `../delivery-pipeline/references/dispatch-runtime-routing.md` 的“选择顺序”被本节替换；其 Dispatch critical
  path、Herdr 调度、安全不变量与模式切换章节仍然适用（runtime 名字按覆盖 2 替换）。
- Herdr 访问：coordinator 已在 Herdr pane（`HERDR_ENV=1`）时解析并调用 `$herdr`；
  否则直接执行 Herdr CLI，所有命令显式携带已读回的 visible Herdr session
  （`herdr --session <name>`），session 选择语义与主体的 Codex App Herdr Bridge 相同。

## 覆盖 2：worker kind = herdr-pi-pane

- 新 lane 默认 `runtime: herdr-pi-pane`，registry 写 `agent_permission_mode: default`
  （pi 无完全授权启动旗标）；Execution branch 用 `pi/issue-<ticket-number>`。
- 显式 worker kind 优先：用户指定 Codex 或 Claude pane 时，沿用主体的
  `herdr-codex-pane` / `herdr-claude-pane` 分支与对应 packet，本覆盖不拦截。
- pi lane 的 packet 使用本 skill 的 `assets/HERDR_PI_IMPLEMENT_DISPATCH_PACKET.md`，
  替换主体的 HERDR_CODEX / HERDR_CLAUDE packet。

## 覆盖 3：模型路由

显式模型指令优先；否则按 ticket domain：

- frontend/design → `junbo/kimi-k3:max`
- backend/other → `openai-codex/gpt-5.6-sol:xhigh`

HITL lane（grilling、prototype）同属 frontend/design，使用 `junbo/kimi-k3:max`。

pi pane 启动命令——替换主体 `../delivery-pipeline/references/pane-lifecycle-rules.md` 的 Agent 启动命令分支；
投递机制、落点验证、Working 确认、Listener 挂载与 Lifecycle 配对不变：

```bash
herdr agent start <agent-name> \
  --kind pi \
  --pane <pane-id> \
  -- --model <role-model>
```

worker 启动后模型已由 coordinator 按角色固定，packet 与 worker 都不自行切换模型。

## 覆盖 4：Trusted Execution Bootstrap 的 pi 语义

`--dangerously-skip-permissions`、workspace trust 与 external imports 确认 UI 是 Claude
专有；pi pane 无对应 UI。`bootstrap_authority: trusted_execution_bootstrap` 在 pi 模式下
不承担 Claude 专有确认，其余授权语义（用户一次批准、不覆盖 remote publication）不变。
pi 侧 project-local trust 是否需要 `--approve` 是 Unknown；遇到未知或越界 UI 时按主体
规则记为可恢复 `blocked`，不猜测操作。
