# period_report 节点

## Goal

实现 LangGraph period_report 节点：core 算数字 + LLM 成文并引用 Daily Review 原话。

## Requirements

- core 给统计数字
- LLM 组织成文，引用该周期内 DailyReviewAnswered 的原话
- reports 表落库（kind/period/stats/body_md）
- 支持周报/月报/自定义区间
- LLM 不可用时只存 stats，body 待补

## Acceptance Criteria

- [ ] 周报数字可核对、重复生成一致
- [ ] 周报引用了复盘原话
- [ ] 中间 2 天没复盘仍能基于事件流写出内容（无黑洞）

## Notes

- 引用复盘原话让周报有人味
- 无 LLM 时降级存 stats
