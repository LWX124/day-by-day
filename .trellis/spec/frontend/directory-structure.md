# Directory Structure

> DayByDay.app（SwiftUI 原生 macOS 外壳）的目录组织。前端是常驻桌面宠物 + 几个辅助窗口，spawn 并守护 Python 后端。

---

## Overview

Swift 侧只管**渲染与用户事件**，一切决策与数据在 Python 后端（ADR-0001）。Swift 代码围绕"窗口层级 + PetCommand 处理 + 渲染层协议"三件事组织。窗口组合的硬需求（透明、置顶、跨 Space、不抢焦点、点击穿透）见 design.md §8。

---

## Directory Layout

```
DayByDay/
├── DayByDayApp.swift          # @main，LSUIElement=true，BackendSupervisor 启动
├── App/
│   ├── BackendSupervisor.swift    # spawn Python、退避重启、stdout 汇入日志
│   ├── PetCommand.swift           # PetCommand 枚举（与后端 commands.py 对齐）
│   ├── SSEClient.swift            # GET /events 长连接 + 自动重连
│   └── APIClient.swift            # HTTP 调用（/intent /today /confirm /wake）
├── Windows/
│   ├── PetWindow.swift            # 常驻宠物窗（NSPanel, floating, canJoinAllSpaces）
│   ├── BubbleWindow.swift         # 悬停气泡（ttl 自动消失，可带 quick_replies）
│   ├── TaskCardWindow.swift      # 单击任务卡（~360×480, Esc 关）
│   ├── PanelWindow.swift          # 双击主面板（~900×600，分区）
│   └── CelebrationOverlay.swift  # 全屏特效（.screenSaver level, 点击穿透）
├── Rendering/
│   ├── PetRenderer.swift          # 协议：输入 EmotionState + 动作事件，输出渲染
│   ├── PlaceholderRenderer.swift # 开发期占位（SF Symbols + SwiftUI 动画）
│   ├── SpriteSheetRenderer.swift  # sprite sheet 帧动画实现
│   └── CelebrationView.swift     # Tier 1-4 特效（SpriteKit 粒子）
├── Views/
│   ├── TaskCardView.swift
│   ├── PanelSections/            # 对话/今日/全部任务/复盘历史/Gerrit/知识/设置
│   ├── ConfirmDialog.swift       # 二次确认弹窗（不抢焦点）
│   └── BubbleView.swift
├── Models/
│   ├── Task.swift                 # 与后端对齐的只读模型
│   ├── Schedule.swift
│   └── EmotionState.swift
├── Utilities/
│   ├── PositionStore.swift       # 宠物位置持久化（UserDefaults）
│   └── WakeMonitor.swift         # NSWorkspace.didWakeNotification → POST /wake
└── Resources/
    └── Assets/                    # sprite sheets + JSON 帧描述
```

---

## Module Organization

- **窗口 = 文件**：每种窗口一个文件，NSWindow/NSPanel 子类 + SwiftUI content。
- **渲染层抽象**：`PetRenderer` 是协议，占位实现与 sprite 实现可互换——素材未就位时不阻塞开发（design.md §8）。
- **PetCommand 是前后端契约**：Swift 侧 `PetCommand` 枚举必须与后端 `api/commands.py` 字段对齐，改一处改两边。
- 新增 UI 分区进 `Views/PanelSections/`，每个分区一个文件。

---

## Naming Conventions

- Swift 类型/协议：`PascalCase`（`PetWindow`、`PetRenderer`）。
- SwiftUI 视图：`<功能>View`（`TaskCardView`、`ConfirmDialog`）。
- 枚举 case：`camelCase`（`PetCommand.bubble`、`EmotionState.worried`）。
- 窗口子类：`<功能>Window`，后缀 `Window` 表 NSWindow/NSPanel 子类。

---

## Examples

- `Windows/PetWindow.swift` 是窗口配置范本：透明无边框 + floating + canJoinAllSpaces + 拖拽。
- `Rendering/PetRenderer.swift` 是协议抽象范本：占位与正式实现可互换。
