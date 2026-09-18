# Orca implementation ticket sizing

关联 [canonical Spec](2026-09-12-delivery-pipeline-orca.md)、[tracker Spec #129](https://github.com/Dimon94/delivery-pipeline/issues/129)、[Map #114](https://github.com/Dimon94/delivery-pipeline/issues/114)。用户已确认测试切入点、九票粒度/依赖与预算建议，见 [确认记录](https://github.com/Dimon94/delivery-pipeline/issues/129#issuecomment-5646715861)。规划已收口；本次不启动代码实施。后续复用确认，不重问；ready 标签不豁免各票依赖及真实验收。

全部 token 数均为 **推断**，单位为上下文 tokens，不是累计输入输出或费用。分项按同时在场估算：I = 指令/相关 Spec/owner；R = 代码、测试、原生 reference；V = 实现、验证和调试输出。共享材料只计一次，采用目标节加载，不能把整份研究、全仓源码同时塞入每个 worker。建议预算 = 峰值上界 + 表中余量。

## 逐票交付与预测

| 票 | 单个 Execution Worktree 的交付 / 直接依赖 | 峰值预测 | 建议预算 | 数值依据、假设与置信度 | 粒度结论 |
| --- | --- | ---: | ---: | --- | --- |
| [#120](https://github.com/Dimon94/delivery-pipeline/issues/120) 入口/发现/preflight | 安装并调用独立壳；当前操作配置与能力可读，缺失 blocked。无前置票 | 8,000–12,000 | 16,000 | I 3–4k + R 2–4k + V 3–4k；余量 4k 用于 discovery 差异；假设复用 installer/schema，未到 worker lifecycle。中 | 保留；入口到真实 discovery/readback 可独立验收 |
| [#121](https://github.com/Dimon94/delivery-pipeline/issues/121) map Run/lane 持久身份 | 同 map 恢复原 Run/Task，overlay 和 mutation 意图可读回。依赖 #120 | 10,000–15,000 | 20,000 | I 3–4k + R 3–5k + V 4–6k；余量 5k 用于 orphan/response-lost 坐标；runtime markers/现有 tracker checkpoint，不引入数据库。中低 | 保留；无 worker 时也能验证 Run/Task/重复恢复 |
| [#122](https://github.com/Dimon94/delivery-pipeline/issues/122) 本地 dispatch/FIFO | 从 Integration HEAD 启动隔离 worker，startup/effective 与完整 Delivery 记账。依赖 #121 | 15,000–22,000 | 30,000 | I 4–6k + R 5–7k + V 6–9k；余量 8k 用于 agent/readback 与批级交接；只新增原生适配。中 | 保留；原生成功路径已有 #115 行为先例 |
| [#123](https://github.com/Dimon94/delivery-pipeline/issues/123) fan-in/cleanup | Orca evidence 接入既有 Integration/testing/review owners，按项目 gate 清理。依赖 #122 | 12,000–18,000 | 24,000 | I 3–5k + R 4–6k + V 5–7k；余量 6k 用于 archive/branch 残留；复用质量 owner，不实现第二 testing/review dispatcher。中 | 收窄并保留；不把整个质量链重写进本票 |
| [#124](https://github.com/Dimon94/delivery-pipeline/issues/124) 本地恢复与 staged | 从真实停止/丢失响应/重启检查点恢复同 Task、原 session，保持单 writer。依赖 #121、#123（#122 为传递前置） | 17,000–26,000 | 36,000 | I 5–7k + R 6–9k + V 6–10k；余量 10k 用于原 session continuation 与 native retry；假设无需修改 Orca 上游。低 | 暂保留；retry/重启共享恢复接缝，staged 触发下述拆分规则 |
| [#125](https://github.com/Dimon94/delivery-pipeline/issues/125) browser/automation | 一个交付测试场景跑通浏览器证据与有限自动任务，权限/失败可恢复。依赖 #124 | 9,000–14,000 | 20,000 | I 3–4k + R 3–5k + V 3–5k；余量 6k 用于 browser/job readback；不封装整个浏览器。中低 | 保留；只验收交付相关纵向场景 |
| [#126](https://github.com/Dimon94/delivery-pipeline/issues/126) tracker/artifact/provider 联动 | tracker → artifact → 既有 PR/MR ready 状态的外部证据往返；复用各 owner。依赖 #124 | 14,000–22,000 | 30,000 | I 4–6k + R 4–7k + V 6–9k；余量 8k 用于 provider 幂等差异；假设只适配已声明 operation，无新认证系统。低 | 暂保留一条联动验收；若 provider 合同不能共用则拆分 |
| [#127](https://github.com/Dimon94/delivery-pipeline/issues/127) federation/多 host | 远程 placement、输出回取、失联保留、原 Run 接管和清理。依赖 #124 | 18,000–28,000 | 40,000 | I 4–6k + R 6–10k + V 8–12k；余量 12k 用于 host/selector/stop/archive；至少两个可用 execution host，无新 federation 服务。低 | 暂保留；没有对 #126 的无条件依赖 |
| [#128](https://github.com/Dimon94/delivery-pipeline/issues/128) remote closeout | PR/MR、CI/review、merge/rebase、parity 与可恢复清理。依赖 #126、#127 | 18,000–30,000 | 44,000 | I 4–6k + R 6–10k + V 8–14k；余量 14k 用于冲突、response-lost 和 provider parity；复用现有 remote owner。低 | 暂保留；以授权后的完整收口为单一交付 |

实测 token 校准：全部 **Unknown**。#115 仅提供原生生命周期行为证据，没有 token 测量。每票可用模型/宿主上下文容量：**Unknown**；容量适配均待实施前核验。不得把上述预算当作已验证可容纳或自动选模型的依据。

## 加载坐标与验收

| 票 | 最小读取与复用 | 必须观察到的外部行为 |
| --- | --- | --- |
| #120 | bundle manifest/installer/validator、setup schema、Orca `agent-context` 与 `skills installed` | exact skill selector/name/providers/source 与 agent owner realpath；非法共享配置/能力缺失无 dispatch；旧入口正常 |
| #121 | canonical lane registry、tracker 合同、Orca Run/Task/request references | 写意图 → mutation → 真实 ID readback；第二次恢复沿原 Run/Task，identity 不明不创建副本 |
| #122 | dispatch packet、frontier/gate、model freeze、worker-start、messaging references | Integration Base/真实 worktree/launch；整批 startup 交接；消息和 ownership 决策持久后 ack；重复消息不 fan-in 两次 |
| #123 | execution-worktree-integration、review evidence、test-decision、Orca release/archive | commit integrated 或非 commit consumed；原 testing/review owners 通过后本地交回；dirty/Unknown/清理失败保留；branch 无残留或明确 close_pending |
| #124 | checkpoint/continuation helper 与直接 caller、native recovery | 正面 failed/stopped retry、同 request response-lost、旧 coordinator 退出证明、原 provider session staged 成功；不确定时零新 writer |
| #125 | native browser/automation reference 与 #124 的操作恢复证据 | 交付测试 artifact、job/action receipt 与 host 绑定；有限任务重复触发/暂停可读回；无授权外部写操作不发生 |
| #126 | tracker/artifact/provider reference、现有 issue/remote authority owner | GitHub/Linear 与 artifact/既有 PR/MR 状态的真实 readback；重复/失联不造重复对象 |
| #127 | native placement/federation/recovery、local registry/fan-in | exact remote selector、跨 host writer 排他、完整 fleet 分页、输出归档回取、连接丢失不释放，恢复同 Run |
| #128 | 既有 remote-closeout/test-decision/review owner、provider native reference | scoped authority、CI/review、PR/MR 身份、重试/parity、cleanup；冲突修复不减需求 |

共享代码坐标以 Spec 的文件/调用索引为准；外部行为检查从 coordinator 操作边界进入，不为测试复制状态机。每票运行 `python3 scripts/validate.py`、相关 `git diff --check` 与其 assigned 场景。缺必需真机证据时保持 blocked，不能因静态绿或已写 Unknown 而关闭实施票。Phase 1 要 #120–#124 全部通过。

## 拆分触发与依赖取舍

- 预算超过目标模型/宿主已证实可用容量，或初次读取后预测超出预算时，在启动 mutation 前重新估算并沿独立验收拆分。当前容量 Unknown 不替代此检查。
- #124 若同 session staged 需要独立 CLI 协议或 Orca 上游能力改动，就拆成“Task/Dispatch 故障恢复”和“原 session staged continuation”；后者依赖前者，Phase 1 总验收仍等待两者。不能删掉 staged 来把票做小。
- #126 若 GitHub/Linear/PR/MR 操作需要不同认证/幂等协议且无法在单次联动范围完成，则按 provider/输出合同拆票，保留 artifact 与各 provider 的验收。#127 若 placement 与远程 takeover/cleanup 各自超过预算则拆为先执行再恢复；#128 若 PR 创建与 merge/recovery 超预算则沿这两个阶段拆分。
- 新拆票先作为本票的明确前置，保留原票作为完整验收门槛；已 claim/已派发的票不自动改范围。主要 Unknown 是原生 API/权限与运行证据，不据它们编造兼容层。
- #123 复用质量 gate，只有 Orca transport 的 fan-in/cleanup 是新增行为。#124 必须等 #121 的坐标和 #123 的项目 authority；#125/#126 要依赖完整本地恢复。#127 不无条件依赖 provider mutation，因为它的执行/归档不需要 tracker 发布。
- 四阶段表示能力与验收集合；实际执行按显式依赖。最终完整 Orca 能力需九票全部验收，不以 #128 单票 closed 推断 #125 browser 已交付。
