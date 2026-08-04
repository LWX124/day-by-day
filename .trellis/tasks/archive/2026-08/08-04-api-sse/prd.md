# API+SSE 通信层

## Goal

实现 FastAPI 端点与 SSE 推送通道，token 鉴权，只 bind 127.0.0.1。

## Requirements

- POST /intent {text}、GET /today、POST /tasks CRUD、POST /confirm {action_id}、POST /wake 占位端点
- GET /events SSE 长连接：推送 PetCommand（set_emotion/bubble/celebrate/notify/open_panel/request_confirm/badge）
- 鉴权：Bearer token，token 由 Swift 启动时生成并以命令行参数传入，不落盘不进环境变量
- 只 bind 127.0.0.1，随机高位端口
- Pydantic 模型定义全部请求/响应/PetCommand

## Acceptance Criteria

- [ ] 无 token 请求被 401 拒绝
- [ ] SSE 连接能收到一条测试 PetCommand
- [ ] Swift 侧（占位）能调通 /today
- [ ] 崩溃后端口释放，重启不冲突

## Notes

- token 生成在 Swift 侧，本任务先定义接口契约
- SSE 是 Python→Swift 的唯一主动通道，PetCommand 枚举要和 Swift 侧对齐
