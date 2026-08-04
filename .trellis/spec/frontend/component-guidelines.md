# Component Guidelines

> SwiftUI 视图约定。（本工程 frontend 是原生 macOS Swift，非 React。）

---

## Overview

视图分两类：**窗口内容**（各 Window 的 content view）和**面板分区**（PanelWindow 内的 section）。所有视图从后端拉只读数据展示，写操作走 APIClient 发请求，**不本地决策业务逻辑**。

---

## Component Structure

- 每个视图文件一个主 `View` struct，必要时配套 `ViewModel`（`@Observable`）。
- 视图只做渲染 + 把用户事件转成 APIClient 调用，不内嵌判定。
- 复杂分区拆子视图，子视图通过 init 参数传数据，不直接读全局单例。

```swift
// 范本：视图只渲染 + 发请求
struct TaskCardView: View {
    let today: TodayView
    let api: APIClient
    var body: some View {
        List(today.tasks) { task in
            TaskRow(task: task) { id in api.completeTask(id) }
        }
    }
}
```

---

## Props Conventions

- Swift 用 init 参数（不是 React props）。简单数据用值类型直传，复杂状态用 `@Observable` ViewModel。
- 闭包作为回调传入（如 `onComplete: (TaskID) -> Void`），视图不持有 APIClient 之外的业务对象。

---

## Styling Patterns

- 透明无边框窗口：`NSWindow` 设 `isOpaque=false`、`backgroundColor=.clear`、`hasShadow` 按需。
- 宠物窗口圆角与阴影靠 sprite 自身，窗口本身全透明。
- 不用 Storyboard，全部 SwiftUI + `NSHostingView`/`NSHostingController`。
- 配色跟随系统外观（light/dark），除宠物 sprite 外不强制定制颜色。

---

## Accessibility

- 宠物窗口本身无障碍标签：`accessibilityLabel("Day by Day 宠物")`，`accessibilityRole(.button)`。
- 面板内控件遵循标准 SwiftUI 无障碍，列表项带 `accessibilityHint`。
- 全屏特效 overlay 设 `accessibilityElement(children: .ignore)`，避免读屏被烟花干扰。

---

## Common Mistakes

- **在视图里写业务判定**（如算 Tier、算该催谁）——这些在后端 `core/`，Swift 只展示结果。
- **窗口抢焦点**——`canBecomeKey`/`canBecomeMain` 按需设 false，宠物窗与 overlay 绝不抢焦点。
- **直接改后端模型**——Swift 侧模型是只读快照，所有改动走 APIClient。
