# Fresh Session Boundaries

新 coordinator 会话或恢复 named map 时读取。

## Coordinator

当前调用会话就是 coordinator；记录 `pi-cli | codex-cli | claude-cli`，模型沿当前会话，不读取
worker role config。恢复只依赖 repo instructions、tracker、Git、latest lane registry 与当前 gate
所需 reference，不重读未变化的 owner body。

## Worker Session

每条 configured worker lane 都是 fresh Herdr pane + fresh Execution Worktree。Packet 只包含本 role/
work item、resolved owner path、配置的 agent/model/effort、允许/禁止范围与持久坐标；worker 不继承
coordinator 对话，也不领取 sibling。

- planning worker：一个 research/spec/tickets gate及其持久 artifact。
- design/frontend/backend worker：一张 implementation/HITL work item。
- testing worker：一次 whole-change checks与证据。
- review worker：一次 code-review verdict与证据。

## Recovery

新会话先从 registry 枚举所有 active writer；Herdr lane 按 stored runtime/model/effort 恢复，不应用
新 config。路径、pane或 Git 证据不唯一时记 Unknown并停止 replacement。只有事实变化或
coordinator session 改变时重读对应边界。
