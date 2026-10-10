# Pipeline 分支加载与短恢复记录：实现及文本回放实测

日期：2026-10-09。仓库：`Dimon94/delivery-pipeline`，变更基线 `3f3c5d059aa5e009d1da199b4ad4f0f3e0502490`。
本次完成 [优化方案](2026-10-09-pipeline-context-optimization-plan.md) 中优先的分支加载和 coordinator
短恢复合同；未提交或推送。下面是实际合同展开及两份历史恢复文本的 token 测量，**不是新业务地图的
运行用量或 API 账单节省**。尚未验证模型在下一次启动中是否完全遵守新读取范围。

## 1. 实际改动

- App worker 从 packet 的分支表进入。全部分支读取公共执行、终态和参数证据；commit 加实施前置，
  staged 加 Prewalk/机械核验，planning 加用户确认，内部委派和正式 Review 在调用前加载对应合同。
  指针定义了标题及子节边界，避免一条全文读取指令重新带入创建、归档和不适用阶段。
- Core 与 Herdr/Orca packet 同步入口指针；完整 owner 与本票业务输入仍读。coordinator 的操作合同
  按 gate 消费，Orca 原生能力/授权 preflight 不变。详细容量表覆盖 App，不外推到其他 transport。
- 原 map registry 新增唯一的 `Coordinator Recovery` 节，复用已有六字段，不增 ledger/schema。
  gate、writer、阻断或决定改变时随既有持久化操作更新；交接/可控压缩前核验。
- 恢复记录保留全部 active writers 的枚举入口、Integration base/HEAD/dirty、用户决定、独有约束、
  失败及原审查版本。独有事实先持久化并 readback，再改成指针。冷恢复重读必要合同，重新核验现场。
  陈旧/矛盾记录不得触发 replacement 或复用旧 head 的 PASS。
- `CONTEXT.md` 增加 Coordinator Recovery 术语；它是可重建导航快照，权威仍是运行证据、registry、
  Git 和 tracker。没有新增全局加载器、缓存、预算服务或自动改写宿主摘要的 hook。

触达坐标：core `SKILL.md`、`lane-registry.md`、`fresh-session-boundaries.md`、`gate-state-machine.md`；
三个 transport 的 `SKILL.md` 与 packet；App `development-mode.md`、`codex-app-dispatch.md`；
`CONTEXT.md`、`scripts/validate.py`。

审查和验收保留：完整 owner 三字段、spec/tickets/sizing 前置、Git 隔离、独立 Standards/Spec、
Review Evidence Bundle、scope/fixed point/head、原始 reviewer 来源核验、失败/Unknown、用户确认、
Testing/Integration/发布授权。staged 始终沿原 task/session 和冻结 checkpoint 接续。

## 2. App 分支加载测量

tokenizer：既有本地环境的 `o200k_base`。前后都计 packet 与完整选中章节，包含子节。
优化前按旧全文入口计 core/壳/development-mode/dispatch 四文件（12,047 tokens），另计原 packet、
公共执行/终态，以及分支必需的实施前置或 review preflight。优化后按真实 packet 表展开。
这样不会用“旧四文件”对比“新四文件外的额外合同”，混淆计数边界。

| 分支 | 优化前 | 优化后 | 减少 tokens | 降幅 |
|---|---:|---:|---:|---:|
| direct implementation | 13,926 | 3,630 | 10,296 | 73.93% |
| staged implementation | 13,926 | 5,694 | 8,232 | 59.11% |
| planning artifact | 13,117 | 3,160 | 9,957 | 75.91% |
| 正式 Review 调用 | 14,313 | 6,294 | 8,019 | 56.03% |

本表是入口控制合同，不含完整 Owner SKILL.md、repo instructions、业务 spec、代码、工具 schema
和测试结果；这些输入前后都仍需要。direct/staged 之后准备候选审查证据时还会读取 preflight；
发生内部委派、咨询、异常时也有条件加载成本，不能把本表当成整条 lane 的净用量。
不是每个历史 worker 原本都全文读取；本表没有乘以地图数或会话数外推总节省。

direct 的 3,630 和 staged 的 5,694 略高于方案目标上缘 3,500/5,500；保留必要证据与边界，
不为达预算删审查。源文件总量可以增加，而特定分支实际需要展开的内容减少。

## 3. Coordinator 历史恢复回放

固定使用原复盘选出的 #1725、#1062 两条 Pi 摘要：

- #1725：`~/.pi/agent/sessions/--Users-dimon-.herdr-worktrees-app-studio-map-1725--/2026-10-01T04-42-01-628Z_01a0f5c4-f81c-7204-86a7-9d5c8bc58559.jsonl:5487`。
- #1062：`~/.pi/agent/sessions/--Users-dimon-02-Work-10-Projects-worktrees-app-studio-map-1062--/2026-09-30T17-42-18-815Z_01a0f368-fbbf-72d9-8c33-7c0e82805a68.jsonl:5223`。

