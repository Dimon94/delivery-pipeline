## Problem Statement

用户希望在 Codex App 的一张开发票中，让 Astra low 先调查并建立实现路径，再由 Luna high 接续，保留同一任务的对话和工具历史。当前仓库已有三种模式的文字合同与 CLI fork 原型，但验证主要检查文档内容，尚未证明 App 同任务模型切换、检查点恢复与最终交付真的连通。仅生成 spec 或交接文档不能满足用户明确要求的“不拆分上下文”。

## Solution

提供三种票级开发模式：默认 astra-luna，支持 astra-sol 和 sol-direct。前两种由协调器在 Astra 起步轮停止后，向原 App task 发送带目标模型和思考档位的下一轮请求；继续使用原 Execution Worktree 和任务历史。起步、接续、审查和集成具有可核对的证据。无法在原任务接续时报告受阻，不用新任务或独立子代理冒充接续。

## User Stories

1. 作为开发者，我希望新开发票默认采用 Astra low → Luna high，以便先建立实现路径再接续开发。
2. 作为开发者，我希望为单票选择 Astra low → Sol high，以便为该票使用不同的执行模型。
3. 作为开发者，我希望选择 Sol high 直接执行，以便无需单独起步阶段。
4. 作为开发者，我希望为 map 后续新票保存模式，以便无需每票重复选择。
5. 作为开发者，我希望单票选择优先于 map 默认，以便精细控制例外。
6. 作为开发者，我希望恢复已有票时保留其模式，以便默认值变化不会重启工作。
7. 作为执行者，我希望 Astra 先读取规则、spec 和直接调用者，以便接续建立在实际代码证据上。
8. 作为执行者，我希望 Astra 完成第一处有意义的修改和最小检查，以便看到可延续的实现路径。
9. 作为开发者，我希望 Astra 将剩余 TODO、验收命令与决策理由留在原任务中，以便接续理解已有工作。
10. 作为开发者，我希望 Luna/Sol 接续使用同一个任务 ID 和工作目录，以便不拆分主执行上下文。
11. 作为协调器，我希望先确认起步轮停止，以便避免两个执行轮同时写入。
12. 作为协调器，我希望核验 HEAD、dirty 文件与检查点一致，以便拒绝过期交接。
13. 作为协调器，我希望 PREWALK_READY 仅表示中间检查点，以便不会提前集成或归档。
14. 作为协调器，我希望发送结果未知时先检查原任务，以便避免重复启动执行者。
15. 作为开发者，我希望看到请求参数和实际运行证据的区别，以便知道换模是否真的得到验证。
16. 作为开发者，我希望无法确认的模型、档位和历史完整性明确标注 Unknown，以便不会把推断当事实。
17. 作为开发者，我希望宿主不支持原任务换模时保留现场，以便恢复不丢失代码或上下文。
18. 作为执行者，我希望接续消息明确解除起步轮限制，以便可以完成剩余实现、测试和原 owner 的交付步骤。
19. 作为审查者，我希望 Astra 起步与独立双轴 Review 分开，以便实现仍经过 Standards/Spec 核验。
20. 作为开发者，我希望三种模式使用相同验收标准，以便模式选择不降低交付质量。
21. 作为协调器，我希望只有最终交付证据满足原 gate 时才 fan-in，以便起步完成不会被当成开发完成。
22. 作为维护者，我希望 CLI/Herdr 主干不受 App 模式影响，以便 runtime-neutral 边界继续成立。
23. 作为维护者，我希望验证能发现接续被误改成新任务或文档交接，以便防止上下文分离的回归。
24. 作为开发者，我希望真实 App 探针和逻辑模拟分别报告，以便不会把模拟通过当作宿主能力已验证。

## Implementation Decisions

