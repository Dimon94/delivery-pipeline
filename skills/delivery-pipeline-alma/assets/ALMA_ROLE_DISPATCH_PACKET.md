# Alma Role Dispatch Packet

派发与 FINAL_REPORT 使用 `../../delivery-pipeline/references/lane-registry.md` §轻量交接的
固定模板。仅展开当前分支，输入省略不适用项；本壳只追加三个回传字段：

```text
Coordinator thread：<原生 threadId>
Task tool transport：alma-task
Terminal 回传合同：<absolute alma-dispatch.md，读取 Terminal 回传节>
```

coordinator 先持久化完整 Alma overlay；公共模板的 Registry 指向本 lane，输入引用其
config_path、direct_target 与实施前置证据，传当前请求值（model）。
Review 分支的输入包含 scope、fixed point、owner 三字段、两轴配置与 preflight 绝对路径。
Execution Worktree 由 coordinator 创建，startup 后补真实坐标，派发前完成隔离核验。

## 按分支加载

worker 从本节进入，每次调用的执行核验按当前 role/output_mode 与冻结配置选行；按标题读取
完整章节及子节，到下一个同级或更高标题前停止。所有分支共用 Terminal 回传合同。

### 你是谁

**你是一个 Alma Task worker**，从 handoff packet 的 `artifactRefs` 中找到本文件的绝对路径并读取。
先读"Terminal 回传合同"，再根据你的 `output_mode` 跳到对应章节：

- `artifact` → §Artifact Lane
- `commit` → §Commit Lane
- 其他 output_mode → 不使用本 packet；coordinator 直接通过 subagent 入口调用

### Terminal 回传合同

所有 output mode 共用本节。

1. 按你的 output_mode 完成工作（见对应章节）
2. 完成所有必要的文件修改、commit 或 artifact 生成
3. 组装 FINAL_REPORT（按 `../../delivery-pipeline/references/lane-registry.md` §轻量交接 - 终态模板）：
   - `Lane ID`：你的 lane_id
   - `状态`：completed | blocked
   - `交付`：commit SHA 或 artifact 坐标
   - `证据`：完整命令/结果、Git 现场
   - `现场`：HEAD、dirty 状态、dirty/untracked 路径
   - `确认`：用户决定（无新增写"无"）
   - `阻断`：原因与失败工件（无阻断写"无"）
4. **在最终回复中输出**：`LANE_DONE <你的 lane_id>`

coordinator 通过检测这个标记 + Task status + 持久证据来确认完成。缺少此标记将导致 coordinator 无法识别。

## §Artifact Lane

**适用于**：planning、research、prototype、design HITL（`output_mode: artifact`）

### 输入

从 handoff packet 的 `artifactRefs` 读取：
- Spec 或需求文档路径
- Tracker ticket URL
- 相关背景材料

### 执行

1. 读取输入材料，理解需求
2. 完成你的工作：
   - planning：产出 Wayfinder map、spec 或 tickets
   - research：产出调研报告
   - prototype：产出原型或设计草图
   - design HITL：与用户沟通，产出设计决策
3. 将产物保存到明确的文件路径（repo 内或 repo 外）
4. 更新 tracker：记录决策、关闭已完成的 decision ticket

### 产物

- `artifact_path`：你产出的主要文件的绝对路径
- `tracker_updated`：是否已更新 tracker

### 回传

按"Terminal 回传合同"组装 FINAL_REPORT，`交付` 写 artifact 坐标，包含 `LANE_DONE <lane_id>` 标记。

## §Commit Lane

**适用于**：design、frontend、backend implementation（`output_mode: commit`）

### 输入

从 handoff packet 的 `artifactRefs` 读取：
- **Execution Worktree 绝对路径**（你的所有命令必须显式指向该路径，不要假设当前目录）
- Execution branch 名称
- Spec 文档路径
- Ticket URL
- Integration base commit
- Review evidence preflight 绝对路径（用于自评）

### 约束

- **只修改 Execution Worktree 内的文件**，不修改 Source 或 Integration Worktree
- 所有 Git 命令使用 `-C <Execution Worktree>` 或 `--git-dir` 显式指定工作目录
- Commit message 使用中文
- 代码符合项目风格
- 通过相关测试

### 执行

1. 读取 spec 和 ticket，理解需求
2. **在 Execution Worktree 内**实现功能（所有命令显式指定路径）
3. 运行测试，确保通过
4. 产出一个清晰的 commit
5. （可选）按 Review evidence preflight 运行自评，但**自评不能放行**

### 产物

- `head_commit`：Execution branch 当前 HEAD
- `candidate_commit`：可 merge 的 commit SHA
- `execution_worktree`：Execution Worktree 绝对路径
- `execution_branch`：分支名
- `dirty_state`：`clean`（无未提交修改）或 `declared-dirty`（有已知的合理未提交修改）
- `dirty_paths`：如果 declared-dirty，列出路径和原因

### 回传

按"Terminal 回传合同"组装 FINAL_REPORT，`交付` 写 candidate_commit SHA，包含 `LANE_DONE <lane_id>` 标记。

如果你无法完成（遇到阻碍、需求不清晰、测试失败等），设置 `状态: blocked` 并说明原因，仍然输出 `LANE_DONE` 标记。

---

## 调试提示

如果 coordinator 没有收到你的完成通知：

1. 检查你的最终回复是否包含 `LANE_DONE <lane_id>` 标记
2. 确认 lane_id 字面相等（不要加引号、前缀或后缀）
3. 确认 FINAL_REPORT 格式正确，BEGIN/END 配对

如果你遇到权限问题或工具不可用：

1. 保存你已完成的工作
2. 在 FINAL_REPORT 中设置 `状态: blocked`
3. 详细说明 `阻断` 与 `证据`
4. 仍然输出 `LANE_DONE <lane_id>` 标记，让 coordinator 知道你已停止
