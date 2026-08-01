# Gate Worker Packet

用于把一个持久 gate 交给 fresh worker。完整填写后一次发送。

```text
Coordinator task：
Source owner projectId：
当前 gate：spec | tickets | review | evidence
输入 issue：
Wayfinder map：<url | none>
Spec：<url | none>
Tracker/repo：
Source branch/commit：

Owner skill name：<to-spec | to-tickets | code-review | research>
Owner skill SKILL.md：<absolute resolved path>
Owner skill invocation label：<$to-spec | $to-tickets | $code-review | $research>

先读：
-

允许写入：
- <tracker items / artifact paths>

完成标准：
- spec：published spec URL/ID、source map link 和 body 已 readback
- tickets：published ticket IDs、spec Parent links 和 dependency edges 已 readback
- review：基于指定 base 的 Standards/Spec verdict 已返回
- evidence：问题已有直接证据与来源

规则：
- 先完整读取 Owner skill SKILL.md，回报 frontmatter name 与 resolved path，再执行该
  contract；invocation label 只用于说明，不依赖 child catalog。
- 对应 owner skill 决定产物内容；不要增加另一套 gate。
- 所有 tracker create/update/comment 后立即 readback。
- 面向 tracker、用户和 coordinator 的自然语言使用中文。
- 不进入后续 gate；把持久坐标和结果交回 coordinator。

Final report：
Gate：
状态：completed | blocked
输入坐标：
输出坐标：
Readback：
验证：
阻塞：
下一 gate 建议：
```
