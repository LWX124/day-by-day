# Frontend Development Guidelines

> DayByDay.app（SwiftUI 原生 macOS 外壳）开发规范。前端只管渲染与用户事件，决策在 Python 后端（ADR-0001）。

---

## Overview

Swift 侧围绕窗口层级 + PetCommand 处理 + 渲染层协议组织。窗口组合的硬需求（透明、置顶、跨 Space、不抢焦点、点击穿透）见 design.md §8。

---

## Pre-Development Checklist

写 Swift 代码前确认：

- [ ] 这段逻辑是渲染/事件，还是业务判定？判定进后端 `core/`，Swift 不内嵌。
- [ ] 新窗口 `canBecomeKey`/`canBecomeMain` 按需 false 了吗（不抢焦点）？
- [ ] 透明/置顶/跨 Space/点击穿透配置正确吗？
- [ ] `PetCommand` 新增 case 两边都改了吗（`commands.py` + `PetCommand.swift`）？
- [ ] 异步任务可取消，SSE 重连有退避吗？

---

## Guidelines Index

| Guide | Description | Status |
|-------|-------------|--------|
| [Directory Structure](./directory-structure.md) | 窗口/渲染/视图分层 | ✅ 已填 |
| [Component Guidelines](./component-guidelines.md) | SwiftUI 视图约定，不内嵌判定 | ✅ 已填 |
| [Hook Guidelines](./hook-guidelines.md) | async/await + SSE 订阅模式 | ✅ 已填 |
| [State Management](./state-management.md) | @Observable + 后端权威快照 | ✅ 已填 |
| [Quality Guidelines](./quality-guidelines.md) | forbidden patterns、不抢焦点、测试 | ✅ 已填 |
| [Type Safety](./type-safety.md) | Codable 契约、PetCommand 枚举对齐 | ✅ 已填 |
| [Process Supervision](./process-supervision.md) | spawn 子进程环境陷阱 + 退避重启单一路径 | ✅ 已填 |

---

## Quality Check

提交前自查：

- [ ] `xcodebuild build` 通过，无 warning
- [ ] SwiftLint 通过
- [ ] 严格并发检查通过
- [ ] 新窗口有对应的配置测试
- [ ] 后端不可用时降级展示正常

---

**语言**：本工程文档用**中文**。
