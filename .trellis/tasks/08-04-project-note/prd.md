# Project/Note 与别名解析

## Goal

实现 Project 结构化实体与 Note 自由文本，含别名解析。

## Requirements

- Project CRUD：name/aliases(数组)/local_path/gerrit_repo
- 别名解析：说'主站'命中对应 Project
- Note CRUD：project_id 可空/tags 数组/body 自由文本
- Task 关联 Project 而非裸路径（project_id 外键）
- 改 Project.local_path 后所有关联任务立即生效

## Acceptance Criteria

- [ ] 说'主站'能命中 Project
- [ ] Task 关联 Project 后改 local_path 全局生效
- [ ] Note 可挂 Project 或 tag

## Notes

- Project 结构化是为程序直接执行 git 命令（路径不能幻觉）
- Note 自由文本给 LLM 读
