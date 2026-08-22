# 04 — 迁移路径与原子性

Status: open
Type: wayfinder:grilling
Blocked by: 01, 02, 03

## Question

01、02、03 票决定了目标形态后，这张票要定怎么从当前状态迁移过去。
核心问题是原子性：一次性切换，还是渐进式迁移。

当前状态：
- `f6dd77b` 已提交 6 张决策票的修复
- 双树结构（`skills/` + `claude/skills/`）
- `pane-dispatch` 已在 `claude/skills/` 下（Claude-only）
- `install.sh` 支持 `--target codex|claude|all`
- `skill-bundle.json` 是双 entrypoint
- `validate.py` 断言双树结构

目标状态（01-03 票决定）：
- 可能是单树（`skills/delivery-pipeline/` 唯一编排器）
- 可能是三 skill（`delivery-pipeline` + `pane-dispatch` + `thread-dispatch`）
- `validate.py` 断言单树或三 skill 结构

要决定的点：

1. **迁移策略**。候选：
   - (a) 一次性切换：一个 commit 完成所有改动，`main` 直接从双树跳到单树/三 skill
   - (b) 渐进式：先合并 runtime 无关的文件（01），再拆 runtime 相关的（02），
     最后改 validate.py（03），每步一个 commit
   - (c) 平行宇宙：新建 `skills/delivery-pipeline-v2/`，新旧并存一段时间，
     验证稳定后删除旧版

2. **向后兼容**。迁移期间，`main` 上的 `install.sh` 是否必须始终工作？
   - 如果是，那每次 commit 都要保证 `install.sh --target all` 成功
   - 如果否，可以在一个 feature branch 上完成所有改动，最后一次性 merge

3. **回滚计划**。如果迁移后发现破坏了 Claude Code 或 Codex 的调用，如何回滚？
   - Git revert 是否足够（因为改动涉及文件删除/移动）
   - 是否需要保留旧结构的备份分支
   - `~/.claude/skills/delivery-pipeline` 和 `~/.codex/skills/delivery-pipeline` 的软链
     在迁移期间如何处理

4. **验证清单**。迁移完成后，如何验证没有破坏：
   - `python3 scripts/validate.py` 通过
   - `./scripts/install.sh --target all` 成功
   - Claude Code 能调用 `delivery-pipeline`（如何测试？）
   - Codex CLI 能调用 `delivery-pipeline`（如何测试？）
   - `pane-dispatch` 能正常派发 pane（如何测试？）

5. **与 07 票原始问题的关系**。按 invocation 拆分后，"双树漂移"问题是否自然消失？
   - 如果所有 runtime 无关的文件都合并了，就不存在"两份拷贝"的漂移问题
   - 如果仍有少量共享文件（比如 `CONTEXT.md`），是否需要同步机械？
   - 这张票是否应该关闭 07 票，还是 07 票的问题在拆分后仍然存在？

## 落地

决策定下后直接改文件（本 map 授权 execution）：按决策执行迁移，
更新 `.scratch/dispatch-routing-repair/issues/07-dual-tree-sync-strategy.md` 的状态
（关闭或保留），跑完整验证清单。
