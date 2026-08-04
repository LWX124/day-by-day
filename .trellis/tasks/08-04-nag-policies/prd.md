# Nag 策略四对象

## Goal

实现 four schedule 各自的 nag 策略对象，纯函数，输出 NagCandidate 列表。

## Requirements

- one_shot：now - last_activity_at > idle_threshold(weight) 触发（S7d/M14d/L21d/XL30d 可配）
- deadline：due 前 lead_days(weight) 天、due 当天、逾期后每日一次；未到窗口不触发
- recurring：连续断签 ≥ 2 个应有 occurrence 触发；永不因总时长触发
- openended：距上次 review > 30 天触发；本月已 review 过则不触发
- due_nags(tasks, occurrences, now) -> list[NagCandidate]

## Acceptance Criteria

- [ ] deadline 未到 lead_days 一声不出（对应'订好1月完成没到期限不提醒'）
- [ ] recurring 挂半年也不因总时长触发
- [ ] one_shot 按 weight 阈值触发
- [ ] openended 月度触发且本月已 review 不重复
- [ ] 全部用伪造时钟单测，不 mock LLM

## Notes

- 这是需求 10 三个例外的代码落点，最关键的纯函数
- 阈值全部可配
