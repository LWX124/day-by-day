"""FastAPI 路由注册（design.md §4）。

将 /intent 路由注册到主 app。
"""

from __future__ import annotations

from api.routes.intent import router as intent_router
from api.routes.main import (
    get_bus,
    get_conn,
    init_app_state,
    router,
)

__all__ = [
    "get_bus",
    "get_conn",
    "init_app_state",
    "intent_router",
    "router",
]
