# 06 — Codex 依赖供给面：install.sh 的 9 个硬门禁

Status: resolved
Type: wayfinder:grilling
Blocked by: 03

## Question

03 票已定下 owner 传递契约：**Codex pane 不需要本地持有 owner 副本**，owner 由派发方解析成
绝对 `SKILL.md` 路径写进 packet。契约这一面已经落地。剩下的是安装/供给面，与契约矛盾：

`./scripts/install.sh --target codex` **今天会直接失败退出**。已验证 `install.sh:11` 声明的
9 个依赖（wayfinder、grilling、domain-modeling、prototype、research、to-spec、to-tickets、
implement、code-review）在 `~/.codex/skills` 与 `~/.agents/skills` 下**全部缺失**——
`~/.codex/skills` 实有的只是 `.system`、`brainstorming-only`、`complexity-optimizer`、
`delivery-pipeline`(软链本仓)、`hatch-pet`、`thermo-nuclear-code-quality-review`。

于是安装被一个**按 03 契约并不需要**的前置条件卡死。三处相关代码：
`install.sh:158-174`（缺依赖即 `exit 1`）、`expose_codex_dependencies()`
（`install.sh:133-156`，遇断链也 `exit 1`）、`validate.py` 断言这两者必须存在
（`DEPENDENCIES` 元组 + `require()` 查 `expose_codex_dependencies`、`ln -s`）。

要决定的点：

1. **`DEPENDENCIES` 硬门禁的去向**。既然 Codex 侧不需要本地副本，这 9 个依赖检查是否
   应当降级成 warning、只在 `--target claude` 下检查、还是整体删除？注意 `validate.py`
   目前**断言** `install.sh` 里必须含 `DEPENDENCIES=(...)` 那一整行和
   `expose_codex_dependencies`，删除会同时打红闸门，两处要一起改。

2. **`expose_codex_dependencies()` 是否还有存在理由**。它的唯一作用是把
   `AGENTS_HOME` 下的依赖 symlink 进 `CODEX_HOME`，服务的正是 03 契约要取消的
   "按名字查找"路径。若保留，它是否该改成指向 plugin marketplace
   （`~/.claude/plugins/marketplaces/*/skills/*/<name>`）——但那是 plugin 内部布局、
   非公开契约，且升级/卸载即断链，而断链会让安装 `exit 1`。

3. **install 时是否需要验证 owner 可解析**。03 定的是 best-effort 探测 + fail closed
   报缺 owner（运行时）。要定安装期是否也做一次探测并报告哪些 owner 找不到——
   作为诊断信息而非阻塞条件。

4. **9 个依赖清单本身是否还准**。`skill-bundle.json` 的 `requires` 与 `install.sh` 的
   `DEPENDENCIES` 和 `validate.py` 的 `DEPENDENCIES` 三处重复且顺序被断言绑定
   （`validate.py` 查 `dependency order mismatch`）。若清单语义从"必须本地存在"变成
   "owner 归属说明"，这三处的表达形式要不要跟着改。

## 落地

决策定下后直接改文件（本 map 授权 execution）：按决策改 `install.sh` 与 `validate.py`，
跑 `python3 scripts/validate.py`，并实测 `./scripts/install.sh --target codex` 能通过。

## Answer

**事实修正（拷问中核查）**：票面"9 个依赖全部缺失、install 今天直接失败"已过时——
08-09 起 `~/.agents/skills` 下 9 个依赖全部以软链存在（指向本地 mattpocock/skills checkout），
门禁靠巧合供给"恰好通过"。症状消失，但设计矛盾仍在，按以下决策改造。

1. **硬失败删除**。`install.sh` 缺依赖 `exit 1` 块整块删除，`--skip-deps-check` 旗标
   随之删除（门禁没了它就是死参数）。03 契约下 Codex 本地有无副本不影响任何运行时
   行为，exit 1 守护的是已取消的按名查找路径。
2. **`expose_codex_dependencies()` 整体删除**，连同只服务它的 `has_codex_dependency()` /
   `find_codex_dependency()`。运行时解析链（`owner-skill-resolution.md` 第 4 步）本就
   直探 `AGENTS_HOME`，AGENTS→CODEX 软链桥冗余；不改指 plugin marketplace（内部布局
   非公开契约，升级即断链）。
3. **安装期诊断，非阻塞**。新增 `report_owner_availability()`：名单用 `python3` 从
   `skill-bundle.json requires` 读（无 python3 则打印跳过说明继续），探测
   plugin cache / `${CODEX_HOME}/skills` / `${AGENTS_HOME}/skills` 三处，每个 owner
   打一行 found-at 或 `MISSING`，永不 `exit 1`，三个 target 末尾都跑。session catalog
   一步 bash 探不到，由运行时覆盖。
4. **清单收敛为"声明 vs 校验"两处**。`skill-bundle.json requires` 不动（唯一事实源，
   语义本来就是归属说明）；`validate.py` 保留 `DEPENDENCIES` 常量与顺序断言作为锁
   manifest 的锚点；删 install.sh 4 条断言中死的 3 条，保留 `ln -s "$source" "$dest"`
   （守护软链安装本体机制，由 `install_codex()` 等满足）。

**验证**：`python3 scripts/validate.py` 通过；真机 `./scripts/install.sh --target codex`
通过并打印 9 个 owner 的 found-at 诊断；空 HOME 沙箱下 `--target all` 全部 `MISSING`
仍 `exit 0`。fog 区无可成票项。
