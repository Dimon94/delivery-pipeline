# Task Coordinate Title

创建、替换、重命名或恢复 user-visible Codex App task 时读取本文件。Task Coordinate Title 是
稳定的导航坐标；Codex App task lifecycle 承载动态状态，lane registry 承载恢复真相。

## 生成坐标

1. 解析 owning map 的 tracker key，保留 `#<number>` 形态。
2. 按 lane 职责选择 role：

   | Role | 职责 |
   | --- | --- |
   | `LEAD` | coordinator |
   | `G` | grilling / planning |
   | `X` | execution |
   | `P` | prototype |
   | `R` | review |
   | `D` | diagnosis / research |

3. 非 `LEAD` task 解析自己的 tracker work-item key，保留 `#<number>` 形态。
4. 从 tracker title 压缩 short summary：优先“动作＋对象”，保留领域词，省略 identifier、state
   和 workflow prefix。同一 map 内出现摘要碰撞时，补充最短的领域限定词，直到每条 task 可区分。
5. 用无空格 ASCII `-` 连接坐标：

   ```text
   lane:        <map-key>-<role><work-item-key>-<short-summary>
   coordinator: <map-key>-LEAD-<short-summary>
   ```

   例如：`#86-X#957-修复恢复去重`、`#86-LEAD-派发通道确认`。

## 生命周期与 Readback

1. child task 创建时向 `create_thread` 显式传入 `title`；map coordinator 在 map key 确定后用
   `set_thread_title` 设置 `LEAD` 坐标。
2. lifecycle 状态变化时保持标题稳定。map、role、work item 或 scope 被纠正时生成新坐标；只有
   lane registry 已唯一确认目标 task，才调用 `set_thread_title` 修正并再次 readback。
3. 用 `list_threads` 验证返回 title 与预期逐字符相等。pending setup 的 task 还要同时匹配
   Source owner project 与 lane work item；恢复 existing task 时以 registry 的 `thread_id`、
   `host_id`、`project_id` 为主坐标，title 只提供导航与 bounded recovery 交叉证据。

完成标准：标题符合唯一一种 canonical grammar，role 与 lane 职责一致，short summary 在同一 map
内可区分，`list_threads` 精确读回预期 title，registry 与 task identity 互相一致。
