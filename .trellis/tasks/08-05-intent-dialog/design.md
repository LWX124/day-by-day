# Intent Dialog 技术设计

## 1. Scope

实现双击宠物 → 打开意图对话框 → 自然语言 → 后端解析 → 执行 Tool/确认流 的完整链路。

## 2. 架构

```
┌─────────────┐     ┌─────────────────┐     ┌─────────────────┐
│ Swift 侧    │     │ HTTP API        │     │ Python 侧       │
├─────────────┤     ├─────────────────┤     ├─────────────────┤
│ PetView     │────▶│ POST /intent    │────▶│ /routes/intent  │
│ 双击手势      │     │                 │     │ IntentParser    │
│             │     │                 │     │ ToolExecutor    │
│ IntentPanel │◀────│ PetCommand push │◀────│ ResponseBuilder │
│ 输入框+对话流  │     │ (SSE/WebSocket) │     │                 │
└─────────────┘     └─────────────────┘     └─────────────────┘
```

## 3. 前端设计

### 3.1 IntentPanel（NSPanel 子类）
- 继承 `PetPanel` 的透明/无边框/不抢焦点特性
- 尺寸：`CGSize(width: 400, height: 200)`，支持动态扩展（多行输入时增高）
- 位置：宠物中心上方，自动避边（检测屏幕边缘，若溢出则向下/左/右偏移）
- 组件：
  - `TextEditor`：多行输入，聚焦时边框高亮
  - `Button`：发送（纸飞机图标）
  - `ScrollView + LazyVStack`：对话流，用户右对齐，系统左对齐
  - `DismissButton`：右上角 X

### 3.2 双击手势
- `PetView.body` 加 `.onTapGesture(count: 2)`
- 触发 `PetWindowDelegate.openIntentDialog()`
- `PetWindowDelegate` 管理 `intentPanel: IntentPanel?`，生命周期与 `petPanel` 同级

### 3.3 焦点管理
- `IntentPanel` 继承 `PetPanel.canBecomeKey = false`
- 但 `TextEditor` 需要焦点：对话框打开时调 `NSApp.activate(ignoringOtherApps: true)` 临时激活
- 关闭后 `petPanel.orderFrontRegardless()` 恢复

### 3.4 PetCommand 新增
- `case openIntentDialog`：Swift → Swift，本地触发
- `case intentResponse(text: String, actions: [IntentAction])`：Python → Swift，展示结果
- `case clarify(question: String)`：Python → Swift，追问

## 4. 后端设计

### 4.1 路由 `/intent`
- `POST /intent`
- Request：`{session_id: str, text: str, context: list[Message] | null}`
- Response：`{intent: str, args: dict, confidence: float, action: "execute" | "confirm" | "clarify", message: str}`

### 4.2 IntentParser
- 复用 `providers.py` LLM 调用
- Prompt 模板：few-shot 示例 + 当前输入 → 结构化 JSON
- 模型：gpt-4o-mini 起步（便宜+快，M2 优化）
- 输出 schema：`IntentParseResult`（Pydantic model）

### 4.3 ToolExecutor
- 置信度 ≥0.7：直接 `ToolRegistry.invoke(intent, ctx, args)`
- read/write 级：执行后包装结果返回
- confirm 级：调用 `ToolRegistry.invoke`（confirm 级内部生成 pending_action），返回 `action_id` + `RequestConfirm` PetCommand
- 置信度 <0.7：返回 `clarify` + 追问文本

### 4.4 Session 管理
- 简单内存 dict：`{session_id: list[Message]}`，TTL 10 分钟
- Message：`{role: "user" | "assistant", content: str, timestamp}`
- M2 再考虑持久化/Redis

## 5. 数据流

### 5.1 成功路径（高置信度 write 级）
1. 双击 → `openIntentDialog`
2. 用户输入 → `POST /intent`
3. 后端解析 → 置信度 0.9 → `ToolRegistry.invoke(create_task, ...)`
4. 返回 `event_id` → 包装 `intentResponse` → SSE push
5. 前端展示"已创建任务 xxx"

### 5.2 确认路径（confirm 级）
1-3 同上，但意图是 `delete_task`
4. 后端生成 `pending_action` → push `RequestConfirm`
5. 前端对话框展示确认 UI（是/否）
6. 用户确认 → `POST /confirm`（confirm-action 任务）
7. 执行后 push `IntentResponse`

### 5.3 追问路径（低置信度）
1-3 置信度 0.5 → 返回 `clarify` + "你是想创建任务还是查询任务？"
4. 前端展示追问，用户继续输入
5. 追加到 context，重新 `POST /intent`

## 6. 错误处理

- LLM 不可用：`ProviderUnavailable` → 降级为"请用结构化 Tool 调用"
- 解析失败：JSON decode error → 返回 clarify "我没听懂，请再描述一下"
- Tool 执行失败：ToolResult.error → 展示错误信息在对话框

## 7. 测试策略

- 单元：IntentParser prompt 测试（mock LLM）
- 集成：`POST /intent` end-to-end（真实 LLM，skip CI）
- UI：截图对比（人工）

## 8. 契约

### Swift → Python HTTP
```json
POST /intent
{
  "session_id": "uuid",
  "text": "创建明天下午3点的会议",
  "context": [
    {"role": "user", "content": "...", "ts": "ISO8601"}
  ]
}
```

### Python → Swift SSE
```json
PetCommand.intentResponse(
  text: "已创建任务'明天下午3点的会议'",
  actions: [{"type": "open_task", "task_id": "..."}]
)
```

## 9. 与现有系统关系

- 复用 `PetPanel` 窗口机制
- 复用 `ToolRegistry` 所有已注册 Tool
- 复用 `providers.py` LLM 抽象
- 依赖 `confirm-action` 任务确认流程
