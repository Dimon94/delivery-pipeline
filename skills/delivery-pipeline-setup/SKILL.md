---
name: delivery-pipeline-setup
description: 初始化或重配 delivery-pipeline 的任务类型 worker 配置。
disable-model-invocation: true
---

# Delivery Pipeline Setup

初始化或重配 `~/.config/delivery-pipeline/model-roles.json`。先完整读取
`../delivery-pipeline/references/model-config-schema.md`；它是 version 4 schema（任务类型、命名
mode 预设、review 矩阵、transport 必需集）的唯一来源。再读取
`../delivery-pipeline/references/model-role-routing.md` 获取 agent adapter 与 evidence 规则。
本流程在当前会话交互执行，不派发 lane。

## 流程

1. **探测并严格验证现状。** 从本 SKILL.md realpath 解析并运行
   `scripts/model_config.py validate ~/.config/delivery-pipeline/model-roles.json`，同时执行第 2 步的
   本机 evidence probe。旧 version 2/3 文件先运行 `scripts/model_config.py migrate <config>`
   机械迁移并 readback；迁移报错（同 agent 冲突或混合 default_mode）时进入初始化流程。
   只有 version 4 配置结构与实时 evidence 都通过才报告当前表并结束：
   顶层 key、任务类型全集与 CLI 必需集、review 矩阵、mode 预设与 `default_mode` 覆盖规则按
   schema 文档逐项核对；每个 entry 的 `agent/model/effort` 非空、binary 存在、model/effort 命中
   对应实时 evidence。任何非法配置进入初始化；合法配置仅在用户明确要求重配时覆盖。
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
   binary、文件或字段不存在时记 Unknown，不臆造候选。
3. **逐项选择。** 按 `planning`、`design`、`frontend`、`backend`、`testing` 顺序，每个任务
   类型先选 agent，再从该 agent 的真实 evidence 选择 model 与 effort；随后选择 review 矩阵四格
   （`implementation`/`whole-change` × `standards`/`spec`）。展示任务管辖工作、候选来源与当前
   选择。Claude model 只从 settings.json env 候选选择；无候选时不能选择 Claude。Skill 不提供内置默认，由用户明确选择全部必需项。再选择 `default_mode` 引用的命名 mode：为每个用到的
   agent 填 starting/execution/direct 三组参数，`kind` 选 `staged` 或 `direct`；只有
   `design`/`frontend`/`backend` 且 `output_mode: commit` 的 lane 消费该计划，其他任务类型
   直接用 work 项。
4. **验证选择。** 每个 agent binary 可用；pi/Codex model+effort 命中权威 catalog；Claude
   model 命中 env 候选且 effort 命中 CLI 枚举。失败只重问对应项，不重跑稳定选择。
5. **写入并 readback。** 创建父目录，只写目标 config；写完再次运行
   `scripts/model_config.py validate <config>`，再验证 binary 与实时 evidence。两层都通过后报告最终
   任务类型 → agent/model/effort 表与 mode 预设。之后新 lane 按本票 → map → 配置 `default_mode`
   解析并冻结计划；不能把计划选择写进 coordinator 配置。

完成标准：CLI 必需任务类型与 review 矩阵都由用户明确选择，配置 readback 与选择一致；没有
默认值、空字段、非法 agent、额外字段或未命中本机 evidence 的 model/effort。所有 startup 都需要
当前 capability evidence。Pi/Codex/Claude staged 均通过 `model_config.py start` 起步，
`model_config.py resume --request <payload.json>` 复用各自现有 native adapter 生成接续计划；
payload 与核验合同见 `../delivery-pipeline/references/model-role-routing.md`。
任何 agent 都不能静默生成 direct 启动请求。
