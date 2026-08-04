# BackendSupervisor 守护

## Goal

Swift app 作为父进程 spawn 并守护 Python 后端，退避重启，统一日志。

## Requirements

- BackendSupervisor：spawn `uv run uvicorn`，传端口与 token 命令行参数
- stdout/stderr 汇入 ~/Library/Application Support/DayByDay/logs/，与 Python 侧同一时间线
- 退避重启：1s→2s→4s→8s→30s，连续 5 次失败后宠物切 worried 并气泡提示
- app 退出即回收子进程（SIGTERM 优雅退出 + 超时 SIGKILL）
- 位置持久化：宠物拖拽位置写 UserDefaults

## Acceptance Criteria

- [ ] 手动 kill Python 进程，8 秒内自动恢复连接，SSE 重连
- [ ] 连续 kill 5 次后宠物变 worried 并气泡提示，不再无限重启
- [ ] 退出 app 后无残留 Python 进程
- [ ] 宠物位置重启后保持

## Notes

- SMAppService 开机自启注册可放本任务或独立，先放这里
- token 生成逻辑在此任务（供 api-sse 对接）
