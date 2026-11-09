# ADR-0023: replacement 不自选模型

**Status:** Accepted
**Date:** 2026-11-08
**Decider:** User (Dimon)
**Supersedes:** ADR-0022 §1「工具或模型报错：按配置 `work` 的 key 顺序取第一个 model 与原 lane 不同的项」

## Context

ADR-0022 按 pstack `orchestrate.md` Supervision 节“工具报错换模型”，让 replacement 从配置 `work`
中取第一个 model 不同的项。`work` 的 key 是任务类型，不是备用顺序，结果等于任选一个模型。

pstack 的前提是可用模型多且都是一线模型。本仓用户的模型有限：部分额度稀缺，部分价格高，要花在
关键处；换到更弱的模型等于白派。是否值得换、换到哪个，只有用户能排序。额度在启动前不可探测
（DD-218：认证/实际运行状态 Unknown）。

## Decision

1. replacement 不换模型。连接中断、工具或模型报错、原因 Unknown 都用同一 packet 与原配置重派。
2. 每次重派计入 ADR-0022 §3 的两次上限；两次仍中断，原票置 `superseded` 并重拆。
3. 用户排序的备用模型清单并入配置桌面端第一期（Linear DD-199）的 Spec：与配置读写、能力证据和
   schema 迁移共用 `model_config.py`。清单落地前不存在备用模型。

## Consequences

- 不再出现 agent 自选模型；模型额度只按用户配置消耗。
- 模型持续报错的票会更快走到重拆或上浮，代价是少一次“换个模型可能就过了”的机会。
- 备用清单的形状、版本号与迁移归 DD-199，本 ADR 不定 schema。
