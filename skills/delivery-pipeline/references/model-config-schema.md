# 模型配置 Schema（version 4）

本文件是 worker 模型配置的唯一定义点，CLI/Herdr 主干与 App 壳共用同一份格式。
两个 transport 的调度逻辑各自实现（见 `dispatch-runtime-routing.md` 与
`../../delivery-pipeline-codex-app/references/development-mode.md`），配置 schema 只有这一份。

## 配置实例

同一份 schema 有两个文件实例：

- **CLI 实例**：`~/.config/delivery-pipeline/model-roles.json`，由 `delivery-pipeline-setup`
  写入并 readback；CLI/Herdr dispatch 只读。
- **App 实例**：`skills/delivery-pipeline-codex-app/config/models.json`，由用户编辑；
  App 壳 helper 只读，不改配置。

skill 与 reference 不提供默认 agent/model/effort。缺必需项、未知 key、空值或 `Unknown`
一律阻塞对应 transport 的新分派；不静默回落。

## 顶层结构

```json
{
  "version": 4,
  "default_mode": "<modes 中的名字>",
  "work": {
    "planning": { "agent": "<agent>", "model": "<native-model-id>", "effort": "<native-effort>" }
  },
  "modes": {
    "<name>": {
      "kind": "staged",
      "agents": {
        "<agent>": {
          "starting":  { "model": "<native-model-id>", "effort": "<native-effort>" },
          "execution": { "model": "<native-model-id>", "effort": "<native-effort>" },
          "direct":    { "model": "<native-model-id>", "effort": "<native-effort>" }
        }
      }
    }
  },
  "review": {
    "implementation": {
      "standards": { "agent": "<agent>", "model": "<native-model-id>", "effort": "<native-effort>" },
      "spec":      { "agent": "<agent>", "model": "<native-model-id>", "effort": "<native-effort>" }
    },
    "whole-change": {
      "standards": { "agent": "<agent>", "model": "<native-model-id>", "effort": "<native-effort>" },
      "spec":      { "agent": "<agent>", "model": "<native-model-id>", "effort": "<native-effort>" }
    }
  }
}
```

顶层 key 精确为 `version`、`default_mode`、`work`、`modes`、`review`，外加仅 App 实例允许的
可选 `legacy_execution`（见下文）。`version` 必须等于 4。

## work：任务类型

配置按**任务类型**组织，不按角色。已知 key 精确为 12 个：

| 任务类型 | 覆盖工作 |
| --- | --- |
| `coordinator` | 当前协调会话的推荐观测值；只记录观测，不切换当前会话 |
| `research` | 独立调查、搜索 |
| `prototype` | design 原型 / HITL |
| `planning` | 地图沟通、规划、spec、issue 拆分；CLI 的 AFK discovery/research、spec、tickets gate lane 也读此项 |
| `design` / `frontend` / `backend` | implementation；`output_mode: commit` 时走 `modes` 分阶段计划，其余 output mode 直接用本项 |
| `testing` | whole-change tests |
| `integration` | 逐票 Integration 辅助 |
| `assistance` | 内部辅助（检索、研究、有界实现） |
| `second-opinion` | 咨询子代理 |
| `ticket-sizing` | 拆分评估 |

每个 work 项精确为 `{agent, model, effort}` 三字段，非空且不写 `Unknown`。
`agent` 属于 `pi|codex|claude|codex-app`；agent 值决定 transport：前三个经 Herdr 起对应
CLI pane，`codex-app` 经 App task。配置文件可以只定义已知 key 的子集；每个 transport
声明自己的必需集（见下文），缺必需项阻塞该 transport，未消费的定义项不阻塞，未知 key 拒绝。

## modes：命名执行预设

一个 mode 是有名字的起步续接套餐：`kind` 为 `staged` 或 `direct`，`agents` 按 agent 给出
`starting` / `execution` / `direct` 三组 `{model, effort}`。三组都必须填写，缺项、空值或
`Unknown` 拒绝。

