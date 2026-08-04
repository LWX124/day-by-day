# Evidence 接入复盘候选

## Goal

把 git/Gerrit evidence 接入 Daily Review 候选清单，挑出有活动未标完成的任务。

## Requirements

- Daily Review 候选增加：有 Activity Evidence 但 task 未标 done 的任务
- Gerrit merged 权重高于本地 commit
- 复盘时展示 evidence 摘要 + LLM 一句总结
- 仍不自动改状态，只问用户

## Acceptance Criteria

- [ ] 任务有 commit 但未标完成，复盘时被挑出来问
- [ ] Gerrit merged 的任务优先问
- [ ] 绝不自动标完成

## Notes

- 有提交≠完成（ADR-0004 第1条），evidence 只问不改
- 这是扫描结果的主要消费点
