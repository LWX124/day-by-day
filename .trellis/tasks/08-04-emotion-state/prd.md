# Emotion State 推导

## Goal

实现 emotion() 纯函数，由积压/断签/近期庆祝/时钟推导宠物情绪状态。

## Requirements

- 状态：idle/happy/focused/worried/grumpy/sleeping
- 输入：today_view, overdue_count, broken_streaks, recent_celebration, clock
- sleeping：夜间或锁屏
- worried：后端连续崩溃或积压严重
- grumpy：断签多或有逾期未处理
- happy：近期有庆祝
- 不经 LLM（否则表情随机漂移）

## Acceptance Criteria

- [ ] 积压严重时宠物 worried
- [ ] 断签多时 grumpy
- [ ] 夜间 sleeping
- [ ] 纯函数可单测

## Notes

- Emotion 不经 LLM 是为了表情稳定
- 驱动 sprite 多状态切换
