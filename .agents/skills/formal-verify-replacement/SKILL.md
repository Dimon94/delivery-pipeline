---
name: formal-verify-replacement
description: 修改 Registry claim、launch、recover 或冻结备用选序时，检查有界 replacement 安全性。
---

# Replacement 安全性

用户承诺：一次源失败只能有一个 successor，accepted replacement 最多两次，未知启动不能再启动。
违反会消耗用户未授权的模型额度或产生两个 writer。

运行（Python 3.11 标准库，无新增依赖）：

```bash
python3 scripts/replacement_model.py
python3 scripts/check_replacement.py
python3 scripts/check_replacement_branches.py
```

模型枚举一个 work_item、0/1/2/3 备用、两个通知者、两次 accepted claim，以及 claim→launch 标记→receipt
之间崩溃与 Unknown 的持久前缀。状态中的 count 对应 Registry 血缘行数，不是实现中的独立计数器。
预算（含空清单）、跳游标、重复 launch、active writer、双 successor、耗尽和停止分类共十一个破坏变体必须被拒绝。列表内容与重复位置由真实公开 decide/claim
检查承担；模型仅抽象位置，不验证模型身份。active writer 与 native gate 的有限真假输入同时进入模型和真实 Registry 检查。

真实联系：`skills/delivery-pipeline/scripts/replacement.py decide` 是纯决定面；`lane_registry.py`
claim/launch/recover_launch 分别对应原子 claim、持久 launching、原 receipt adoption。
公开检查用真实临时 v2 Registry、两个独立 Python 进程竞争，以及进程在 start 回调 os._exit(23) 崩溃。
检查长度及重复、第三次、writer 活跃、revision 冲突、response lost 不重发。
`model_config.py recover_registry` 沿既有块 parser 取 latest row，不能建立另一 ledger。

本地 resolved path 的永久 flock、合作写者、原子 replace 是假设。observe 是 Adapter 提供的实时原生
只读边界；检查里的观察替身不证明真实 native 能力。外部调用与本地事务不原子，launching 后不能证明
未启动时只 inspect；此模型不证明原生 exactly-once、原生去重、断电、NFS、外部编辑器或实际模型响应。
配置事务另运行既有 formal-verify-config-transaction，不能用其锁模型代替本检查。

同步基线：e9d9d88cb4914dc2cd7b41dacf1e460d04eb8d0e 上的 DD-415 特殊失败扩展。
该批代码坐标用 `git log -1 --format=%H -- skills/delivery-pipeline/scripts/lane_registry.py` 读回。
修改覆盖函数时先核对步骤、原子性和崩溃假设，重跑上述命令及真实近似错误探针，确认代码联系后再更新同步记录。
反例先落公开接口回归；不得削弱不变量迁就实现。维护入口：maintain-formal-verification-skill。

DD-415 同步：增加空 work/explicit_mode、原因 Unknown/断连原样分支，及 outcome_unknown inspect、取消 stop、上下文 resplit。模型枚举这些分类与 0..3 位置，11 个破坏变体必须拒绝；真实 Registry 分支检查承担模型反例回归。两次预算优先于下一备用，耗尽保留 blocked。预算返回 budget，由既有 coordinator 执行 superseded/重拆；本模块不写 Tracker。

R1 同步（代码 32cd572，基线 8c42162，所选能力门禁）：claim 在同一 flock 内 decide → observe 双视图 → persist。
observe 的 `_selected` 为共享选中的启动快照，顶层为旧身份；四壳必须核验所选能力，不以旧 A
启动资格替代 B。bind/launch 重核；accepted 重放直接返回原 intent。模型新增 selected 可用/不可用
输入及跳过该门禁的破坏变体（共 11 个）；不抽象能力目录的变化时刻，不能保证观察后远端能力不变化。
真实对应回归为 `python3 scripts/check_r1_replacement.py` 及四壳 `check_*_native_replacement.py`；
后者替身仅在原生 I/O 边界，selected 能力由生产解析器验证。并发仍由真实双进程检查承担。

DD515 同步：正式 review 不走 work claim/replacement。`reserve_review` 在唯一 Registry 的
flock 内冻结原计划与 request，占位成功的唯一 dispatch 持久 `herdr.startup_state=launching`
后才调用 start；receipt 沿原 herdr 字段保存。恢复只读原 plan/receipt/Review Budget，取消、
终态停止，response lost inspect，不重发、不重选。运行 `python3 scripts/review_recovery_model.py`
枚举同 request 两调用者、配置变化、启动持久前缀和取消，拒绝重复占位、重发、重选与取消后
replacement 四变体。真实联系为 `check_review_dispatch.py --case same-round-recovery` 的
公开 CLI、真实文件及独立双进程竞争。该模型不覆盖网络、强制断电、NFS 或原生去重；没有
扩张旧 M2 原生验收结论。原有 replacement 模型与检查继续执行。

DD516 同步：同一个 review_recovery_model 增加 R1–R3、FIX/终态、同 head、修复者和取消
的有界组合，拒绝预算、终态、漏修复者、相同 head 重跑与取消后轮五变体。
真实联系为 review_gate.prepare_round（原预算唯一决定面）、dispatch --round/--review-head/
--review-ledger/--previous-review-registry，以及两条 later-round 公开检查。新 request 只用于
合法新轮，原 request 的 immutable plan/intent/receipt 仍由 DD515 恢复。模型不证明贡献者
Registry 的外部真实性、原生执行或 exactly-once；真实文件/CLI 和 Root 最终验收继续承担。

DD517 同步：T3 ReviewDispatch 使用相同 reserve_review 唯一锁内占位，t3code overlay
持久 accepted→launching→receipt；recover 只读、取消 stop，无第二 native 启动边。
review_recovery_model 的既有状态空间及九个破坏变体直接适用，源码已补同构联系；
真实文件联系为 T3 check_review_dispatch.py --case native-evidence。模型不验证
能力目录、逐轴身份、宿主权限或原生去重；真实 T3 接受仍由 Root 完成。
