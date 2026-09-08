---
name: delivery-pipeline-setup
description: 初始化或重配 delivery-pipeline 的六角色 worker 配置。
disable-model-invocation: true
---

# Delivery Pipeline Setup

初始化或重配 `~/.config/delivery-pipeline/model-roles.json`。先完整读取
`../delivery-pipeline/references/model-role-routing.md`；它是 schema version 2 兼容层、version 3
执行计划、六角色、agent adapter 与验证规则的唯一来源。本流程在当前会话交互执行，不派发 lane。

## 流程

1. **探测并严格验证现状。** 从本 SKILL.md realpath 解析并运行
   `scripts/model_config.py validate ~/.config/delivery-pipeline/model-roles.json`，同时执行第 2 步的
   本机 evidence probe。只有配置结构与实时 evidence 都通过，且以下条件
   全部满足，才报告当前表并结束：顶层 key 精确为 `version` + `roles`（version 2）或加 `execution`（version 3）；
   version 必须是已知版本；role key 精确
   为 `planning/design/frontend/backend/testing/review`；每个 role object 的 key 精确为
   `agent/model/effort`；agent 属于 `pi|codex|claude`；三字段非空；binary存在；model/effort命中
   对应实时 evidence。任何非法配置进入初始化，不把非法既有 v2 文件当作完成；合法配置仅在用户明确要求重配时覆盖。
   已严格验证的旧 v2 配置继续保留旧启动行为；不会因为升级
   setup 自动迁移已有 lane 或隐式改为 staged。
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
3. **逐角色选择。** 按 `planning`、`design`、`frontend`、`backend`、`testing`、`review`
   顺序，每个角色先选 agent，再从该 agent 的真实 evidence选择 model 与 effort。展示角色管辖
   工作、候选来源与当前选择。Claude model只从 settings.json env候选选择；无候选时不能选择
   Claude。Skill 不提供内置默认，由用户明确选择全部六角色。若用户启用 version 3，
   再按 `pi`、`codex`、`claude` 选择 `default_mode` 与 starting/execution/direct 三组参数；
   只为 implementation role 使用 staged，其他 role 继续 role triple。
4. **验证选择。** 每个 agent binary可用；pi/Codex model+effort命中权威 catalog；Claude
   model命中 env候选且 effort命中 CLI枚举。失败只重问对应角色，不重跑稳定选择。
5. **写入并 readback。** 创建父目录，只写目标 config；写完再次运行
   `scripts/model_config.py validate <config>`，再验证 binary与实时 evidence。两层都通过后报告最终
   role → agent/model/effort表及（如适用）execution 计划。之后新 lane 按本票 → map → 用户配置
   解析并冻结计划；只有 `output_mode: commit` 的 implementation lane 读取 staged/direct 计划，
   artifact/checks/verdict lanes 继续沿原 role 行为；不能把计划选择写进 coordinator 配置。

完成标准：六角色都由用户明确选择，配置 readback与选择一致；没有默认值、空字段、非法 agent、
额外字段或未命中本机 evidence 的 model/effort。所有 startup（含 version 2）都需要当前
capability evidence。Pi/Codex/Claude staged 均通过 `model_config.py start` 起步，
`model_config.py resume --request <payload.json>` 复用各自现有 native adapter 生成接续计划；
payload 与核验合同见 `../delivery-pipeline/references/model-role-routing.md`。
任何 agent 都不能静默生成 direct 启动请求。
