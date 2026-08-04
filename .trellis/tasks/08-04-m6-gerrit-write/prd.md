# M6 Gerrit 写操作

## Goal

面板里直接对 Gerrit change 打分/abandon/rebase，全程确认流护栏，LLM 不得自主发起。

参考：`design.md §6.4；ADR-0004`

## 子任务依赖

- gerrit-write-tools 依赖 gerrit-query(M4) 与 confirm-action(M1)
- gerrit-confirm-guard 依赖 gerrit-write-tools

## Acceptance Criteria

- [ ] 诱导 agent 直接 +2 只生成待确认不落地
- [ ] 确认框有 change 详情与浏览器打开按钮
- [ ] 超时作废
- [ ] agent 自主发起写操作在代码层不可达

## Notes

- 盲打 +2 是真风险，护栏防呆
- 复用 M1 的 confirm-action 通路
- LLM 不可自主发起是硬约束
