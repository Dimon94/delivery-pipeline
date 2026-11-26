# 看板快照合同样本（DD-669）

`board.json` 是 Python 命令桩、Go `ReadBoard()` 桩和前端共用的无探针样本。两仓库各有一个 Epic，其中一个已结束。活动 Epic 有一个包含 12 张票、4 个拓扑层的 MMF，含 Halt、`close_pending` 和各类静态 lane 状态。`errors` 记录一条读不出的 map。

`probed.json` 模拟已取得现场结果的快照。Inbox 的三条 map 来自两个仓库，覆盖运行且现场工作、阻塞、已合入。直挂集成 lane 的 MMF 显示执行中；只有子票在执行的 Inbox 条目自身保持静态。它可以直接用于前端测试。空注册表对这两个样本的所有 running lane 均返回 `unknown`，命令桩使用 `board.json`。

快照字段由 `board_snapshot.py` 的 `BoardSnapshot` 与 `validate_snapshot` 定义，前端用 `apps/delivery-config/src/board.ts` 消费。Host 的 `validateBoard` 负责 JSON 与 schema 版本边界，原样传递通过的字节。`LIVE_PROBES` 按 runtime 前缀注册，`probe_lanes` 接受同一前缀的 lane 批次。

DD-671 负责打包。`board_snapshot.py` 与现有 `model_config.py` 同放在 `Contents/Resources/`，依赖脚本放到同级以保留 Python 导入路径。若打包期间仍需调用样本桩，`board_samples/board.json` 保持相对于快照命令的同级子目录路径。

## DD-668 场景验收分工

| 场景 | 验收票及入口 |
| --- | --- |
| S1–S5、S7 | DD-670，快照命令 |
| S6、S10 | DD-675，左栏与回前台刷新 |
| S8 | DD-670，快照合同；DD-672，启动与设置入口 |
| S9 | DD-671，Host 错误返回；DD-672，读取失败页与重试 |
| S11 | DD-674，中栏依赖图与选中；DD-675，右栏联动 |
| S12 | DD-670，真实快照；DD-675，打包 App 使用真实数据 |
| S13、S14、S20、S21 | DD-673，现场探针与执行状态 |
| S15、S17、S18 | DD-674，卡片状态、动画和视口 |
| S16 | DD-674，状态更新后的执行标识；DD-675，真实回前台联动 |
| S19 | DD-670，Inbox 归组；DD-675，Inbox 展示 |
| S22 | DD-672，左右栏折叠 |
