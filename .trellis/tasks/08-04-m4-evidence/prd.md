# M4 外部证据

## Goal

接入 git 只读扫描与 Gerrit 查询，产出 Activity Evidence 接入复盘，绝不自动改状态。

参考：`design.md §6.3-§6.4；ADR-0004`

## 子任务依赖

- git-collector/gerrit-query 独立
- project-note 是它们的前置
- evidence-review 依赖 daily-review-node(M2) 与 collectors
- gerrit-nag 依赖 gerrit-query

## Acceptance Criteria

- [ ] 问任务状态返回 commit/Gerrit 证据且明确不改状态
- [ ] git 写命令白名单越权被拒
- [ ] 改 Project.local_path 关联任务立即生效
- [ ] 有活动未标完成的任务复盘时被挑出

## Notes

- 有提交≠完成（ADR-0004），evidence 只问不改
- git 白名单是红线，扫描真实工作目录无补救
- Gerrit 2.8.4 只走 SSH CLI（已验证）
