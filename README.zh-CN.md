# Delivery Pipeline

[English README](README.md)

一个可恢复的 Codex/Claude 交付链：

```text
idea/map -> discovery -> spec -> implementation tickets
  -> 自动分配 worktrees -> integration -> summary PR/MR
```

新会话里给出链路中的任意 issue 即可。skill 会沿 tracker relationships 向上、向下重建
map/spec/ticket 状态，并从最早未完成的 gate 自动继续。

各阶段 owner 保持权威：`wayfinder` 负责 discovery，`to-spec` 负责 spec，`to-tickets`
负责发布 implementation tickets，`implement` 负责单张票。orchestrator 只验证持久链接和
状态转换，不再增加第二套票面判断。

执行自动分配：每张 ready ticket 对应一个隔离的 worker 和一个 Git worktree——前端与设计走
Claude Code，后端走 Codex。
dependency 与 mutable-resource 冲突只串行受影响的 tickets。
每个被派发的 child 都保存 pane/thread ID、worktree、branch、commit 和生命周期状态。
新会话会先恢复已有 child 并重挂 terminal listener。Claude 在集成与 focused checks 成功后
自动关闭对应 worker pane。
派发包会携带 owner skill 的 resolved `SKILL.md` 路径，因此用户调用型 stage owner 不依赖
子任务当前加载的 skill catalog。

## 依赖

**运行时** —— Claude Code、Codex 或两者（双端 bundle，可只装一端）。

**Owner skills** —— 全部来自 [mattpocock-skills](https://github.com/mattpocock/skills)。机器可读清单在 `skill-bundle.json` 的 `requires`，安装器会诊断缺失项：

- Discovery：`wayfinder`、`grilling`、`domain-modeling`、`prototype`、`research`
- 交付：`to-spec`、`to-tickets`、`implement`、`code-review`
- 集成/收尾：`resolving-merge-conflicts`

**Herdr** —— 承载派出会话的终端 multiplexer（CLI + `herdr` skill）。独立组件，本仓库不附带；使用 pane 派发前按其自身文档安装。

## 安装

1. 安装 owner skills。
   - Claude Code：`/plugin install mattpocock-skills@claude-plugins-official`
   - Codex：clone 源仓库，把每个 owner 软链进 skills 目录：
     ```bash
     git clone https://github.com/mattpocock/skills && cd skills
     for s in wayfinder grilling domain-modeling prototype research to-spec to-tickets implement code-review resolving-merge-conflicts; do
       ln -s "$(find "$PWD/skills" -maxdepth 2 -type d -name "$s")" "${AGENTS_HOME:-$HOME/.agents}/skills/$s"
     done
     ```
2. 安装本 bundle——两端都软链到当前 checkout，并附带 pre-commit 校验器：
   ```bash
   ./scripts/install.sh --target all
   ```
   安装器末尾输出依赖可用性诊断（owner skills + Herdr CLI/skill）；任何 `MISSING` 行就是还没装的组件。
3. 在某个项目 repo 首次使用前，先在那里运行一次 `setup-matt-pocock-skills` skill，配置 owner skills 依赖的 issue tracker、triage 标签和 domain 文档。

## 使用

用链路中的任意节点启动——skill 会沿 tracker 关系重建链路，从最早未完成的 gate 继续，所以任何阶段的 map 都能接入：

1. **Discovery**——松散想法建成 Wayfinder map（建图拷问在当前会话进行，不派发）。调研票派后台 subagent，拷问票和原型票派独立 Claude pane。
2. **Spec → Tickets**——`to-spec` 发布 spec；`to-tickets` 发布带链接的 implementation tickets。
3. **Dispatch**——每张 implementation ticket 一个 worktree + 一个 execution pane：前端/设计票走 Claude Code（默认模型），后端票走 Codex。
4. **托管与回报**——派出的会话自主执行（HITL 票直接与用户对话）。terminal 后 listener 唤醒调度会话，验证 final report、集成 commit，然后派发下一批。
5. **收尾**——graph 清空后 rebase、push，产出一个 summary PR/MR。

Codex：

```text
使用 $delivery-pipeline 继续 <任意 map/spec/ticket issue>。
```

Claude（通过 `/herdr` skill 管理 panes）：

```text
使用 /delivery-pipeline <任意 map/spec/ticket issue>。
```

## 校验

```bash
python3 scripts/validate.py
```

`scripts/install.sh` 会同时安装 `scripts/hooks/pre-commit`：它对**暂存树**跑校验器，
红灯直接拒绝 commit。`--no-hooks` 可跳过安装，`--no-verify` 可主动绕过。同一个校验器
在 CI（`.github/workflows/validate.yml`）里再跑一遍，为新 clone 兜底。

Skill 引用写法按 runtime 区分并强制校验：Codex 树（`skills/`）用 `$name`，
Claude 树（`claude/skills/`）用 `/mattpocock-skills:name`。Codex 树里出现 Claude
plugin locator 会被拒绝——那种写法在 Codex 下无法解析。
