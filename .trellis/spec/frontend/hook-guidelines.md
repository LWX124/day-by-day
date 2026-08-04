# Hook Guidelines

> 异步数据获取与副作用管理。（本工程非 React，此文件对应 Swift 的 Combine/async 数据获取模式。）

---

## Overview

Swift 侧数据来自后端 HTTP/SSE。获取模式分两类：**拉取**（一次性 HTTP 请求，如 `/today`）和**推送**（SSE 长连接，接收 PetCommand）。用 `async`/`await` + `AsyncStream` 处理，不用 Combine 的高级操作符。

---

## Custom Hook Patterns → Swift 异步模式

- **一次性请求**：`APIClient` 方法 `async`，视图 `.task { await load() }` 触发。
- **SSE 推送**：`SSEClient` 暴露 `AsyncStream<PetCommand>`，`@Observable` ViewModel 订阅并 dispatch。
- **退避重连**：SSE 断开后 1s→2s→4s→8s→30s 重连，与后端 BackendSupervisor 退避一致。

```swift
// 范本：SSE 订阅
@Observable final class PetController {
    private(set) var emotion: EmotionState = .idle
    private let sse: SSEClient

    func start() async {
        for await cmd in sse.commands() {
            switch cmd {
            case .setEmotion(let s): emotion = s
            case .bubble(let text, _): // show bubble
            case .celebrate(let tier, _): // trigger overlay
            }
        }
    }
}
```

---

## Data Fetching

- 所有请求走 `APIClient`，统一带 Bearer token，统一错误处理。
- 不在视图层直接 `URLSession`，统一经 `APIClient` 便于测试与 token 管理。
- 后端不可用时，`APIClient` 返回失败，视图显示降级提示或缓存数据。

---

## Naming Conventions

- 数据获取方法：动词（`loadToday()`、`sendIntent(_:)`、`completeTask(_:)`）。
- ViewModel：`<功能>Controller` 或 `<功能>ViewModel`，`@Observable`。
- AsyncStream 属性：名词复数（`commands()`、`events()`）。

---

## Common Mistakes

- **在视图 `.task` 里做重逻辑不取消**——长任务用 `.task(id:)` 或检查 `Task.isCancelled`。
- **SSE 消息直接改 UI 不经 ViewModel**——dispatch 走控制器，便于测试与状态可追溯。
- **重连不退避**——SSE 断了立即死循环重连会打爆后端。
