# 模型任务路由

本文件定义核心链路如何消费配置并启动 worker。配置 schema（version 5、任务类型、
命名 mode 覆盖预设、review 矩阵、transport 必需集）的唯一权威是
`model-config-schema.md`；各 transport 壳共用同一 schema，调度细节在各壳内。

## 配置实例与验证

CLI 实例路径：`~/.config/delivery-pipeline/model-roles.json`，version 5，由
`delivery-pipeline-setup` 写入并 readback。旧 version 2/3/4 配置不再被直接消费：dispatch 遇到
旧版本时阻塞并运行 `scripts/model_config.py migrate`（机械迁移）或重跑 setup。结构验证：

```bash
scripts/model_config.py validate ~/.config/delivery-pipeline/model-roles.json
```

CLI 实例必需 `work` 中的 `planning`、`design`、`frontend`、`backend`、`testing` 与完整
review 矩阵；entry 与 review 轴的 agent 属于 `pi|codex|claude`；CLI 实例禁止
`default_mode`。除结构外，所有 startup（含非实现任务
的一次启动）都要求当前 capability evidence：binary 存在、model/effort 命中实时探测；
没有 evidence 的计划只能解析，不能生成启动请求。

## 任务类型映射

选择或配置任务类型时读取 `frontier-lanes.md` 的 Task Binding 表；该表统一定义工作、
任务类型与 output mode。当前 coordinator 会话不属于任何 work 项；它使用启动时已经选择的
agent/model，`work.coordinator` 若定义仅作推荐观测。

lane 直接使用 work 项的 `{agent, model, effort}` 单轮直跑。ticket 或 map 显式点名 `modes`
中的命名预设时，用该 mode 对应 lane agent 的 `direct` 组整体覆盖；mode 缺该 agent 计划即阻塞。
解析出的 mode 名（默认 none）、source、agent、model、effort 冻结到 packet 和 lane registry，
再启动 worker。旧票据遗留的 `staged`/`direct` 字面值不是合法 mode 名，遇到即阻塞并要求用户
显式选择。已有 lane 只按 registry 恢复，不重新解析新配置。

配置只绑定 lane 启动参数。Lane 启动后用户在 worker pane 中改 model/effort 属正常操作：
coordinator 不做运行中或 fan-in 的 pane model 对账，不把 pane 实际 model 与 registry 不符
当作 setup 失败，不因此重建 lane、回写配置或拒收交付；fan-in 只验收持久交付证据。

review lane 用配置 `review.<scope>.standards` 的 `{agent, model, effort}` 启动 pane；
packet 携带该 scope 的 standards/spec 两轴模型配置，交给 resolved code-review owner 使用。

setup/dispatch 可把实时探测归一化为 `{ "pi|codex|claude": { "binary": true,
"models": { "<model>": ["<supported-effort>"] } } }`，交给
`model_config.py resolve ... --output-mode commit --evidence`。
缺 evidence、binary、model 或所选 model 不支持该 effort 时返回阻塞。
`model_config.py freeze ...` 输出同一冻结 overlay，coordinator 将其写入既有 packet 与 lane
registry 后必须用 `verify_overlay` 精确 readback 校验，缺项、空值或不匹配 fail-closed；它不是
第二套配置或 registry truth。

## Capability Evidence

| agent | evidence 来源 |
| --- | --- |
| pi | `pi --list-models` 的 provider/model 与 thinking 支持 |
| codex | `codex debug models` 的 `models[].slug` 与 `supported_reasoning_levels[].effort` |
| claude | `~/.claude/settings.json` 的 `env`：`ANTHROPIC_DEFAULT_FABLE_MODEL`、`ANTHROPIC_DEFAULT_HAIKU_MODEL`、`ANTHROPIC_DEFAULT_OPUS_MODEL`、`ANTHROPIC_DEFAULT_SONNET_MODEL`、`ANTHROPIC_MODEL`、`CLAUDE_CODE_SUBAGENT_MODEL`（显示名 `*_MODEL_NAME`，effort `CLAUDE_CODE_EFFORT_LEVEL`） |

缺失 binary、文件或字段记 Unknown。Setup 只允许从这些 `*_MODEL` / `ANTHROPIC_MODEL` /
`CLAUDE_CODE_SUBAGENT_MODEL` 候选中选择 Claude model；校验时 Claude 必须匹配
settings.json env 候选与 CLI effort 枚举。

启动参数（含 kind-specific permission，纳入 trusted execution bootstrap）只由
`model_config.py start` 从冻结计划生成，不从 coordinator 模型推断；registry 必须先于 worker
写入并 readback。既有 lane 的恢复与 replacement 使用所属壳 dispatch 合同的“恢复与切换”。
