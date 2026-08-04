# 意图入口与对话 UI

## Goal

打通 POST /intent → agent 图 → 回执/气泡/面板对话的全链路，PanelWindow 先做对话+今日两分区。

## Requirements

- POST /intent 接用户文本 → 路由进 LangGraph 图
- PanelWindow 对话分区：消息流 + 输入框，接 SSE 回执
- PanelWindow 今日分区：展示 today_view
- TaskCardWindow（单击）展示今日+近期截止+断签习惯
- BubbleWindow（悬停）展示今日剩余数 + 最近一条 nag

## Acceptance Criteria

- [ ] 对宠物说一句话，面板对话区出现回执，今日分区出现新任务
- [ ] 单击宠物弹任务卡显示今日任务
- [ ] 悬停宠物弹气泡显示剩余数

## Notes

- 这是 M1 的集成验收点，把前几个子任务串起来
- PetCommand 全集在此任务对齐 Swift 侧渲染
