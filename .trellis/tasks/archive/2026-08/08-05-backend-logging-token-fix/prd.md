# 后端启动日志崩溃与 token 噪音修复

## Goal

修复后端启动时的两个日志/启动问题：
1. `api/__main__.py:59` logging 格式崩溃（`%d` 配字符串导致 TypeError）
2. `api/app.py:124` 模块级 `app = create_app()` 触发 `_dev_token()` 打 warning 噪音（实际 token 由 `__main__.py` 正确传入）

## Background

- 现状：`python -m api --token <t>` 启动时，日志出现两条异常：
  - `TypeError: %d format: a real number is required, not str`（`__main__.py:59`，`args.port or "<random>"` 在 port=0 时变成字符串，但格式串用 `%d`）
  - `WARNING create_app 未收到 token`（`app.py:118`，模块级 `app = create_app()` 在 import 时执行，token 为 None）
- 根因 1：`__main__.py:59` `log.info("starting backend on %s:%d ...", args.host, args.port or "<random>", ...)` —— `args.port` 是 `0`，`0 or "<random>"` → `"<random>"`（字符串），`%d` 要数字 → TypeError
- 根因 2：`api/app.py:124` 有模块级 `app = create_app()`，在 `__main__.py` `from api.app import create_app` 时触发，此时 token 为 None，`_dev_token()` 打 warning。但 `__main__.py` 随后调 `create_app(token=token)` 创建正确的 app，uvicorn 跑的是后者，功能正确但日志误导。

## Requirements

- **修复 logging 崩溃**：`__main__.py:59` 的 `log.info` 格式串兼容 port=0 的情况。port=0 是合法值（OS 随机分配），不应 fallback 到字符串。用 f-string 或 `%s` 替代 `%d`。
- **消除 token 噪音**：模块级 `app = create_app()` 的 warning 日志降级为 info 或不打（开发期直接 `uvicorn api.app:app` 跑时才需要提示）。或改为懒加载，避免 import 时触发。
- **不破坏开发期直接跑**：`uvicorn api.app:app` 直接跑时（不走 `__main__.py`），仍应生成 dev token 并正常工作。
- **不破坏 token 鉴权**：`__main__.py` 传入的 token 必须正确到达 `create_app`，鉴权依赖 `_token_dep` 从 `app.state.api_token` 取，不能改错。

## Acceptance Criteria

- [ ] `python -m api --token <t>` 启动，日志无 TypeError，无 "未收到 token" warning
- [ ] `uvicorn api.app:app` 直接跑（开发期），日志有 info 级提示生成 dev token，功能正常
- [ ] `/health` 端点 200，其余端点带正确 token 鉴权通过
- [ ] 后端日志格式正常，无崩溃堆栈

## Notes

- 模块级 `app = create_app()` 是给 `uvicorn api.app:app` 用的工厂入口。`__main__.py` 路径是生产入口。两者不能互相破坏。
- 修复后建议统一后端日志格式（时间线前缀与 Swift 侧一致），但那是 logging-guidelines 的长期任务，不纳入本任务。
