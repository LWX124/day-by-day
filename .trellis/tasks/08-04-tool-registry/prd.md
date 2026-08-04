# Tool 注册表与授权分级

## Goal

实现 Tool 注册表与读/常规写/需确认三级授权框架。

## Requirements

- 读级 Tools：list_tasks/get_task/today_view/compute_stats/query_git_evidence(占位)/query_gerrit_changes(占位)/get_project/search_notes
- 常规写级：create_task/update_task/complete_task/checkin_occurrence/reschedule_task/abandon_task/upsert_project/upsert_note
- 需确认级：delete_task/gerrit_review_vote/gerrit_abandon/gerrit_rebase
- Tool schema 由 pydantic 自动生成
- 需确认 Tool 不直接执行，登记 pending_action 并推 request_confirm

## Acceptance Criteria

- [ ] agent 调常规写 Tool 直接落库并回执，且可撤销
- [ ] agent 调需确认 Tool 只生成 pending_action 不落地
- [ ] 读 Tool 可自由调用

## Notes

- git/gerrit 查询 Tool 在 M4 实现真实逻辑，本任务只注册签名
- 授权分级是 ADR-0004 的核心
