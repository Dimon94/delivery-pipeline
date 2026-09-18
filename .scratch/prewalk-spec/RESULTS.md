# #94 开发与验证记录

Spec：https://github.com/Dimon94/delivery-pipeline/issues/94

新增 App 专用 prewalk CLI：resolve 选择三模式，snapshot 核对 Git 现场，prepare 校验原任务与检查点并返回待持久化 overlay/原任务接续参数。协调器先持久化再使用 App 工具发送；helper 本身不发送、不写 registry、不新增调度服务。packet 与 transport 直接引用该入口。

## 实际 App 探针

| 模式 | 同任务坐标 | 宿主 model/effort | 结果 |
|---|---|---|---|
| astra-luna | 01a07af9-d9ac-74c0-88ac-36d20f37c8cb | Astra low → Luna high，纠正后同任务再次 Astra low → Luna high | 完成；纠正后口令与独立行为检查通过 |
| astra-sol | 01a07afe-a3b6-7b13-94e6-5209e30c903e | Astra low → Sol high | 口令与独立行为检查通过 |
| sol-direct | 01a07afe-a3f8-7af2-ba77-9d4fe82007f3 | Sol high | 独立行为检查通过 |

模型证据来自本地宿主 session turn_context，不是模型自述，也不是后端服务身份证明。接续始终在原 task/worktree，未 fork。首次 Luna 将任务误解为协调器监控，纠正后完成；由于该轮查询过父任务，其口令结果不计作独立上下文证明。随后在原任务引入新口令并复测，明确 worker 身份后直接完成，无 thread/log 查询。该纠正已写入生产接续 prompt 与 packet。

创建工具先返回 clientThreadId；list_threads 未列出已运行探针。通过本机 session metadata 获得候选 taskId，再用 App read_thread 核对标题/cwd/状态，并用 Git common dir 验证项目，避免重复创建。该列表可见性限制仍需在实际部署中关注。

隔离 worktrees 保留在 bacf、b4da、2866 对应的 Codex worktree 中，未删除、未归档、未提交。原始宿主证据摘要、检查点、prepared request、overlay 和生成代码保存在 app-evidence。最初两个检查点采用首版 helper，补齐 base/first_edit 后默认模式复测使用最终 helper；另外两模式的最终 helper 行为由同一 CLI 检查覆盖。

## 验证

- python3 scripts/validate.py：prewalk dispatch: pass；bundle: pass。
- git diff --check：通过。
- check_prewalk.py 通过真实 CLI stdin/stdout 覆盖模式优先级、direct、旧lane、非法模式、原task坐标、idle、stale、暂存变化、untracked、重复/Unknown无重发、base和首改证据。
- detached HEAD 缺陷：同一检查先失败后通过。
- Spec Review 发现缺 base/首改核验：补拒绝检查先失败，再修复通过。
- Astra low Standards Review：通过；Spec Review：1项P2已修复并复核关闭。

## 尚未验证

完整业务 map 的独立 Review fan-in 与 Integration 未在本次小探针端到端运行；没有把三模式小任务成功报告为整个交付链已验证。Luna fast/service tier 仍为 Unknown。检查点不保证宿主逐 token 保留历史。

GitHub spec 已按本票分派接缝验收关闭；本轮未做 Git 提交或推送。

验收回填：https://github.com/Dimon94/delivery-pipeline/issues/94#issuecomment-5568590669。完整业务地图端到端验证的边界保持不变。

## 空闲唤醒与连续推进（2026-09-07）

复用两个隔离 App 任务，以固定 registry 执行两阶段只读检查。协调任务先结束进入 idle；worker 回传 a 后自动唤醒协调任务，核验 SHA256 和两个合法转换后，先持久化 next_sent，再向同一个 worker 自动发送 Sol/high 的 b。b 的十个非法组合检查通过，协调任务再次自动唤醒，写入 complete、consumed=[a,b]，最终向当前主任务发送 IDLE_WAKE_COMPLETE；主任务实际收到并独立核对 registry 与文件哈希。两个阶段之间没有人工续发。

- 协调任务：01a07afe-a3f8-7af2-ba77-9d4fe82007f3；worker：01a07afe-a3b6-7b13-94e6-5209e30c903e。
- armed 轮于 Unix 1788772988 结束；a 唤醒轮于 1788773111 开始，1788773227 结束；b 唤醒轮于 1788773245 开始，1788773340 结束。
- App 回读及最终 registry：app-evidence/idle-wake-readback.json、idle-wake-registry.json。
- 隔离探针验证消息传输与两阶段检查接续，不替代完整业务 map 的 Review/Integration 验证。

修复 READY 先于起步轮停止到达的竞态：prepare 对有宿主证据的 active 返回 wait-for-stop 和原任务坐标；协调器持续有界等待，idle 后重新核验现场再发送，Unknown 不发送。相同 CLI 检查先失败后通过；v4 Astra low Standards/Spec 双轴复核均为零 findings。
