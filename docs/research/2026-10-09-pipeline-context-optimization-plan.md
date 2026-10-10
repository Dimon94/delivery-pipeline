# Pipeline 上下文优化方案与 token 情景估算

日期：2026-10-09。坐标：`Dimon94/delivery-pipeline`，本地 HEAD `3f3c5d0`。
状态：方案与容量评估；尚未修改运行合同、配置或调度行为。
基础样本与原始证据见 [30 张地图复盘](2026-10-09-pipeline-context-retro-30.md)。

建议先做四项：**按分支加载、短恢复记录、helper 结果投影、真实输出检查**。
目标是让模型处理当前 work item 和必要证据，让机器继续处理完整核验输入。
按本次能单独核算的历史块，中性情景净省约 **122 万 tokens**；保守到顺利情景约 **66–190 万**。
这相当于 30 张样本累计可见文本的 **0.26%–0.75%**，不是 API 输入或账单节省率。
单次 App worker 的调度入口目标由约 12k 降至 2.5–3.5k；局部窗口的改善会明显大于全历史比例。

## 1. 保留的能力与边界

- Owner 三字段与完整 Owner SKILL.md；实施前置、spec/tickets/sizing 和仍适用的用户确认。
- 一项一 lane、一 Execution Worktree、一个 active writer；真实 Git/base/HEAD/dirty 与冻结计划。
- Standards/Spec 独立审查、正确 scope/fixed point/候选 head、完整 Review Evidence Bundle；新 head 仍使旧结论失效。
- helper 对完整机器工件的核验、expected/actual、失败原文和证据来源。指针可读不等于 PASS。
- Unknown、未决业务约束、用户决定、错误处理、tracker authority 与独立的远程发布授权。
- staged worker 沿原 task/session 接续，direct/staged 选择与模型配置保持现有权威。

省去的是其他角色分支、已消费历史、机械清单的展示和无需诊断的 helper 源码读取。
需要的原证据仍读取。体积目标不通过截断权限、未决事项或失败证据达成；无法满足时保留内容并记录原因。

## 2. 执行方案

### P0-A：把完整调度入口改成按角色、阶段和操作加载

复用现有文件与唯一规则源，不增加一批 worker skills 或新的配置层。

| 消费者 | 默认加载 | 条件触发 |
|---|---|---|
| coordinator | core/所属壳入口、当前 gate、恢复坐标 | 新分派读配置/dispatch；终态读 fan-in；异常读对应失败分支 |
| direct implementation | canonical Worker 共同行为、完整 owner、本票 scope/验收、所属壳执行与终态章节 | 首次写入读实施前置；需要内部辅助读其权限/模型/并发入口 |
| staged implementation | direct 共同行为 + 当前 starting/executing 阶段 | checkpoint/prepare 的 caller 读取对应输入合同；同 task 接续 |
| reviewer | 完整 review owner、scope/fixed point/head、不可变 bundle、只读约束 | 只有其实际调用的内部辅助才读 subagent 入口 |
| planning/testing/integration | 完整本 role owner 与 output-mode 证据 | planning 用户确认、checks、Integration 写边界各自加载 |

触达：`delivery-pipeline/references/lane-registry.md` 的 Worker 共同行为；App
`references/development-mode.md`、`references/codex-app-dispatch.md` 与 `SKILL.md` 的直接入口；
三个壳的 packet 指针。共享语义留 core，runtime 章节留原壳；Orca 的能力与授权 preflight 保留。
尤其修订 App “worker 完整读这些当前入口”的加载要求，仍要求当前 realpath 与完整 owner，
避免 core 的“当前分支”规则被壳入口重新扩大。

同一未压缩窗口内，未变化合同沿已读内容使用；事实、版本、权限或当前分支变化时重读。
压缩后的上下文是否保留规则需核验，不能用磁盘上“曾经读过”的标记跳过冷启动必读内容。

验收：direct 不加载 staged/legacy/创建/归档分支；staged 保留接续合同；reviewer 保留独立性与证据输入。
用现有固定字段检查验证加载指针和分支，检查真实首次启动的读文件清单。

### P0-B：用当前状态恢复 coordinator，消除历史摘要反复增长

复用 lane-registry 的六项恢复模板。恢复正文目标 **≤2k tokens**，保留当前 gate、全部 active writers、
base/HEAD/dirty、未决决定与约束、通过/失败证据指针、一个下一动作。
已消费 lane 的过程、旧失败尝试、过期模型请求、完成检查的日志正文回到既有 tracker/artifact。
当前权威源没有保存的独有业务事实先持久化到既有对应源，再从恢复正文移除。

触达：core `references/fresh-session-boundaries.md`、`references/lane-registry.md`，
以及各壳已有恢复 caller。新 coordinator 恢复时核验全部 active writers，避免重复分派。
普通恢复预留 **2k** 当前 gate 证据读取量，故容量模型按 **4k** 合计保留。

