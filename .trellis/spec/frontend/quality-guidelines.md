# Quality Guidelines

> Swift 前端代码质量标准。

---

## Overview

- **lint/format**：SwiftFormat + SwiftLint。
- **类型**：开启严格并发检查（`SWIFT_STRICT_CONCURRENCY=complete`），Swift 6 并发安全。
- **测试**：XCTest，覆盖窗口配置、PetCommand dispatch、APIClient mock。渲染层靠肉眼 + 截图。

---

## Forbidden Patterns

### 1. 窗口抢焦点
宠物窗、Bubble、CelebrationOverlay **绝不** `canBecomeKey=true`/`canBecomeMain=true`。抢焦点是桌面工具最招人恨的行为（design.md §7）。

### 2. 视图层写业务判定
Tier、该催谁、EmotionState 推导都在后端 `core/`。Swift 视图不内嵌这类逻辑。

### 3. 直接改后端模型
Swift 侧 `Task` 等是只读快照。所有状态变更走 APIClient，等后端回执。

### 4. Storyboard
不用 Storyboard/XIB，全部 SwiftUI + 代码配置窗口。

### 5. 保留全局可变业务状态
业务数据不进单例，只存快照，避免双写。

### 6. 给 NSWindow/NSPanel 的只读属性赋值
`canBecomeKey`、`canBecomeMain`、`isFloatingPanel` 是**只读属性**，不能 `window.canBecomeKey = false` 赋值。必须用**子类重写**：
```swift
final class PetPanel: NSPanel {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }
}
```
因此宠物窗、overlay 窗必须用 NSPanel 子类手动创建（`PetWindowDelegate` 里 `init` + `orderFrontRegardless`），**不能走 SwiftUI WindowGroup**——WindowGroup 创建的是 NSWindow，无法换成自定义子类。透明/置顶/跨Space/可拖拽这些可写属性才在子类的 `init` 里赋值。

**NSPanel 子类必须显式关掉自动隐藏**——这是 borderless panel 不上屏的头号原因：
```swift
// configurePetStyle() 里必加，否则 panel 不显示
hidesOnDeactivate = false        // NSPanel 默认 true：失焦即隐藏
becomesKeyOnlyIfNeeded = false  // 默认 true：不成为 key 就不上屏
styleMask.insert(.nonactivatingPanel)  // 非 key panel 也可被推上前
```
诊断特征：`panel.isVisible == true`、`isOnActiveSpace == true`、`level = .screenSaver`、红色不透明背景，但屏幕上什么都没有——必查这三个属性。LSUIElement app 尤其容易踩（无 Dock 图标，app 未激活为 frontmost 时 panel 全部隐身）。

### 7. screencapture / osascript 自动化验收
桌面宠物 app 的肉眼验收（跨 Space 可见、overlay 点击穿透、拖拽）依赖屏幕录制/辅助功能权限，CI 与自动化环境拿不到。这类验收写成本机验证脚本，人工执行。

### 8. 对话框焦点管理

宠物窗、Bubble、CelebrationOverlay 必须保持 `canBecomeKey = false`。`IntentPanel` 是唯一例外：它由用户主动双击打开且包含文本输入，因此必须允许成为 key window，但仍不能成为 main window：

```swift
// IntentPanel.swift — 正确
override var canBecomeKey: Bool { true }
override var canBecomeMain: Bool { false }

func activateForInput() {
    makeKeyAndOrderFront(nil)
}

// 错误 — 不要这样
override var canBecomeKey: Bool { false }  // ❌ makeKeyAndOrderFront 不会生效，输入框无法获得键盘事件
```

`nonactivatingPanel` 让面板可以在不激活整个应用的情况下成为 key window，但不会绕过 `canBecomeKey` 资格检查。因此不要先调用 `NSApp.activate`；它会改变前台应用状态，并可能与 key window 切换竞争。只有在用户主动打开输入面板时调用 `activateForInput()`；关闭后恢复宠物窗口：`petPanel.orderFrontRegardless()`。

SwiftUI 输入视图的 `FocusState` 要在 `IntentPanel` 成为 key window 后设置；在 `.onAppear` 中延后一轮主队列，避免第一响应者停留在窗口本身。

### 9. 从 `NSApplication.shared.delegate` 反查 SwiftUI adaptor

`@NSApplicationDelegateAdaptor` 的实例不等于 `NSApplication.shared.delegate`；运行时后者是 SwiftUI 的内部代理。视图事件必须通过 init closure 显式上报，不能强转全局 delegate。强转失败如果写成 `if let` 会静默吞掉点击。

---

## Required Patterns

- 每种窗口一个文件，NSWindow/NSPanel 子类 + SwiftUI content。
- `PetRenderer` 协议抽象渲染层，占位与 sprite 实现可互换。
- `PetCommand` 枚举与后端 `commands.py` 字段对齐。
- 透明窗口：`isOpaque=false` + `backgroundColor=.clear` + 按需 `hasShadow`。
- 跨 Space：`collectionBehavior = [.canJoinAllSpaces, .stationary]`。
- 开机自启：`SMAppService.loginItem`。

---

## Testing Requirements

| 层 | 要求 |
|---|---|
| 窗口配置 | XCTest 断言各窗口的 level/collectionBehavior/canBecomeKey 符合预期 |
| PetCommand dispatch | mock SSE 流，断言各命令正确路由到对应窗口 |
| APIClient | mock URLProtocol，断言请求带 token、错误处理 |
| 渲染层 | 不单测，靠肉眼 + 截图比对；窗口配置在 swift-window-spike 已验证 |

---

## Code Review Checklist

- [ ] 新窗口抢焦点了吗？（canBecomeKey/canBecomeMain 按需 false）
- [ ] 视图层有没有偷偷写业务判定？
- [ ] PetCommand 新增 case 两边都改了吗（commands.py + PetCommand.swift）？
- [ ] 透明/置顶/跨 Space 配置正确吗？
- [ ] 异步任务可取消吗？
- [ ] 后端不可用时有降级展示吗？
