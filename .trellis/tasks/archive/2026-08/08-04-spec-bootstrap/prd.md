# 填充 .trellis/spec

## Goal

在写任何实现代码前，把 backend/ 与 frontend/ 的空模板填上真实约定，让后续 sub-agent 写出符合本工程结构的代码。

## Requirements

- backend 分层约定：core（纯函数域，禁 import LLM/网络/IO）、store、agent、api、collectors、scheduler 各自职责边界
- backend 事件流写入规范：只 append、撤销靠 EventUndone、投影可重建
- frontend Swift 窗口层级约定：PetWindow/BubbleWindow/TaskCardWindow/PanelWindow/CelebrationOverlay 各自 NSWindow 配置
- frontend PetCommand 处理约定：SSE 消费、dispatch 到各窗口
- frontend PetRenderer 协议约定：占位实现与 sprite 实现可互换
- 所有文档用中文（覆盖 Trellis 模板的 English 要求）

## Acceptance Criteria

- [ ] backend 与 frontend 的 index.md 勾选状态从 To fill 变为已填
- [ ] core 禁依赖约束能被一条检查（import-linter 规则或 CI 脚本）钉死
- [ ] sub-agent 读取 spec 后能写出符合分层的代码（人工抽查一条）

## Notes

- 这是 M0 的前置任务，必须在 py-scaffold 之前完成
- 参考 .trellis/docs/design.md 各章节
- 覆盖原 00-bootstrap-guidelines 任务，那个任务可归档
