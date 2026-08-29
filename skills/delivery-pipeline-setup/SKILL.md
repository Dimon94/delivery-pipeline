---
name: delivery-pipeline-setup
description: Initialize or reconfigure delivery-pipeline version 3 worker routing, optional Pi Gearshift bootstrap models, and deterministic off/opt-in/all-eligible policy from live model evidence.
disable-model-invocation: true
---

# Delivery Pipeline Setup

初始化或重配 `~/.config/delivery-pipeline/model-roles.json`。先完整读取 `../delivery-pipeline/references/model-role-routing.md`；它是 version 3 schema、六角色、Bootstrap Gearshift Policy、agent adapter 与验证规则的唯一来源。本流程在当前会话交互执行，不派发 lane。

## 流程

1. **探测并严格验证现状。** 从本 SKILL.md realpath 解析并运行 `scripts/model_config.py validate ~/.config/delivery-pipeline/model-roles.json`，同时执行第 2 步 evidence probe。只有以下条件全部满足才报告当前表并结束：
   - 顶层 key 精确为 `version + gearshift + roles`，version = 3；
   - 六角色完整；base role fields 为 `agent/model/effort`；
   - 只有 pi frontend/backend 可有精确 `bootstrap.model/effort`；
   - Gearshift mode、label、eligible bootstrap 和实时 model evidence 全部有效。

   任何失败都进入初始化，不把 version 2 或非法 version 3 当作完成。只有用户明确要求重配时才覆盖已严格验证的配置。

2. **探测本机 evidence。** 并行运行：
   - pi：`pi --list-models`，记录 provider/model 与 thinking 支持；
   - Codex：`codex debug models`，解析 model slug 与 reasoning effort；
   - Claude：读取 `~/.claude/settings.json` env 中的 Fable/Haiku/Opus/Sonnet、`ANTHROPIC_MODEL`、`CLAUDE_CODE_SUBAGENT_MODEL` 与 effort；
   - Gearshift Core：运行 `pi --help`，验证 `--gearshift-profile`、`--gearshift-target`、`--gearshift-target-thinking`、`--gearshift-adapter`、`--gearshift-arm-authority` flags。

   binary、文件或字段不存在时记 Unknown，不臆造候选。Gearshift flags 缺失不阻止 mode=`off`，但不能选择 active mode。

3. **逐角色选择普通 route。** 按 `planning`、`design`、`frontend`、`backend`、`testing`、`review` 顺序，每个角色先选 agent，再从该 agent 的实时 evidence 选择普通 model 与 effort。普通 route 永远是 role 的长期执行 route；Skill 不提供默认。

4. **选择 Bootstrap entry。** 仅对 agent=pi 的 frontend/backend 分别询问是否配置 bootstrap。选择时从相同 pi catalog 选择不同于普通 model 的 Source Model 与 effort。其他角色和 runtime 不显示 bootstrap 选项。

5. **选择 Gearshift Policy。** 用户明确选择：
   - `off`
   - `opt_in`
   - `all_eligible`

   `opt_in`/`all_eligible` 要求至少一个 bootstrap 且 Gearshift flags 已验证。`opt_in` label 默认建议 `bootstrap-handoff`，但仍要求用户确认非空值。mode 只改变新 lane；不迁移 existing lane。

6. **验证选择。** 每个普通和 bootstrap model/effort 命中对应实时 catalog；bootstrap 只属于 pi frontend/backend；Source/Target 不相同；active mode 的 Gearshift Core flags 完整。失败只重问对应选择，不静默回落。

7. **写入并 readback。** 创建父目录，只原子写目标 config；写完再次运行 `scripts/model_config.py validate <config>`，再验证 binary、实时 model evidence 与 Gearshift flags。全部通过后报告：
   - role → agent / ordinary model / effort；
   - frontend/backend bootstrap（或 none）；
   - mode 与 opt-in label。

完成标准：version 3 严格 readback；六角色与 policy 都由用户明确选择；没有默认模型、空字段、非法 bootstrap、额外字段或未命中本机 evidence 的值。
