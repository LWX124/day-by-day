# M5 报告

## Goal

按时间段聚合事件流生成周报/月报，数字确定性可核对，LLM 组织成文引用复盘原话。

参考：`design.md §4 reports, §6.1 period_report；ADR-0002`

## 子任务依赖

- stats-aggregation 纯函数先行
- period-report-node 依赖 stats 与 langgraph-skeleton(M1)
- report-archive 依赖 period-report-node

## Acceptance Criteria

- [ ] 周报数字可核对、重复生成一致
- [ ] 引用了复盘原话
- [ ] 中间没复盘的日子不出现黑洞
- [ ] 周日 20:00 提示可生成（不自动）

## Notes

- 事件流是事实来源（ADR-0002），数字可复现
- 引用原话让报告有人味
- 无 LLM 时降级存 stats
