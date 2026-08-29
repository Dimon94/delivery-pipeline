# Configured Lane Monitoring

默认运行终点是 Dispatch Handoff，不持续监控。用户完成信号、真实 terminal event 或显式
monitor 请求才进入本文件。

## Herdr Lanes

- 从 registry 恢复 session/workspace/tab/pane、role、output_mode、agent/model/effort 与 worktree。
- 显式 monitor 时对目标 lane 做一次 bounded get/read；routine progress不触发 fan-in。
- final marker 缺字段记 Unknown；Git、tracker、artifact与 registry 是持久证据，不要求重显。
- HITL `awaiting_human` 只由用户返回触发；恢复不挂新 watcher、不定时 wait。

## Role-aware Terminal Outcomes

| Output mode | Required terminal evidence | Fan-in state |
|---|---|---|
| `commit` | terminal commit + code-review Review Evidence Bundle readback + configured Gearshift Projection readback（enabled 时）+ actual model history + clean/declared dirty state + touched files | cherry-pick → `integrated` |
| `artifact` | tracker/artifact坐标 + clean worktree | `consumed` |
| `checks` | commands/results + clean worktree | `consumed`，失败阻塞 review |
| `verdict` | map-base fixed point + Review Evidence Bundle readback + verdict/findings + clean worktree | `consumed`，blocking finding阻塞 closeout |

只有 `commit` mode 进入 cherry-pick。其他 mode 不要求 commit；出现未说明文件变更时 fail closed。

## Fan-in

按 output mode 验证 work item acceptance与持久证据；成功后调用
`execution-worktree-integration.md` 的对应 cleanup。lane blocked不停止其他 ready work。一次异常只做
一次状态检查；未知 active writer fail closed。
