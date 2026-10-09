# App Studio 十张近期地图的交接 token 审计

结论：主要负担是完整机器快照和回读副本进入上下文，其次是重复背景和不适用字段。
文件指纹、component/checkpoint SHA256、ignored 指纹清单退出交接正文；机器工件仍由 helper 校验。
base/head/交付 commit 的 Git SHA 保留为审查、恢复和 Integration 的版本坐标。

## 口径与样本

- 2026-10-09 检查。以 GitLab `wayfinder:map` 的 `updated_at` 降序，选本机能找到 pipeline
  packet/registry/map 工件的前十张。统计这些地图的**存量历史产物**，不只最近一轮。
- #1927、#1971、#1344 的本机 map 命名坐标未命中；跳过不表示它们没有其他运行记录。
  未将独立 Spec #1910 强行归属地图，也未审计其他仓库。
- 扫描 `~/.config/delivery-pipeline/{packets,lanes,artifacts,checkpoints,review-bundles,review-evidence,reports}`
  及其中 lanes 子目录、`~/.codex/delivery-pipeline/app-studio/map-*`；归属取 map 命名坐标或
  tracker child IID。排除软链、构建/依赖目录、二进制、`.log/.jsonl`、未映射工作区和非过程文档。
  JSON 类含 tracker/API/宿主回读，不表示每个 JSON 都应由模型阅读。
- 使用 `tiktoken o200k_base` 统一估算正文。这里的 tokens 是**每份文件整读一次的容量**，
  不含请求封装，也不是各 runtime 的精确 tokenizer 或账单 token。工具截断、缓存、读取次数、
  实际输入/输出与计费用量均为 **Unknown**。
- 其他地图会话仍在运行；这是逐文件读取的扫描样本，不是所有目录的原子快照。

| Map | packet / registry / 文本交接 tokens | 全部纳入的过程工件 tokens |
|---|---:|---:|
| #1725 广告授权与共享监测链接 | 433,817 | 417,988,760 |
| #1917 OPPO 全链路接入 | 18,955 | 144,500 |
| #1958 OPPO 点击先行联调 | 365,981 | 36,736,143 |
| #1977 小火龙 OTA | 46,683 | 575,525 |
| #1062 广告中台 | 344,202 | 101,107,609 |
| #1850 小仙女瑜伽 | 65,646 | 2,140,463 |
| #765 魔鬼轻断食 | 191,201 | 20,123,940 |
| #795 减肥王者 | 45,152 | 45,152 |
| #1439 APK 瘦身 | 125,388 | 117,094,115 |
| #1262 埋点与报表 | 566,961 | 15,101,526 |
| 合计 | **2,203,986** | **711,057,733** |

共纳入 11,321 个过程文件，1,883,832,815 字节。其中：packet 668,915 tokens，registry
540,053，文本交接 995,018，机器 JSON 527,249,104，checkpoint/快照 162,531,669，
Review patch/清单 19,072,974。大数主要来自机器数据，不是数亿 tokens 的已知消费。

## 能量化的冗余

1. **完全相同的工件副本：251,447,112 tokens。** 同一地图内比较完整内容；JSON 先紧凑序列化，
   其他文件逐字比较。保留一份内容，用原文件绝对路径替代后续副本的上下文展示，并扣除指针成本。
   不删除历史证据或取消写入回读。
2. **JSON 排版与转义：67,187,231 tokens。** 每次解析后紧凑序列化，断言解析值相等；只计算
   token 数实际下降的部分。主要是缩进、空白与 Unicode 转义；已有字符串内容不删。
   第 1 项按紧凑内容计算，与这一项不重复。合计 318,634,343，约为整读容量的 **44.8%**。
   这是存量展示冗余，不是已证明的账单浪费；仅在原本要展示这些文件时才形成节省。
3. **`none/null` 占位：4,444 行，24,496 tokens。** 来自 packet/registry 的字段行，仅表示
   人读正文可省，机器 schema 不删；保留 Unknown。此数不与上两项累加。
