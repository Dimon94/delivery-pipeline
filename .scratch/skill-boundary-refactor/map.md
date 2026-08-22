# 重构 delivery-pipeline skill 边界：按 invocation 拆分

Status: open
Type: wayfinder:map

## Destination

`delivery-pipeline` 的 skill 结构按 invocation 边界重组：编排器逻辑（runtime 无关）合并为单树，
runtime 相关的派发机制各自独立。消除"双树同步"这个伪问题——不是通过同步机械，而是通过正确的边界拆分。
完成后，`skills/delivery-pipeline/` 是唯一的编排器（Claude Code CLI 和 Codex CLI 共用），
`claude/skills/pane-dispatch/` 是 Claude 特有的 pane 派发，未来的 `thread-dispatch` 是 Codex app 特有的 thread 派发。

## Notes

**领域**：Codex/Claude skill bundle。当前是双树结构（`skills/` 供 Codex，`claude/skills/` 供 Claude Code），
试图维护"一个 skill 的两份拷贝"，但这是错误的边界。

**核心洞察**（来自 07 票的讨论）：CLI 层面 Claude Code 和 Codex 是一样的，差异只在 Codex app 的跨线程调度。
真正的边界不是"两个 runtime 的两份拷贝"，而是 invocation——agent 在什么情境下调用它。

**已定方向**：
- 编排器（推进 gate、持有 frontier/registry）是 runtime 无关的，应该只有一份
- 派发机制（pane vs thread）是 runtime 相关的，应该各自独立
- `pane-dispatch` 已经按这个原则拆了（04 票），现在要把同样的逻辑应用到 `delivery-pipeline` 本身

**本图授权 execution**：每张票定下决策的同时直接改文件。理由：这是结构性重构，决策和落地无法分离。
风险自觉：这是在改 delivery-pipeline 自身，改动后必须跑 `python3 scripts/validate.py`，并验证 `install.sh` 仍然工作。

**每张票收尾**：跑 `python3 scripts/validate.py`；更新 CONTEXT.md 术语表（如果有新概念）；按需 local commit。

**consult 的 skills**：`/mattpocock-skills:grilling`、`/mattpocock-skills:domain-modeling`、`/mattpocock-skills:writing-for-agents`（skill 拆分原则）。

**前置工作**：`f6dd77b` 已提交 6 张决策票的修复（agent kind 绑定、HITL 自动 pane、Codex owner 解析、
pane-dispatch 合并、validate.py 闸门、install.sh 依赖供给）。当前 main 领先 origin/main 两个 commit。

## Decisions so far

<!-- one line per closed ticket -->

## Not yet specified

- **thread-dispatch 的形态**：Codex app 的跨线程调度具体长什么样，是否与 pane-dispatch 对称。
  当前只有 `pane-dispatch`（Claude 侧），Codex 侧的 thread-based dispatch 还没有独立 skill。
  等第一个 runtime 相关文件拆出去后，这个 fog 会清晰。

- **迁移路径的原子性**：双树合并成单树是一次性切换，还是渐进式迁移（先合并 runtime 无关的文件，
  再拆 runtime 相关的）。这取决于 `install.sh` 和 `skill-bundle.json` 能否支持中间态。

- **07 票的原始问题是否还存在**：按 invocation 拆分后，"双树漂移"问题是否自然消失，
  还是仍有少量共享文件需要同步机械。等拆分边界定下后重新评估。

## Out of scope
