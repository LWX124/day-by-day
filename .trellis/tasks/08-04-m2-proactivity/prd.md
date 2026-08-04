# M2 主动性

## Goal

让宠物主动起来：四策略 nag、升级与 Re-decision 终点、18:30 复盘、唤醒补偿。

参考：`design.md §5.1-§5.2, §7；ADR-0004`

## 子任务依赖

- nag-policies→nag-escalation
- scheduler/wake-catchup/daily-review-trigger 协作
- daily-review-node 依赖 langgraph-skeleton(M1)
- system-notify 独立

## Acceptance Criteria

- [ ] deadline 未到窗口不催、recurring 不因总时长催、one_shot 按 weight 催（全靠伪造时钟单测）
- [ ] 连续 3 次 nag 后转 Re-decision
- [ ] 18:30 不抢焦点、30 分钟降级、睡眠补偿、周末跳过
- [ ] 复盘中断数小时后续接

## Notes

- 验收必须靠伪造时钟，等不出来
- 催办有终点是产品存活前提
- 非侵入触发是桌面工具存活前提
