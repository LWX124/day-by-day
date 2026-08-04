# Gerrit 写操作 Tool

## Goal

实现 gerrit_review_vote/gerrit_abandon/gerrit_rebase 三个 Tool，全部走确认流。

## Requirements

- gerrit_review_vote：ssh gerrit review <change>,<patchset> --code-review +1/+2
- gerrit_abandon：ssh gerrit review --abandon
- gerrit_rebase：ssh gerrit rebase
- 全部注册为需确认级 Tool，不直接执行
- 执行前展示 change 主题/owner/改动行数

## Acceptance Criteria

- [ ] 三个 Tool 调用时只生成 pending_action 不落地
- [ ] 确认后正确执行对应 gerrit 命令
- [ ] SSH 命令失败有明确错误

## Notes

- 写操作对外不可逆，必须确认（ADR-0004 第2条）
- 复用 confirm-action 通路
