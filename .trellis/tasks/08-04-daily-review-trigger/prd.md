# Daily Review 触发协议

## Goal

实现 18:30 非侵入触发、30 分钟降级、补偿窗口、周末跳过全套协议。

## Requirements

- 18:30 宠物动作 + 气泡 + 一条系统通知，绝不抢焦点
- 30 分钟无响应降级为宠物徽标，当天不再追
- 睡眠错过在 18:30–23:00 窗口内补触发（接 wake-catchup）
- 超窗标 missed 并入次日早报开场
- 周末默认跳过（可配开关）
- daily_reviews 表状态机：pending→prompted→in_progress→done/skipped/missed

## Acceptance Criteria

- [ ] 18:30 触发不抢焦点（只通知+气泡+动作）
- [ ] 30 分钟不理降级为徽标且当天不再弹
- [ ] 周末跳过
- [ ] missed 状态次日早报能看到

## Notes

- 非侵入是桌面工具存活前提，抢焦点会被两周内关掉
- 与 wake-catchup 协作