这项依赖 runtime 的可控恢复/压缩入口。Pi/Codex/Claude 是否能约束内置摘要的执行路径仍为 **Unknown**；
先做入口能力验证。只有已有恢复、重启或可控压缩点使用短记录；App 新建会话仍需相应授权。
不强制改写宿主加密摘要，也不为了节省 token 给 staged worker 换任务。
宿主不受控时，该部分收益降低，不能以多写一条“摘要要短”视为实现。

验收：回放 #1725/#1062 的一次恢复，得到相同的 active writer 判定、最早未完成 gate、
阻断/确认与下一动作；当前业务约束、原失败和审查版本均能从指针恢复。
这里要求核验行为相同；本次容量计算尚未完成这项语义验证。

### P1：helper 校验完整数据，向模型返回必要字段与差异

成功返回以 **≤500 tokens** 为普通目标：动作/status、需要原样发送的请求参数、
expected/actual 差异、持久结果路径；错误保留原原因与失败工件，不按成功预算截断。
完整 checkpoint、overlay、fingerprints/ignored 清单与 checks 留在既有工件，机器完整读回。
已有 JSON 接口默认输出与指纹算法保留，展示裁剪落在消费端，先验证文件持久读回再展示。

触达：checkpoint/prewalk/model_config 的实际 caller，以及各壳 packet 的机械核验指针。
已有 `models/resolve/prepare/review` 查询用于正常执行；helper 实现源码只在修改、工具异常诊断时读取。
源码的普通接口/结果导航目标 **≤250 tokens**，完整源仍可按需读取。
delivery-pipeline 自身开发和审查需要读源码，不能按执行冗余删除。

历史回读沿已有 compact snapshot + cursor；只有待消歧事实才读原线程。
权限、并发、startup/readback、终态取证和用户明确监控仍执行；调用次数不是无效轮询的判据。

验收：同一输入的完整机器结果与原判据不变；模型获得下一动作所需全部字段。
失败时保护现场不变；Unknown 不转换为 PASS；旧 callers 不因展示优化失去字段。

### P1：把短模板检查延伸到真实产物

派发 10 项、终态 8 项、恢复 6 项已经落地，不重设计字段。
在 `scripts/validate.py` 的现有 `check_handoff_contract` 附近增加少量实际展开样例：
当前分支的信息完整，不嵌套旧 packet/FINAL_REPORT，不展示整份机器清单；独有约束显式保留。
用超长旧报告作为消融输入，证明剥离背景后仍能定位原验收证据。
token 容量沿本地既有审计环境测量，不为 CI 新增 tokenizer 依赖或另一套 ledger。

验收：`python3 scripts/validate.py` 通过，且下一张新地图的真实 packet/恢复/读文件清单符合当前分支。
该项主要防止优化回退，收益与前三项重叠，**不单独加 token**。

## 3. 节省量如何计算

分母仍是上一轮冻结统计的 **252,893,602** 个日志可见文本 tokens，tokenizer 为 `o200k_base`。
没有将 Codex 跨请求 input/cached input、文件磁盘容量、图片编码或旧模板静态缩减加进来。

本次重新按 tool-use/call ID 配对原始返回，并匹配冻结记录的行号、正文 SHA-256。
仅计直接文件读取与能明确识别的简单 shell 调用；JS/批量混合读回、业务代码/spec、
不可读压缩、delivery-pipeline 自身合同/源码开发读取不计。
同名工具并行调用逐 ID 配对，避免把邻近业务返回算成合同。
角色与 map 归属仍沿上一轮推断口径。

| 互斥候选 | 块数 | 原可见 tokens | 容量目标 | 全部适用时的容量差 |
|---|---:|---:|---|---:|
| 纯合同读取返回 | 939 | 1,391,618 | 单份 worker 文档相关章节 1k；coordinator 2k | 376,797 |
| 其他业务地图中的 helper 源码读取 | 396 | 431,571 | 单份导航/接口 250 | 348,672 |
| 可独立配对的简单 helper 返回 | 25 | 6,634 | 必要字段 500 | 2,269 |
| 可读 coordinator 恢复摘要 | 79 | 1,914,567 | 短记录 2k + 当前 gate 证据读取 2k | 1,612,128 |
| 合计 | 1,439 | 3,744,390 | 小于目标的块原样保留 | **2,339,866** |

公式：`容量差 = Σ max(原块 tokens − 本类保留预算, 0)`。
它是这些候选在目标全部可达时的算术差值，**不是全 pipeline 的可省上限，也不是已验证的可删冗余**。
每一块只归一个类别；合同缩减、少读源码、去重不再次相加。
可读摘要含业务事实，只有完成持久化与等价恢复的部分才适用。

为了折算未适用分支、必要全文、宿主不受控与额外加载，设三个透明情景：

