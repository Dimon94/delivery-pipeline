# 模型配置 Schema（version 5）

本文件是 worker 模型配置的唯一定义点，核心链路与各 transport 壳共用同一份格式。
各 transport 的调度逻辑在其壳内实现，配置 schema 只有这一份。

## 配置实例

同一份 schema 可有多个文件实例，每个 runtime 一个。实例清单与写入职责由
`delivery-pipeline-setup` 维护；本文件不枚举实例路径。

skill 与 reference 不提供默认 agent/model/effort。缺必需项、未知 key、空值或 `Unknown`
一律阻塞对应 transport 的新分派；不静默回落。

## 顶层结构

```json
{
  "version": 5,
  "work": {
    "planning": { "agent": "<agent>", "model": "<native-model-id>", "effort": "<native-effort>" },
    "backend": {
      "agent": "<agent>",
      "model": "<native-model-id>",
      "effort": "<native-effort>",
      "execution": { "model": "<native-model-id>", "effort": "<native-effort>" }
    }
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

CLI 实例顶层 key 精确为 `version`、`work`、`modes`、`review`。App 实例额外必需
`default_mode`，并允许可选 `legacy_execution`（见下文）。`version` 必须等于 5。

## work：任务类型

配置按**任务类型**组织，不按角色。已知 key 精确为 12 个：

| 任务类型 | 覆盖工作 |
| --- | --- |
| `coordinator` | 当前协调会话的推荐观测值；只记录观测，不切换当前会话 |
| `research` | 独立调查、搜索 |
| `prototype` | design 原型 / HITL |
| `planning` | 地图沟通、规划、spec、issue 拆分；CLI 的 AFK discovery/research、spec、tickets gate lane 也读此项 |
| `design` / `frontend` / `backend` | implementation；`output_mode: commit` 时的 starting 模型，可选 `execution` 决定 staged 续接 |
| `testing` | whole-change tests |
| `integration` | 逐票 Integration 辅助 |
| `assistance` | 内部辅助（检索、研究、有界实现） |
| `second-opinion` | 咨询子代理 |
| `ticket-sizing` | 拆分评估 |

每个 work 项必需 `{agent, model, effort}` 三字段，非空且不写 `Unknown`。`agent` 属于
`pi|codex|claude|codex-app`；agent 值决定 transport：前三个经 Herdr 起对应 CLI pane，
`codex-app` 经 App task。仅 implementation 任务类型（`design`/`frontend`/`backend`）
允许附加可选 `execution: {model, effort}`；其他任务类型写 `execution` 一律拒绝。
配置文件可以只定义已知 key 的子集；每个 transport 声明自己的必需集（见下文），缺必需项
阻塞该 transport，未消费的定义项不阻塞，未知 key 拒绝。

## implementation lane 的默认计划（CLI）

`design`/`frontend`/`backend` 且 `output_mode: commit` 的 lane，默认计划直接来自本任务
类型的 work 项，不再经过任何 mode：

- work 项的 `{model, effort}` 是 **starting**：lane 用它起步。
- work 项设了 `execution` → **staged**：starting 完成第一处修改并保存 checkpoint 后停止，
  核验现场后在同一 session 用 `execution` 续接。
- work 项未设 `execution` → **direct**：starting 单轮一路跑完，无 checkpoint 暂停。

非 implementation lane 与 `artifact`/`checks`/`verdict` output mode 也直接用 work 项的
`{agent, model, effort}`（`execution` 在这些路径非法且不被消费）。

## modes：命名覆盖预设

一个 mode 是有名字的起步续接套餐：`kind` 为 `staged` 或 `direct`，`agents` 按 agent 给出
`starting` / `execution` / `direct` 三组 `{model, effort}`。三组都必须填写，缺项、空值或
`Unknown` 拒绝。

- `kind: staged`：用 `starting` 起步，完成第一处修改并保存 checkpoint 后停止；核验现场后在
  同一 session 用 `execution` 续接。`direct` 组仍必填，供冻结一致性校验。
- `kind: direct`：用 `direct` 单轮跑完，无起步续接。

CLI 实例的 `modes` 可以为空对象；它只在 ticket 或 map **显式点名** mode 名时被消费，
选中时该 lane 的 starting/execution/direct 整体由 mode 的 per-agent 计划提供（覆盖 work 项
默认）。CLI 实例的 `agents` key 属于 `pi|codex|claude`。

App 实例的 `modes` 必须非空，`agents` key 精确为 `codex-app`；App 的 implementation lane
没有对应 work 项，阶段计划只能来自 mode，解析顺序为 本票 → map → 配置 `default_mode`。
`default_mode` 必须命中 `modes` 的 key；它是 App-only 顶层 key，CLI 实例出现即拒绝。

旧票据遗留的 `staged`/`direct` 字面值不是合法 mode 名；遇到时阻塞并要求用户显式选择
mode 名，不做别名映射。

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
  轴的 agent 属于 `pi|codex|claude`；禁止 `default_mode` 与 `legacy_execution`。
- **App 实例**：`work` 精确为 `coordinator`、`research`、`prototype`、`planning`、`testing`、
  `integration`、`assistance`、`second-opinion`、`ticket-sizing` 九项；所有 entry 与 review
  轴的 agent 必须等于 `codex-app`；必需 `default_mode`；`modes` 非空且 `agents` key 精确为
  `codex-app`。

## 迁移

`delivery-pipeline-setup/scripts/model_config.py migrate` 机械迁移旧配置并 readback：

- CLI v4：每个 implementation work 项对照 `default_mode` 的 per-agent 计划——`kind: staged`
  时 `starting` 与 work 项不一致、或 `kind: direct` 时 `direct` 与 work 项不一致，均报错并
  要求重跑 setup（fail-closed）；一致时 `execution` 与 starting 不同才携带为 work 项的
  `execution`（相同则不携带，按 version 5 语义成为直跑）。删除 `default_mode` 顶层 key，
  `modes` 原样保留作显式覆盖词汇。
- CLI v3：work 与 review 同 v4 规则的前身（roles → work，review role → 四格矩阵）；每
  agent 的 staged 计划按同一规则并入 implementation work 项（starting 冲突或 direct 计划
  冲突时报错重跑 setup）；`modes` 迁移为空对象。v3 的同 agent 角色冲突与混合 default_mode
  在 version 5 下不再是冲突：per-task 权威消除了共享。
- CLI v2：五个 role triple 落入同名 work 项（无 `execution`，即全部直跑）；`review` role
  triple 填入四格矩阵；`modes` 为空对象。
- App v4：仅版本号升为 5，其余原样（App 规则在 version 5 不变）。
- App v1：work/review 各项补 `agent: "codex-app"`；每个 mode 的 `phase_plan` 包入
  `agents: {"codex-app": ...}`；`default_mode` 与 `legacy_execution` 原样保留；版本号升为 5。

迁移只改配置格式；已有 lane 沿 registry 恢复的老规则不变，不受配置版本影响。
