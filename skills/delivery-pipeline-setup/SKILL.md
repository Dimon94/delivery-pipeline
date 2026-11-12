---
name: delivery-pipeline-setup
description: 初始化或重配 delivery-pipeline 的任务类型 worker 配置。
disable-model-invocation: true
---

# Delivery Pipeline Setup

初始化或重配 `~/.config/delivery-pipeline/model-roles.json`。先完整读取
`../delivery-pipeline/references/model-config-schema.md`；它是 version 5 schema（任务类型、
命名 mode 覆盖预设、review 矩阵、transport 必需集）的唯一来源。再读取
`../delivery-pipeline/references/model-role-routing.md` 获取 agent adapter 与 evidence 规则。
本流程在当前会话交互执行，不派发 lane。

配置实例清单（schema 只有一份，见上；实例归各 runtime）：

- **CLI 实例**：`~/.config/delivery-pipeline/model-roles.json`，由本流程写入并 readback；
  CLI/Herdr dispatch 只读。
- **App 实例**：`skills/delivery-pipeline-codex-app/config/models.json`，由用户编辑；
  App 壳 helper 只读，不改配置。

pi coordinator 的上下文上限由 `pi/coordinator-context-cap.ts` 提供（默认 150K，
`DP_COORDINATOR_CONTEXT_CAP` 可覆盖）；确认它已软链到
`~/.pi/agent/extensions/dp-coordinator-context-cap.ts`，缺失时创建该软链。

## 流程

1. **探测并严格验证现状。** 从本 SKILL.md realpath 解析并运行
   `scripts/model_config.py validate ~/.config/delivery-pipeline/model-roles.json`，同时执行第 2 步的
   本机 evidence probe。旧 version 2/3/4 文件先运行 `scripts/model_config.py migrate <config>`
   机械迁移并 readback；迁移提交前拒绝后，经用户明确授权才进入重配流程；退出 3 时先显式读取核对，不进入初始化。
   只有 version 5 配置结构与实时 evidence 都通过才报告当前表并结束：
   顶层 key、任务类型全集与 CLI 必需集、review 矩阵与命名 mode 覆盖预设按 schema 文档逐项核对；每个 entry 的 `agent/model/effort` 非空、binary 存在、model/effort 命中
   对应实时 evidence。任何非法配置给出修复引导，用户明确授权后才按实际 hash 重配；合法配置仅在用户明确要求重配时覆盖。
   迁移或重配不会迁移已有 lane；已有 lane 继续按 registry 恢复。
2. **探测本机 evidence。** 并行运行：
   - pi：`pi --list-models`，记录 provider/model 与 thinking 支持；
   - Codex：`codex debug models`，解析 `models[].slug` 与
     `supported_reasoning_levels[].effort`；
   - Claude：读取 `~/.claude/settings.json` 的 `env`，解析
     `ANTHROPIC_DEFAULT_FABLE_MODEL`、`ANTHROPIC_DEFAULT_HAIKU_MODEL`、
     `ANTHROPIC_DEFAULT_OPUS_MODEL`、`ANTHROPIC_DEFAULT_SONNET_MODEL`、
     `ANTHROPIC_MODEL`、`CLAUDE_CODE_SUBAGENT_MODEL`、对应 `*_MODEL_NAME` 与
     `CLAUDE_CODE_EFFORT_LEVEL`；effort候选同时受 Claude CLI `--effort` 枚举约束。
   每份 evidence 记录来源命令/文件与探测结果；binary、文件或字段不存在时记 Unknown，
   指明缺失项与下一核验动作，沿真实来源补齐后再选择该项候选。
3. **逐项选择。** 按 `planning`、`design`、`frontend`、`backend`、`testing` 顺序，每个任务
   类型先选 agent，再从该 agent 的真实 evidence 选择 model 与 effort；随后选择 review 矩阵四格
   （`implementation`/`whole-change` × `standards`/`spec`）。展示任务管辖工作、候选来源与当前
   选择。Claude model 只从 settings.json env 候选选择；无候选时不能选择 Claude。Skill 不提供
   内置默认，由用户明确选择全部必需项。每个任务类型的 work 项就是该 lane 单轮直跑的
   `{agent, model, effort}`。`modes` 命名覆盖预设可选维护：只在 ticket/map 显式点名时用其
   `direct` 组覆盖，默认路径不消费。
4. **验证选择。** 每个 agent binary 可用；pi/Codex model+effort 命中权威 catalog；Claude
   model 命中 env 候选且 effort 命中 CLI 枚举。失败只重问对应项，不重跑稳定选择。
5. **共享事务提交并 readback。** 禁止用 shell 重定向、编辑器或临时脚本直接写目标。
   用户确认本次候选后生成唯一 request-id，重新采集本轮能力，按配置 Module 的
   `ProbeEvidence` 交接（request_id、observed_at、capabilities、sources；来源状态 ok 才可用于改动格）。
   能力判断复用 Python `capability_errors` / `validate_selection`，不在 Skill 复制规则。
   候选写入独立临时文件，证据也只放临时文件，不能写进用户配置。
   从实际原字节读取 SHA-256 基线（包括坏 JSON 的显式修复）；缺失才省略 --base-hash。
   用户明确重配或修复授权后运行：
   `python3 <setup-realpath>/scripts/model_config.py configure <config> --base-hash <实际hash> --request-id <本次id> --evidence <本轮证据文件>`，
   stdin 接完整候选（例如 `< <候选临时文件>`）。目标缺失时去掉 --base-hash；
   父目录、稳定 sidecar 锁、原子写入及精确 readback 全由该入口负责。
   退出 0 且 status=applied 才报告成功，返回 config 与 base_hash 是实际读回值。
   退出 1 / rejected 保留候选；base_conflict 必须重新读取、人工核对再确认，不自动合并或重提。
   退出 3 / commit_unverified 表示已越过替换点但待确认；仅显式读取实际结果供用户核对，
   不自动回滚、重试，也不能宣称未写入。migrate 同样遵守 1/3 分类；迁移失败不可自动接着初始化。
   无语义改动 changed=false 保留原字节。两层都通过后报告最终
   任务类型 → agent/model/effort 表。之后新 lane 默认按 work 项解析并冻结计划；ticket/map
   显式点名 mode 时用其 `direct` 组覆盖。不能把计划选择写进 coordinator 配置。

完成标准：CLI 必需任务类型与 review 矩阵都由用户明确选择，配置 readback 与选择一致；没有
默认值、空字段、非法 agent、额外字段或未命中本机 evidence 的 model/effort。所有 startup 都需要
当前 capability evidence；启动请求由 `model_config.py start` 生成。
