# 系统通知权限与 notify

## Goal

申请 macOS 通知权限，实现 notify PetCommand 到 UNUserNotificationCenter。

## Requirements

- 首次启动申请通知权限
- notify PetCommand → UNUserNotificationCenter，含 title/body
- 通知点击行为：打开面板到对应分区
- 通知不抢焦点、可静默（气泡已展示时通知降级）

## Acceptance Criteria

- [ ] 18:30 复盘触发时收到系统通知
- [ ] 点击通知打开面板
- [ ] 拒绝权限时降级为仅气泡+徽标，不崩

## Notes

- 通知是非侵入触发的载体之一
- 权限被拒要有降级