4. **六个巨大 Git/ignored 快照：162,345,475 tokens。** 四个 #1439 快照、一个 #1062
   checkpoint、一个 #765 checkpoint 占 checkpoint/快照容量的 99.9%。每份含约 10.5–16.9 万
   ignored 路径。摘要演练总计 1,750 tokens，仅列坐标、dirty 路径、ignored 数量/状态与 Unknown。
   完整指纹不进入摘要；这些摘要没有通过当前现场验收，不能用于授权接续。该数也不与前项累加。

代表坐标：

- `~/.config/delivery-pipeline/checkpoints/lane-1062-1147-starting-001.json`：76,561,402 字节，
  28,597,915 tokens；几乎全在 `snapshot.ignored`。
- `~/.config/delivery-pipeline/lanes/artifacts/map-1439/1478/checkpoint-starting-002.json`：
  28,941,138 tokens。
- `~/.config/delivery-pipeline/lanes/artifacts/map-1725/lane-1889/r1/resume-2/review-fixes-cancel-budget-r2/cancellation-readback.json`：
  7,376,313 tokens。将宿主历史回读再写成大 JSON，也会放大后续整读成本。

没有把“可以在源码找到”一律判为可删。唯一业务约束、授权边界、失败原因、固定版本与未决事项
仍需可恢复。按需读取的内容也可能产生 token，不能把交接正文缩小等同于总运行成本下降。

## 已落地的边界

唯一规则位于 `skills/delivery-pipeline/references/lane-registry.md` §轻量交接，核心入口与
Herdr/App/Orca packet 引用它：

- 生成正文只展开当前 role/output_mode/runtime/phase，省去不适用字段和占位；完整冻结 overlay
  仍持久化到原 registry/工件，packet 引用路径/字段及当前请求。
- Spec、ticket、repo instructions、检查日志不再整份抄进交接。指针携带读取条件和定点；
  可变 tracker 仍保留来源/时间，失效或冲突继续走原 gate。
- helper 校验完整工件，模型读取判定和必要字段；snapshot 输出重定向落盘。失败保留错误原文、
  命令、来源与恢复坐标。readback 仍逐项核对 expected/actual。
- 内容哈希和文件指纹留在机器工件；Git 版本 SHA、发布/完整性验收明确需要的 digest 保留。
- FINAL_REPORT 只传终态增量和完整证据的坐标。clean commit 路径从 base→commit diff 恢复，
  dirty/untracked 仍给精确路径；outcome、dirty 状态、失败和未决事项显式保留。
- Review prompt 传 bundle 绝对目录，不逐个重复七条绝对路径。先读定点、路径和 worktree 状态，
  再按轴读 patch/历史/命令；七文件校验和两个轴的完整职责范围仍保留。

三个壳仍只有各自的 transport；没有新 schema、额外 registry、压缩框架或新的运行依赖。
历史工件、正在工作的 lane 和 App Studio 源码均未改写。

## 消融与验证

| 尝试 | 去留 | 验证依据与限制 |
|---|---|---|
| 交接正文移除文件指纹/内容哈希 | 去掉正文重复，保留机器输入 | 新交接合同 RED→GREEN；机器 checkpoint 校验仍可读原字段 |
| 直接删除机器 `component_sha256` / `checkpoint_sha256` | 保留 | 原 checkpoint 校验 PASS；分别删字段后同一校验拒绝。证明现有合同不兼容，不证明永远不能重设计 |
| JSON 紧凑输出 | 保留 | 统计时逐份断言解析前后值相等；历史文件不改写 |
| 完全相同内容改用指针展示 | 保留 | 完整内容相等且扣除指针成本；历史副本不删除 |
| 不适用分支和占位退出生成正文 | 保留 | 三壳模板与 canonical 合同检查 PASS；未进行新地图真实分派 |
| 七个重复绝对路径合为 bundle 目录 | 保留 | 原七文件名、存在/可读/非空检查与审查定点仍保留；真人/模型跨轴回放 Unknown |
| 删除审查范围、失败证据、权限或版本坐标 | 保留 | 属原验收/恢复边界；本次没有证明可删 |