- 保持既有 App transport 壳、dispatch packet、lane registry overlay 和开发模式合同；不新增通用调度框架。
- development_mode 仅控制 implementation lane；其他 delegated roles 沿现有工作分工。模式选择顺序为单票明确选择、map 已保存选择、astra-luna 默认。非法值拒绝新建；旧 lane 缺字段时按原流程恢复。
- astra-luna 与 astra-sol 起步请求 Astra low；接续分别请求 Luna high 与 Sol high。sol-direct 直接请求 Sol high。运行中调整只在原轮停止且现场核验后沿原 task 进行。
- App overlay 保存模式、来源、执行子阶段、检查点、当前阶段请求参数及独立运行证据。沿用 canonical lane state 与 gate；起步阶段不产生独立 owner 或 lane。
- 起步检查点包含任务及隔离坐标、base/HEAD、dirty 路径及内容指纹、首处修改、验证结果、剩余 TODO、决策理由和已读证据。检查点保存在既有 repo 外 lane 工件位置。
- Astra 发出 PREWALK_READY 并结束本轮。协调器核验原轮停止和现场一致后，先持久化 switching，再向原 task 发下一轮请求，显式传 model 与 thinking。观察原任务接续轮后进入 executing。
- 接续必须保留 threadId、hostId 与 Execution Worktree；不得换成 fork、新任务、独立 subagent 或仅文档交接。检查点辅助恢复，原任务历史承担主执行上下文。宿主自动压缩及模型隐藏推理不属于逐 token 保留承诺。
- 发送接受、接续轮启动、实际模型 readback 分开记录。读不到记 Unknown；参数回显、标题和模型自述不作为运行证明。
- switching 期间发生超时或进程恢复时，先核对原任务消息与执行轮。无法消歧时保留现场并报告；不假定 App API 有幂等键，不以本地标记宣称 exactly-once。
- 接续模型完成实现与测试，再沿原 owner 执行独立 Astra low Standards/Spec Review。起步不代替 Review，不增设 Sol 全量复核。最终报告、fan-in、archive、Integration 与远程授权沿原合同。
- 对需要机械重复核验的部分优先复用既有验证入口；只有发现现有入口无法检查外部行为时，才添加 App 壳内最小 helper，并让真实分派合同直接调用它，避免建立仅供测试的第二套状态机。

## Testing Decisions

- 用户已确认的测试接缝：既有 App 分派边界，从解析票级模式到向原 task 接续并读回结果。以输入 packet、实际工具请求、持久 registry 和最终产物为观察面，不测试文档措辞或私有函数布局作为业务正确性证明。
- 静态 bundle 校验继续覆盖引用、字段、runtime 归属与合同入口；它不承担实际换模证明。
- 在同一接缝覆盖三种模式及单票/map/default 优先级；覆盖旧 lane、非法模式、旧检查点、起步轮未停止、重复中间通知、发送结果未知、恢复、缺模型 readback 与 premature fan-in。
- 拒绝分支检查无新建任务、无第二次不确定发送、无提前集成等可观察副作用；修复实际缺陷时先用同一最小检查复现失败再验证通过。
- 真实 App 探针使用隔离的临时测试任务：每条 Prewalk 路径内部始终同一个任务，不 fork。核对起步轮和接续轮的 threadId、worktree、模型/effort 证据及原对话专属非敏感口令。口令只检查历史可见性，不证明全部上下文完整。
- 真机探针必须单独获得新任务创建授权；没有授权时本地开发与可复核静态/行为检查仍可推进，但 App 端到端结果保持 not-run。
- 先验证默认 astra-luna 的主路径，再在同一分派边界验证 astra-sol 与 sol-direct；发生宿主能力阻断时不扩大为替代 transport。
- 先例来自已有 bundle validation、App startup readback/terminal fan-in 合同与三组 CLI 原型；复用其证据口径，不把 CLI fork 结果当作 App 原位切换证明。

## Out of Scope

- CLI/Herdr 模型配置或 transport 改造；全局 Codex 配置覆盖。
- Luna fast 的绑定及所有其他模型禁用 fast 的保证；当前运行证据不足，单独标注 Unknown。
- 模型自动升级策略、通用调度服务、工具调用边界热切换。
- 新任务、fork 或文档替代同任务接续的降级方案。
- 传递隐藏推理或保证宿主压缩后逐 token 历史不变。
- 根据小样本宣称成本、速度或模型质量更优。
- 无关 dirty 修改、Git 提交、推送、PR/MR 与主分支集成。

## Further Notes

用户已确认默认 astra-luna，允许 astra-sol 与 sol-direct，并明确要求不拆分上下文。用户已确认测试接缝，并授权创建隔离 App 测试任务。

已有 CLI 单次原型：Sol 直接执行 82.64 秒，Astra→Sol 143.59 秒，Astra→Luna 124.23 秒，三组均通过 8 项检查；两条接续从同一 Astra 历史 fork，均正确回忆专属口令。该结果支持探索接续，不证明提速或 App 能力。

当前代码已具备三模式文字合同，开发工作的重点是实际调用入口、恢复行为和证据验证，而非重复写一套规划。完成标准为本地验证通过、App 真实结果可追溯或清楚列出宿主阻断，且不以 Unknown 宣称已验证。

在 GitHub Issues 发布并应用 ready-for-agent；实际开发证据回填到该 spec。
