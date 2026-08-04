"""api 测试共享 fixtures。

关键点：
- /health 公开、其余端点走 Bearer token（token 由 create_app(token=...) 注入，
  不读环境变量——对应 PRD「不进环境变量」）。
- DB 用临时库，check_same_thread=False 以便测试线程与 ASGI 线程共享。
- SSE 测试不能靠 TestClient（httpx ASGITransport 不支持流式响应，
  会阻塞到 app 调用结束），改用真实 uvicorn 服务器 + httpx 流式客户端。
"""

from __future__ import annotations

import asyncio
import socket
import sqlite3
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import uvicorn
from fastapi.testclient import TestClient

from api.app import create_app
from store.db import init_db

# 测试用 token。所有鉴权测试用这个。
TEST_TOKEN = "test-token-1234"


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    """构造 TestClient，DB 指向临时库。

    startup 事件会调 init_app_state → init_db(默认 DB_PATH)。我们不想写真实数据目录，
    所以在 create_app 前把 init_app_state monkeypatch 成用临时库。
    """
    db = tmp_path / "test.sqlite3"
    # check_same_thread=False：TestClient 把 ASGI 跑在独立线程，连接需跨线程共享。
    conn = init_db(db, check_same_thread=False)

    # create_app 的 startup handler 引用的是 api.app 模块全局 init_app_state
    # （from api.routes import init_app_state 在 import 时绑定），所以 patch 这里。
    import api.app as app_mod

    original_init = app_mod.init_app_state

    def _fake_init(app: object) -> None:
        # 幂等：startup 可能再调一次，不要覆盖已注入的 bus（否则测试拿到的 bus 引用失效）。
        if getattr(app.state, "db_conn", None) is not None:
            return
        app.state.db_conn = conn  # type: ignore[attr-defined]
        from api.commands import PetCommandBus

        app.state.command_bus = PetCommandBus()  # type: ignore[attr-defined]

    app_mod.init_app_state = _fake_init  # type: ignore[assignment]
    try:
        app = create_app(TEST_TOKEN)
        # 手动初始化 state（TestClient 的 startup 会再调一次，_fake_init 幂等）。
        _fake_init(app)
        with TestClient(app) as c:
            yield c
    finally:
        app_mod.init_app_state = original_init  # type: ignore[assignment]
        conn.close()


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """带 token 的请求头。"""
    return {"Authorization": f"Bearer {TEST_TOKEN}"}


@pytest.fixture
def bus(client: TestClient):
    """从 app.state 取 PetCommandBus，供 SSE 测试 push 命令。"""
    return client.app.state.command_bus


@pytest.fixture
def _conn(client: TestClient) -> sqlite3.Connection:
    """共享 DB 连接，供测试直接写 events 验证投影。"""
    return client.app.state.db_conn


# ---- 真实 uvicorn 服务器（SSE 流式测试用）----


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
async def live_server(tmp_path: Path) -> AsyncIterator[tuple[str, object, object]]:
    """启动真实 uvicorn 服务器，返回 (base_url, bus, app)。

    SSE 端点必须用真实服务器测：httpx 的 ASGITransport 不支持流式响应
    （会阻塞到 ASGI app 完全返回），TestClient 同理。这里起一个绑定 127.0.0.1
    随机端口的 uvicorn，测试用 httpx AsyncClient 流式连接。
    """
    db = tmp_path / "live.sqlite3"
    conn = init_db(db, check_same_thread=False)
    import api.app as app_mod
    from api.commands import PetCommandBus

    original_init = app_mod.init_app_state

    def _fake_init(app: object) -> None:
        if getattr(app.state, "db_conn", None) is not None:
            return
        app.state.db_conn = conn  # type: ignore[attr-defined]
        app.state.command_bus = PetCommandBus()  # type: ignore[attr-defined]

    app_mod.init_app_state = _fake_init  # type: ignore[assignment]
    app = create_app(TEST_TOKEN)
    _fake_init(app)
    bus = app.state.command_bus
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    # 等服务器起来
    for _ in range(50):
        await asyncio.sleep(0.1)
        if server.started:
            break
    try:
        yield (f"http://127.0.0.1:{port}", bus, app)
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(server_task, timeout=5.0)
        except TimeoutError:
            server_task.cancel()
        app_mod.init_app_state = original_init  # type: ignore[assignment]
        conn.close()
