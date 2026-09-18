# Prewalk 原型结果

2026-09-07，单次、固定顺序、同一纯函数任务。产物均为一次性原型。

| 路径 | 总耗时 | 共同检查 | 代码行数 |
|---|---:|---:|---:|
| Sol high 直接执行 | 82.64 秒 | 8/8 | 52 |
| Astra low → Sol high | 143.59 秒 | 8/8 | 42 |
| Astra low → Luna high | 124.23 秒 | 8/8 | 38 |

Prewalk 总耗时均包括 Astra 的 48.34 秒起步。两个接续组 fork 同一个起步会话，并恢复同一份首处代码；只有起步 prompt 含有的随机口令均被正确回忆，接续日志没有读取会话文件的命令。宿主 session turn_context 记录的模型和思考档位符合请求；service tier 没有回读证据，保持 Unknown。所有 CLI 请求使用 default，未测 fast。

结论：本次 CLI fork 保留了足够上下文以接续完成任务，但这个小任务未从 Prewalk 获得总耗时收益。不能依据一次运行或代码行数判断 Luna/Sol 的普遍质量或过度设计倾向。没有实际运行文档交接对照组；页面中的文档模式仅为逻辑模拟。未验证 Codex App 同任务换模型、原位 resume、工具边界自动切换或独立 Astra 双轴审查。

页面演示检查点、重复事件、未知发送结果与 review gate；这里的幂等规则是模拟设计，不代表真实 App API 已保证幂等。

复核已有产物（不会再次调用模型）：

```sh
python3 .scratch/prewalk-prototype/run_probe.py --check-only
```

重新运行实际模型实验（会消耗额度并覆盖本目录同名证据）：去掉 `--check-only`。原始 prompts、JSONL、生成源文件与 results.json 同目录保留。下一步只有在代表性真实开发票上重复测试，且核验 App 接续证据后，才考虑改变生产默认配置。
