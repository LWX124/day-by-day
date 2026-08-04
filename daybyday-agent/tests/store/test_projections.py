"""projections：从 events 重建 tasks / occurrences。"""

from __future__ import annotations

import json
import pathlib
import sqlite3
from datetime import UTC, datetime

from store.events import (
    NAG_SENT,
    OCCURRENCE_CHECKED_IN,
    REDECISION_MADE,
    TASK_ABANDONED,
    TASK_CREATED,
    TASK_FIELDS_UPDATED,
    TASK_RESCHEDULED,
    TASK_STATUS_CHANGED,
    append,
    undo,
)
from store.projections import rebuild_all, rebuild_occurrences, rebuild_tasks

T0 = datetime(2026, 8, 4, 9, 0, tzinfo=UTC).isoformat()
T1 = datetime(2026, 8, 4, 10, 0, tzinfo=UTC).isoformat()
T2 = datetime(2026, 8, 4, 11, 0, tzinfo=UTC).isoformat()
T3 = datetime(2026, 8, 4, 12, 0, tzinfo=UTC).isoformat()


def _create(
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
    return append(conn, TASK_CREATED, "user", task_id=tid, payload=payload, occurred_at=occurred_at)


def _task_row(conn: sqlite3.Connection, tid: str) -> sqlite3.Row:
    return conn.execute("SELECT * FROM tasks WHERE id = ?", (tid,)).fetchone()


def test_rebuild_creates_task_rows(conn: sqlite3.Connection) -> None:
    _create(conn, "t1", title="hello")
    n = rebuild_tasks(conn)
    assert n == 1
    row = _task_row(conn, "t1")
    assert row["title"] == "hello"
    assert row["status"] == "pending"
    assert row["weight"] == "M"


def test_rebuild_applies_status_change(conn: sqlite3.Connection) -> None:
    _create(conn, "t1")
    append(conn, TASK_STATUS_CHANGED, "user", task_id="t1", payload={"to": "in_progress"}, occurred_at=T1)
    append(conn, TASK_STATUS_CHANGED, "user", task_id="t1", payload={"to": "done"}, occurred_at=T2)
    rebuild_tasks(conn)
    assert _task_row(conn, "t1")["status"] == "done"


def test_rebuild_reschedule_increments_count(conn: sqlite3.Connection) -> None:
    _create(conn, "t1", schedule_kind="deadline", due_at=T1)
    append(conn, TASK_RESCHEDULED, "user", task_id="t1", payload={"due_at": T2}, occurred_at=T1)
    append(conn, TASK_RESCHEDULED, "user", task_id="t1", payload={"due_at": T3}, occurred_at=T2)
    rebuild_tasks(conn)
    row = _task_row(conn, "t1")
    assert row["reschedule_count"] == 2
    assert row["due_at"] == T3


def test_rebuild_abandoned(conn: sqlite3.Connection) -> None:
    _create(conn, "t1")
    append(conn, TASK_ABANDONED, "user", task_id="t1", occurred_at=T1)
    rebuild_tasks(conn)
    assert _task_row(conn, "t1")["status"] == "abandoned"


def test_rebuild_nag_count(conn: sqlite3.Connection) -> None:
    _create(conn, "t1")
    append(conn, NAG_SENT, "agent", task_id="t1", occurred_at=T1)
    append(conn, NAG_SENT, "agent", task_id="t1", occurred_at=T2)
    rebuild_tasks(conn)
    assert _task_row(conn, "t1")["nag_count"] == 2


def test_rebuild_redecision_resets_nag(conn: sqlite3.Connection) -> None:
    _create(conn, "t1")
    append(conn, NAG_SENT, "agent", task_id="t1", occurred_at=T1)
    append(conn, NAG_SENT, "agent", task_id="t1", occurred_at=T2)
    append(conn, REDECISION_MADE, "user", task_id="t1", payload={"decision": "reschedule", "due_at": T3}, occurred_at=T3)
    rebuild_tasks(conn)
    row = _task_row(conn, "t1")
    assert row["nag_count"] == 0
    assert row["due_at"] == T3


def test_rebuild_fields_updated(conn: sqlite3.Connection) -> None:
    _create(conn, "t1", title="old")
    append(conn, TASK_FIELDS_UPDATED, "user", task_id="t1", payload={"title": "new", "weight": "L"}, occurred_at=T1)
    rebuild_tasks(conn)
    row = _task_row(conn, "t1")
    assert row["title"] == "new"
    assert row["weight"] == "L"


def test_rebuild_after_drop_reconstructs(conn: sqlite3.Connection) -> None:
    """删掉全部投影表后能从 events 完整重建且数据一致。"""
    _create(conn, "t1", schedule_kind="recurring", recur_rule="FREQ=DAILY", recur_target={"amount": 5, "unit": "页"})
    append(conn, TASK_STATUS_CHANGED, "user", task_id="t1", payload={"to": "in_progress"}, occurred_at=T1)
    append(
        conn,
        OCCURRENCE_CHECKED_IN,
        "user",
        task_id="t1",
        occurrence_date="2026-08-04",
        payload={"done_amount": 5.0, "target_amount": 5.0},
        occurred_at=T2,
    )
    # 先重建一次，记录状态
    rebuild_all(conn)
    before_status = _task_row(conn, "t1")["status"]
    before_occ = conn.execute("SELECT * FROM occurrences").fetchall()
    # 删掉全部投影表（外键开启时 DROP 会被拒，临时关掉再开）
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("DROP TABLE tasks")
    conn.execute("DROP TABLE occurrences")
    conn.execute("PRAGMA foreign_keys=ON")
    # 0001_init 已在 schema_migrations，需要手动重建这两张表。
    # 复用 store.db 的语句拆分（去注释），只挑 tasks/occurrences 重建。
    from store.db import _split_statements

    sql = pathlib.Path(__file__).resolve().parents[2].joinpath(
        "store/migrations/0001_init.sql"
    ).read_text()
    for stmt in _split_statements(sql):
        upper = stmt.upper()
        if upper.startswith("CREATE TABLE TASKS") or upper.startswith("CREATE TABLE OCCURRENCES"):
            conn.execute(stmt)
    # 再次重建
    rebuild_all(conn)
    assert _task_row(conn, "t1")["status"] == before_status
    after_occ = conn.execute("SELECT * FROM occurrences").fetchall()
    assert len(after_occ) == len(before_occ)


def test_rebuild_occurrences_status(conn: sqlite3.Connection) -> None:
    _create(conn, "t1", schedule_kind="recurring", recur_rule="FREQ=DAILY")
    append(
        conn,
        OCCURRENCE_CHECKED_IN,
        "user",
        task_id="t1",
        occurrence_date="2026-08-04",
        payload={"done_amount": 5.0, "target_amount": 5.0},
        occurred_at=T1,
    )
    append(
        conn,
        OCCURRENCE_CHECKED_IN,
        "user",
        task_id="t1",
        occurrence_date="2026-08-05",
        payload={"done_amount": 2.0, "target_amount": 5.0},
        occurred_at=T2,
    )
    # occurrences 外键引用 tasks，须先重建 tasks 再重建 occurrences。
    rebuild_tasks(conn)
    n = rebuild_occurrences(conn)
    assert n == 2
    rows = {r["occurrence_date"]: r for r in conn.execute("SELECT * FROM occurrences")}
    assert rows["2026-08-04"]["status"] == "done"
    assert rows["2026-08-05"]["status"] == "partial"


def test_rebuild_is_idempotent(conn: sqlite3.Connection) -> None:
    """重建多次结果一致（先清空再重放）。"""
    _create(conn, "t1")
    append(conn, TASK_STATUS_CHANGED, "user", task_id="t1", payload={"to": "done"}, occurred_at=T1)
    rebuild_tasks(conn)
    s1 = _task_row(conn, "t1")["status"]
    rebuild_tasks(conn)
    s2 = _task_row(conn, "t1")["status"]
    assert s1 == s2 == "done"


def test_undo_then_rebuild_restores_prior_state(conn: sqlite3.Connection) -> None:
    """撤销一条 TaskStatusChanged 后重建，任务状态回到撤销前。"""
    _create(conn, "t1", status="pending")
    eid = append(conn, TASK_STATUS_CHANGED, "user", task_id="t1", payload={"to": "done"}, occurred_at=T1)
    rebuild_tasks(conn)
    assert _task_row(conn, "t1")["status"] == "done"
    # 撤销
    undo(conn, eid, "user")
    rebuild_tasks(conn)
    assert _task_row(conn, "t1")["status"] == "pending"


def test_rebuild_tasks_returns_count(conn: sqlite3.Connection) -> None:
    _create(conn, "t1")
    _create(conn, "t2")
    assert rebuild_tasks(conn) == 2


def test_rebuild_handles_recur_target_json(conn: sqlite3.Connection) -> None:
    _create(conn, "t1", schedule_kind="recurring", recur_rule="FREQ=DAILY", recur_target={"amount": 5, "unit": "页"})
    rebuild_tasks(conn)
    row = _task_row(conn, "t1")
    rt = json.loads(row["recur_target"])
    assert rt == {"amount": 5, "unit": "页"}


def test_rebuild_all_with_existing_occurrences(conn: sqlite3.Connection) -> None:
    """rebuild_all 在 occurrences 已有数据时不应触发 FK 约束失败。

    回归：occurrences.task_id 外键引用 tasks.id，rebuild_tasks 内部 `DELETE FROM
    tasks` 时若 occurrences 仍有引用行会 FOREIGN KEY constraint failed。
    rebuild_all 须先清空 occurrences（子表）再清 tasks（父表）。
    """
    _create(conn, "t1", schedule_kind="recurring", recur_rule="FREQ=DAILY")
    append(
        conn,
        OCCURRENCE_CHECKED_IN,
        "user",
        task_id="t1",
        occurrence_date="2026-08-04",
        payload={"done_amount": 5.0, "target_amount": 5.0},
        occurred_at=T1,
    )
    # 第一次重建：建出 tasks 与 occurrences 行
    rebuild_all(conn)
    assert conn.execute("SELECT COUNT(*) FROM occurrences").fetchone()[0] == 1
    # 第二次重建：occurrences 已有数据，rebuild_tasks 的 DELETE FROM tasks 不能炸
    rebuild_all(conn)
    assert conn.execute("SELECT COUNT(*) FROM occurrences").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1

