# Nag 升级与 Re-decision 终点

## Goal

实现 nag 语气递增与 3 次后转 Re-decision 的终点逻辑。

## Requirements

- nag_count 0→1 轻推、1→2 认真问、2→3 鞭策（LLM 生成语气递增文案）
- ==3 后停止催'快做'，改为 Re-decision：改期/降级/放弃
- RedecisionMade 事件写入后 nag_count 归零
- 鞭策文案降级模式下用模板
- 改期/降级/放弃三选项的交互（气泡 quick_replies 或面板）

## Acceptance Criteria

- [ ] 同一任务连续 3 次 nag 无响应后第 4 次收到 Re-decision 而非催促
- [ ] 做出 Re-decision 决策后 nag_count 清零
- [ ] 鞭策语气随次数递增（人工抽查三档文案差异）

## Notes

- 催办有终点是产品存活前提（ADR-0004），无上限催办必然导致关掉提醒
- Re-decision 让堆积任务变成清理动作
