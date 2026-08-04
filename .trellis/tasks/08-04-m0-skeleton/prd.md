# M0 骨架

## Goal

搭起双进程骨架并跑通最小闭环：宠物在桌面常驻、单击看到手工建的今日任务、后端崩溃自愈、睡眠唤醒补齐。无 LLM 也能用。

参考：`design.md §1-§4, §8；ADR-0001`

## 子任务依赖

- spec-bootstrap→py-scaffold→event-store→core-domain→api-sse
- swift-window-spike 独立并行
- backend-supervisor 依赖 api-sse 与 swift-window-spike

## Acceptance Criteria

- [ ] 手工建 4 种 schedule 任务各一条，单击宠物看到今日该做什么
- [ ] kill Python 进程 8 秒内恢复
- [ ] 睡到次日唤醒，漏掉的 occurrence 被补齐
- [ ] 删投影表能从 events 重建
- [ ] 透明窗口跨 Space 可见、全屏 overlay 点击穿透

## Notes

- 这是整个工程的地基，必须先跑通
- core 纯函数约束从 spec-bootstrap 开始钉死
- bootstrap-guidelines 任务被 spec-bootstrap 覆盖，可归档
