# 待评审堆积 Nag

## Goal

待我评审的 change 堆积超阈值时触发一次 Nag。

## Requirements

- 查询待评审 change 数量
- 超阈值（可配，默认 5）触发一次 Nag 气泡
- 不进入 nag_count 升级链（独立提醒）
- 气泡带'去面板看'快捷入口

## Acceptance Criteria

- [ ] 待评审 6 个时触发一次提醒
- [ ] 不因这个 nag 累加 nag_count
- [ ] 面板能跳转到 Gerrit 分区

## Notes

- 独立提醒不污染任务 nag 链
- 阈值可配
