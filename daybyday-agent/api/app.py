"""FastAPI app 工厂。

组装路由 + 启动时 init_db + PetCommandBus 单例。token 鉴权：token 由调用方
（Swift / `python -m api` 入口）以参数显式传入，存 app.state，**不读环境变量**——
对应 PRD「token 由 Swift 启动时生成并以命令行参数传入，不落盘不进环境变量」
与 design.md §2「不走环境变量」。

绑定约束（design.md §2）：只 bind 127.0.0.1，随机高位端口。由 uvicorn 启动参数
控制（`python -m api --host 127.0.0.1 --port 0`，port 0 = 随机高位），不在 app 内管。
"""

from __future__ import annotations

import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Security, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.requests import Request

from api.routes import init_app_state, router
from common.errors import DayByDayError, error_payload, http_status

# 模块级 HTTPBearer 实例，供 _token_dep 与路由 dependencies 共用。
_bearer = HTTPBearer(auto_error=False)


def _token_dep(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Security(_bearer),
) -> str:
    """Bearer token 校验。token 从 app.state.api_token 取（由 create_app 注入）。

    对应 PRD 验收「无 token 请求被 401 拒绝」。token 不读环境变量、不落盘。
    """
    expected: str | None = getattr(request.app.state, "api_token", None)
    if expected:
        if creds is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing token")
        if not secrets.compare_digest(creds.credentials, expected):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token")
    return expected or ""


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """启动时 init_db + 注入 PetCommandBus。关闭时无特殊清理（DB 连接随进程退出）。"""
    init_app_state(app)
    yield


def create_app(token: str | None = None) -> FastAPI:
    """构造并返回配好全部路由的 app。

    token：API 鉴权 token。由调用方（Swift / `python -m api` 入口）传入，存
    app.state.api_token，**不读环境变量**（PRD/design.md §2）。开发期可不传，
    此时生成一个随机 token 并记日志，便于本地 `uvicorn api.app:app` 调试。

    启动时（lifespan）调 init_app_state 注入 DB 连接与 PetCommandBus。
    """
    app = FastAPI(title="daybyday-agent", version="0.1.0", lifespan=_lifespan)

    api_token = token if token is not None else _dev_token()
    app.state.api_token = api_token

    # 只允许 loopback：CORS 这里不放开（同机通信），保持默认拒绝跨域。
    # 显式加中间件留个口子说明"不开放跨域"是有意为之。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    # /health 公开（无 token），供 Swift 探活。单独挂载，不带鉴权依赖。
    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    # 其余端点挂 token 依赖。FastAPI 的 APIRouter 不支持"全局 Security 依赖"，
    # 故用 dependencies 参数把 _token_dep 应用到 router 全部路由。
    app.include_router(router, dependencies=[Security(_token_dep)])

    # 统一错误响应：DayByDayError → {error, message, detail}。
    @app.exception_handler(DayByDayError)
    async def _daybyday_handler(_request: Request, exc: DayByDayError) -> JSONResponse:
        return JSONResponse(status_code=http_status(exc), content=error_payload(exc))

    # 请求校验错误也统一格式（422 → 400 user_error）。
    @app.exception_handler(RequestValidationError)
    async def _validation_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={
                "error": "user_error",
                "message": "请求参数校验失败",
                "detail": exc.errors(),
            },
        )

    return app


def _dev_token() -> str:
    """开发期未显式传 token 时生成一个随机 token。

    生产由 Swift 以命令行参数传入（create_app(token=...)），不走本路径。
    用 secrets.token_urlsafe 生成 32 字节熵的 token。
    """
    tok = secrets.token_urlsafe(32)
    import logging

    logging.getLogger("daybyday-agent.api").info(
        "create_app 未收到 token，已生成开发用随机 token（生产应由 Swift 注入）: %s", tok
    )
    return tok


# `uvicorn api.app:app` 直接跑时用开发 token。生产走 `python -m api --token <t>`。
app = create_app()
