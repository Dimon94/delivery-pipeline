# HITL 等待与恢复（Multica 编排）

需要人参与时的完整写读链路。新 coordinator 会话读完本文件 + SKILL.md 应能独立完成一次
HITL 等待，无需口头补充。交互定案：复用现有会话列表/消息视图/输入框，不新增「待我参与」
页面或独立审批模块（决策 01/06，原型变体 B 已验证）。

## 进入等待（三件事，缺一不可）

当本 lane 到达必须由人回答的点（四类保留事项之一、授权失效、回投超限升级等）：

1. **chat 提问卡**：在**当前所属会话**（主控或子会话均可）发一条 assistant 消息，正文用
   中文人话写清问题与所需判断；消息 metadata 写等待指针——key 固定为 `waiting`
   （core 常量 `WAITING_METADATA_KEY`，`packages/core/issues/waiting-pointer.ts`），值为
   `{ who, what, ref? }` 三键：
   - `who`：等谁（首版恒为读会话的用户本人，渲染为「你」）；
   - `what`：等什么，人话（如「发布确认」），必填；
   - `ref`：票标识（如 `MUL-123`），可选但编排场景应填。
   技术字段不进入消息正文；UI 把指针渲染成「等待：你 · <什么>」的 meta 行。
   落库走 chat 消息写入路径（coordinator 作为 agent 在会话里产出 assistant 消息时
   携带 metadata 字段；`chat_message` 的 metadata 为既有 additive 载荷，core schema
   `ChatMessageSchema.metadata: z.record(...).optional()`，旧服务器缺席时 UI 安全降级，
   不需要任何 `chat_message` 新列——决策 07 明确不做）。
2. **Issue metadata 指针**：若该等待挂在某票上，`PUT /api/issues/{id}/metadata/waiting`，
   value 为 `{"who":"...","what":"...","ref":"..."}` 的 **JSON 字符串**（后端 V1 只收
   primitive，拒绝 object；UI 侧 `parseWaitingPointer` 对字符串形态做 `JSON.parse` 归一，
   已验证兼容）。单键原子写（issue_metadata.go 契约：key 匹配
   `^[a-zA-Z_][a-zA-Z0-9_.-]{0,63}$`，≤50 键）；
   不要用 `PUT /api/issues/{id}` 整体更新覆盖 metadata（会与其他 agent 写入竞争）。
3. **deferred**：当前工作行转入 deferred（宿主既有 deferred 原语），不占并发、不进
   claim 热路径；恢复时 PromoteDeferred 提升。

web/桌面 UI 提示（票 06/07 已交付）由 `waiting` 状态驱动：会话行琥珀徽章「等你回答」、
会话内顶部横幅、输入框 hint「回复将作为 <票标识> 的有效回答」。编排层负责写指针；
UI 消费归 `setSessionWaiting`（`packages/core/chat/store.ts`）与
`waiting-pointer.ts` 解析，指针缺失/缺字段时 UI 全部不渲染或退化为裸横幅——编排层
不补偿 UI 降级。

## 有效回答判定（编排层合同，核心不改）

- 有效回答 = 提问卡（带 `waiting` 指针的消息）**之后**该会话内第一条 member/user 消息；
  语义与 core `latestWaitingRef` 一致：从尾部往回扫，先遇 user 消息则等待已解除，先遇
  带指针的 assistant 消息则仍在等待。
- 回答只在**对应会话**有效：用户在别的会话回复不构成本 lane 的有效回答，不恢复。
- 回答到达后：恢复对应 deferred 工作；清除 Issue metadata `waiting` 键
  （`DELETE /api/issues/{id}/metadata/waiting`）；只恢复对应工作，其他 lane 不受影响。
- 已知边界（首版范围外，不要假装覆盖）：多用户抢答、等待超时、断线重连演示。

## 授权复用

- 授权按 `(question_key, applies_to)` 复用，**不设 TTL**（决策 05 Q6）：
  - `question_key`：问题的稳定键（如 `auto-integration`、`push-remote`）；
  - `applies_to`：授权绑定的 SHA/ref。
- 两者一致 → 直接复用，不再提问；任一不一致 → 授权失效，重新提问（即四类保留事项
  第 4 类）。
- 授权记录落 Issue metadata（如 `authz.<question_key>` = `<applies_to>` 字符串），
  与 `waiting` 键互不覆盖（单键原子写的存在意义）。
- 首个真实用例：首次自动 integration 前问一次，之后按本机制复用（决策 05 Q7）。

## 失败与升级

- 验收失败自动回投原 lane（附证据），失败签名 = 同 verdict + 同 SHA 计同一签名；
  同签名 2 次上限后升级 HITL（本文件的进入等待流程）；不自动换 fresh lane。
- 取消/失败后是否改派由 coordinator 在唤醒点决策；平台不自动推进（决策 03 Q5）。
- 用户主动取消：走宿主既有 cancel → Finalize 自动提交 checkpoint → PriorSessionID 接续
  链路；worktree 已回收时显式披露断链，走分支 + Issue 正文重建（决策 04 Q2/Q5）。
  恢复演练脚本见票 09 产物，本文件只定义语义。

## 不做什么

- 不新增审批/答题模块、聚合页、`chat_message` 新列；HITL 判定全部在编排层。
- 不把主控/子会话层级当作是否需要人参与的信号；HITL/AFK 是工作分类，等待是当前状态。
