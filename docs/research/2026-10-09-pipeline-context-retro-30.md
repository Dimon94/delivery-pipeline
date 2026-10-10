# 最近 30 个 Pipeline 地图或 Spec 的上下文复盘

复盘日期：2026-10-09 20:38 PDT。仓库：`Dimon94/delivery-pipeline`，当前本地 HEAD `3f3c5d0`。

结论：按可复算的可见文本口径，**明确识别的调度内容约 6.0%；协调器约 17.7%**。这不是完整模型窗口占比。
污染更集中在长寿命协调器的恢复摘要、重复合同加载、回读和机器工件展示。优先控制这些入口；只继续缩短 packet 解决不了摘要重新膨胀的问题。

## 统计能说明什么

- 以本机原始运行记录的最后活动时间降序，按项目 + map/spec 根坐标去重，取前 30 个有可确认 pipeline 运行坐标的根目标。Spec 属于已纳入 map 时合并，例如 #1522 → map #1262；iCaCal 的内部 spec lane 合并到 map #58。
- 样本覆盖 2026-09-16 至 2026-10-09（America/Los_Angeles）的最后活动时间；使用这些目标关联会话的完整存量历史，而非只截取这段日期的消息。包括 1435 份独立日志：Codex 298、Pi 1070、Claude 67。Orca/Herdr 是 transport，运行记录仍归实际 worker runtime。
- 原始来源：Codex 只读 SQLite 索引与 rollout，Pi/Claude JSONL，以及 `~/.config/delivery-pipeline/lanes/registry-*.md`。Nowledge 线程检索返回 Connection refused，未以记忆替代原始证据。远端主机、云端、已删除日志及未关联记录的覆盖为 Unknown，不能称全球最新 30 张。
- 分母是日志可见文本的 `o200k_base` 估算量：系统正文（日志实际可读部分）、消息、调用参数、工具返回、可读压缩摘要。不是每次 API 输入量之和，也不是当前窗口或账单。排除重复 event 镜像、turn_context 元数据、图片/音频编码、隐藏思考与 encrypted compaction；replacement_history 的持留旧消息不作为新增文本再计。
- 多模态 ContentBlock 先解包再统计 text。PNG Base64 不能按普通文本 token 计算。工具不可见 schema、Claude 未记录的系统正文、图片实际输入量和加密摘要为 Unknown。
- 同一业务会话内部的额外用户工作没有逐回合人工切片；按持久坐标关联整段会话。这会影响分母。样本仍在运行，逐文件扫描不是原子快照。
- “明确调度”由 `measure.py` 中合同/helper 调用意图和短行控制字段识别；不把整份 Spec、代码、测试或混合摘要自动判为调度。正则分类存在漏识别和误识别，**6% 是操作性估算，不能宣称真实下界或统计置信区间**。

| 口径 | tokens | 比例 | 含义 |
|---|---:|---:|---|
| 全部可见文本 | 252,893,602 | 100% | 累计可读文本，已排除媒体编码和事件镜像 |
| 明确识别的调度内容 | 15,145,389 | 6.0% | 合同、helper、控制字段等 |
| 其中合同/helper 整块 | 10,162,951 | 4.0% | 包含脚本源代码和机械接口说明 |
| 含调度标记的整块内容 | 168,726,452 | 66.7% | 混入业务、源码、测试与历史，**不能当纯调度占比或浪费比例** |

全地图“明确调度”比例中位数为 6.8%；地图规模不同，总体比例按文本量加权。
没有证据支持“pipeline 只花 6%”或“其余标记内容全部可以删”。真正的完整窗口归因仍是 Unknown。

角色归属由首次提示与任务坐标推断，仅用于分层观察：

| 会话类型（推断） | 日志数 | 可见文本 tokens | 明确调度 tokens | 比例 |
|---|---:|---:|---:|---:|
| 协调器 | 31 | 26,615,039 | 4,703,020 | 17.7% |
| 执行及其他任务 | 954 | 171,625,621 | 9,028,214 | 5.3% |
| 可识别的审查任务 | 450 | 54,652,942 | 1,414,155 | 2.6% |

Codex 日志另有宿主输入计数：累计 input 3,829,020,604，其中 cached input 3,736,920,576。
这是跨请求反复输入的宿主读数，不能与上表相加，不能据此推导 pipeline 账单或上下文分类。

