# 本机模型设置

MyGo 0.7.4 的网页窗口。读取、能力核验与保存复用 setup 的 canonical `model_config.py show/probe/apply`，不维护第二份 schema。五个工作项与四格检查显示主配置；其他 work 和预设只展示概览。模型身份留在快照，普通界面只显示易读名称；未知名称显示待识别。

构建依赖 Go（模块要求 ≥1.27.3）、Bun、Python ≥3.10：

```sh
cd apps/delivery-config
bun install --frozen-lockfile
python3 build.py --python /absolute/path/to/python3 --install
```

构建验证解释器版本，将绝对路径绑定到二进制，并把仓内 canonical 工具及附带 MIT 许可的 Tomli 2.2.1（Python 3.10 的 TOML fallback）原样复制到 `.app/Contents/Resources`；再进行 ad-hoc 签名。安装位置为 `~/Applications/Delivery Pipeline Settings.app`。

升级：重新运行同一条 `python3 build.py --python /absolute/path/to/python3 --install` 即可，不必先删旧版。同一 bundle id（`com.dimon.delivery-pipeline.settings`）的旧应用会被整体替换：新包先复制到同目录临时位置并验签，通过后才与旧包交换，最后删除备份；备份删不掉时安装仍算成功，会打印警告和残留路径，请手动删除。安装开始前会清掉同目录下本应用遗留的 `.<应用名>.new-*`、`.<应用名>.old-*`（只匹配本应用名前缀；目标不存在时保留 `.old-*`，它可能是回滚失败后唯一的旧包）。以下情况安装会停下并说明原因，旧应用保持原样、不留临时件：`running`（应用正在运行，或 `ps` 失败而无法确认是否在运行，先退出再装/排查后重试）、`foreign_bundle`（目标位置是其他应用，或是符号链接，不替换链接）、`copy_failed`（新包复制、验签或交换失败；交换失败会回滚，若回滚也失败，消息会给出备份的完整路径，请手动改回）。原因解除后重新运行即可。构建只产出这一个 bundle id，没有改 bundle id 的参数。`install(app, destination)` 可被导入；根目录 `python3 scripts/check_config_install.py` 用临时目录里的假 `.app` 检查上述行为（已接入 `validate.py`）。安装后从 Finder 双击，不依赖 shell PATH、当前目录或构建树。解释器被移动或卸载时，请让 AI 助手重新绑定并构建安装；不会静默安装依赖。Developer ID、公证和跨机器分发不在本机验收范围内。

构建号：每次构建由三段组成——提交短哈希、工作区有未提交改动（含未跟踪文件，不含被 `.gitignore` 排除的文件）时加 `+未提交`、构建时间（UTC），例如 `658b108 · 2026-11-16 06:40Z`。同一个构建号经 ldflags（`main.buildCommit/buildDirty/builtAt`）注入二进制，页面右上角显示“本机设置 · <构建号>”（用测试配置打开时为“测试配置 · <构建号>”，见下）；并在签名前写入 `Info.plist` 的 `CFBundleVersion`，Finder“显示简介”可见。读不到 git 时提交部分为 `unknown`，构建不中断；页面取不到构建号显示“构建号未知”，不影响读配置。构建和安装命令结束时打印构建号与 `.app` 路径（安装后为安装位置）。

配置默认读取 `~/.config/delivery-pipeline/model-roles.json`，不自动初始化、修复或迁移；仅在用户预览并明确确认后保存。缺失、损坏、旧版、非法结构、不可读分别引导助手处理，处理后点击“重新读取”。能力状态 Unknown，读取成功不代表模型运行或额度验证成功。显式预设和旧 lane 的既有规则保持。

