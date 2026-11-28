---
name: formal-verify-config-transaction
description: 修改配置锁、hash、replace、readback、configure 或 migrate 时验证共享提交事务。
---

# 配置共享事务验证

用户承诺：同一基线的两个合作写者不能都成功；replace 后读回失败必须待确认。违反会覆盖其他设置或诱发重复保存。

运行（Python ≥3.10，标准库，无新增依赖）：

```bash
python3 scripts/model_config_transaction_model.py
python3 scripts/check_config_transaction.py
```

第一条用显式 BFS 穷举 2 个写者、1 个文件、初始版本 0、候选版本 1/2、每个写者最多一次事务的所有可达交错。正常模型 75 状态，另外运行删锁、删 hash 与错误提交后分类三个反例，必须全部拒绝。第二条通过真实 CLI、临时文件和独立进程验证模型联系，包含真实 replace 与边界故障注入，不能以模型代替它。

对应 canonical `skills/delivery-pipeline-setup/scripts/model_config.py`：获取/释放锁对应 `config_lock` 的 flock（sidecar 永不删除）；read-check 对应 `configuration_transaction` 的 read_snapshot 与 configure.prepare；replace 对应 os.replace；readback 对应 exact bytes 比较及 committed 分类；迁移的读取与转换也位于同一锁内。模型把 prepare 的有限本地验证视作无文件副作用一步，未把核对和 replace 合成原子一步。

假设：合作方只通过同一 canonical resolved path / sidecar 写入，本地 flock 互斥，replace 原子，崩溃时 OS 释放锁。模型允许提交前失败、提交后读回失败、锁内进程崩溃；崩溃无返回值，replace 后文件仍保留。模型不证明外部编辑器 CAS、网络文件系统、断电持久性、能力来源真实性、JSON/schema 所有输入或桌面状态机；能力校验由真实合同测试与既有 validator 负责。

同步基线为 5ebf537d6f9437dbce9ff254ac5f7eff6646b88c，本文件与共享事务实现同批引入；该批实际提交坐标见仓库外 DD-379/result.md。可用 `git log -1 --format=%H -- skills/delivery-pipeline-setup/scripts/model_config.py` 定位最新代码提交。以后修改覆盖函数时，先读 diff 核对步骤、失败与崩溃假设，再运行上面两条命令，确认真实代码联系后更新同步记录；仅改模型至绿不算验证。

反例处置：用代码词汇叙述获取锁→核对基线→replace→读回顺序；分清模型假设错误与真实实现错误。真实缺陷先落公开 CLI 回归再修复，不能削弱不变量。维护入口为 maintain-formal-verification-skill。

DD-381：桌面 apply 的 prepare 复用同一个 configuration_transaction，增加九格/只读区限制，不改变锁与提交点模型。`python3 scripts/check_config_apply.py` 补 apply/configure 独立进程同基线竞争和相同 pre/post/no-op 真实回归；没有新增 formal owner。

DD-411：CLI v6 的 fallbacks 与主配置共用原 prepare/锁/hash/replace/readback 步骤；迁移转换仅在 prepare 内补列表，模型步骤与假设不变。公开 check_config_fallbacks.py 补有序重复、计数证据与只读 candidates；沿用真实进程事务及既有三个反例。

DD-511：CLI v7 的有序 review candidates 与 model_families 进入既有 apply/configure prepare；锁、hash、replace、精确读回、崩溃与失败分类均不改变。check_config_review.py --case candidate-family-transaction 补四格保序/重复计数/仅声明/no-op/stale/pre/post 与真实双进程同基线竞争；原模型与进程检查继续覆盖同一事务，不新增 owner。同步代码坐标由 DD-511/result.md 与 git log 定位。

DD-685：CLI v9 的任务类型目录校验与 v6–v8→v9 升级复用既有 `configuration_transaction`（migrate 与 apply 的 prepare 内执行确定性转换与结构校验）；锁、hash、replace、精确读回、崩溃与失败分类均不改变。`scripts/check_config_task_types.py` 补 v8→v9 迁移幂等（第二次 `changed=false` 零写入）、`show` 只读、必需用途底线拒绝与 v8→v9 原子 `apply` 回归；原 75 状态模型与真实进程检查继续覆盖同一事务，不新增 formal owner。

DD-687：v9 `apply` 的 `prepare` 放开 `work` 任务类型目录增删改（保持 `modes` 只读）并沿用 `validate_selection` 按三元组变更放行能力证据，完全位于锁内核对基线之后、`os.replace` 之前；锁、hash、replace、精确读回、崩溃与失败分类均不改变。`scripts/check_config_apply.py` 与 `scripts/check_config_task_types.py` 补 S2（新增自定义任务类型与 `modes` 只读保护）与 S5（原模型不可用时仅改元数据/删可选类型放行，新增或改模型缺证据返 `capability_unavailable`）回归；原 75 状态模型与真实进程检查继续覆盖同一事务，不新增 formal owner。
