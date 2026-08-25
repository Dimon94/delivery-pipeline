# Remote Closeout Checklist

仅获得 remote publication authority 后加载；本地 Integration 不依赖本文件。

- [ ] execution graph 为空；所有 configured lanes terminal/integrated/closed。
- [ ] testing role whole-change checks通过，证据可读回。
- [ ] review role的 code-review owner verdict允许通过。
- [ ] Integration branch 已 rebase 到最新 main；冲突已按 resolving-merge-conflicts owner收口。
- [ ] Source/Integration/Execution Worktrees 与 branches 符合 cleanup contract。
- [ ] push target、PR/MR策略与用户授权一致。
- [ ] remote CI/CD 与 provider-native review verdict通过。
- [ ] map tracker close、completion comment与 registry readback一致。

任一项失败时报告唯一 remote gate并保留本地证据；不扩大授权范围。
