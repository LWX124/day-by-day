# 唤醒补偿与 wake 通路

## Goal

机器从睡眠唤醒后补跑错过的调度。

## Requirements

- Swift 监听 NSWorkspace.didWakeNotification → POST /wake
- 后端收到 /wake 立即跑一次 hourly_tick + 检查 daily_review 补偿窗口
- Daily Review 补偿：唤醒后若仍在 18:30–23:00 窗口内补触发，超窗标 missed 并入次日早报
- ensure_occurrences 在唤醒时补齐漏掉的 occurrence

## Acceptance Criteria

- [ ] 机器睡过 18:30，20:00 唤醒后补触发 Daily Review
- [ ] 睡到次日才唤醒，Daily Review 标 missed
- [ ] 唤醒后漏掉的 recurring occurrence 被补齐

## Notes

- 桌面应用凌晨睡眠是必然，补偿逻辑必须有
- 补偿窗口 18:30–23:00 可配
