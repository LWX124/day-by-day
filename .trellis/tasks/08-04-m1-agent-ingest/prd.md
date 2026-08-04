# M1 自然语言录入与查询

## Goal

接入 LLM 与 LangGraph，实现自然语言建任务、查状态、自由对话，结构化推断物化落库。

参考：`design.md §6.1-§6.2, §6.5；ADR-0003`

## 子任务依赖

- provider-abstraction→langgraph-skeleton→structured-extraction
- tool-registry→confirm-action
- intent-dialog 集成前几个子任务
- llm-degrade 贯穿

## Acceptance Criteria

- [ ] 说'下周三前做完重构'→建出 deadline 任务 due 正确 weight 有值
- [ ] 说'每天读5页书'→recurring 任务当日实例出现
- [ ] 说'那个做完了'→正确匹配并标完成可撤销
- [ ] 清空 key 后提醒/统计/打卡照常，仅对话禁用

## Notes

- 推断在写入侧、判定在读取侧（ADR-0003）
- 需确认动作通路在此期建立，M6 复用
- 微博网关协议待确认不阻塞，先用百炼/DeepSeek
