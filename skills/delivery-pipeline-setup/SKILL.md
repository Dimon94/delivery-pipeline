---
name: delivery-pipeline-setup
description: 初始化或重配 delivery-pipeline 的任务类型 worker 配置。
disable-model-invocation: true
---

# Delivery Pipeline Setup

初始化或重配 `~/.config/delivery-pipeline/model-roles.json`。先完整读取
`../delivery-pipeline/references/model-config-schema.md`；它是 CLI version 8 / App version 5 schema（任务类型、
命名 mode 覆盖预设、review 矩阵、transport 必需集）的唯一来源。再读取
`../delivery-pipeline/references/model-role-routing.md` 获取 agent adapter 与 evidence 规则。
本流程在当前会话交互执行，不派发 lane。

配置实例清单（schema 只有一份，见上；实例归各 runtime）：

- **CLI 实例**：`~/.config/delivery-pipeline/model-roles.json`，由本流程写入并 readback；
  CLI/Herdr dispatch 只读。
- **App 实例**：`skills/delivery-pipeline-codex-app/config/models.json`，由用户编辑；
  App 壳 helper 只读，不改配置。

pi coordinator 的上下文上限由 `pi/coordinator-context-cap.ts` 提供（默认 150K，
`DP_COORDINATOR_CONTEXT_CAP` 可覆盖）；确认它已软链到
`~/.pi/agent/extensions/dp-coordinator-context-cap.ts`，缺失时创建该软链。

## 流程

1. **探测并严格验证现状。** 从本 SKILL.md realpath 解析并运行
   `scripts/model_config.py validate ~/.config/delivery-pipeline/model-roles.json`，同时执行第 2 步的
   本机 evidence probe。旧 CLI version 2/3/4/5 文件经用户明确确认后运行 `scripts/model_config.py migrate <config>`
   机械迁移并 readback；迁移提交前拒绝后，经用户明确授权才进入重配流程；退出 3 时先显式读取核对，不进入初始化。
   只有受支持的 CLI 配置结构与实时 evidence 都通过才报告当前表并结束：
   顶层 key、任务类型全集与 CLI 必需集、review 矩阵与命名 mode 覆盖预设按 schema 文档逐项核对；每个 entry 的 `agent/model/effort` 非空、binary 存在、model/effort 命中
   对应实时 evidence。任何非法配置给出修复引导，用户明确授权后才按实际 hash 重配；合法配置仅在用户明确要求重配时覆盖。
   迁移或重配不会迁移已有 lane；已有 lane 继续按 registry 恢复。
2. **探测本机 evidence。** 通过 `scripts/model_config.py probe --request-id <本次身份>`
   取得统一 `ProbeEvidence`；stdin 为 `{"gateway":{"status":"ok","data":[...]}}` 原始来源对象。
   网关来源仅取现有本机 `http://127.0.0.1:3425/v1/models` 的 GET；读取失败时传
   `{"gateway":{"status":"unknown"}}`。不输出凭据，不发推理，不修改接入或代理。
   Python 采集本机 harness 元数据与 Claude 一次只读官方模型清单并归一化；`capabilities` 是精确原生模型到有效档位的映射，
   `sources` 给出来源、采集时间、状态、route 与下一核验动作。
   Codex 直连 OpenAI（route=direct）时使用 `codex debug models --bundled` 内置清单及其档位，
   不读取自定义 catalog，未与网关交叉核对；认证、账号可用模型与额度为 Unknown。
   网关路由（route=gateway）仍取本机工具清单与网关清单的交集；其他代理（route=null）
   不提供候选，reason 说明地址既不是本机网关也不是 OpenAI 官方。
   Claude 使用当前账号与地址读取 Anthropic 官方模型清单（route=official，只读不推理），
   GET `<base_url>/v1/models?limit=1000`，超时 15 秒。地址依次取进程环境、settings.env 的
   ANTHROPIC_BASE_URL、官方默认地址；凭据依次取 ANTHROPIC_API_KEY（进程环境优先于
   settings.env）、ANTHROPIC_AUTH_TOKEN（同上）、OAuth。macOS 只读钥匙串项
   Claude Code-credentials，其他平台只读 ~/.claude/.credentials.json；不刷新凭据、不执行 apiKeyHelper。
   过期或缺失 OAuth 提示先去 Claude Code 登录；本机网关与 apiKeyHelper 暂不支持核对，
   清单读取失败时给出原因、不提供候选。仅保留官方清单明确支持的 low/medium/high/xhigh/max，
   无档位模型不提供。凭据不进入输出或异常文本；首次钥匙串读取可能弹授权框，未确认时记 Unknown。
   官方清单不能证明额度或实际调用成功，这两项为 Unknown。
   Antigravity 优先通过 `agy models` / `antigravity models`（route=cli，只读不推理、不触碰凭据）
   获取实时模型与受支持档位；未检测到 CLI 或执行失败时回退只读本地提供方缓存（`~/.t3/caches/antigravity.json`
   与 `~/.t3/userdata/settings.json` 启用态，route=cache）。未安装、未启用或未登录时给出原因、不提供候选。
   网关不可达时，直连 Codex、official Claude 与 Antigravity（cli/cache）的模型仍保留，gateway 状态仍为 unreachable。
   只使用状态为 ok 的候选；
   Unknown 保留已有值，请用户或 AI 助手补齐来源后刷新。
