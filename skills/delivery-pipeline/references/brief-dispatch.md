# 蜂巢执行片（dispatch_briefs）

蜂巢模式把一张票拆成写入范围互斥的执行片（brief），由本机 `delivery-dispatch` 逐片执行，再整票验收。
执行器在核心 `scripts/driver.py`，与 transport 无关：Herdr、T3 Code 等壳调各自 run 入口时都由程序执行。

## Plan Review 前写入

- `plan.tickets[].briefs`：`delegate-ticket` 返回的完整 JSON 数组。
- `plan.tickets[].scenario_check`：父票整体验收命令的 argv，例如 `["node", "check.cjs", "all"]`。
- map row：`integration_worktree_path` 与 `integration_branch`。

模型、档位、轮数与并发只来自 model-roles 配置（默认 `~/.config/delivery-pipeline/model-roles.json`），不用手写。
执行时不重新探测模型清单：配置写入时 setup 已核过模型与档位，执行失败由 `claude -p` 退出码暴露。
Magpie 密钥先取 `MAGPIE_API_KEY`，缺省时取 `~/.pi/agent/models.json` 中指向本机网关的 `magpie` provider。
driver.json `dispatch.config` 只在换配置文件时写。

Plan Review 页的「蜂巢执行预检」逐个 task 列出实际模型、档位与上限；任一行「无法执行」时先修配置再通过。
`delivery-dispatch preflight <task…>` 可单独复查。Plan Review 固定并展示 briefs 与 scenario_check。

## 执行

Driver 按就绪依赖选出写入范围互斥的合同。`delivery-dispatch batch` 按配置限制并发与每次轮数，在各自工作树运行
`claude -p`；整批跑完 run 才返回，coordinator 按长命令执行 run（后台运行并等待退出）。`delivery-dispatch status`
在目标仓库列出现场、attempt、模型和失败原因。执行进程中断且写者状态未知时先核对该现场。

Driver 核对父票、片标识、基线、局部检查与真实提交，串行 merge 完整提交链。所有片到齐后，在集成 HEAD 运行
`scenario_check` 并记录观察。后续 HEAD 改变会重新验收。终态信号与 run 共用同一把 map 锁。