隔离验收（同一 App 加 `--config`）：不另发测试包，也不改 bundle id。用同一个 App 加启动参数打开，例如 `open -n "<.app 路径>" --args --config /tmp/<测试配置>.json`；`--config` 后必须是绝对路径；多个 `--config` 以最后一个为准，最后一个是相对路径或缺值就视为没有参数，退回环境变量或正式配置，不回头采用前一个。页面标签变为“测试配置 · <构建号>”并换底色，悬停显示完整路径；读取、能力核对和保存都只针对该路径。不带参数打开永远读 `~/.config/delivery-pipeline/model-roles.json`，页面标签为“本机设置 · <构建号>”；测试路径只存在于该进程，不写入任何持久位置。其他未知启动参数一律忽略。`--config` 优先于环境变量。开发用途另保留环境变量 `DELIVERY_CONFIG_TEST_PATH`（同样标为测试配置），不是验收的主要方式。

检查：根目录 `python3 scripts/check_config_show.py` 已接入 `scripts/validate.py`；本目录 `go test ./...` 穿过公开 Host 到真实 Python 进程，并覆盖 `hostFromArgs` 的启动参数解析。测试配置不能用来改写真实配置。Finder、窗口交互和异常恢复须另留本机证据，不能由这些命令替代。`scripts/check_config_apply.py` 验证桌面与 setup 的共享事务兼容性。

九格可编辑为窗口草稿，打开、保存成功和恢复后自动核对能力（页面可点“重新核对”），支持差异核对、返回与撤销；确认保存调用 apply，不调用 configure。草稿完整保留 CLI v6 文档及只读区。能力经 Host 的本机网关 GET 与 canonical `model_config.py probe` 归一化，三种工具独立报告；Unknown 保留原配置，只阻止缺证据的新选择。Probe 不验证认证、额度或模型执行。

`bun test src/draft.test.ts` 覆盖受控延迟与草稿行为，`go test ./...` 穿过真实 Python 公开入口。可重复的来源归一化合同由根 `scripts/check_config_probe.py` 进入 validate；真实 MyGo 证据独立记录。

保存经 Host.Apply 在明确确认后重新采集 probe，再调用 canonical apply；Host 不暴露 setup 权限。冲突重读以最新完整文档为起点，旧草稿仅供人工核对，必须重新选择与预览。保存结果待确认时只允许显式检查当前设置，不自动重试或回滚。独立诊断页可查看机器结果。

保存成功的主设置由新 lane 的默认 work 路径读取；显式点名的 mode 继续覆盖模型与思考程度，已有 lane 按原 registry 恢复。`python3 scripts/check_config_lane.py` 穿过公开 apply → resolve/start，检查默认精确身份（含 @ 后缀）、ticket/map 预设优先级和只读区保持；该检查不证明 transport 启动、旧 lane 恢复或模型实际执行，三者仍需独立运行证据。

DD-411：五 work 的备用列表不限长、允许重复，按编号位置编辑；差异显示完整顺序，确认后与主配置同事务保存。旧 CLI 配置必须先由 AI setup 显式迁移 v6；App 保持 v5。Host Interface 不变；备用消费与完整列表异常恢复扩展归后续票。

DD-412：返回与外观切换保留完整有序草稿，撤销恢复完整读取快照。冲突或待核实时禁止再次保存，显式 ReadConfig 失败继续保留；当前等于候选只陈述当前观察。另一有效文档作为新基线，页面展示旧草稿九格完整顺序供参考，重新选择、预览、确认；再次提交前拒绝仍保留参考。Host 不增加 Recover；`bun test src/recovery.test.ts` 验证完整列表恢复合同。

DD-511：四格候选支持增删改移，共享声明覆盖所有 work/review 引用身份（含备用）并保留已声明但不再引用的模型。声明按精确工具/原生模型共享，effort 不改变家族。v7 由 AI setup 显式迁移，App v5 不变。Draft.changes 包含 model_families，Editor.save 冻结完整候选；Host generic payload 不变。冲突/待确认旧草稿同时保留候选与声明，读回后需人工重新选择和预览，不自动重提。`bun test src/review.test.ts` 和 canonical `check_config_review.py --case candidate-family-transaction` 分别检查编辑与真实文件事务；GUI 与实际模型执行独立验收。
