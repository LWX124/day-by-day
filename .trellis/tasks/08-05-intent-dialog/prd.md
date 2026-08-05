# 意图入口与对话 UI（双击宠物打开意图对话框）

## Goal

实现双击宠物打开意图对话框，用户输入自然语言指令，后端解析意图并返回结构化结果，前端展示对话流。

## Background

- M1 已完成 `tool-registry`（三级授权框架），但 agent 只能通过结构化 Tool 调用交互
- 用户需要通过自然语言与宠物交互（"帮我创建明天下午3点的会议"、"今天任务有哪些"）
- 双击宠物是触发意图输入的直观手势（design.md §5.2）

## Requirements

### 前端（Swift）
- **双击手势**：PetView 识别双击，发送 `PetCommand.open_intent_dialog`
- **意图对话框**：新 `IntentPanel`（类似 PetPanel，但带输入框）：
  - 尺寸：400x200，屏幕居中或宠物附近
  - 透明无边框，圆角，带阴影（与 PetPanel 一致的风格）
  - 输入框：多行 TextEditor，placeholder "想让我做什么..."
  - 发送按钮：回车或点击发送
  - 对话流：ScrollView 展示用户输入 + 后端响应（确认/追问/结果）
- **自动聚焦**：对话框打开时输入框自动聚焦，不抢 Dock 焦点（`canBecomeKey=false` 但输入框需要焦点）
- **ESC/点击外部关闭**：对话框可关闭，关闭后返回宠物 idle

### 后端（Python）
- **新路由**：`POST /intent` 接收自然语言文本
- **意图解析**：调用 LLM（复用 M1 的 provider 抽象）解析用户输入：
  - 识别意图类型：create_task/query_task/update_task/delete_task（confirm 级）...
  - 提取参数：时间、标题、优先级等
  - 返回结构化 JSON：{"intent": "...", "args": {...}, "confidence": 0-1}
- **置信度阈值**：<0.7 时追问用户确认，≥0.7 时直接执行对应 Tool
- **Tool 执行**：
  - read/write 级：直接调用 `ToolRegistry.invoke`，返回结果
  - confirm 级：生成 `pending_action` + push `RequestConfirm`，不直接执行
- **对话流管理**：维护多轮对话上下文（简单 session 内存，M2 再持久化）

### 前后端协议
- Swift → Python：`POST /intent {session_id, text, context}`
- Python → Swift：`PetCommand` 推送响应
  - `IntentResponse`：展示确认/结果
  - `RequestConfirm`：需确认级操作
  - `Clarify`：追问参数

## Acceptance Criteria

- [ ] 双击宠物打开意图对话框，输入框自动聚焦，可输入中文/英文
- [ ] 输入"创建任务 xxx"，后端解析为 create_task 意图，参数正确提取
- [ ] 高置信度意图直接执行，结果展示在对话框
- [ ] 低置信度/模糊意图，后端追问"是指创建任务还是查询任务？"
- [ ] confirm 级意图（如 delete_task）触发确认流程，对话框展示确认 UI
- [ ] 对话框 ESC 或点击外部关闭，宠物恢复 idle
- [ ] 后端 `/intent` 端点可独立测试（curl 或 pytest）

## Constraints

- 对话框风格必须与 PetPanel 一致（透明、无边框、圆角、不抢 Dock）
- LLM 调用复用 M1 `provider-abstraction`（已归档）的 provider 层
- 意图解析走 events.append 落事件流（推断/判定分离原则）
- 不实现语音输入（M3 考虑）

## Dependencies

- `tool-registry`（已完成）：后端 Tool 调用能力
- `confirm-action`（M1 下个任务）：confirm 级 Tool 的确认流程

## Notes

- 本任务只实现单轮/简单多轮对话，复杂多轮（跨 session）放 M2
- 意图解析模型可用简单 prompt + gpt-4o-mini 起步，M2 优化为微调/专用模型
- 对话框位置若宠物在屏幕边缘，应自动调整避免超出屏幕
