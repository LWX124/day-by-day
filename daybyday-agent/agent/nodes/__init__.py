"""agent 节点：LangGraph 图的各执行单元。

每个节点是纯函数 `(state) -> partial state`。节点需要的外部依赖（router、
bus、conn）通过 `build_graph` 闭包注入，不在节点签名里暴露——保持节点函数
可单独测试（传 state 即可）。

design.md §6.1 节点清单（本里程碑只接骨架四节点）：
    classify       意图分类 → 路由
    ingest_task    结构化抽取 → 落库 → 回执
    query_status   取任务 + evidence → 总结成话
    freeform       通用对话 + Note 读写（占位）

后续里程碑在此加：daily_review / period_report / redecision / gerrit_ops。
"""