首轮模板源仍是所有分支的目录，没有因为规则改变就大幅变短：App 源 1,536→1,598 tokens，
Herdr 源 2,215→2,106；两者合计仅减 47。**收益应在生成后的当前分支正文和有限回读中验证**，
不能拿静态模板长度宣称未来每张地图已经省了固定百分比。

本次命令与证据：

- `.scratch/handoff-token-audit/venv/bin/python .scratch/handoff-token-audit/audit.py`：生成
  `inventory.json` / `counts.log`。tokenizer 仅装在忽略的审计 venv，未加项目依赖。
- 交接最小检查：`scripts.validate.check_handoff_contract()`，改前缺少合同失败；改后通过。
  `handoff-red.log` 保留失败，最新直接调用通过。
- `checkpoint.validate_checkpoint()`：已存在的小型 canonical checkpoint 原输入 PASS；
  两种删除机器哈希字段的消融均拒绝，原文件未改。
- `python3 scripts/validate.py`：**bundle: pass**，完整结果在 `validate-final.log`。
  首次基线因 `/tmp` 两个旧测试 marker 导致 watcher 重试断言失败；验证时仅隔离这两个精确
  测试 marker，结束后恢复。没有修改 watcher 或真实 lane 的去重文件。
- `git diff --check`：PASS。

未提交、推送或建 PR。保留两处原有改动：App `config/models.json` 与 `scripts/check_prewalk.py`。
真实新地图的恢复、分派、双轴审查能力与总 token 节省量仍为 Unknown；建议在下一张授权地图
用同样验收边界比较工具输出和实际输入用量，不提前承诺节省比例。

## 第二轮：固定短模板

用户继续要求简化后，将长字段目录替换为固定正文。唯一模板在
`skills/delivery-pipeline/references/lane-registry.md` §轻量交接：

- 派发 10 项：Lane ID、Work item、执行、Owner、Registry、现场、范围、验收、输入、Worker 合同。
- 终态 8 项：Lane ID、状态、交付、证据、现场、确认、阻断、下一步；保留 FINAL_REPORT markers。
- 恢复 6 项：Map/Spec、Registry、Gate/状态、现场、证据、下一步。

每项一句或指针。无事项写“无”，证据不足写 Unknown；范围和差异保留直接输入，其余从现有
registry/工件按字段读取。壳只补回传坐标，阶段计划、用户确认、失败记录和机器指纹的 schema 不变。
Worker 共同行为收在同一节；三个壳只保留各自的阶段、审查权限和终态通知，设备分支按条件读取。
Owner 三字段格式也引用公共模板，不维护第二份格式。

| 壳 | 派发字段数，改前→改后 | 模板文件 tokens，改前→改后 |
|---|---:|---:|
| Codex App | 41→13（10+3） | 1,598→526 |
| Herdr | 38→12（10+2） | 2,106→687 |
| Orca | 13→12（10+2） | 655→350 |

三份壳文件合计约减少 **64%**。这只比较本轮修改前后的壳模板文件，公共模板成本不在此百分比内，
也不代表地图总用量下降 64%。原始统计和比较结果保存在 `.scratch/handoff-token-audit/round2/metrics.json`。

`scripts/validate.py` 增加公共 10/8/6 项与各壳 3/2/2 项的字段名、顺序及引用检查；额外的交接字段
会失败。相关 owner、实施前置、隔离、Review 定点和停止/通知约束按新的唯一来源检查，原有 helper
行为测试继续执行，没有删除机器 gate。

本轮消融：移除壳内重复字段与 FINAL_REPORT 正文、合并 Owner 格式，固定模板检查通过；临时给
派发增加一个字段，同一检查拒绝，恢复后通过。新检查在改模板前失败、改后通过，证据为
`round2/red.log`、`green.log`、`extra-field-rejected.log`。完整校验见 `round2/validate.log`。
历史工件与运行中的 lane 未改写；新格式的真实地图分派、恢复和实际 token 用量仍为 Unknown。