3. **逐项选择。** 按 `planning`、`design`、`frontend`、`backend`、`testing` 顺序，每个任务
   类型先选 agent，再从该 agent 的真实 evidence 选择 model 与 effort；随后选择 review 矩阵四格
   （`implementation`/`whole-change` × `standards`/`spec`）。展示任务管辖工作、候选来源与当前
   选择。Claude 同样只从统一 probe 的有效候选选择；无候选时不能新增 Claude 选择。Skill 不提供
   内置默认，由用户明确选择全部必需项。每个任务类型的 work 项就是该 lane 单轮直跑的
   `{agent, model, effort, fallbacks}`；初始化 `fallbacks: []`，review 四格补 `candidates: []`，已有列表按位置保留，不截断或去重。`modes` 命名覆盖预设可选维护：只在 ticket/map 显式点名时用其
   `direct` 组覆盖，默认路径不消费。
   询问最多同时执行的任务数 `dispatch.parallel` 和每次执行的轮数上限 `dispatch.max_turns`。初次设置留空分别取 4、100。编辑时留空保留当前有效值。仅接受正整数，显式保存时生成 v8 候选并读回两项。降低并发后等待空出名额，新轮限从下一次启动生效。
4. **验证选择。** 复用配置 Module 的 `capability_errors` / `validate_selection`，
   检查精确 agent/model/effort 命中本轮证据。失败只重新选择对应项。
5. **共享事务提交并 readback。** 禁止用 shell 重定向、编辑器或临时脚本直接写目标。
   用户确认本次候选后生成唯一 request-id，重新采集本轮能力，按配置 Module 的
   `ProbeEvidence` 交接（request_id、observed_at、gateway、capabilities、sources；`gateway` 为 `{status: ok|unreachable}`，仅当 Host 传入的网关状态为 ok 时才是 ok；来源状态 ok 才可用于改动格）。
   桌面 Host 仅 GET 本机网关模型清单，将原始 gateway 来源经 stdin 交给
   `model_config.py probe --request-id <本次身份>`；setup 使用同一命令（stdin 为 gateway 来源对象）。
   probe 读取本机 harness 元数据与 Claude 官方模型清单，不发推理；sources 中 Unknown 的工具不提供新增选择。
   能力判断复用 Python `capability_errors` / `validate_selection`，不在 Skill 复制规则。
   候选写入独立临时文件，证据也只放临时文件，不能写进用户配置。
   从实际原字节读取 SHA-256 基线（包括坏 JSON 的显式修复）；缺失才省略 --base-hash。
   用户明确重配或修复授权后运行：
   `python3 <setup-realpath>/scripts/model_config.py configure <config> --base-hash <实际hash> --request-id <本次id> --evidence <本轮证据文件>`，
   stdin 接完整候选（例如 `< <候选临时文件>`）。目标缺失时去掉 --base-hash；
   父目录、稳定 sidecar 锁、原子写入及精确 readback 全由该入口负责。
   退出 0 且 status=applied 才报告成功，返回 config 与 base_hash 是实际读回值。
   退出 1 / rejected 保留候选；base_conflict 必须重新读取、人工核对再确认，不自动合并或重提。
   退出 3 / commit_unverified 表示已越过替换点但待确认；仅显式读取实际结果供用户核对，
   不自动回滚、重试，也不能宣称未写入。migrate 同样遵守 1/3 分类；迁移失败不可自动接着初始化。
   无语义改动 changed=false 保留原字节。两层都通过后报告最终
   任务类型 → agent/model/effort 表。之后新 lane 默认按 work 项解析并冻结计划；ticket/map
   显式点名 mode 时用其 `direct` 组覆盖。不能把计划选择写进 coordinator 配置。

完成标准：CLI 必需任务类型与 review 矩阵都由用户明确选择，配置 readback 与选择一致；没有
默认值、空字段、非法 agent、额外字段或未命中本机 evidence 的 model/effort。所有 startup 都需要
当前 capability evidence；启动请求由 `model_config.py start` 生成。