每条产生六字段记录、证据正文与保留完整原摘要的归档。为了避免高估，本次证据正文**逐字保留原摘要
全部业务叙述**，仅把 `read-files` / `modified-files` 两份历史路径清单移到原摘要，按需查找。
SHA-256 与逐字比较检查通过，未改生产 registry。文件清单不作为删除的业务证据，仍可回读。

优化前计原摘要 + 旧恢复合同；优化后计短记录 + 全部业务叙述回读 + 新恢复合同。
新合同 920 tokens，旧合同 276 tokens，新增规范成本已计入。

| 样本 | 短记录 | 必读业务叙述 | 优化前合计 | 优化后合计 | 减少 tokens | 降幅 |
|---|---:|---:|---:|---:|---:|---:|
| #1725 | 457 | 30,421 | 52,407 | 31,798 | 20,609 | 39.32% |
| #1062 | 446 | 34,461 | 48,345 | 35,827 | 12,518 | 25.89% |

两条正文都远低于 2k，但回读业务叙述仍然很大。**原方案的 #1725 约省 92% 未得到本次测量支持**；
不能把短记录本身的大小当作恢复总输入，也不能据此宣布此前 66–190 万 tokens 情景已经实现。

两个旧摘要前后存在不同阶段快照：#1725 前段 R10 与尾部 R11 不同；#1062 前段 #1892 待处理与尾部
已集成、转入 #1893 不同。本次记录因此把实时 gate/writer/Git 标为 Unknown，要求先查原现场，
不从旧 Next Steps 重放动作。这证明原约束可达、陈旧信息显式保留待核验，**没有证明实时恢复后
得到相同的 active writer 判定、最早 gate 或业务验收结果**。

原 Git/宿主/tracker 的实时 readback、额外文件清单定位及后续业务输入成本为 Unknown，表中未计；
实际净省会受这些成本影响。这是两条历史文本的保守容量回放，不是执行过两次真实业务续跑。

## 4. 宿主能力与消融

本机 Pi 安装的 `docs/compaction.md` 确认 `/compact [instructions]` 支持额外摘要指示，
`session_before_compact` 可自定义摘要。此次只接入已知手动入口的合同：先持久化短记录，再输入
已核验记录与未决约束，压缩后 readback。未安装扩展或触发实际压缩；Codex/Claude 自动摘要替换能力
仍为 Unknown。宿主不受控时使用短记录恢复，不声称它已经替换内置自动摘要。

| 消融项 | 同组检查/测量 | 决定 |
|---|---|---|
| 删除 direct 独立章节，内联现有 Worker 执行 | 前后必要合同检查通过，少一行分支映射；净少 19 tokens | 保留简化 |
| 移除 commit 分支实施前置入口 | 合同检查拒绝缺失分支 | 保留入口 |
| 移除 Review / output-mode 验收标题边界 | reviewer 多加载 coordinator fan-in；多 249 tokens，检查拒绝 | 保留一个标题边界 |
| 删除恢复中的全部 writer 与独有业务约束保护 | 恢复合同检查拒绝 | 保留保护 |

消融在临时副本中运行，恢复后检查重新通过。标题读取 helper 仅供 validator 与容量审计使用，
不成为运行时加载器；检查包含子节结束边界，以及标题缺失/重复拒绝。

## 5. 验证与复算

- 最小合同检查先失败后通过：初始缺分支表、短恢复与旧全文加载冲突见 `red.log`；最终加载、
  固定交接字段、prompt 分支检查及消融正反例通过。
- `python3 scripts/validate.py`：退出 0，`bundle: pass`；包括现有 staged/legacy 恢复、Review
  independence 与 watcher 检查。运行前仅隔离 `/tmp` 两个已知固定测试 marker，结束逐字节恢复，
  原标记 SHA-256 前后一致；未改 watcher 或业务 lane。
- `git diff --check` 通过；用户既有 `config/models.json`、`scripts/check_prewalk.py` 内容散列与
  开始时一致。未 stage、commit、push 或创建新业务会话。
- Nowledge 定向检索连接失败；使用本机原日志及当前合同核验，未写记忆或用记忆补充运行结论。

复算命令（仓库根目录）：

```sh
.scratch/handoff-token-audit/venv/bin/python .scratch/branch-context-optimization/measure.py
python3 .scratch/branch-context-optimization/ablate.py
python3 .scratch/branch-context-optimization/validate-isolated.py
git diff --check
```

证据目录 `.scratch/branch-context-optimization/`：`baseline.json`、`before/`、`measurements.json`、
各分支 `*-before.md` / `*-after.md`、`replay/checks.json` 与原文/证据/六字段记录、
`ablation.json`、`validate.log`、`validation-isolation.json`。这些是本机可复算审计材料，
未上传包含历史业务内容的原日志。

下一张新地图仍需检查真实读文件清单、短恢复后的现场判定和额外回读成本；P1 helper 结果投影
不在本轮实现。没有降低测试、独立审查或验收要求来获取表中的节省。