## 冗余候选，按影响排序

### 1. 高：恢复摘要携带历史过程，成为新的大上下文

可读压缩摘要共 526 段，累计约 4,433,080 tokens，中位数 4,509。
#1725 的一段达到 **52,131 tokens**，#1062 达到 **48,069 tokens**。这两段都是业务与调度混合内容，不能把其全部计入可删冗余；但单段体积已说明污染入口。

证据：

- [#1725 摘要原文](/Users/dimon/.pi/agent/sessions/--Users-dimon-.herdr-worktrees-app-studio-map-1725--/2026-10-01T04-42-01-628Z_01a0f5c4-f81c-7204-86a7-9d5c8bc58559.jsonl:5487)。同一日志有多段 4.6–5.2 万 token 摘要。
- [#1062 摘要原文](/Users/dimon/.pi/agent/sessions/--Users-dimon-02-Work-10-Projects-worktrees-app-studio-map-1062--/2026-09-30T17-42-18-815Z_01a0f368-fbbf-72d9-8c33-7c0e82805a68.jsonl:5223)。后续摘要仍携带大量历史执行与恢复内容。

建议：使用已存在的 6 项恢复模板保存当前 gate、active writers、现场、未决约束与一个下一动作。
已消费 lane、旧失败尝试、已过期模型请求、已完成检查只保留证据指针；独有业务约束和用户决定留在当前权威源。
自然 gate 完成后允许以既有恢复合同重建协调器上下文。**staged worker 仍沿原 task/session 接续**，不改变 ADR 的同会话切换与单写者边界。
初始建议目标为恢复正文 1–2k tokens，先回放 #1725/#1062 的恢复判定；这是待验证目标，未宣称节省率。

### 2. 高：worker 加载与自身职责无关的完整调度合同

当前 App 的核心入口、App 壳、development-mode 与 dispatch 四份文件整读约 **12,047 tokens**。
其中 development-mode 单份约 5,490，混合 coordinator 分工、配置 schema、staged 接续、legacy、planning、内部辅助和咨询。
[每次调用规则](/Users/dimon/01-Personal/10-Projects/delivery-pipeline/skills/delivery-pipeline-codex-app/references/development-mode.md:64)
要求 worker 完整读当前入口，容易让 direct implementation 也载入接续/恢复和其他角色分支。
这与 canonical 的“仅加载当前分支”目标存在张力。

读取语法审计中，development-mode 出现在 151 个调用块，同会话首次以外 107 个；单个 Bebobo 协调器有 30 个调用块。
这些是 literal path + 读取语法的命中，包含片段读取、混合命令和合法恢复，**不等于 107 次可删除整读**。
[实际读取样例](/Users/dimon/.codex/sessions/2026/09/29/rollout-2026-09-29T09-36-33-01a0ee06-6cee-72b2-baea-f300905f80b8.jsonl:1881)。

建议：保留现有文件和唯一规则源，明确按 coordinator / direct worker / staged worker / reviewer 的章节入口读取。
模型解析、配置迁移、legacy、完整 helper 参数说明由实际 caller 按分支加载；worker 接收已核验的当前请求与必要验收指针。
权限、真实模型 readback、owner、实施前置和终态通知仍保留；不把验证职责仅写进 prompt。
没有必要增加一批新 skill 或复制一套 worker 规则。

### 3. 中高：helper/API/历史回读放大控制过程

机械合同/helper 整块已占约 4.0% 的可见文本；读取脚本源码、配置和机器工件会继续诱导模型学习运行机制。
读取语法命中 checkpoint.py 515 个调用块、prewalk.py 357 个，其中单会话 prewalk.py 命中最高 81 个；混合命令也可能只执行 helper，因此不作为实际整读次数。
调用块还包含 wait_threads 631、read_thread 209、list_threads 185 个命中。正常等待、startup/readback、用户显式监控都可能必要，未把这些计数统称无效轮询。

建议：沿现有 helper 做机器校验，展示 status、expected/actual 差异与原工件指针；失败时定位原错误。
helper 的实现源码仅在诊断工具失败或修改 helper 时读取。配置用现有 models/resolve 查询；保持已存 overlay 的恢复语义。
恢复/终态优先用有 cursor 的简短快照，取原始历史只为定位尚未解决的事实。
已有大 JSON/checkpoint/ignored 清单留在机器工件，使用字段提取，不再次整读。

### 4. 中：短模板已有静态门禁，运行输出仍可再次膨胀

当前 `ffd7b28` 已落地派发 10 项、终态 8 项、恢复 6 项；三个壳只补 transport 坐标。
前一份审计已记录约 64% 的壳模板正文缩减，这是静态文件效果。大多数本轮历史会话运行在旧合同下，不能当新模板的 A/B 验证。

[check_handoff_contract](/Users/dimon/01-Personal/10-Projects/delivery-pipeline/scripts/validate.py:596)
只验证模板字段、顺序和规则存在，未验证真实生成 packet、恢复摘要或 helper 返回的体积。
因此通过 validate 不保证模型没有继续复制 Spec、旧 FINAL_REPORT 或机器 JSON。

建议：后续在现有检查中增加真实派发/终态/恢复样例的文本体积与分支校验，用超长回读/嵌入旧报告作消融。
不重新设计字段或增加运行 ledger；先验证下一张新地图的生成正文与恢复能力。
体积限额应允许独有约束说明，不能通过截断权限、失败证据或未决事项来过线。

### 5. 低：全局文案和 AGENTS 不是本仓主要来源

本仓 AGENTS 约 784 tokens，Codex 全局 AGENTS 文件为空。当前证据不支持先围绕本仓 AGENTS 大改。
DRI、Tactical/Strategic、Pit of success 等解释性段落可在后续定点编辑时合并到可执行步骤，收益较小。
跨仓业务标准、全部技能目录和工具 schema 还有基线成本；没有把它们全部归罪于 pipeline。

## 最小精简策略

继续使用现有链路与工具，只改变送进模型的材料：

1. coordinator：核心入口一次 + 当前 gate/transport 必要章节；批次间使用状态增量。
2. worker：本票范围/验收、owner、现场/权限、当前执行分支、证据与回传坐标。
3. 恢复：既有 6 项模板；历史只作可追溯指针，读取由当前缺口触发。
4. 机器：完整 registry、checkpoint、readback、review bundle 继续持久化并由 helper 校验。

双轴独立审查、候选 head/fixed point、实施前置、单写者、Unknown、失败证据与发布授权是能力边界。
压缩应改变展示和按需加载，不取消这些边界。本次产出复盘和可复算证据，**未修改调度规则或 runtime helper**。

## 30 个样本

按采样时本机最后活动排序；日期为 America/Los_Angeles。表中比例采用明确识别口径。

| Map/Spec | 最后活动 | 日志数 | 可见文本 tokens | 明确调度 tokens | 比例 |
|---|---|---:|---:|---:|---:|
| bebobo-ai-project-template/map-1 | 10-09 20:23 | 12 | 7,160,590 | 1,389,004 | 19.4% |
| app-studio/map-1725 | 10-09 20:23 | 87 | 30,682,890 | 2,027,656 | 6.6% |
| app-studio/map-1850 | 10-09 20:04 | 20 | 4,198,730 | 178,584 | 4.3% |
| app-studio/map-765 | 10-09 20:14 | 61 | 10,163,983 | 370,931 | 3.6% |
| app-studio/map-1262 | 10-09 06:34 | 287 | 50,777,520 | 3,246,482 | 6.4% |
| app-studio/map-1977 | 10-09 01:15 | 7 | 1,082,043 | 102,864 | 9.5% |
| app-studio/map-1958 | 10-09 00:07 | 7 | 2,520,644 | 217,573 | 8.6% |
| app-studio/map-1062 | 10-08 05:32 | 347 | 57,663,535 | 3,206,444 | 5.6% |
| app-studio/map-1917 | 10-08 02:01 | 6 | 1,282,015 | 135,969 | 10.6% |
| refresh/map-258 | 10-07 23:05 | 133 | 17,273,657 | 194,025 | 1.1% |
| comic-drama-studio/map-187 | 10-07 16:49 | 44 | 19,403,292 | 526,689 | 2.7% |
| app-studio/map-1699 | 09-30 05:22 | 1 | 692,479 | 235,434 | 34.0% |
| pagugu/map-57 | 09-29 07:48 | 1 | 306,308 | 57,181 | 18.7% |
| app-studio/map-1629 | 09-29 00:17 | 29 | 1,547,542 | 58,442 | 3.8% |
| app-studio/map-1439 | 09-27 22:49 | 53 | 6,576,535 | 459,560 | 7.0% |
| creator-ops/spec-32 | 09-26 19:36 | 32 | 2,928,672 | 371,611 | 12.7% |
| creator-ops/map-1 | 09-25 21:42 | 5 | 335,621 | 55,567 | 16.6% |
| app-studio/spec-1381 | 09-23 21:50 | 52 | 7,004,766 | 495,000 | 7.1% |
| app-studio/spec-1254 | 09-21 01:35 | 6 | 600,936 | 54,781 | 9.1% |
| app-studio/map-795 | 09-21 00:05 | 24 | 2,780,428 | 43,000 | 1.5% |
| codex-with-chatgpt/map-1 | 09-20 17:30 | 2 | 1,950,809 | 201,844 | 10.3% |
| app-studio/map-823 | 09-19 18:59 | 38 | 4,393,605 | 83,251 | 1.9% |
| multica-delivery-pipeline/map-1 | 09-19 18:04 | 1 | 457,262 | 75,954 | 16.6% |
| iCaCal/map-58 | 09-19 09:42 | 9 | 809,610 | 148,952 | 18.4% |
| delivery-pipeline/map-114 | 09-18 02:45 | 37 | 7,967,867 | 957,310 | 12.0% |
| app-studio/map-832 | 09-18 00:41 | 14 | 1,062,819 | 11,652 | 1.1% |
| app-studio/map-784 | 09-17 21:07 | 58 | 4,564,622 | 94,672 | 2.1% |
| app-studio/map-814 | 09-17 14:29 | 39 | 2,948,211 | 54,617 | 1.9% |
| app-studio/spec-842 | 09-17 05:46 | 19 | 3,391,151 | 82,815 | 2.4% |
| app-studio/map-794 | 09-16 02:28 | 4 | 365,460 | 7,525 | 2.1% |

## 复算、验证与限制

复算入口：

```sh
python3 .scratch/retro-context-30/index.py
.scratch/handoff-token-audit/venv/bin/python .scratch/retro-context-30/measure.py
.scratch/handoff-token-audit/venv/bin/python .scratch/retro-context-30/findings.py
python3 scripts/validate.py
```

脚本缓存以本次日志快照为依据；重采样应使用新的输出目录，避免把后续追加事件与旧缓存混用。
[汇总统计](/Users/dimon/01-Personal/10-Projects/delivery-pipeline/.scratch/retro-context-30/summary.json)、
[聚合与角色统计](/Users/dimon/01-Personal/10-Projects/delivery-pipeline/.scratch/retro-context-30/aggregate.json)、
[调用与摘要证据](/Users/dimon/01-Personal/10-Projects/delivery-pipeline/.scratch/retro-context-30/findings.json)
保留原日志路径和行号。tokenizer 复用此前审计 venv 的 tiktoken 0.14.0，未安装项目依赖。

- 自检 PASS：30 个唯一根目标，1,435 个独立 session/agent 坐标；分类边界成立；多模态编码不进入文本计数。
- `python3 scripts/validate.py` 首次因 watcher 测试复用 `/tmp` 的两个旧去重 marker 失败，和本次分析改动无关。
  仅将对应 fake lane 的两份 marker 临时隔离，运行同一命令后 **bundle: pass**；finally 原位恢复，前后 SHA256 一致。
  [完整通过日志](/Users/dimon/01-Personal/10-Projects/delivery-pipeline/.scratch/retro-context-30/validate-isolated.log)
  与 [隔离/恢复证据](/Users/dimon/01-Personal/10-Projects/delivery-pipeline/.scratch/retro-context-30/validate-fixture-isolation.json)。
  测试本身的全局临时文件污染是独立低优先级机械问题，建议以后让测试使用独立 lane ID/目录，本次未修。
- 已有 pre-commit 与 CI 都运行 validate；没有建议重新造一套缺失的 gate。
- 当前 App models.json 与 check_prewalk.py 的用户改动保留。未提交、推送、建 PR，也未派发新业务 lane。
- 精确模型窗口比例、账单节省、远端覆盖、新策略真实分派与恢复保持能力均为 Unknown。
