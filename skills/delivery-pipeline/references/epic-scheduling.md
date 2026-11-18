# Epic 调度

启动或恢复已发布 Epic、收到 Epic lane 的唤醒，或恢复从属于 Epic 的单个 MMF 时读取。
Epic Issue 是目标、已确认 MMF 索引和跨 MMF 依赖的唯一来源。Spec Issue 保存各 MMF 的范围、
Interface 和验收。Wayfinder 的调查和决定留在决策 Issue。需要复用的调研或原型证据由 Issue 链接。

## 建立或恢复

1. 读回 Epic 正文、关系和相关决定。按 tracker 坐标识别用户输入，核实目标仓库，跨仓按本入口规则路由。
   用 Epic 上的稳定 MMF 标识关联已发布的 Map、Spec。精确链接、原生关系，或能同时读回
   `Epic: <URL>` 和 `MMF: <标识>` 的正文构成关联证据。已有 Epic 可以通过候选表和 Spec 链接恢复。
   标识或关系不唯一时暂停该项并报告缺口。
2. 对已确认的范围核对候选准备度。按 `wayfinder-frontier-loop.md` 处理影响拆分、Interface 或
   验收的调查与决定。未决项保留候选状态，其余就绪项继续。并发前读回共享 Module 的 owner、
   调用方所需的 Interface、测试使用的 Seam 以及共享写入的隔离方式。
3. 为每个依赖读回前置 MMF 或外部条件、受影响阶段和解除证据。开工依赖挡开发，发布时仍须成立。
   上线依赖挡相应验收或发布动作。Interface 提前确认的证据可解除对应开工边。
   需要真实验收的边等上游交付证据。用原生依赖发现关联，开工／上线时点和解除条件按 Epic 上的决定。
4. 核对每个 Map 的 registry、Git 和原宿主，确认 coordinator、active writers、最早未完成 gate
   与验收坐标。尚无 Map 时用 Epic URL 与 MMF 标识定位已有规划 lane。已有活跃 owner 时沿原现场接续或等待。
   确认缺少 Map 或 Spec 后交给对应 owner，
   创建时写入 Epic 与 MMF 标识，发布后汇总读回双向链接。中断后首先按原标识查找。
   原写入结果不明时保留该项并对账。

## 计算就绪批次

coordinator 将刚读回的资料标准化，经 stdin 运行核心 skill 的 `python3 scripts/epic_frontier.py`。
JSON 只用于本轮决策，恢复时重建。传入当前已批准结果所需的所有 MMF，按 Epic 优先级排序。
从单个 MMF 入口传入顶层 `mmf` 标识，只返回该项的可执行动作。`accepted` 与 `done` 仍报告 Epic 全局验收。

```json
{
  "epic": "https://tracker.example/issues/30",
  "items": [
    {"id": "A", "state": "development", "dependencies": []},
    {"id": "B", "state": "development", "dependencies": [
      {"source": "A", "gate": "development", "requires": "evidence", "evidence": null},
      {"source": "A", "gate": "release", "requires": "accepted"}
    ]}
  ]
}
```

- `id` 用 Epic 上的稳定标识。有坐标则带 `map` 和／或 `spec`，不同 MMF 各有其坐标。
- `state` 取 `candidate`（仍需细化）、`development`（可继续开发侧 gate，含 Map、Spec 和 tickets）、
  `release`（到达受上线依赖约束的动作）、`active`（已有执行者）、`blocked`（其他阻断或现场 Unknown）、
  `accepted`（有验收和交付证据，带 `acceptance` 指针）。`release`／`accepted` 都带 Spec URL。
- `dependencies` 空数组表示已确认无依赖。每边的 `source` 为前置 MMF 标识，外部条件用
  `external:<条件标识>`。`gate` 为 `development` 或 `release`。等待证据用 `requires: evidence`，
  核实后填具体指针，未核实填 `null`。等待上游实际验收用 `requires: accepted`。
- 输出含 `development`／`release` 就绪坐标、`active`、`waiting`、`accepted` 和 `done`。
  `cycle` 给出一条未解除的验收依赖环。校正相关关系，其余就绪项继续。非零退出先校正不一致的读回。

## 推进与收口

- 当前 Epic coordinator 按就绪批次推进各 Map 或独立 Spec 的最早未完成 gate，并创建所属壳的
  常规 lane。不同 MMF 可同批派发。各 Map 的批次、Integration 和单 active writer 各自核验。
  一个 Epic 由一个 coordinator 写入。接手前按各 Map 恢复合同核验原 owner 与现场。
- 新 Spec 调用 resolved `to-spec` owner，复用仍有效的确认，按原 gate 核验发布。已有 Spec 从实际 gate 续跑。
  用户启动 Epic 授权该范围内的常规 tracker 转换。发布 Spec 所需确认、权限与远程发布授权沿各自 gate。
- 派发 packet 列出本项的 Epic、Map／Spec、依赖和已确认决定的精确 Issue 指针，worker 开工前读回。
  Epic 和 Spec 的正式计划只持久化到 Issue。运行现场及恢复坐标沿原 registry／宿主合同。
- 任一 lane 回流后，先在所属 Map 完成 fan-in，再读回受影响的依赖并重算。各 Map 独立收口，
  发布前沿原合同核验目标分支与授权。报告本批推进项及各自阻断。全部已批准结果验收后才报告 Epic 完成。
