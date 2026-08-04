# 事件流存储与投影

## Goal

实现 events append-only 表、全部投影表建表、事件写入、重放、撤销、投影重建。

## Requirements

- store/migrations/0001_init.sql：建 design.md §4 的全部表（events/tasks/occurrences/projects/notes/activity_evidence/daily_reviews/reports）
- 事件 append 函数：写 events 表，payload JSON 序列化
- 投影重建函数：从 events 重放得到 tasks/occurrences 当前状态
- 撤销：写 EventUndone{target_event_id}，重放时跳过被撤销事件
- WAL 模式，迁移按编号顺序执行
- LangGraph SqliteSaver 用同库文件独立表（占位配置，不阻塞）

## Acceptance Criteria

- [ ] 建 4 种 schedule 任务各一条 + 打卡 + 改期，events 表有对应记录
- [ ] 删掉全部投影表后能从 events 完整重建且数据一致
- [ ] 撤销一条 TaskStatusChanged 后任务状态回到撤销前
- [ ] 重复迁移幂等（已执行的不重复跑）

## Notes

- 这是事实来源层，core 和 agent 都依赖它
- schema 见 design.md §4，严格按表结构
- 体积在个人量级可忽略，不必担心 events 增长
