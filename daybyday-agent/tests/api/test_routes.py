"""api/routes 端点测试。

覆盖 PRD 验收：
- 无 token → 401
- 有 token → /today 返回今日视图
- POST /tasks 建任务 → /today 能看到
- SSE：推一条 PetCommand 到 bus，GET /events 能收到
- 占位端点 /intent /confirm /wake 返回结构正确
- 非法 schedule 组合 → 400 user_error
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from api.commands import Badge, SetEmotion

# ---- 鉴权 ----


def test_no_token_returns_401(client: TestClient) -> None:
    r = client.get("/today")
    assert r.status_code == 401


def test_wrong_token_returns_401(client: TestClient, auth_headers: dict[str, str]) -> None:
    r = client.get("/today", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_health_is_open(client: TestClient) -> None:
    """无 token 也能访问 /health（探活用）。"""
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


# ---- /today ----


def test_today_empty(client: TestClient, auth_headers: dict[str, str]) -> None:
    r = client.get("/today", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["recurring_today"] == []
    assert body["deadlines"] == []
    assert body["in_progress"] == []
    assert "today" in body


def test_today_after_create_one_shot(client: TestClient, auth_headers: dict[str, str]) -> None:
    """建一个 one_shot 任务（pending），/today 的 in_progress 不含它（pending 非 in_progress），
    但建 in_progress 的能看到。"""
    # 先建 pending one_shot
    r = client.post(
        "/tasks",
        headers=auth_headers,
        json={"action": "create", "title": "demo", "schedule_kind": "one_shot"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "task_id" in body
    # /today 应该空（pending 不进 in_progress）
    r2 = client.get("/today", headers=auth_headers)
    assert r2.status_code == 200
    assert r2.json()["in_progress"] == []


def test_today_shows_in_progress_task(
    client: TestClient, auth_headers: dict[str, str], _conn
) -> None:
    """in_progress 的 one_shot 任务进 today 的 in_progress 区。"""
    # 建任务
    r = client.post(
        "/tasks",
        headers=auth_headers,
        json={"action": "create", "title": "进行中任务", "schedule_kind": "one_shot", "weight": "M"},
    )
    assert r.status_code == 200
    task_id = r.json()["task_id"]
    # 直接通过 events 把状态改 in_progress（M0 没 status 端点，用 store）
    from store import events as ev
    from store.projections import rebuild_all

    ev.append(_conn, ev.TASK_STATUS_CHANGED, "user", task_id=task_id, payload={"to": "in_progress"})
    rebuild_all(_conn)

    r2 = client.get("/today", headers=auth_headers)
    body = r2.json()
    assert any(t["id"] == task_id for t in body["in_progress"])


# ---- /tasks CRUD ----


def test_create_one_shot(client: TestClient, auth_headers: dict[str, str]) -> None:
    r = client.post(
        "/tasks",
        headers=auth_headers,
        json={"action": "create", "title": "t", "schedule_kind": "one_shot", "weight": "S"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["task_id"].startswith("task_")
    assert body["event_id"] > 0


def test_create_deadline(client: TestClient, auth_headers: dict[str, str]) -> None:
    r = client.post(
        "/tasks",
        headers=auth_headers,
        json={
            "action": "create",
            "title": "带期限",
            "schedule_kind": "deadline",
            "due_at": "2026-09-01T00:00:00+00:00",
            "weight": "L",
        },
    )
    assert r.status_code == 200


def test_create_recurring(client: TestClient, auth_headers: dict[str, str]) -> None:
    r = client.post(
        "/tasks",
        headers=auth_headers,
        json={
            "action": "create",
            "title": "每天读书",
            "schedule_kind": "recurring",
            "recur_rule": "FREQ=DAILY",
            "recur_target": {"amount": 5, "unit": "页"},
        },
    )
    assert r.status_code == 200


def test_create_recurring_with_due_rejected(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """recurring 带 due_at 是非法组合（design.md §3.1），应 400 user_error。"""
    r = client.post(
        "/tasks",
        headers=auth_headers,
        json={
            "action": "create",
            "title": "非法",
            "schedule_kind": "recurring",
            "recur_rule": "FREQ=DAILY",
            "due_at": "2026-09-01T00:00:00+00:00",
        },
    )
    assert r.status_code == 400
    body = r.json()
    assert body["error"] == "user_error"
    assert "recurring" in body["message"]


def test_create_deadline_without_due_rejected(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    r = client.post(
        "/tasks",
        headers=auth_headers,
        json={"action": "create", "title": "缺 due", "schedule_kind": "deadline"},
    )
    assert r.status_code == 400
    assert r.json()["error"] == "user_error"


def test_complete_task(client: TestClient, auth_headers: dict[str, str]) -> None:
    # 建
    r = client.post(
        "/tasks",
        headers=auth_headers,
        json={"action": "create", "title": "完成我", "schedule_kind": "one_shot"},
    )
    task_id = r.json()["task_id"]
    # 完成
    r2 = client.post(
        "/tasks", headers=auth_headers, json={"action": "complete", "task_id": task_id}
    )
    assert r2.status_code == 200
    assert r2.json()["ok"] is True


def test_abandon_task(client: TestClient, auth_headers: dict[str, str]) -> None:
    r = client.post(
        "/tasks",
        headers=auth_headers,
        json={"action": "create", "title": "放弃", "schedule_kind": "one_shot"},
    )
    task_id = r.json()["task_id"]
    r2 = client.post(
        "/tasks", headers=auth_headers, json={"action": "abandon", "task_id": task_id}
    )
    assert r2.status_code == 200


def test_checkin_task(client: TestClient, auth_headers: dict[str, str]) -> None:
    r = client.post(
        "/tasks",
        headers=auth_headers,
        json={
            "action": "create",
            "title": "打卡",
            "schedule_kind": "recurring",
            "recur_rule": "FREQ=DAILY",
            "recur_target": {"amount": 5, "unit": "页"},
        },
    )
    task_id = r.json()["task_id"]
    r2 = client.post(
        "/tasks",
        headers=auth_headers,
        json={
            "action": "checkin",
            "task_id": task_id,
            "occurrence_date": "2026-08-04",
            "done_amount": 5.0,
            "target_amount": 5.0,
        },
    )
    assert r2.status_code == 200


def test_reschedule_task(client: TestClient, auth_headers: dict[str, str]) -> None:
    r = client.post(
        "/tasks",
        headers=auth_headers,
        json={
            "action": "create",
            "title": "改期",
            "schedule_kind": "deadline",
            "due_at": "2026-09-01T00:00:00+00:00",
        },
    )
    task_id = r.json()["task_id"]
    r2 = client.post(
        "/tasks",
        headers=auth_headers,
        json={
            "action": "reschedule",
            "task_id": task_id,
            "due_at": "2026-10-01T00:00:00+00:00",
        },
    )
    assert r2.status_code == 200


def test_update_task(client: TestClient, auth_headers: dict[str, str]) -> None:
    r = client.post(
        "/tasks",
        headers=auth_headers,
        json={"action": "create", "title": "old", "schedule_kind": "one_shot"},
    )
    task_id = r.json()["task_id"]
    r2 = client.post(
        "/tasks",
        headers=auth_headers,
        json={"action": "update", "task_id": task_id, "title": "new", "weight": "L"},
    )
    assert r2.status_code == 200


def test_complete_unknown_task_returns_400(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    r = client.post(
        "/tasks", headers=auth_headers, json={"action": "complete", "task_id": "nope"}
    )
    assert r.status_code == 400
    assert r.json()["error"] == "user_error"


# ---- 占位端点 ----


def test_intent_placeholder(client: TestClient, auth_headers: dict[str, str]) -> None:
    r = client.post("/intent", headers=auth_headers, json={"text": "建个任务"})
    assert r.status_code == 200
    body = r.json()
    assert body["handled"] is False
    assert body["echo"] == "建个任务"


def test_confirm_placeholder(client: TestClient, auth_headers: dict[str, str]) -> None:
    r = client.post("/confirm", headers=auth_headers, json={"action_id": "a1"})
    assert r.status_code == 200
    body = r.json()
    assert body["action_id"] == "a1"
    assert body["status"] == "accepted"


def test_wake_placeholder(client: TestClient, auth_headers: dict[str, str]) -> None:
    r = client.post("/wake", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["ok"] is True


# ---- SSE（用真实 uvicorn 服务器，TestClient 不支持流式响应）----


async def _drain_sse_data(resp) -> list[dict]:
    """从 SSE 流里读出 data: 行的 JSON，收到第一条即返回。"""
    received: list[dict] = []
    async for raw in resp.aiter_bytes():
        if not raw:
            continue
        for line in raw.decode().splitlines():
            if line.startswith("data:"):
                payload = line[len("data:"):].strip()
                if payload:
                    received.append(json.loads(payload))
        if received:
            break
    return received


@pytest.mark.asyncio
async def test_sse_receives_pushed_command(live_server) -> None:
    """推一条 PetCommand 到 bus，SSE 连接能收到。

    SSE 必须用真实服务器测：httpx ASGITransport/TestClient 会阻塞到 ASGI app
    完全返回，无法流式消费 SSE。这里起 uvicorn 绑 127.0.0.1 随机端口。
    """
    import httpx

    base_url, bus, _app = live_server
    headers = {"Authorization": "Bearer test-token-1234"}
    async with (
        httpx.AsyncClient(base_url=base_url) as client,
        client.stream("GET", "/events", headers=headers, timeout=10.0) as resp,
    ):
        assert resp.status_code == 200
        # 等 SSE handler 订阅上 bus 再 push。
        for _ in range(100):
            if bus.subscriber_count > 0:
                break
            await asyncio.sleep(0.05)
        assert bus.subscriber_count > 0
        bus.push(SetEmotion(state="happy"))
        received = await _drain_sse_data(resp)
        assert received
        assert received[0]["type"] == "set_emotion"
        assert received[0]["state"] == "happy"


@pytest.mark.asyncio
async def test_sse_receives_badge_command(live_server) -> None:
    import httpx

    base_url, bus, _app = live_server
    headers = {"Authorization": "Bearer test-token-1234"}
    async with (
        httpx.AsyncClient(base_url=base_url) as client,
        client.stream("GET", "/events", headers=headers, timeout=10.0) as resp,
    ):
        assert resp.status_code == 200
        for _ in range(100):
            if bus.subscriber_count > 0:
                break
            await asyncio.sleep(0.05)
        bus.push(Badge(count=7))
        received = await _drain_sse_data(resp)
        assert received
        assert received[0]["type"] == "badge"
        assert received[0]["count"] == 7


@pytest.mark.asyncio
async def test_sse_requires_token(live_server) -> None:
    """无 token 的 SSE 连接被 401 拒。"""
    import httpx

    base_url, _bus, _app = live_server
    async with httpx.AsyncClient(base_url=base_url) as client:
        r = await client.get("/events", timeout=5.0)
        assert r.status_code == 401


# ---- PRD 验收：崩溃后端口释放，重启不冲突 ----


@pytest.mark.asyncio
async def test_port_released_after_server_exit(tmp_path) -> None:
    """server 退出后端口可立即复用（对应 PRD 验收「崩溃后端口释放，重启不冲突」）。

    手动起一个 uvicorn 绑随机端口，退出后再用同端口起第二个 server，验证端口真的
    释放（不残留 TIME_WAIT 占用导致重启冲突）。
    """
    import socket as sk

    import uvicorn
    from fastapi.testclient import TestClient  # noqa: F401  # 保证 import 路径可用

    import api.app as app_mod
    from api.app import create_app
    from api.commands import PetCommandBus
    from store.db import init_db

    db = tmp_path / "port_reuse.sqlite3"
    conn = init_db(db, check_same_thread=False)
    orig = app_mod.init_app_state

    def _fake(app: object) -> None:
        if getattr(app.state, "db_conn", None) is not None:
            return
        app.state.db_conn = conn  # type: ignore[attr-defined]
        app.state.command_bus = PetCommandBus()  # type: ignore[attr-defined]

    app_mod.init_app_state = _fake  # type: ignore[assignment]
    try:
        # 选一个空闲端口
        s = sk.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()

        # 第一次 server
        app1 = create_app("test-token-1234")
        _fake(app1)
        cfg1 = uvicorn.Config(app1, host="127.0.0.1", port=port, log_level="warning")
        srv1 = uvicorn.Server(cfg1)
        t1 = asyncio.create_task(srv1.serve())
        for _ in range(50):
            await asyncio.sleep(0.1)
            if srv1.started:
                break
        assert srv1.started
        srv1.should_exit = True
        await asyncio.wait_for(t1, timeout=5.0)

        # 第二次 server 复用同端口（端口应已释放）
        app2 = create_app("test-token-1234")
        _fake(app2)
        cfg2 = uvicorn.Config(app2, host="127.0.0.1", port=port, log_level="warning")
        srv2 = uvicorn.Server(cfg2)
        t2 = asyncio.create_task(srv2.serve())
        try:
            for _ in range(50):
                await asyncio.sleep(0.1)
                if srv2.started:
                    break
            assert srv2.started, "端口未释放，第二次 server 起不来（重启冲突）"
        finally:
            srv2.should_exit = True
            await asyncio.wait_for(t2, timeout=5.0)
    finally:
        app_mod.init_app_state = orig  # type: ignore[assignment]
        conn.close()
