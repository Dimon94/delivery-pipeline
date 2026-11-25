# ADR-0028: 每张 commit 票派发前必带一份派发合同，fan-in 前由 Driver 核对

**Status:** Accepted（取代提交 3a6e03f 中“普通票不带合同即可派发”的含义；ADR-0026 的状态机归属不变）
**Date:** 2026-11-25
**Decider:** User (Dimon)

## Context

蜂巢模式的本意是让每次派发都带一份机器可核的合同：只改哪些文件、先读哪些先例、用哪条命令验收、期望看到什么。
落地时合同被做成了可选项，并且只接在本机无头执行器上。证据：

- 2026-11-21 至 2026-11-25 的 25 张 Driver map、103 张票，`plan.tickets[].briefs` 非空的为 0 张
  （`~/.config/delivery-pipeline/lanes/*/driver.json`）。唯一带该键的 `lanes/tkada-jb476/driver.json` 五张票全是空数组。
- 同期 `dispatch_briefs` Action 只出现 2 次，都在开发蜂巢功能自身的会话里；真实任务 0 次。
- 入口是判断题：上游 `implement` 写“技术负责人需要委派时调用 `delegate-ticket`”，Run 循环没有一步要求产出合同；
  `brief_delivery.has_briefs` 把空数组当普通票放行。
- 合同的意图靠 coordinator 在派发包里手写散文表达（例 `~/.config/delivery-pipeline/packets/jb512-m3-01.md`），
  回收时没有程序核对改动范围和验收结果。
- 回放 255 条历史 commit lane（`git diff base...head`）：每条改动文件中位数 7、P90 为 18；
  142 条（56%）新增了文件，其中 99 条新增测试文件、21 条新增迁移文件。这些文件名派发前定不准，
  所以可写范围不能只认精确文件名，越界也不能直接拦。

## Decision

1. `output_mode` 为 `commit` 的票，派发前必须有一份合同。Driver 在 frontier 上先交回
   `prepare_contract`（id `contract:<票号>`），回执是上游 `delegate-ticket` 的 `prepare.js` 输出。
   合同恰好一份，必填 `ticket`、`writable`、`read_first`、`check`、`expected`；残缺或多份一律拒收。
   `writable` 的一项是精确文件，或以 `/` 结尾的目录（覆盖其下所有文件）。
2. 合同存 `driver.json` 的 `contracts`，按票号索引，不进 `plan`。合同在派发时按当时的集成 HEAD 准备，
   所以它不参与计划冻结和计划 hash。
3. 执行通道不变。`dispatch` Action 带上合同和由合同生成的 `scope`、`acceptance`、`inputs`；
   T3 Code、Herdr 等壳照旧起 lane，模型与档位仍只来自 setup。
4. fan-in 前 Driver 核对三件事：交付提交相对集成基线的净变更非空；执行工作树的 HEAD 就是交付提交；
   在该工作树跑合同的 `check` 退出 0 且工作树保持干净。任一不符，lane 置 `blocked` 并带原因，
   走 ADR-0012 的诊断修复链，提交不进集成分支。
5. 越出 `writable` 的文件不拦。Driver 把它们记进 lane 行的 `scope_drift`，Merge Review 页在该票下显示
   “超出合同范围”和文件清单，由人审时判断。越界率量出来之前不升级成拦截。
6. 诊断结论是“合同划错了”（例如验收命令不对）时，诊断回执带新的 `briefs` 换合同，原提交按新合同重核。
7. 一张票要拆成多片并行时，仍在计划阶段写 `briefs` 与 `scenario_check`，走原有的本机执行片路径。
   这是例外，不是默认。并行片靠写入范围互斥防冲突，所以拆片的 `writable` 只接受精确文件，越界照拦。

## Consequences

- 每张票多一步合同准备，coordinator 多一轮回执。净收益是 Unknown，先在一张真实 map 上试跑再评估（见 §试跑）。
- 越界只记不拦，所以合同对“改了不该改的文件”暂时没有强制力，只有可见性。
  强制力在验收命令和空变更两项上。越界率是试跑要量的第一个数字。
- 已在跑的 map 不受影响：没有合同的已派出 lane 按旧路径 fan-in；尚未派发的票会先要合同。
- 验收命令在执行工作树里跑，不在集成分支上跑。集成后的回归仍由 `focused_checks`、测试 lane 和整票场景负责。
- 核对读的是 lane 行里的 `worktree` 和交付提交，基线取交付提交与集成 HEAD 的 merge-base。`worktree` 缺失时按违约处理。

## 试跑

全量依赖本决定前，先在一张真实 map 上跑完并记下：

- 合同准备每票耗时与 token；`prepare.js` 首次退出 1 的票数。
- fan-in 违约次数，分验收失败、空变更两类；其中靠换合同解决的次数。
- 带 `scope_drift` 的票占比，以及越出的文件里人审认为不该改的占比。
- 同一批票的 coordinator 上下文峰值与亲手改码次数（`scripts/orchestration_metrics.py`），对比上一张 map。

Backlog：越界里“不该改”的占比高、而误报少时，把越界升级成拦截；合同准备的 token 成本若高于手写派发包，
把准备改派成只读 lane。
