# 验收与恢复（Multica 编排）

验收判据、失败签名与自动回投上限、授权复用流的完整合同。新 coordinator 会话读完本文件
+ SKILL.md 应能独立完成一次验收与一次失败处理，无需口头补充。术语与权责表以
`../SKILL.md` 为准；等待三件套与有效回答判定见 `hitl-waiting-recovery.md`，本文件只
在其边界处引用，不重复定义。

## 验收判据

worker 终态回流到达后，coordinator 对该 run 做验收。判定输入全部来自持久证据
（Git/Daemon 读回、queue 终态、Issue metadata），不信 worker 汇报、不信内存。

### 默认判据（三件套，全部 pass 才算 pass）

1. **产物存在**：终态回流所述产物在其声明位置实际存在——文件系统读回、
   Git 读回（分支/SHA/diff）核对，不采信 worker 自述。
2. **CI 绿**：该票声明的 checks 全绿（本地实跑或读 CI 状态）；checks 集合 = 票正文
   明示的检查命令，缺省时按宿主该工作区标准检查集（frontend `pnpm typecheck` 等）。
3. **状态机到位**：`agent_task_queue` 中本 run 任务行已达终态（completed/failed/
   cancelled），不存在同票残留 `queued|dispatched|running` 行；Issue metadata 无悬空
   `waiting` 指针指向已结束的工作。

### 票正文追加项

- 位置：Issue 正文 `## Orchestration` 块的 `acceptance` 数组（格式定义见 SKILL.md
  依赖声明格式节），每条一个字符串判据。
- 写法要求：可执行、可观察（如「产物 x 存在于 artifacts/<lane>/」「pnpm typecheck
  绿」）；不可观察的判据视为书写缺陷，验收时记 fail 并升级（属范围/判据变更，四类
  保留事项第 3 类，不得由 coordinator 自行改写）。
- 缺省或空数组 = 仅默认三件套。
- 追加项与默认判据是**追加**关系：默认三件套永远适用，不得用追加项豁免。

### verdict 记录（投影，不建新表）

验收结论投影到 Issue metadata（决策 07：review verdict 不建新表，首版落 Issue
正文/metadata 投影）：

- key 固定为 `verdict`；value 为 JSON 字符串（后端 V1 只收 primitive，见
  cross-check 已知偏差 1）：
  `{"verdict":"pass|fail","reason":"<失败判据的人话概括，fail 时必填>","sha":"<被验收 run 的 HEAD SHA>","sig_count":<同签名连续次数>}`
- 单键原子写（`PUT /api/issues/{id}/metadata/verdict`），与 `waiting`、`authz.*` 键
  互不覆盖。每次验收覆盖写最新一条；历史追溯依赖 chat 汇报消息，不追求 metadata 内
  留存全量历史。

## 失败签名与自动回投

- **失败签名** = `(verdict, SHA)`：同 verdict（归一化后的失败原因）+ 同 SHA 计同一
  签名。SHA 变了（worker 改了代码）或失败原因变了 = 新签名。
- **自动回投**：验收 fail → 自动回投**原 lane**（附证据：失败判据、verdict、SHA、
  日志/产物指针）；回投是一次新派发，按 `dispatch-frontier.md` 生成新 lane-id 后缀的
  `orchestration_ref`，不复用旧引用。**不自动换 fresh lane**。
- **计数与上限**：读 `verdict` metadata，与本次失败比对——同签名则 `sig_count+1`，
  新签名则重置为 1，然后覆盖写回。同签名达 **2 次**（即第二次失败）后**升级 HITL**：
  走 `hitl-waiting-recovery.md` 进入等待三件套（chat 提问卡 + Issue metadata
  `waiting` 指针 + deferred），不再自动回投第三次。
- 升级后的改派/换 lane/改票由 coordinator 在唤醒点按用户回答决策；平台不自动推进
  （决策 03 Q5）。签名计数按票独立；一票升级只影响该票及其传递依赖方，其余
  frontier 照常推进。

## 授权复用流

授权按 `(question_key, applies_to)` 复用，**不设 TTL**（决策 05 Q6）：

- `question_key`：问题的稳定键（如 `auto-integration`、`push-remote`）；
- `applies_to`：授权绑定的对象（SHA/ref）。
- **记录**：Issue metadata `authz.<question_key>` = `<applies_to>` 字符串（key 匹配
  metadata 键名正则；单键原子写，与 `waiting`/`verdict` 互不覆盖）。
- **命中**：待授权动作的 (question_key, applies_to) 与已记录值两者一致 → 直接复用，
  不再提问。
- **失效**：任一不一致 → 授权失效 → 属四类保留事项第 4 类，必须重新提问（走 HITL
  等待流程）；拿到新回答后覆盖写 `authz.<question_key>`。
- **首个真实用例**：首次自动 integration 前问一次（question_key=`auto-integration`，
  applies_to=被集成的 base SHA/ref），之后按本机制复用（决策 05 Q7）。
- **scope 外升级**：动作落在已授权 (question_key, applies_to) 集合之外，或本身属四类
  保留事项第 1–3 类（不可逆/动钱/范围变更）→ 不查授权、直接升级 HITL。授权只豁免
  同一键同一对象的重复提问，不创造新权限。

## 不做什么

- 不建 verdict 新表、不设授权 TTL、不自动改派 fresh lane、不在回投时复用旧
  `orchestration_ref`。
- 不由 coordinator 自行改写不可观察的验收判据（范围/判据变更永远留人）。
