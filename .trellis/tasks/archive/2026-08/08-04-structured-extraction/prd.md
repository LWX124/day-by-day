# 结构化抽取与置信度

## Goal

LLM 把模糊自然语言推断成 Schedule/due/Weight/Project 引用结构化字段，每字段带置信度，高置信直接落库低置信反问。

## Requirements

- pydantic 模型：TaskDraft{schedule_kind, due_at, recur_rule, recur_target, weight, project_ref, confidence_per_field}
- 推断在写入侧（ADR-0003）：结果物化落库到 tasks.inference
- 高置信字段直接落库 + 一行回执气泡
- 低置信字段（无任何时间线索等）触发反问一句
- Project 引用按别名解析命中已存在 Project，未命中则反问或新建
- 事后一句话可改任一字段（改动本身是一条事件）

## Acceptance Criteria

- [ ] '下周三前把登录重构做完' → deadline 任务、due 正确、weight 有值、回执一行
- [ ] '每天读5页书' → recurring 任务、当日实例出现
- [ ] '那个重构做完了' → 正确匹配任务并标完成
- [ ] 推断错误后一句话能改 schedule/due/weight

## Notes

- 推断与判定分离是核心架构（ADR-0003），判定全在 core 纯函数
- 置信度阈值可配
