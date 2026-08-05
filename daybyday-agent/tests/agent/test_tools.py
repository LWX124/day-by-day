"""agent/tools 注册表与授权分级测试（ADR-0004）。

验收（PRD acceptance criteria）：
- 读 Tool 调用返回数据（list_tasks/get_task）
- 常规写 Tool 直接落库 + 回执 + 返回 event_id + 可 undo
- 需确认 Tool 调用只生成 pending_action 不落地（events 计数不变）
- 需确认 Tool push 了 request_confirm PetCommand
- registry 按级别过滤正确
- pending_action 超时作废
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent.tools.registry import (
    DEFAULT_PENDING_ACTION_TTL,
    PendingActionStore,
    ToolContext,
    ToolLevel,
    ToolRegistry,
    make_default_registry,
)
from api.commands import PetCommandBus, RequestConfirm
from store import events as event_store
from store.db import init_db


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    db = tmp_path / "tools.sqlite3"
    c = init_db(db, check_same_thread=False)
    try:
        yield c
    finally:
        c.close()


@pytest.fixture
def bus() -> PetCommandBus:
    return PetCommandBus()


@pytest.fixture
def registry(bus: PetCommandBus) -> ToolRegistry:
    return make_default_registry(bus=bus)


def _ctx(conn: sqlite3.Connection, bus: PetCommandBus, *, actor: str = "agent") -> ToolContext:
    return ToolContext(conn=conn, bus=bus, actor=actor, now=datetime.now(UTC))


def _capture_pushes(bus: PetCommandBus) -> list:
    pushed: list = []
    bus.push = pushed.append  # type: ignore[method-assign]
    return pushed


def _create_task(registry: ToolRegistry, conn, bus, **overrides) -> dict:
    args = {"title": "测试任务", "schedule_kind": "openended", "weight": "M"}
    args.update(overrides)
    r = registry.invoke("create_task", _ctx(conn, bus), args)
    assert r.ok, r.message
    return r.data


# ---- 读 Tool ----


def test_list_tasks_returns_data(registry, bus, conn):
    _create_task(registry, conn, bus, title="A")
    _create_task(registry, conn, bus, title="B", schedule_kind="deadline", due_at="2026-12-31T23:59:00+00:00")
    r = registry.invoke("list_tasks", _ctx(conn, bus), {})
    assert r.ok
    assert r.data["count"] == 2
    titles = {t["title"] for t in r.data["tasks"]}
    assert titles == {"A", "B"}


def test_list_tasks_filter_by_status(registry, bus, conn):
    tid = _create_task(registry, conn, bus, title="A")["task_id"]
    registry.invoke("complete_task", _ctx(conn, bus), {"task_id": tid})
    r = registry.invoke("list_tasks", _ctx(conn, bus), {"status": "done"})
    assert r.ok
    assert r.data["count"] == 1
    assert r.data["tasks"][0]["title"] == "A"


def test_get_task_returns_detail(registry, bus, conn):
    tid = _create_task(registry, conn, bus, title="查我")["task_id"]
    r = registry.invoke("get_task", _ctx(conn, bus), {"task_id": tid})
    assert r.ok
    assert r.data["id"] == tid
    assert r.data["title"] == "查我"


def test_get_task_not_found(registry, bus, conn):
    r = registry.invoke("get_task", _ctx(conn, bus), {"task_id": "nope"})
    assert not r.ok
    assert "not found" in (r.message or "")


def test_today_view_and_compute_stats(registry, bus, conn):
    _create_task(registry, conn, bus, title="A")
    r = registry.invoke("today_view", _ctx(conn, bus), {})
    assert r.ok
    assert "recurring_today" in r.data
    s = registry.invoke("compute_stats", _ctx(conn, bus), {})
    assert s.ok
    assert s.data["total"] == 1


# ---- 常规写 Tool：直接落库 + 回执 + event_id + 可 undo ----


def test_create_task_lands_event_and_returns_event_id(registry, bus, conn):
    r = registry.invoke(
        "create_task", _ctx(conn, bus), {"title": "新任务", "schedule_kind": "openended"}
    )
    assert r.ok
    assert r.event_id is not None
    assert r.data["task_id"]
    # 事件流有 TaskCreated
    kinds = [row["kind"] for row in conn.execute("SELECT kind FROM events")]
    assert event_store.TASK_CREATED in kinds
    # 投影有任务
    t = conn.execute("SELECT title FROM tasks WHERE id = ?", (r.data["task_id"],)).fetchone()
    assert t["title"] == "新任务"


def test_create_task_rejects_illegal_combination(registry, bus, conn):
    # recurring 带 due → 非法组合在写入层拒绝
    r = registry.invoke(
        "create_task",
        _ctx(conn, bus),
        {"title": "x", "schedule_kind": "recurring", "recur_rule": "FREQ=DAILY", "due_at": "2026-12-31T23:59:00+00:00"},
    )
    assert not r.ok
    # 不落库
    assert conn.execute("SELECT COUNT(*) AS c FROM tasks").fetchone()["c"] == 0


def test_complete_task_lands_status_changed(registry, bus, conn):
    tid = _create_task(registry, conn, bus)["task_id"]
    r = registry.invoke("complete_task", _ctx(conn, bus), {"task_id": tid})
    assert r.ok and r.event_id is not None
    t = conn.execute("SELECT status FROM tasks WHERE id = ?", (tid,)).fetchone()
    assert t["status"] == "done"


def test_checkin_occurrence_lands_event(registry, bus, conn):
    tid = _create_task(
        registry, conn, bus,
        title="读书", schedule_kind="recurring", recur_rule="FREQ=DAILY",
        recur_target={"amount": 5, "unit": "页"},
    )["task_id"]
    today = datetime.now(UTC).date().isoformat()
    r = registry.invoke(
        "checkin_occurrence",
        _ctx(conn, bus),
        {"task_id": tid, "occurrence_date": today, "done_amount": 5, "target_amount": 5},
    )
    assert r.ok and r.event_id is not None
    oc = conn.execute(
        "SELECT status FROM occurrences WHERE task_id=? AND occurrence_date=?",
        (tid, today),
    ).fetchone()
    assert oc["status"] == "done"


def test_reschedule_task_increments_count(registry, bus, conn):
    tid = _create_task(registry, conn, bus, schedule_kind="deadline", due_at="2026-12-31T23:59:00+00:00")["task_id"]
    r = registry.invoke("reschedule_task", _ctx(conn, bus), {"task_id": tid, "due_at": "2027-01-15T23:59:00+00:00"})
    assert r.ok and r.event_id is not None
    t = conn.execute("SELECT reschedule_count, due_at FROM tasks WHERE id = ?", (tid,)).fetchone()
    assert t["reschedule_count"] == 1


def test_abandon_task_sets_status(registry, bus, conn):
    tid = _create_task(registry, conn, bus)["task_id"]
    r = registry.invoke("abandon_task", _ctx(conn, bus), {"task_id": tid})
    assert r.ok and r.event_id is not None
    t = conn.execute("SELECT status FROM tasks WHERE id = ?", (tid,)).fetchone()
    assert t["status"] == "abandoned"


def test_update_task_changes_fields(registry, bus, conn):
    tid = _create_task(registry, conn, bus)["task_id"]
    r = registry.invoke("update_task", _ctx(conn, bus), {"task_id": tid, "weight": "L", "title": "改名"})
    assert r.ok and r.event_id is not None
    t = conn.execute("SELECT weight, title FROM tasks WHERE id = ?", (tid,)).fetchone()
    assert t["weight"] == "L"
    assert t["title"] == "改名"


def test_write_tool_event_undoable(registry, bus, conn):
    """常规写 Tool 返回的 event_id 可经 events.undo 撤销。"""
    r = registry.invoke(
        "create_task", _ctx(conn, bus), {"title": "撤销我", "schedule_kind": "openended"}
    )
    eid = r.event_id
    assert eid is not None
    before = conn.execute("SELECT COUNT(*) AS c FROM tasks").fetchone()["c"]
    event_store.undo(conn, eid, "user")
    from store.projections import rebuild_all
    rebuild_all(conn)
    after = conn.execute("SELECT COUNT(*) AS c FROM tasks").fetchone()["c"]
    assert after == before - 1


# ---- 需确认 Tool：只生成 pending_action 不落地 ----


def test_confirm_tool_does_not_land_event(registry, bus, conn):
    before_events = conn.execute("SELECT COUNT(*) AS c FROM events").fetchone()["c"]
    r = registry.invoke("delete_task", _ctx(conn, bus), {"task_id": "task_x"})
    assert r.ok
    assert r.pending_action_id is not None
    # events 计数不变（没落任何业务事件）
    after_events = conn.execute("SELECT COUNT(*) AS c FROM events").fetchone()["c"]
    assert after_events == before_events
    # pending_action 已登记
    pa = registry.pending_store.get(r.pending_action_id)
    assert pa is not None
    assert pa.tool_name == "delete_task"
    assert pa.status == "pending"


def test_confirm_tool_pushes_request_confirm(registry, bus, conn):
    pushed = _capture_pushes(bus)
    registry.invoke("delete_task", _ctx(conn, bus), {"task_id": "task_x"})
    confirms = [c for c in pushed if isinstance(c, RequestConfirm)]
    assert len(confirms) == 1
    assert confirms[0].action_id
    assert "delete_task" in confirms[0].title or "确认" in confirms[0].title


def test_confirm_tool_gerrit_vote_pending(registry, bus, conn):
    pushed = _capture_pushes(bus)
    r = registry.invoke(
        "gerrit_review_vote",
        _ctx(conn, bus),
        {"change": "12345", "patchset": 1, "label": "Code-Review", "score": 1},
    )
    assert r.ok
    assert r.pending_action_id is not None
    confirms = [c for c in pushed if isinstance(c, RequestConfirm)]
    assert len(confirms) == 1


def test_invoke_confirmed_executes_after_confirm(registry, bus, conn):
    """invoke_confirmed 路径执行真实逻辑（delete_task 占位 = 撤销 TaskCreated）。"""
    tid = _create_task(registry, conn, bus, title="待删")["task_id"]
    # 先 pending
    r = registry.invoke("delete_task", _ctx(conn, bus), {"task_id": tid})
    action_id = r.pending_action_id
    assert action_id is not None
    # 确认后执行
    res = registry.invoke_confirmed(action_id, _ctx(conn, bus))
    assert res.ok
    pa = registry.pending_store.get(action_id)
    assert pa.status == "executed"
    # 任务被撤销（delete_task 占位 = undo TaskCreated）→ 投影无该任务
    t = conn.execute("SELECT id FROM tasks WHERE id = ?", (tid,)).fetchone()
    assert t is None


def test_invoke_confirmed_expired_fails(registry, bus, conn):
    r = registry.invoke("delete_task", _ctx(conn, bus), {"task_id": "x"})
    action_id = r.pending_action_id
    # 伪造过期：直接把 expires_at 拨到过去
    pa = registry.pending_store.get(action_id)
    pa.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    res = registry.invoke_confirmed(action_id, _ctx(conn, bus))
    assert not res.ok
    assert "expired" in (res.message or "")


def test_invoke_confirmed_unknown_action_fails(registry, bus, conn):
    res = registry.invoke_confirmed("pa_does_not_exist", _ctx(conn, bus))
    assert not res.ok


# ---- registry 按级别过滤 ----


def test_registry_filters_by_level(registry):
    reads = registry.by_level(ToolLevel.READ)
    writes = registry.by_level(ToolLevel.WRITE)
    confirms = registry.by_level(ToolLevel.CONFIRM)
    read_names = {t.name for t in reads}
    write_names = {t.name for t in writes}
    confirm_names = {t.name for t in confirms}
    assert read_names == {
        "list_tasks", "get_task", "today_view", "compute_stats",
        "query_git_evidence", "query_gerrit_changes", "get_project", "search_notes",
    }
    assert write_names == {
        "create_task", "update_task", "complete_task", "checkin_occurrence",
        "reschedule_task", "abandon_task", "upsert_project", "upsert_note",
    }
    assert confirm_names == {
        "delete_task", "gerrit_review_vote", "gerrit_abandon", "gerrit_rebase",
    }


def test_registry_args_schema_generated(registry):
    schema = registry.args_schema("create_task")
    assert schema is not None
    assert "title" in schema["properties"]
    assert "schedule_kind" in schema["properties"]


def test_registry_validates_args(registry, bus, conn):
    # 缺 title → pydantic 校验失败
    r = registry.invoke("create_task", _ctx(conn, bus), {"schedule_kind": "openended"})
    assert not r.ok
    assert "invalid args" in (r.message or "")


def test_registry_unknown_tool(registry, bus, conn):
    r = registry.invoke("bogus_tool", _ctx(conn, bus), {})
    assert not r.ok


# ---- pending_action 超时作废 ----


def test_pending_action_store_ttl_expiry():
    store = PendingActionStore(ttl=timedelta(seconds=1))
    pa = store.register("delete_task", title="t", detail=None, args={"task_id": "x"})
    assert store.get_valid(pa.action_id) is not None
    # 拨过期
    pa.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert store.get_valid(pa.action_id) is None
    assert pa.status == "expired"


def test_pending_action_default_ttl_is_5_minutes():
    assert timedelta(minutes=5) == DEFAULT_PENDING_ACTION_TTL


def test_pending_action_store_expire_all():
    store = PendingActionStore(ttl=timedelta(seconds=1))
    pa1 = store.register("delete_task", title="t", detail=None, args={})
    pa2 = store.register("gerrit_abandon", title="t", detail=None, args={})
    pa1.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    n = store.expire_all()
    assert n == 1
    assert pa1.status == "expired"
    assert pa2.status == "pending"


def test_pending_action_status_after_confirm(registry, bus, conn):
    tid = _create_task(registry, conn, bus)["task_id"]
    r = registry.invoke("delete_task", _ctx(conn, bus), {"task_id": tid})
    action_id = r.pending_action_id
    registry.invoke_confirmed(action_id, _ctx(conn, bus))
    pa = registry.pending_store.get(action_id)
    assert pa.status == "executed"


# ---- bus 后置注入 ----


def test_registry_set_bus(registry, bus, conn):
    """registry 先于 bus 构造时，set_bus 后 confirm 也能 push。"""
    reg = make_default_registry(bus=None)
    reg.set_bus(bus)
    pushed = _capture_pushes(bus)
    reg.invoke("delete_task", _ctx(conn, bus), {"task_id": "x"})
    assert any(isinstance(c, RequestConfirm) for c in pushed)
