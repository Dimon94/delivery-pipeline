# 模型配置 Schema（CLI version 9（兼容 6、7、8）/ App version 5）

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
  "version": 9,
  "dispatch": {"parallel": 4, "max_turns": 100},
  "model_families": {},
  "work": {
    "planning": { "agent": "<agent>", "model": "<native-model-id>", "effort": "<native-effort>", "fallbacks": [], "label": "规划", "hint": "拆需求、定方案", "purpose": "planning" },
    "backend":  { "agent": "<agent>", "model": "<native-model-id>", "effort": "<native-effort>", "fallbacks": [], "label": "后端开发", "hint": "写服务端代码", "purpose": "code" }
  },
  "modes": {
    "<name>": {
      "kind": "direct",
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
      "standards": { "agent": "<agent>", "model": "<native-model-id>", "effort": "<native-effort>", "candidates": [] },
      "spec":      { "agent": "<agent>", "model": "<native-model-id>", "effort": "<native-effort>", "candidates": [] }
    },
    "whole-change": {
      "standards": { "agent": "<agent>", "model": "<native-model-id>", "effort": "<native-effort>", "candidates": [] },
      "spec":      { "agent": "<agent>", "model": "<native-model-id>", "effort": "<native-effort>", "candidates": [] }
    }
  }
}
```

CLI v9 实例顶层 key 精确为 `dispatch`、`version`、`work`、`modes`、`review`、`model_families`。App 实例额外必需
`default_mode`。CLI 只读 v6、v7 时使用并发 4 和每次 100 轮，只读 v6–v8 时在内存中补齐内置任务类型默认元信息。显式迁移输出 v9。App 保持 v5。

`dispatch` 仅含 `parallel` 与 `max_turns` 两个正整数。v8/v9 缺键或非法值会阻止派发。降低并发后，已有执行继续，新任务等到空出名额。每次启动时固定轮限。

## work：任务类型

配置按**任务类型**组织，不按角色。已知 key 精确为 12 个：

| 任务类型 | 覆盖工作 |
| --- | --- |
| `coordinator` | 当前协调会话的推荐观测值；只记录观测，不切换当前会话 |
| `research` | 独立调查、搜索 |
| `prototype` | design 原型 / HITL |
| `planning` | 地图沟通、规划、spec、issue 拆分；CLI 的 AFK discovery/research、spec、tickets gate lane 也读此项 |
| `design` / `frontend` / `backend` | implementation |
| `testing` | whole-change tests |
| `integration` | 逐票 Integration 辅助 |
| `assistance` | 内部辅助（检索、研究、有界实现） |
| `second-opinion` | 咨询子代理 |

每个 work 项必需 `{agent, model, effort}` 三字段，非空且不写 `Unknown`。`agent` 属于
`pi|codex|claude|antigravity|codex-app`：agent 值决定 worker kind，前四个由所选 CLI transport 壳（Herdr pane、T3Code task 或 Lody session）承载，
`codex-app` 经 App task。App 与非编辑 work 项精确为这三个字段；CLI 五 work 另必需 `fallbacks`，见 v6 条款。其他字段（含旧 `execution`）拒绝。
配置文件可以只定义已知 key 的子集；每个 transport 声明自己的必需集（见下文），缺必需项
阻塞该 transport，未消费的定义项不阻塞，未知 key 拒绝。

## modes：命名覆盖预设

一个 mode 是有名字的模型套餐：`kind` 只能为 `direct`（`staged` 已退役），`agents` 按 agent 给出
`starting` / `execution` / `direct` 三组 `{model, effort}`，三组都必填。

CLI 只跑 direct：CLI 实例的 mode `kind` 必须为 `direct`，lane 只消费 `direct` 组；`modes`
可以为空，只在 ticket 或 map **显式点名** mode 名时整体覆盖 work 项，`agents` key 属于
`pi|codex|claude|antigravity`。没有点名时 lane 直接用 work 项的 `{agent, model, effort}`。

App 实例的 `modes` 必须非空，`agents` key 精确为 `codex-app`，`kind` 同样必须为 `direct`
（App Prewalk 已退役，见 ADR-0007 修订）；App 的 implementation lane 计划只能来自 mode，解析顺序为 本票 → map → 配置 `default_mode`。`default_mode` 必须
命中 `modes` 的 key；它是 App-only 顶层 key，CLI 实例出现即拒绝。

旧票据遗留的 `staged`/`direct` 字面值不是合法 mode 名；遇到时阻塞并要求用户显式选择。

## review：双轴矩阵

`review` 精确为 `implementation` 与 `whole-change` 两个 scope，每个 scope 精确为
`standards` 与 `spec` 两轴，App 每轴为 `{agent, model, effort}`；CLI 另必需 `candidates`（M2 只保留）。CLI review lane 用
`standards` 轴的 `{agent, model, effort}` 启动 pane，packet 携带该 scope 的两轴配置交给
resolved code-review owner；App 由 coordinator 的 subagent 入口解析两轴模型传给 owner。
两轴独立性与 verdict 放行规则不变，模型配置不构成豁免。

## Transport 必需集

- **CLI 实例**：`work` 必需 `planning`、`design`、`frontend`、`backend`、`testing` 与完整
  `review` 矩阵；允许定义其余已知任务类型（当前调度不消费，为后续留口）；entry 与 review
  轴的 agent 属于 `pi|codex|claude|antigravity`；禁止 `default_mode`。两个实例都禁止已退役的 `legacy_execution`。
- **App 实例**：`work` 精确为 `coordinator`、`research`、`prototype`、`planning`、`testing`、
  `integration`、`assistance`、`second-opinion` 八项；所有 entry 与 review
  轴的 agent 必须等于 `codex-app`；必需 `default_mode`；`modes` 非空且 `agents` key 精确为
  `codex-app`。

## 迁移

`delivery-pipeline-setup/scripts/model_config.py migrate` 机械迁移旧配置并 readback：

- CLI v4/v3：implementation work 项对照旧默认计划；starting/direct 与 work 项不一致，或
  staged 的 `execution` 与 starting 不同（CLI 已不支持续接），均报错并要求重跑 setup。
  一致时删除 `default_mode`，`modes` 改为 `kind: direct` 保留作显式覆盖词汇（v3 为空对象），
  v3 roles → work、review role → 四格矩阵。
- CLI v2：五个 role triple 落入同名 work 项；`review` role
  triple 填入四格矩阵；`modes` 为空对象。
- App v4：仅版本号升为 5，其余原样（App 规则在 version 5 不变）。
- App v1：work/review 各项补 `agent: "codex-app"`；每个 mode 的 `phase_plan` 包入
  `agents: {"codex-app": ...}`；staged 的 starting 与 execution 不同则报错并要求重跑 setup，
  相同时改为 `kind: direct`；`default_mode` 原样保留，`legacy_execution` 丢弃；版本号升为 5。

迁移只改配置格式；已有 lane 沿 registry 恢复的老规则不变，不受配置版本影响。

## CLI v6 有序列表（DD-407 / DD-411 已确认 Spec）

五个必需 work 项精确为 `{agent, model, effort, fallbacks}`，fallbacks 为不限长、允许重复的精确 `{agent, model, effort}` 列表。按位置保存，不排序、去重或截断。非编辑 work 仍精确三字段。
review 四格精确为 `{agent, model, effort, candidates}`，candidates 同形列表；M2 桌面只保留，不编辑或消费。
AI setup 显式 migrate 将 CLI v5 升 v6，仅补空列表；更旧版本先沿既有转换，同一事务保存。重复迁移零写入。App 不使用 CLI 迁移。
新增或改值以及增加重复次数需本次精确能力证据；未改值排序和删除可保留 Unknown 原值。桌面与 setup 共用原有锁/hash/replace/readback 事务。列表消费由后续票实现。

## v7：有序 review 候选与厂商手动覆盖

显式 v6→v7 仅增加空 `model_families` 并更新版本；show/probe 不迁移。v6 空 candidates 的单模型路径继续有效。App 保持 v5，不增加字段。
四格 candidates 保持 ModelTriple 有序列表，允许重复；新增或增加重复次数、改值须当前精确能力，排序/删除/仅声明变更无需构造新能力。删除候选不删除声明。
`model_families` 为 `{agent: {native_model: {family, source: "user_declared"}}}`。family 使用小写 ASCII slug（字母数字段以单个连字符连接）。默认按内置厂商对照表判断，手动声明覆盖：覆盖只按精确 agent/native model 检索，不看 effort；未声明时取模型代号最后一段、去掉 `@` 后缀、转小写后按前缀查表，未命中为 Unknown。仅影响有候选的整体交付检查选择。声明由 AI 助手维护，仅为用户证据，不是外部认证。候选与声明共用 canonical apply/configure 原子事务。

新声明必须对应当前 work/review（含 fallback/candidate）引用的精确身份；已有声明可在删除候选后继续保留和维护，不接受新清单外身份注入。

`preview-review --candidate <file> --evidence <file>` 只读预览当前草稿。证据沿用 `probe` 的
`request_id`、`observed_at`、`sources`、`capabilities`；缺完整核对证据时报错。
仅返回整体交付检查中有候选的轴，每轴含 `selected`、`selected_index`、`outcome`、`unrecognized`。
`outcome` 为 `different`、`no_different_family`、`unrecognized` 或 `none_runnable`；
无可运行模型时选择与索引均为 null。写代码一方取设计、前端、后端主模型，运行时则取实际执行身份，
所以预览按当前设置推算，可能与备用接替后的结果不同。预览与运行时共用同一选择规则。

## v9：任务类型目录与用途约束（DD-684）

CLI v9 将 `work` 改为用户可维护的任务类型目录，每个 key 即任务类型 id：

- **标识规则**：id 必须为小写 ASCII slug（`[a-z0-9]+(?:-[a-z0-9]+)*`），禁止保留词 `review`、`map`、`all`。
- **条目结构**：每项精确定义 `{agent, model, effort, fallbacks, label, hint, purpose}` 七个字段，缺字段或多字段均拒绝。`label` 为非空且非 `Unknown` 的字符串；`hint` 为非 `Unknown` 字符串；`purpose` 属于 `planning | code | artifact | checks | advisory` 五种受限用途之一。
- **必需用途底线**：`work` 中 `planning`、`code`、`checks` 三类用途各至少保留一项；删除最后一个必需用途时校验与 `apply` 均拒绝且磁盘原字节不变。
- **内置 5 项默认元信息**（用于 v6–v8 内存规范化与升级到 v9）：
  - `planning`：显示名 `规划`，说明 `拆需求、定方案`，用途 `planning`
  - `design`：显示名 `设计`，说明 `界面与交互`，用途 `code`
  - `frontend`：显示名 `前端开发`，说明 `写页面代码`，用途 `code`
  - `backend`：显示名 `后端开发`，说明 `写服务端代码`，用途 `code`
  - `testing`：显示名 `测试`，说明 `写测试并验证`，用途 `checks`
- **只读兼容与原子升级**：CLI v6–v8 仍通过 `validate_document`，内存经 `normalize_work_entries` 补齐默认元信息；`show` 只读不改字节与 hash，v9 时 `cells` 按当前 `work` 键动态生成；`migrate` 与 `apply` 经同一 sidecar 锁/hash/replace/readback 原子事务升级到 v9，重复迁移返回 `changed: false` 且零写入。App 配置保持 v5 不变。
