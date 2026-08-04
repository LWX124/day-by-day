# Python 脚手架与分层约束

## Goal

建立 daybyday-agent 的 uv + FastAPI 项目骨架，分层目录到位，分层依赖约束可被检查。

## Requirements

- uv 项目初始化，pyproject.toml 含 fastapi/uvicorn/pydantic/langchain-core/langgraph/sqlite/APScheduler
- 目录：core/ store/ agent/ api/ collectors/ scheduler/ common/
- core/ 的 import-linter 规则：禁止 import 任何 agent/store/api/collectors/scheduler 模块及 langchain*
- pytest 配置就绪，core/ 下至少一个占位测试跑通
- 应用配置加载：config.toml 解析（数据目录 ~/Library/Application Support/DayByDay/）

## Acceptance Criteria

- [ ] uv run pytest 通过
- [ ] uv run lint import-linter 报告 core 无越界依赖
- [ ] uvicorn 能起一个空 FastAPI app 监听 127.0.0.1

## Notes

- 依赖 event-store 之前先有骨架，但本任务只建结构不建存储逻辑
- core 纯函数约束是全工程最重要的架构红线，从这里开始钉
