# 确认动作通路

## Goal

打通需确认动作的登记→推送→用户确认→落地/超时作废全链路。

## Requirements

- pending_action 表/内存结构：action_id, tool, args, created_at, expires_at(默认5分钟)
- 登记后推 request_confirm PetCommand 到 Swift
- POST /confirm {action_id} 接收确认，校验未过期，执行真实 Tool
- 超时未确认自动作废
- Swift 侧确认弹窗 UI（标题/详情/确认/取消）

## Acceptance Criteria

- [ ] agent 发起 delete_task，Swift 弹确认框，点确认后任务删除，取消则作废
- [ ] 5 分钟不操作自动作废，再确认报错
- [ ] 确认弹窗不抢焦点

## Notes

- 这是对外不可逆动作的护栏，LLM 不得绕过
- Gerrit 写操作在 M6 复用此通路
