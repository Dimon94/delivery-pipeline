---
name: delivery-pipeline-orca
description: 在 Orca runtime 中检查交付编排入口、原生 discovery 与当前操作能力；证据不足时明确阻塞，不切换其他 transport。
disable-model-invocation: true
---

# Delivery Pipeline（Orca）

本入口与 CLI/Herdr、Codex App 并列，严格绑定 Orca。当前 Orca terminal 是 coordinator；
外部会话不能冒充该身份。本入口先做 preflight；coordinator 核验 native provenance 后，才可通过
`worker_lifecycle.py` 记录 dispatch intent、native 坐标、readback、final 与 cleanup 状态。

## 复用边界

- 执行真相源：owner 三字段（name、绝对 SKILL.md path、runtime-specific invocation label）。
- canonical gate 与实施前置证据：`../delivery-pipeline/references/gate-state-machine.md`。
- owner 解析：`../delivery-pipeline/references/owner-skill-resolution.md`。
- worker policy：`../delivery-pipeline/references/model-config-schema.md`；只读现有
  `~/.config/delivery-pipeline/model-roles.json`（CLI 实例），不新建 Orca override 配置。
- lane registry：共享 schema，Orca overlay 仅写入嵌套 `orca` 槽位。
- dispatch packet 与 worker 生命周期合同：`assets/ORCA_ROLE_DISPATCH_PACKET.md` 与
  `references/orca-dispatch.md`；本文件不重复其字段定义。
- 从本文件的 realpath 解析 canonical siblings，不从调用者 cwd 猜路径，也不完整执行
  `../delivery-pipeline/SKILL.md` 的 Herdr startup。

## 每次进入操作前

1. 固定一个 Orca executable：`export ORCA_CLI_COMMAND="<exact argv prefix>"`，记录 `realpath`
   与 `--version` 首行；会话内不变，失败不试下一个 binary。
2. 读取该 binary 的 version-matched `skills get orca-cli`、`skills get orchestration` 与本次
   operation 所需 reference；记录实际读取命令。
3. 以 `agent-context` 确认当前 Orca terminal 身份；外部会话不能冒充。
4. 以 `skills installed --json` 确认 bundle 与 owner skill 的绝对 realpath。
5. `target_host`、status 的 target + runtimeId、terminal identity、所需 capability 精确一致。
6. 全部证据可读回才进入机械 preflight。

## 机械 preflight

固定 Orca executable 后运行：

```bash
python3 scripts/preflight.py run --payload <json>
```

helper 只校验 caller-declared 字段、绑定与可读绝对 source path（含 `model_config.py`
校验 plan），不证明原生 provenance。字段缺失/格式非法 → `blocked`；dispatch 请求缺证据 →
`dispatch unavailable`；结构成功仅 `preflight-ready`，并输出 `authority: false`——
coordinator 必须核验原生 source provenance 后才授权。逐字段 request 合同与 CLI 探测顺序见
`references/orca-preflight.md`。

## 共享 registry caller

共享 registry 的 Orca overlay 只经由 caller 脚本写入：

```bash
python3 scripts/registry_overlay.py apply --payload <json>
```

action ∈ `record_dispatch_intent` / `record_native_coordinates` / `record_readback` /
`record_final_state` / `record_cleanup_state`；顺序 intent → native → readback → final →
cleanup，缺前置即拒绝，不写 registry。payload schema 与一致性检查见
`references/orca-registry-overlay.md`。

## Recovery 与 staged continuation

先读 `references/orca-recovery.md`，再运行 `scripts/recovery.py check <payload>`。
重试同 Task 串行，FIFO；只有正面 failed/stopped 才考虑同 Task retry；Unknown 保留现场。
staged 复用 canonical continuation/checkpoint helper（见「复用边界」）。

## Provider mutation gate（Phase 2B）

Provider mutation 操作先读 `references/orca-provider-mutation.md`，每次运行
`scripts/provider_mutation.py check <payload>`；缺失或非法不执行。mutation 只在当前固定
binary 的 readback 内成立，不跨 binary 合并证据。

## Browser/automation operation gate（Phase 2A）

Browser/automation 操作先读 `references/orca-browser-automation.md`，每次运行
`scripts/browser_gate.py check <payload>`。任一缺失 → 操作不可执行。

## Remote publication gate（Phase 4）

Remote publication 操作先读 `references/orca-remote-publication.md`，每次运行
`scripts/remote_publication.py check <payload>`。任一 gate 缺证据 → 该操作不可执行，
registry 写 `close_pending`。不代用户发起 push/PR/MR/merge/publication。

## 项目侧 fan-in 与 cleanup

Lane 状态读取经 `scripts/worker_lifecycle.py`（`worker-start` / `worker-status` /
`worker-stop` / `worker-wait` / `worker-list`），不存在时记 Unknown。整批 lanes 完成
startup 后 FIFO 处理 terminal signal；fan-in 的 Execution Worktree、packet、registry、
receipt 与 cleanup 六步口径一致，worker 退出/丢失不自动重试，registry 最终 transition 经
`scripts/project_lifecycle.py` 的 `project_lane_transition`。Orca lane 不继承 CLI/Herdr pane
lifecycle。逐字段与 readback 细节见 `references/orca-dispatch.md` 的「项目侧 fan-in /
cleanup readback」。

## 结果与权限

缺 CLI/runtime/reference/discovery/capability、shared agent/model/effort、native 同 session
证据或 identity 不一致时，输出 `blocked` 与具体缺口；dispatch 请求输出
`dispatch unavailable` 与同一原因。不 fallback 到 Herdr 或 Codex App，不启动 worker。
真机未运行明确写 `not-run/Unknown`，静态 validator 通过不等于 Orca 能力已验证。
