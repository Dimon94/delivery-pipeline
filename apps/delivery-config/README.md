# 本机模型设置

MyGo 0.7.4 的网页窗口。读取、能力核验与保存复用 setup 的 canonical `model_config.py show/probe/apply`，不维护第二份 schema。五个工作项与四格检查显示主配置；其他 work 和预设只展示概览。模型身份留在快照，普通界面只显示易读名称；未知名称显示待识别。

构建依赖 Go（模块要求 ≥1.27.3）、Bun、Python ≥3.10：

```sh
cd apps/delivery-config
bun install --frozen-lockfile
python3 build.py --python /absolute/path/to/python3 --install
```

构建验证解释器版本，将绝对路径绑定到二进制，并把仓内 canonical 工具及附带 MIT 许可的 Tomli 2.2.1（Python 3.10 的 TOML fallback）原样复制到 `.app/Contents/Resources`；再进行 ad-hoc 签名。安装位置为 `~/Applications/Delivery Pipeline Settings.app`。安装脚本遇已有应用即停止，不覆盖。安装后从 Finder 双击，不依赖 shell PATH、当前目录或构建树。解释器被移动或卸载时，请让 AI 助手重新绑定并构建安装；不会静默安装依赖。Developer ID、公证和跨机器分发不在本机验收范围内。

配置默认读取 `~/.config/delivery-pipeline/model-roles.json`，不自动初始化、修复或迁移；仅在用户预览并明确确认后保存。缺失、损坏、旧版、非法结构、不可读分别引导助手处理，处理后点击“重新读取”。能力状态 Unknown，读取成功不代表模型运行或额度验证成功。显式预设和旧 lane 的既有规则保持。

检查：根目录 `python3 scripts/check_config_show.py` 已接入 `scripts/validate.py`；本目录 `go test ./...` 穿过公开 Host 到真实 Python 进程。`DELIVERY_CONFIG_TEST_PATH` 可让受控独立测试进程读取临时配置，不能用它改写真实配置。Finder、窗口交互和异常恢复须另留本机证据，不能由这些命令替代。`scripts/check_config_apply.py` 验证桌面与 setup 的共享事务兼容性。

九格可编辑为窗口草稿，支持能力刷新、差异核对、返回与撤销；确认保存调用 apply，不调用 configure。草稿完整保留 CLI v6 文档及只读区。能力经 Host 的本机网关 GET 与 canonical `model_config.py probe` 归一化，三种工具独立报告；Unknown 保留原配置，只阻止缺证据的新选择。Probe 不验证认证、额度或模型执行。

`bun test src/draft.test.ts` 覆盖受控延迟与草稿行为，`go test ./...` 穿过真实 Python 公开入口。可重复的来源归一化合同由根 `scripts/check_config_probe.py` 进入 validate；真实 MyGo 证据独立记录。

保存经 Host.Apply 在明确确认后刷新 probe，再调用 canonical apply；Host 不暴露 setup 权限。冲突重读以最新完整文档为起点，旧草稿仅供人工核对，必须重新选择与预览。保存结果待确认时只允许显式检查当前设置，不自动重试或回滚。独立诊断页可查看机器结果。

保存成功的主设置由新 lane 的默认 work 路径读取；显式点名的 mode 继续覆盖模型与思考程度，已有 lane 按原 registry 恢复。`python3 scripts/check_config_lane.py` 穿过公开 apply → resolve/start，检查默认精确身份（含 @ 后缀）、ticket/map 预设优先级和只读区保持；该检查不证明 transport 启动、旧 lane 恢复或模型实际执行，三者仍需独立运行证据。

DD-411：五 work 的备用列表不限长、允许重复，按编号位置编辑；差异显示完整顺序，确认后与主配置同事务保存。旧 CLI 配置必须先由 AI setup 显式迁移 v6；App 保持 v5。Host Interface 不变；备用消费与完整列表异常恢复扩展归后续票。

DD-412：返回与外观切换保留完整有序草稿，撤销恢复完整读取快照。冲突或待核实时禁止再次保存，显式 ReadConfig 失败继续保留；当前等于候选只陈述当前观察。另一有效文档作为新基线，页面展示旧草稿九格完整顺序供参考，重新选择、预览、确认；再次提交前拒绝仍保留参考。Host 不增加 Recover；`bun test src/recovery.test.ts` 验证完整列表恢复合同。

DD-511：四格候选支持增删改移，共享声明覆盖所有 work/review 引用身份（含备用）并保留已声明但不再引用的模型。声明按精确工具/原生模型共享，effort 不改变家族。v7 由 AI setup 显式迁移，App v5 不变。Draft.changes 包含 model_families，Editor.save 冻结完整候选；Host generic payload 不变。冲突/待确认旧草稿同时保留候选与声明，读回后需人工重新选择和预览，不自动重提。`bun test src/review.test.ts` 和 canonical `check_config_review.py --case candidate-family-transaction` 分别检查编辑与真实文件事务；GUI 与实际模型执行独立验收。
