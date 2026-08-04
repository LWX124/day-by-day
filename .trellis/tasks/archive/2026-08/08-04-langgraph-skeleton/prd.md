# LangGraph 图骨架与 checkpointer

## Goal

搭建 LangGraph 主图与 SqliteSaver checkpointer，接入 classify 节点与 ingest/query/freeform 三节点。

## Requirements

- 图结构：classify → {ingest_task | query_status | freeform} 分发
- SqliteSaver 用主库文件独立表，thread_id 维度持久化
- ingest_task：调用结构化抽取 → 落库 → 回执
- query_status：取任务 + 占位 evidence → LLM 总结成话
- freeform：通用对话 + Note 读写占位
- 节点间状态用 TypedDict，含 messages 与 scratch

## Acceptance Criteria

- [ ] 对图输入'建个任务：下周三前做完重构'，classify 路由到 ingest_task 并落库
- [ ] 同一 thread_id 两次输入能保持上下文
- [ ] 断点续跑：图执行到一半中断可恢复

## Notes

- Daily Review / period_report / redecision / gerrit_ops 节点在后续里程碑接，本任务只搭骨架
- checkpointer 是选 LangGraph 的主要收益点（跨小时中断对话）
