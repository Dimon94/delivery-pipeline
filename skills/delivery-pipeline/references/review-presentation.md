# 审核页呈现（Plan Review / Merge Review）

`ask_human` 的 `kind` 为 `merge-review` 或 `plan-review` 时读取。审核页是人类决定“通过 / 退回”的唯一界面，按 `show-me` 的 PR / Review 原则组织：先看懂变更，再看证据，再判合入危险，最后对照计划。

## 事实基线与增补边界

- `args.html` 是 Driver 确定性渲染的事实基线（波次与关键路径流图、变更文件树、解析后的审查与检查证据、风险、自动偏差、逐票计划对照与测试策略）。保留 `args.html` 原件，不覆盖它。
- 当 `args.html` 的结构化内容已足以看清本次变更（如小范围直白改动），直接呈现 `args.html`。
- 当逻辑、调用链、状态机、UI 或跨模块接线需要领域视角才能一眼看懂时，在 `args.html` 同目录生成兄弟文件 `show-me-<kind>-review.html` 并呈现它。兄弟页必须保留 `args.html` 的全部事实结论（验收证据、风险、偏差、计划对照与回复指令），不得删减或编造数字；缺失事实写 `Unknown`。

## 四个必答板块（Merge Review）

1. **Summary（改了什么）**：选能让本次变更一眼看懂的最小视图，放在简短领域说明旁，不用长段散文替代：
   - 算法或门禁规则 → 伪代码
   - 运行时控制流 → 调用树（call tree）
   - 状态转换、跨模块交互或数据流 → 轻量 SVG / 流程图
   - 已有结构上的局部修改 → `diff` 草图（组件、文件布局、调用树或状态流 diff）
   - 涉及多目录的新增/重构 → 带一句职责注释的浅层文件树
2. **Evidence（证明跑通）**：展示具体 **Before / After** 与实跑结果，不贴裸文件路径或原始 JSON：
   - UI/视觉改动优先放真实对比截图
   - 逻辑与门禁改动放实际执行的检查命令、通过计数、关键观测结果，以及整体审查两轴（Standards / Spec）的 P0–P3 计数与发现
3. **Merge Danger（合入危险）**：
   - **Door**：标明 `two-way`（低成本回滚）还是 `one-way`（破坏性迁移、持久 schema、外部合同或难逆操作）及一句理由
   - **Blast Radius**：点名受影响的调用方、钩子、发布链或数据面，并列明剩余 `verification_gaps`、非阻断 P2/P3 与自动处理过的偏差
4. **Plan vs Delivery（计划对照）**：保留逐票计划验收与实际交付状态、测试策略和最终授权口令。

## Plan Review（旧 map）

保留 `args.html` 的波次、关键路径、逐票验收、测试策略与蜂巢预检（失败项醒目暴露）；仅当模块边界或依赖关系难以从波次图读出时，在兄弟页补一张最小边界图。

## 视觉与主题基线

- 颜色、字体、圆角全部走宿主主题 CSS 变量（`--foreground`、`--muted-foreground`、`--card`、`--secondary`、`--border`、`--primary`、`--success`、`--warning`、`--destructive`、`--code-background`、`--radius`、`--font-sans`、`--font-mono`），附独立浏览器明暗回退；不写死浅色或深色背景。
- `html`、`body` 和最外层容器不设页面背景、外边框、顶部横幅或左右大留白，不用 `vh` 或 `height: 100%`；宽屏（约 728px+）与窄屏（约 360px）均无横向挤爆。
- 用真实标签、真实提交短 SHA 与真实数据；所有长路径与原始 JSON 折进次级 `<details>`。

完成标准：用户看到一份可读、适配主题、回答 Summary / Evidence / Merge Danger / Plan vs Delivery 四问的审核页及明确回复指令，无裸 JSON 或裸证据路径。
