"""events：append / replay / undo。"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

import pytest

from store import events
from store.events import (
    EVENT_UNDONE,
    TASK_CREATED,
    TASK_RESCHEDULED,
    TASK_STATUS_CHANGED,
    append,
    get,
    replay,
    undo,
)

T0 = datetime(2026, 8, 4, 9, 0, tzinfo=UTC).isoformat()
T1 = datetime(2026, 8, 4, 10, 0, tzinfo=UTC).isoformat()
T2 = datetime(2026, 8, 4, 11, 0, tzinfo=UTC).isoformat()


def _create_task(
    conn: sqlite3.Connection,
    tid: str,
    schedule_kind: str = "one_shot",
    occurred_at: str = T0,
    **extra: object,
) -> int:
    payload: dict = {
        "title": f"task-{tid}",
        "schedule_kind": schedule_kind,
        "weight": "M",
        "status": "pending",
    }
    payload.update(extra)
    return append(
        conn, TASK_CREATED, "user", task_id=tid, payload=payload, occurred_at=occurred_at
    )


def test_append_returns_id_and_writes_row(conn: sqlite3.Connection) -> None:
    eid = _create_task(conn, "t1")
    assert eid > 0
    row = conn.execute("SELECT * FROM events WHERE id = ?", (eid,)).fetchone()
    assert row["kind"] == TASK_CREATED
    assert row["actor"] == "user"
    assert row["task_id"] == "t1"
    assert '"title"' in row["payload"]


def test_append_rejects_unknown_kind(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="unknown event kind"):
        append(conn, "BogusKind", "user")


def test_replay_returns_in_time_order(conn: sqlite3.Connection) -> None:
    _create_task(conn, "t1", occurred_at=T2)
    _create_task(conn, "t2", occurred_at=T0)
    _create_task(conn, "t3", occurred_at=T1)
    evs = replay(conn)
    # 按 occurred_at 升序
    assert [e.occurred_at for e in evs] == [T0, T1, T2]


def test_replay_filters_by_task(conn: sqlite3.Connection) -> None:
    _create_task(conn, "t1")
    _create_task(conn, "t2")
    evs = replay(conn, task_id="t1")
    assert len(evs) == 1
    assert evs[0].task_id == "t1"


def test_replay_payload_deserialized(conn: sqlite3.Connection) -> None:
    _create_task(conn, "t1", title="hello")
    evs = replay(conn)
    assert evs[0].payload["title"] == "hello"


def test_undo_marks_event_skipped_in_replay(conn: sqlite3.Connection) -> None:
    """撤销一条 TaskStatusChanged 后，replay 跳过它，任务状态回到撤销前。"""
    _create_task(conn, "t1", occurred_at=T0, status="pending")
    eid = append(
        conn,
        TASK_STATUS_CHANGED,
        "user",
        task_id="t1",
        payload={"to": "done"},
        occurred_at=T1,
    )
    # 撤销前：replay 包含 status change
    assert len(replay(conn)) == 2
    undo(conn, eid, "user")
    # 撤销后：replay 跳过被撤销事件，只剩 TaskCreated
    evs = replay(conn)
    assert len(evs) == 1
    assert evs[0].kind == TASK_CREATED


def test_undo_does_not_physically_delete(conn: sqlite3.Connection) -> None:
    _create_task(conn, "t1")
    eid = append(conn, TASK_STATUS_CHANGED, "user", task_id="t1", payload={"to": "done"})
    undo(conn, eid, "user")
    # 原事件仍在表里
    assert get(conn, eid) is not None
    # 且有一条 EventUndone 指向它
    undone = conn.execute(
        "SELECT * FROM events WHERE kind = ?", (EVENT_UNDONE,)
    ).fetchone()
    assert undone is not None
    assert json.loads(undone["payload"])["target_event_id"] == eid


def test_undo_unknown_target_raises(conn: sqlite3.Connection) -> None:
    with pytest.raises(KeyError):
        undo(conn, 9999, "user")


def test_undo_cannot_undo_undone(conn: sqlite3.Connection) -> None:
    _create_task(conn, "t1")
    eid = append(conn, TASK_STATUS_CHANGED, "user", task_id="t1", payload={"to": "done"})
    uid = undo(conn, eid, "user")
    with pytest.raises(ValueError, match="cannot undo"):
        undo(conn, uid, "user")


def test_four_schedule_kinds_all_writable(conn: sqlite3.Connection) -> None:
    """建 4 种 schedule 任务各一条，events 表有对应记录。"""
    _create_task(conn, "os", schedule_kind="one_shot")
    _create_task(conn, "dl", schedule_kind="deadline", due_at=T2)
    _create_task(
        conn,
        "rc",
        schedule_kind="recurring",
        recur_rule="FREQ=DAILY",
        recur_target={"amount": 5, "unit": "页"},
    )
    _create_task(conn, "oe", schedule_kind="openended")
    evs = replay(conn)
    kinds = {e.payload.get("schedule_kind") for e in evs}
    assert kinds == {"one_shot", "deadline", "recurring", "openended"}


def test_checkin_and_reschedule_events(conn: sqlite3.Connection) -> None:
    """打卡 + 改期事件可写入并重放。"""
    _create_task(conn, "rc", schedule_kind="recurring", recur_rule="FREQ=DAILY")
    append(
        conn,
        events.OCCURRENCE_CHECKED_IN,
        "user",
        task_id="rc",
        occurrence_date="2026-08-04",
        payload={"done_amount": 5.0, "target_amount": 5.0},
        occurred_at=T1,
    )
    append(
        conn,
        TASK_RESCHEDULED,
        "user",
        task_id="rc",
        payload={"due_at": T2},
        occurred_at=T2,
    )
    evs = replay(conn)
    assert [e.kind for e in evs] == [TASK_CREATED, events.OCCURRENCE_CHECKED_IN, TASK_RESCHEDULED]


def test_replay_stable_order_same_timestamp(conn: sqlite3.Connection) -> None:
    """同 occurred_at 的事件按 id 升序。"""
    _create_task(conn, "t1", occurred_at=T0)
    _create_task(conn, "t2", occurred_at=T0)
    _create_task(conn, "t3", occurred_at=T0)
    evs = replay(conn)
    assert [e.id for e in evs] == sorted(e.id for e in evs)
