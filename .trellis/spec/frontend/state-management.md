# State Management

> Swift 侧状态管理。（本工程用 Swift `@Observable` + 窗口局部状态，非 Redux/Context。）

---

## Overview

状态分三层：**窗口局部状态**（@State）、**跨视图共享状态**（@Observable 控制器）、**后端权威状态**（只读快照）。所有业务状态以后端为准，Swift 侧只缓存展示用快照。

---

## State Categories

| 类别 | 存放 | 示例 |
|---|---|---|
| 窗口局部 UI 状态 | `@State` | 弹窗开关、输入框文本 |
| 跨视图共享 | `@Observable` 控制器 | 当前 EmotionState、今日任务快照、SSE 连接状态 |
| 后端权威 | 只读模型快照 | Task/Schedule，从 APIClient 拉，不本地改 |
| 持久化偏好 | UserDefaults | 宠物位置 |

---

## When to Use Global State

- 单例仅限**生命周期贯穿 app** 的对象：`BackendSupervisor`、根 `PetController`、`APIClient`。
- 业务状态不进单例——面板分区的数据用各自 `@Observable` ViewModel，避免全局可变。
- 后端崩溃时，控制器保留最后一份快照供降级展示（design.md §2）。

---

## Server State

- 后端推送的 PetCommand 经控制器更新 EmotionState / 触发特效 / 显示气泡，**不本地推断**。
- `today` 等查询结果缓存为快照，刷新靠显式 `loadToday()` 或后端 `open_panel` 命令。
- 不做本地乐观更新——所有改动经后端，等后端回执或 SSE 确认后再展示新状态（事件流保证一致性）。

---

## Common Mistakes

- **本地推断业务状态**（如自己算该不该催、自己切 Tier）——判定全在后端 `core/`，Swift 只消费结果。
- **全局可变单例装任务数据**——数据是后端权威的，本地只存快照，避免双写不一致。
- **窗口状态不隔离**——每个窗口自己的控制器，宠物窗状态别污染面板。
