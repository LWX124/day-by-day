# daily_review 节点与可中断对话

## Goal

实现 LangGraph daily_review 节点：候选清单逐项问，结论写回事件流，支持跨小时中断续接。

## Requirements

- 候选清单：今日应做 + 有活动未标完成（接 evidence 占位）+ 断签习惯
- 逐项问状态，用户回答写 DailyReviewAnswered 事件
- thread_id = review-YYYY-MM-DD，checkpointer 支持中断数小时后续接
- 全部问完生成结构化 summary 写 daily_reviews.summary
- 中途可暂停，下次接着上文

## Acceptance Criteria

- [ ] Daily Review 问到一半中断，几小时后回复能接上上文（同 thread_id）
- [ ] 回答写回事件流可查
- [ ] 全部问完生成 summary

## Notes

- 跨小时中断续接是选 LangGraph 的主要收益
- 有活动未标完成的真实 evidence 在 M4 接入，本任务用占位
