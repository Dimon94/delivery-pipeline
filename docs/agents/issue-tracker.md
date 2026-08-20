# Issue tracker

本仓的 issue 归 GitHub,项目坐标 `Dimon94/delivery-pipeline`。所有操作走 `gh` CLI(在 clone 内自动识别 remote)。

## 约定

- **建 issue**:`gh issue create --title "..." --body "..."`,多行 body 用 heredoc。
- **读 issue**:`gh issue view <number> --comments`。
- **列 issue**:`gh issue list --state open --json number,title,body,labels`,按需加 `--label` 过滤。
- **评论**:`gh issue comment <number> --body "..."`。
- **打标/摘标**:`gh issue edit <number> --add-label "..."` / `--remove-label "..."`。
- **关闭**:`gh issue close <number> --comment "..."`。
- **triage 标签**:五个 canonical 角色的映射见 repo://docs/agents/triage-labels.md。

`.scratch/<feature>/` 是 feature 工作区(分析、repair 草案),不是 issue tracker;issue 只归 GitHub。

**PR 不作为 request 表面。**(如需把外部 PR 纳入 triage 队列,把此旗标改为 yes,triage 会按同套标签读外部 PR。)

## 当 skill 说 "publish to the issue tracker"

在本仓 GitHub Issues 创建 issue。

## 当 skill 说 "fetch the relevant ticket"

`gh issue view <number> --comments`。

## 阻断与依赖

阻断语义以 issue body 里的 `Blocked by: #x #y` 文字为准。判断是否解除阻断,读被引用 issue 的状态是否 closed。

## Wayfinding 编排

- **map**:一个 issue,label `wayfinder:map`。
- **子 ticket**:普通 issue,label `wayfinder:map-<map_number>`(归属)+ `wayfinder:research|prototype|grilling|task`(类型);body 首行写 `Map: #<map_number>`。
- **frontier 查询**:`gh issue list --label wayfinder:map-<n> --state open`,排除带 `wayfinder:claimed` 的、以及 body 中 `Blocked by` 未闭合的。
- **认领**:会话开工前给 ticket 加 label `wayfinder:claimed`;做完写 resolution comment、close issue、回 map 的 Decisions-so-far 追加一行索引。
- `wayfinder:map-<n>` 标签随地图创建即时新建;静态标签(map/claimed/四种类型)已预建。
