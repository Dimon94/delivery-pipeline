# ADR-0024：本机配置桌面端与共享提交事务

**Status:** Accepted
**Date:** 2026-11-12
**Decider:** User (Dimon)

用户在 DD-377 实施会话确认 MyGo 本机方案与真实 Python / MyGo / lane 分层验收；来源为实施事实包的 DD-250、DD-251 resolution（2026-11-12）。决定完成不代表产品实测通过。

桌面采用 MyGo 网页窗口，只调整 CLI 实例的五个 work 与 review 四格主配置；AI setup 负责初始化、修复和迁移。配置 Module 是 schema、能力归一化与写入的单一 owner。桌面不静默创建或迁移，不编辑 App 实例；CLI 按 ADR-0018 只 direct，保持 v5，显式 mode 覆盖与旧 lane registry 语义不变。

setup 与桌面共用 canonical Python 事务：合作方使用同一个稳定 sidecar 文件锁，在锁内读取原字节、核对 hash、验证、原子替换和精确读回。初始化只有目标仍缺失时接受空 hash，存在目标必须绑定实际 hash。替换前失败保留原字节，无语义更改不写；替换后无法确认返回 commit_unverified，禁止自动回滚或重试。这不是任意外部编辑器的文件系统 CAS，也不承诺断电后的磁盘持久性。

锁定 MyGo 版本；构建携带同源 canonical 工具并绑定构建时验证的 Python ≥3.10 绝对路径，安装到 ~/Applications，Finder 启动不依赖 shell PATH、cwd 或临时树。Go/Bun 仅为构建依赖；本机先 ad-hoc 签名，Developer ID、公证与跨机分发不作 M1 门槛。依赖缺失给 AI setup 引导，不静默安装。

可重复的真实 Python 进程/文件事务检查进入 validate/CI，补充有界模型；MyGo/Finder 与真实新 lane 独立留证，启动与模型执行分别记录，缺证据写 Unknown。模型、fixture、静态页面与 HTTP 成功均不能代替真实用户链路验收。M2 备用与 M3 家族选择不属于本决定。