`净节省 = 容量差 × 可达覆盖率 × (1 − 额外加载抵销比例)`。

覆盖率作用于候选容量差；额外加载包括诊断、例外与超出预算的重新读取。
**40%/65%/90% 与 30%/20%/10% 是评估假设，不是历史测得的概率或置信区间。**

| 情景 | 可达覆盖率 | 额外加载抵销 | 净省 tokens | 占全历史文本 |
|---|---:|---:|---:|---:|
| 保守 | 40% | 30% | **655,162，约 66 万** | **0.26%** |
| 中性，作为首轮预算参考 | 65% | 20% | **1,216,730，约 122 万** | **0.48%** |
| 顺利 | 90% | 10% | **1,895,291，约 190 万** | **0.75%** |

66 万不是保底，190 万不是全量上限；实际可达率和额外加载成本不同，结果会随之变化。

中性情景：短恢复约 **83.8 万**，合同分支加载约 **19.6 万**，helper 源码/返回约 **18.2 万**。
约 77% 的收益集中于 #1725/#1062；不能按每张新地图都同样省来外推。
约 88.3 万分配到已识别 coordinator 历史，相当于其可见文本的约 3.3%；这是累计量，仍非单次窗口比例。

### 单次窗口可改善多少

当前 App core/壳/development-mode/dispatch 四份文件全读 **12,047 tokens**。
直接从现有权威章节取 Worker 共同行为、执行核验、独立审查边界、终态回传，基础正文 **1,637**；
再加当前 staged 接续章节为 **2,538**。这些是章节容量测量，尚未证明能替代完整加载。
为参数来源、实施前置、当前阶段和导航保留额外空间，建议目标如下：

| 入口 | 当前四文件容量 | 优化目标 | 单次容量差 | 局部降幅 |
|---|---:|---:|---:|---:|
| direct worker | 12,047 | 2,500–3,500 | **8,547–9,547** | **71%–79%** |
| staged worker | 12,047 | 4,500–5,500 | **6,547–7,547** | **54%–63%** |
| #1725 一次长恢复 | 52,131 | 记录/首轮证据合计 4,000 | **48,131** | **92%** |

owner、业务 spec、代码和必要测试输入另计。不是每个当前 worker 都全读这四文件，
也不是每个分支都能降到目标；以上用于设计加载入口，**不乘以会话数加入总节省**。
#1725 的 92% 依赖短记录可控且证据重建在预算内，不能泛化到所有恢复。

## 4. 顺序、最小验证与停止条件

1. 先验证 coordinator 恢复入口的可控性，回放 #1725/#1062；无可控入口时把该项收益移出可达部分。
2. 调整现有分支指针与真实 caller，检查 direct/staged/reviewer/恢复四条路径，保持完整 owner 与必需证据。
3. 调整 helper 消费端的持久化与结果投影，检查一个成功、一个失败/Unknown；不改指纹或配置。
4. 用现有 validate 加真实输出样例防回退；观察下一张新地图，计首次加载、恢复、回读及例外成本。

首轮做到上述范围即可，不扩成全 runtime 重构、全量 benchmark 或自动预算控制系统。
如果短输入引起更多读回、丢失决定或误判 PASS，恢复该分支原加载路径，修复指针/证据后再测。
实测至少同时记录：累计可见控制文本、一次启动/恢复加载量、额外重读量、恢复/审查正确性。
不以缩短必要测试、减少独立审查或限制验收修复次数换取 token。

## 5. 本次交付与限制

已完成：本方案、严格配对的容量估算、重叠与总量自检、章节容量测量。
重算：`.scratch/handoff-token-audit/venv/bin/python .scratch/retro-context-30/estimate.py`；
产物：`.scratch/retro-context-30/estimate.json`、`entry-capacity.json`。
审计脚本包含同名并行工具配对、混合读取排除与块唯一性 self-check。

验证结果：估算 self-check、报告数值/比例核对通过；`python3 scripts/validate.py` 返回 0，
`bundle: pass`。沿上一轮已定位的 watcher fixture 污染，运行前仅暂存两个固定 `lane` 测试标记，
运行后逐字节恢复，SHA-256 前后相同；未修改 watcher 或业务 lane。
日志：`.scratch/retro-context-30/validate-plan.log`、`validate-plan-isolation.json`。
`git diff --check` 通过；用户既有 models.json/check_prewalk.py 改动保留，未提交或推送。

待执行：分支合同调整、runtime 恢复入口验证、历史语义回放与新地图实测。
JS/复杂混合输出中的额外收益、加密摘要、API 多次复用输入与缓存计费变化均为 **Unknown**。
本次只能给可复算的容量情景，不能承诺美元成本或时延同比例下降。
Nowledge 定向线程检索连接失败；继续使用本机原始日志和仓内当前合同，未用记忆填补证据。
