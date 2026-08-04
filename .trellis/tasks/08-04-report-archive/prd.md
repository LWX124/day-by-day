# 报告回看与导出

## Goal

PanelWindow 复盘历史分区可回看与导出报告。

## Requirements

- 复盘历史分区列出已生成 reports
- 点击查看 body_md 渲染
- 导出为 Markdown 文件
- 周日 20:00 weekly_prompt 触发生成入口

## Acceptance Criteria

- [ ] 能列出历史周报/月报
- [ ] 能查看内容
- [ ] 能导出 .md
- [ ] 周日提示可生成周报

## Notes

- weekly_prompt 只提示不自动生成（尊重用户意愿）
