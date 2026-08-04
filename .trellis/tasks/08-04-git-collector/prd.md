# git 只读采集器

## Goal

实现 git 只读子命令白名单采集器，产出 Activity Evidence。

## Requirements

- 白名单：log/status/diff/branch/rev-list/show/shortlog
- 参数数组 exec 不经 shell
- 拒绝 -c/--exec/--upload-pack 等注入向量
- 工作目录必须落在某 Project 的 local_path 内
- 产出 EvidenceCollected 事件：commits 数/时间分布/分支/message/改动行数

## Acceptance Criteria

- [ ] 尝试让 agent 执行 git reset --hard 被拒绝且记日志
- [ ] 拒绝 -c 注入
- [ ] 工作目录不在任何 Project 内被拒
- [ ] 正常采集产出结构化 evidence

## Notes

- git 写子命令不可达是 ADR-0004 红线，扫描的是真实工作目录无补救
- evidence 永远只是证据不改状态
