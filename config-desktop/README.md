# 本机模型设置

MyGo 0.7.4 的网页窗口，当前只读。数据来自 setup 的 canonical `model_config.py show`，不维护第二份 schema，也不调用网关。五个工作项与四格检查显示主配置；其他 work 和预设只展示概览。模型身份留在快照，普通界面只显示易读名称；未知名称显示待识别。

构建依赖 Go（模块要求 ≥1.27.3）、Bun、Python ≥3.10：

```sh
cd config-desktop
bun install --frozen-lockfile
python3 build.py --python /absolute/path/to/python3 --install
```

构建验证解释器版本，将绝对路径绑定到二进制，并把仓内 canonical 工具原样复制到 `.app/Contents/Resources`；再进行 ad-hoc 签名。安装位置为 `~/Applications/Delivery Pipeline Settings.app`。安装脚本遇已有应用即停止，不覆盖。安装后从 Finder 双击，不依赖 shell PATH、当前目录或构建树。解释器被移动或卸载时，请让 AI 助手重新绑定并构建安装；不会静默安装依赖。Developer ID、公证和跨机器分发不在本机验收范围内。

配置默认读取 `~/.config/delivery-pipeline/model-roles.json`，从不初始化、修复、迁移或保存。缺失、损坏、旧版、非法结构、不可读分别引导助手处理，处理后点击“重新读取”。能力状态 Unknown，读取成功不代表模型运行或额度验证成功。显式预设和旧 lane 的既有规则保持。

检查：根目录 `python3 scripts/check_config_show.py` 已接入 `scripts/validate.py`；本目录 `go test ./...` 穿过公开 Host 到真实 Python 进程。`DELIVERY_CONFIG_TEST_PATH` 可让受控独立测试进程读取临时配置，不能用它改写真实配置。Finder、窗口交互和异常恢复须另留本机证据，不能由这些命令替代。桌面保存与 setup 事务兼容验收由后续票接入。
