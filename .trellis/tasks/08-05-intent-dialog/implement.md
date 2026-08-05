# Intent Dialog 执行计划

## 前置检查
- [ ] `tool-registry` 已提交（✅ 6039c78）
- [ ] `PetPanel` 修复已提交（✅ 71a4f2d）

## 阶段 1：后端 API（Python）

### 1.1 新增文件 `api/routes/intent.py`
- `POST /intent` 路由
- `IntentParser` 类（LLM prompt + 解析）
- `SessionManager` 类（内存 session，TTL 10分钟）
- 依赖：`ToolRegistry`, `providers`

### 1.2 `api/models/intent.py`
- `IntentRequest`, `IntentResponse`, `Message` Pydantic models
- `IntentAction` enum

### 1.3 `api/routes/__init__.py`
- 注册 `/intent` 路由

### 1.4 测试 `tests/api/test_intent.py`
- mock LLM 的单元测试
- 高置信度/低置信度/confirm 级路径

## 阶段 2：前端窗口（Swift）

### 2.1 新建 `DayByDay/Windows/IntentPanel.swift`
- `IntentPanel: PetPanel` 子类
- 添加 `TextEditor`, `Button`, `ScrollView`
- 双击手势检测
- 位置自动避边逻辑

### 2.2 `DayByDay/Rendering/IntentView.swift`
- SwiftUI 视图：输入区 + 对话流
- 消息气泡样式（用户右对齐灰色，系统左对齐蓝色）

### 2.3 `DayByDay/Windows/PetWindow.swift`
- 添加 `intentPanel: IntentPanel?`
- `openIntentDialog()` 方法
- 双击手势触发

### 2.4 `PetCommand` 扩展
- `openIntentDialog`
- `intentResponse`, `clarify`

## 阶段 3：协议对接

### 3.1 后端 `api/commands.py`
- `IntentResponse`, `Clarify` PetCommand

### 3.2 前端 `APIClient`
- `POST /intent` 方法
- SSE 监听 IntentResponse

## 阶段 4：集成测试

### 4.1 端到端
- 双击 → 输入 → 后端解析 → Tool 执行 → 结果展示

### 4.2 边界
- 屏幕边缘对话框位置调整
- 多显示器
- 长文本输入自动增高

## 验收检查
- [ ] `pytest tests/api/test_intent.py` 全过
- [ ] `xcodebuild build` 通过
- [ ] 真机：双击打开对话框 → 输入 → 结果展示

## 提交计划
1. 后端 API + 测试
2. 前端窗口 + 视图
3. 协议对接 + 集成

## 依赖
- LLM provider 配置（复用现有）
- `confirm-action` 任务（可选，confirm 级意图先展示确认 UI，执行放后续）
