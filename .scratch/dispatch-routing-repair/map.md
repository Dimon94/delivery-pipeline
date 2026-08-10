# 修复派发路由：agent kind 绑定与 Codex owner 解析

Status: open
Type: wayfinder:map

## Destination

`/delivery-pipeline` 的派发链路能正确落地每一张 ticket：HITL 拷问票自动开
**Claude Code** pane 并在其中完成拷问，实现票自动开 **Codex** pane 并收到 Codex
能真正解析的 owner 指令。`dispatch-to-codex` 的派发机械并入本 repo、改造成融合后的
派发层，本地安装同步更新。改动直接落在本 repo 文件上，不只产出规格。

## Notes

**领域**：Codex/Claude skill bundle，双树结构（`skills/` 供 Codex，
`claude/skills/` 供 Claude Code），两棵树几乎全文件不同，每个修复都要落两遍。
`scripts/validate.py` 与 `scripts/install.sh` 是本 repo 自带的验证与安装闸门。

**本图授权 execution**（覆盖 Wayfinder 默认的 planning-only）：每张票在定下决策的
同时直接修改 repo 文件。理由：三个缺陷已定位到行号，剩余未知是设计取舍而非定位。
风险自觉：这是用 delivery-pipeline 改 delivery-pipeline 自身，改动落地后必须跑
`python3 scripts/validate.py`，并优先修复"派发正确性"再谈其他。

**每张票收尾**：跑 `python3 scripts/validate.py`；双树都改到；本 repo 已在 git 下，
按需 local commit。

**已定下的用户决策**（不要重新提问）：
- HITL 拷问票 = Claude Code pane；实现票 = Codex pane。
- HITL 票**自动开 pane**，拷问在新 pane 里进行，不停下流水线交还当前会话。
- 采用合并方案 C：把 `dispatch-to-codex` 并入本 repo 融合成派发层，再回灌
  `~/.claude/skills/dispatch-to-codex`。不抽第三方共享层。

**consult 的 skills**：`/mattpocock-skills:grilling`、
`/mattpocock-skills:domain-modeling`、`/do-not-repeat-yourself`（合并时避免二次重复）。

**闸门状态**：`python3 scripts/validate.py` 已恢复通过（05 已 resolved）。`2238745` 的
红灯真实规模是 8 条而非 1 条，详见 05 票。现在起 pre-commit hook 会对暂存树跑校验并
拒绝红灯 commit（`--no-verify` 可主动绕过），CI 兜底。写法面（Codex `$name` /
Claude plugin locator）已由闸门强制；内容跨树漂移仍无检查，见 07 票。

## Decisions so far

- [01 — agent kind 按 ticket 类别显式绑定](issues/01-bind-agent-kind.md) — `--kind` 写在 packet 模板内，按 label 查表选模板，缺失时 fail closed，tab-kind 交叉验证；融合后派发层不承载 kind 路由逻辑
- [02 — HITL 票自动开 pane：消除两份文件的矛盾](issues/02-hitl-auto-pane.md) — 删除"遇到 HITL 就停止"规则；lead 强制报告 pane 坐标，frontier 清空时停为 ask-user；packet 措辞改为交付方式说明；双树都改
- [03 — Codex pane 收到的 owner 指令必须是 Codex 能解析的](issues/03-codex-owner-resolution.md) — plugin locator 只准出现在 Claude 树、Codex 树由 `validate.py` 新禁则拦住；Codex 不需本地 owner 副本，靠派发方解析的绝对路径；供给面 graduate 成 06
- [04 — 把 Codex 派发抽成一个实质承载的独立 skill](issues/04-codex-dispatch-skill.md) — 新增 `pane-dispatch` skill（Claude-only 单树），kind-generic（claude|codex），职责边界为"已填 packet → 验证的 pane+listener → 回报坐标"；合并 dispatch-to-codex 机械（禁词替换 6 处 + 4 条机械修正）；delivery-pipeline 的 34 处 `/herdr` 引用改指 `/pane-dispatch`
- [05 — 修复被 2238745 打红的 validate 闸门](issues/05-restore-validate-gate.md) — invariant 改为分树断言 sigil（Codex `$name` / Claude plugin locator），消灭 `/wayfinder` 假阳性；`require()` 一次报全部错（真实红灯是 8 条不是 1 条）；防回归 = pre-commit hook 校验暂存树 + CI 兜底，hook 源码进版本库由 `install.sh` 安装；禁则只扫 `skills/`
- [06 — Codex 依赖供给面：install.sh 的 9 个硬门禁](issues/06-codex-dependency-supply.md) — 缺依赖 `exit 1` 与 `expose_codex_dependencies()` 整体删除（守护的是 03 已取消的按名查找路径），`--skip-deps-check` 同删；换装非阻塞 `report_owner_availability()` 诊断（名单读 `skill-bundle.json`，探 plugin cache/CODEX_HOME/AGENTS_HOME）；`validate.py` 只留 `ln -s` 软链机制断言，清单锚点保留

<!-- one line per closed ticket -->

## Not yet specified

- 新 Codex 派发 skill 的 tracker 坐标参数化形状：现在写死 GitLab IP 与
  `junbo/official/comic-drama-studio`。参数来源（repo tracker 文档 / 显式实参 / 环境变量）
  是 04 票第 5 点，但一旦定下，"本 repo 该不该有自己的 tracker 文档"会成为独立问题——
  本 repo 目前没有，Wayfinder 按约定落到 local-markdown。
- 多 skill repo 的骨架改造范围：`skill-bundle.json` 是单 entrypoint 格式
  （`codex`/`claude` 各一个），`install.sh` 的 `SKILL_NAME` 是单值常量，
  `validate.py` 的 `CODEX_ROOT`/`CLAUDE_ROOT` 也写死单 skill。容纳第二个 skill 要动这三处，
  具体改法等 04 票定下新 skill 的物理位置与安装形态。

## Out of scope
