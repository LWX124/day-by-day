# APScheduler 调度装配

## Goal

装配 APScheduler 的 hourly_tick / daily_review / weekly_prompt 三个 job。

## Requirements

- hourly_tick：每小时 ensure_occurrences + 扫 nag 候选 + 推送
- daily_review：18:30 触发（见 daily-review-trigger 子任务协议）
- weekly_prompt：周日 20:00 气泡提示可生成周报，不自动生成
- APScheduler AsyncIO scheduler 与 FastAPI 同进程
- job 失败不影响其他 job，记日志

## Acceptance Criteria

- [ ] hourly_tick 每小时触发且幂等
- [ ] daily_review 在 18:30 触发
- [ ] weekly_prompt 周日 20:00 提示
- [ ] 伪造时钟能验证各 job 触发时机

## Notes

- 唤醒补偿在 wake-catchup 子任务
- APScheduler 选 AsyncIO 避免线程问题
