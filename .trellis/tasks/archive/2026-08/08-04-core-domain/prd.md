# core 纯函数域

## Goal

实现 Schedule 四态联合类型、非法组合校验、ensure_occurrences_up_to、today_view，全部纯函数无 LLM 依赖。

## Requirements

- Schedule 联合类型：one_shot/deadline/recurring/openended 各自字段，非法组合拒绝（recurring 不许有 due 等）
- ensure_occurrences_up_to(today, backfill_days=30)：幂等生成 Recurring 当日实例，改规则只重算未来、过去冻结
- today_view(now)：返回今日应做（deadline 到期/临近、recurring 当日 occurrence、其他 in_progress）
- 当前时间作参数传入，core 内不读系统时钟
- Weight 枚举 S/M/L/XL

## Acceptance Criteria

- [ ] one_shot 任务出现在 today_view（in_progress 状态）
- [ ] deadline 任务未到 lead_days 窗口不出现在 today_view 的催办区
- [ ] recurring 任务 sleep 一晚后 ensure_occurrences 补齐当日实例且不重复
- [ ] 改 recur_rule 后未来 occurrence 重算、过去不动
- [ ] core/ 下所有函数可脱离数据库单测（传入内存数据）

## Notes

- core 是全工程最该高覆盖的地方，验收靠伪造时钟
- ensure_occurrences 的三触发时机（启动/唤醒/hourly）在 scheduler 任务接，本任务只做函数
