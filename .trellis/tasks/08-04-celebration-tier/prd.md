# Tier 函数

## Goal

实现 celebration_tier(task, now) 纯函数，按 Weight/拖延时长/里程碑算 1–4 档。

## Requirements

- 基线 tier = weight 映射 S1/M2/L3/XL4
- 拖延 > 30 天 +1（拖了一个月终于干掉，情绪峰值）
- 当日/当周最后一个完成 +1（清空里程碑）
- clamp 到 4
- 逾期完成不降档（完成就该庆祝），逾期事实只进复盘与报告

## Acceptance Criteria

- [ ] S 任务完成得 Tier 1
- [ ] 拖了一个月的 M 任务完成得 Tier 4（2+1+1）
- [ ] XL 任务完成得 Tier 4（clamp）
- [ ] 逾期完成不比按时完成档位低

## Notes

- Tier 是纯函数，可单测不 mock LLM
- 情绪价值峰值在'拖了很久终于干掉'那一刻
