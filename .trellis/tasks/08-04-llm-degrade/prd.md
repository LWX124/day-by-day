# 无 key 降级模式

## Goal

LLM 不可用时系统降级为纯确定性模式，提醒/统计/打卡/特效照常，仅禁用自然语言录入与成文。

## Requirements

- Provider 不可用时 UI 隐藏对话入口，显示降级提示
- 降级下仍可：手工 CRUD 任务、打卡、看今日视图、被 nag、看统计
- 降级下禁用：自然语言录入、Daily Review 对话、报告成文（统计数字仍可算）
- Provider 恢复后自动切回，无需重启

## Acceptance Criteria

- [ ] 清空 key 后手工建任务/打卡/看今日均正常
- [ ] Provider 恢复后对话入口自动恢复
- [ ] 降级期间 nag 照常推送

## Notes

- 降级是 ADR-0003 的副产品：判定全在 core 纯函数，所以 LLM 挂了判定不挂
- 这是系统能长期存活的关键——LLM 服务不稳定时不至于全哑