- `kind: staged`：用 `starting` 起步，完成第一处修改并保存 checkpoint 后停止；核验现场后在
  同一 session 用 `execution` 续接。`direct` 组仍必填，供 ticket/map 显式选择直跑外的
  冻结一致性校验。
- `kind: direct`：用 `direct` 单轮跑完，无起步续接。

mode 名是两个 transport 共享的词汇；`agents` 层解决同一策略在不同 CLI 上的模型名翻译。
ticket、map 与配置默认引用的都是 mode 名。CLI 实例的 `agents` key 属于
`pi|codex|claude`；App 实例的 `agents` key 精确为 `codex-app`。

## default_mode 与解析顺序

`default_mode` 必须命中 `modes` 的 key。implementation lane（`design` / `frontend` /
`backend` 且 `output_mode: commit`）的 mode 解析顺序为 本票 → map → 配置 `default_mode`；
解析出的 mode 必须含该 lane agent 的 `agents` 项，否则阻塞。CLI 实例额外要求
`default_mode` 的 `agents` 覆盖 `design`、`frontend`、`backend` 三项各自的 agent。
非 implementation lane 与 `artifact`/`checks`/`verdict` output mode 不消费 modes，
直接用 work 项的 `{agent, model, effort}`。

旧配置或旧票据遗留的 `staged`/`direct` 字面值不是合法 mode 名；遇到时阻塞并要求用户
显式选择 mode 名，不做别名映射。

## review：双轴矩阵

`review` 精确为 `implementation` 与 `whole-change` 两个 scope，每个 scope 精确为
`standards` 与 `spec` 两轴，每轴为 `{agent, model, effort}`。CLI review lane 用
`standards` 轴的 `{agent, model, effort}` 启动 pane，packet 携带该 scope 的两轴配置交给
resolved code-review owner；App 由 coordinator 的 subagent 入口解析两轴模型传给 owner。
两轴独立性与 verdict 放行规则不变，模型配置不构成豁免。

## legacy_execution（仅 App 实例，可选）

App 实例允许可选的 `legacy_execution`，key 精确为 `astra-luna` 与 `astra-sol`，值为
`{model, effort}`；仅供无 `phase_plan` 的旧 lane 恢复，新分派不消费。CLI 实例禁止该 key。

## Transport 必需集

- **CLI 实例**：`work` 必需 `planning`、`design`、`frontend`、`backend`、`testing` 与完整
  `review` 矩阵；允许定义其余已知任务类型（当前调度不消费，为后续留口）；entry 与 review
  轴的 agent 属于 `pi|codex|claude`；禁止 `legacy_execution`。
- **App 实例**：`work` 精确为 `coordinator`、`research`、`prototype`、`planning`、`testing`、
  `integration`、`assistance`、`second-opinion`、`ticket-sizing` 九项；所有 entry 与 review
  轴的 agent 必须等于 `codex-app`；`modes` 的 `agents` key 精确为 `codex-app`。

## 迁移

`delivery-pipeline-setup/scripts/model_config.py migrate` 机械迁移旧配置并 readback：

- CLI v2：五个 role triple 落入同名 work 项；`review` role triple 填入四格矩阵；生成
  kind 为 `direct` 的 `migrated-direct` mode（implementation 三项的 agent 各自的 direct
  计划取自其 triple；同 agent 不同 triple 冲突时报错，重跑 setup）；`default_mode` 为
  `migrated-direct`。
- CLI v3：work 与 review 同 v2 规则；每 agent 的 starting/execution/direct 计划包进
  `migrated-staged`（`default_mode` 为 staged 的 agent）与 `migrated-direct`（全部 agent 的
  direct 计划）两个 mode；全部 agent 的 `default_mode` 一致时全局 `default_mode` 取对应
  mode 名，不一致时迁移报错并要求用户经 setup 显式选择。
- App v1：work/review 各项补 `agent: "codex-app"`；每个 mode 的 `phase_plan` 包入
  `agents: {"codex-app": ...}`；`default_mode` 与 `legacy_execution` 原样保留。

迁移只改配置格式；已有 lane 沿 registry 恢复的老规则不变，不受配置版本影响。
