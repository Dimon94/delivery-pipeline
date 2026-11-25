# 派发合同与蜂巢执行片

蜂巢模式给每次派发配一份机器可核的合同：只改哪些文件（`writable`）、先读哪些先例（`read_first`）、
用哪条命令验收（`check`）、期望看到什么（`expected`）。默认一张票一份合同，沿所属壳的派发通道执行。
一张票拆成多片并行是例外，见 §执行。

## 单票合同（默认）

1. Driver 交回 `prepare_contract`，`args` 带 `work_item` 与 `base`（当前集成 HEAD）。
2. 按 `owner-skill-resolution.md` 调用 `delegate-ticket`，做到 `prepare.js` 退出 0 为止，只写一份草案。
   要读的代码多时交给只读子代理，主线只留 `prepare.js` 的输出。
3. 回执 `{"briefs": <prepare.js 输出的数组>}`。Driver 只收恰好一份、字段齐全的合同。
   `prepare.js` 退出 1 时把缺项交给它点名的 owner，补齐后重跑，不回执残缺合同。
4. 随后的 `dispatch` Action 带 `contract` 以及由合同生成的 `scope`、`acceptance`、`inputs`。
   packet 的范围、验收、输入三行照抄这三个值，不改写、不补充范围。
5. worker 交回提交后，Driver 在 fan-in 前核对：净变更非空、执行工作树 HEAD 是交付提交、
   `check` 在该工作树退出 0 且工作树保持干净。不符时 lane 进 `blocked`，`blocked_reason` 以“合同违约”开头。
6. 违约走验收诊断。合同本身划错了（例如验收命令不对），诊断回执带新的 `briefs` 换合同；否则修复 lane 改代码。
7. 越出 `writable` 的文件不拦。Driver 记进 lane 行的 `scope_drift`，Merge Review 页在该票下列出，不需要你处理。

`writable` 的一项是精确文件，或以 `/` 结尾的目录。拆片的票只接受精确文件。

## Plan Review 前写入

只有要拆片的票才写：

- `plan.tickets[].briefs`：`delegate-ticket` 返回的完整 JSON 数组。
- `plan.tickets[].scenario_check`：父票整体验收命令的 argv，例如 `["node", "check.cjs", "all"]`。
- map row：`integration_worktree_path` 与 `integration_branch`。

Driver 的模型、档位、轮数与并发只来自 setup 的 `~/.config/delivery-pipeline/model-roles.json`。
执行时不重新探测模型清单：配置写入时 setup 已核过模型与档位，执行失败由 `claude -p` 退出码暴露。
Magpie 密钥先取 `MAGPIE_API_KEY`，缺省时取 `~/.pi/agent/models.json` 中指向本机网关的 `magpie` provider。

计划页逐个 task 列出 Setup 解析的模型、档位与上限。Driver 校验全部任务的预检结果后才授予 Autonomy Grant；
预检失败时修正配置后重新 run。沿人工审核的旧 map 若配置已变化，Driver 更新计划页并等待对新页面的答复。
`delivery-dispatch preflight <task…>` 可单独复查。

## 执行

本节只管拆片的票。Driver 按就绪依赖选出写入范围互斥的合同。`delivery-dispatch batch` 按配置限制并发与每次轮数，在各自工作树运行
`claude -p`；整批跑完 run 才返回，coordinator 按长命令执行 run（后台运行并等待退出）。`delivery-dispatch status`
在目标仓库列出现场、attempt、模型和失败原因。执行进程中断且写者状态未知时先核对该现场。

Driver 核对父票、片标识、基线、局部检查与真实提交，串行 merge 完整提交链。所有片到齐后，在集成 HEAD 运行
`scenario_check` 并记录观察。后续 HEAD 改变会重新验收。终态信号与 run 共用同一把 map 锁。
Merge Review 展示计划路由、执行片启动路由、Worker 回报模型和提交，以及当前集成 HEAD 的整票观察。
回执记录每次执行耗时与 Worker 提供的 token 用量，缺失字段为 Unknown。
