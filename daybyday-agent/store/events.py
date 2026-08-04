"""事件流：append / undo / replay。

唯一事实来源（ADR-0002）。所有状态写走 `append`，撤销 = append EventUndone，
重放时跳过被 undone 的事件。事件不可变，只增不改。

事件 kind 见 design.md §3.2：
TaskCreated / TaskFieldsUpdated / TaskStatusChanged / TaskRescheduled /
TaskAbandoned / OccurrenceCheckedIn / EvidenceCollected / NagSent /
RedecisionMade / DailyReviewAnswered / ReportGenerated / EventUndone
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

# 事件 kind 枚举（design.md §3.2）。PascalCase 字符串。
TASK_CREATED = "TaskCreated"
TASK_FIELDS_UPDATED = "TaskFieldsUpdated"
TASK_STATUS_CHANGED = "TaskStatusChanged"
TASK_RESCHEDULED = "TaskRescheduled"
TASK_ABANDONED = "TaskAbandoned"
OCCURRENCE_CHECKED_IN = "OccurrenceCheckedIn"
EVIDENCE_COLLECTED = "EvidenceCollected"
NAG_SENT = "NagSent"
REDECISION_MADE = "RedecisionMade"
DAILY_REVIEW_ANSWERED = "DailyReviewAnswered"
REPORT_GENERATED = "ReportGenerated"
EVENT_UNDONE = "EventUndone"

ALL_KINDS: frozenset[str] = frozenset(
    {
        TASK_CREATED,
        TASK_FIELDS_UPDATED,
        TASK_STATUS_CHANGED,
        TASK_RESCHEDULED,
        TASK_ABANDONED,
        OCCURRENCE_CHECKED_IN,
        EVIDENCE_COLLECTED,
        NAG_SENT,
        REDECISION_MADE,
        DAILY_REVIEW_ANSWERED,
        REPORT_GENERATED,
        EVENT_UNDONE,
    }
)


@dataclass(frozen=True)
class Event:
    """事件行。payload 已反序列化为 dict。"""

    id: int
    occurred_at: str
    kind: str
    task_id: str | None
    occurrence_date: str | None
    actor: str
    payload: dict[str, Any]
    undone_by: int | None


def _now_iso() -> str:
    """当前时间 ISO8601 带时区。事件写入时间戳用。"""
    return datetime.now(UTC).isoformat()


def append(
    conn: sqlite3.Connection,
    kind: str,
    actor: str,
    *,
    task_id: str | None = None,
    occurrence_date: str | None = None,
    payload: dict[str, Any] | None = None,
    occurred_at: str | None = None,
) -> int:
    """写一条事件到 events 表。返回新事件 id。

    - kind 必须是已知枚举之一（防止拼写错误静默写脏数据）。
    - payload JSON 序列化；None 视为 {}。
    - occurred_at 缺省取当前 UTC 时间。
    """
    if kind not in ALL_KINDS:
        raise ValueError(f"unknown event kind: {kind!r}")
    payload_json = json.dumps(payload or {}, ensure_ascii=False, sort_keys=True)
    occurred = occurred_at or _now_iso()
    cur = conn.execute(
        """
        INSERT INTO events (occurred_at, kind, task_id, occurrence_date, actor, payload)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (occurred, kind, task_id, occurrence_date, actor, payload_json),
    )
    # lastrowid 在 autocommit/INSERT 后非 None；显式断言给 mypy 收窄类型。
    assert cur.lastrowid is not None
    return int(cur.lastrowid)


def undo(conn: sqlite3.Connection, target_event_id: int, actor: str) -> int:
    """撤销一条事件：append 一条 EventUndone{target_event_id}。

    不物理删除原事件（ADR-0002）。重放时根据 undone_by 跳过被撤销事件。
    被撤销事件本身也会被标记 undone_by（指向这条 EventUndone 的 id），
    以便双向追溯——但跳过逻辑只看"是否被某条 EventUndone 指向"。
    """
    # 校验目标事件存在。
    row = conn.execute("SELECT id FROM events WHERE id = ?", (target_event_id,)).fetchone()
    if row is None:
        raise KeyError(f"target event not found: {target_event_id}")
    # 不允许撤销一条 EventUndone（撤销撤销会让重放语义混乱）。
    kind_row = conn.execute("SELECT kind FROM events WHERE id = ?", (target_event_id,)).fetchone()
    if kind_row is not None and kind_row["kind"] == EVENT_UNDONE:
        raise ValueError(f"cannot undo an EventUndone: {target_event_id}")
    undo_id = append(
        conn,
        EVENT_UNDONE,
        actor,
        payload={"target_event_id": target_event_id},
    )
    # 在原事件上记 undone_by，便于双向查询。这是 events 表上唯一的非 append 写，
    # 但它不改事件语义（重放仍按 EventUndone 跳过），只补一个反向指针。
    conn.execute("UPDATE events SET undone_by = ? WHERE id = ?", (undo_id, target_event_id))
    return undo_id


def _row_to_event(row: sqlite3.Row) -> Event:
    return Event(
        id=row["id"],
        occurred_at=row["occurred_at"],
        kind=row["kind"],
        task_id=row["task_id"],
        occurrence_date=row["occurrence_date"],
        actor=row["actor"],
        payload=json.loads(row["payload"]) if row["payload"] else {},
        undone_by=row["undone_by"],
    )


def _undone_ids(conn: sqlite3.Connection) -> set[int]:
    """被撤销的事件 id 集合（重放时跳过这些）。"""
    rows = conn.execute(
        """
        SELECT payload FROM events WHERE kind = ?
        """,
        (EVENT_UNDONE,),
    ).fetchall()
    ids: set[int] = set()
    for r in rows:
        try:
            data = json.loads(r["payload"])
        except (json.JSONDecodeError, TypeError):
            continue
        tid = data.get("target_event_id")
        if isinstance(tid, int):
            ids.add(tid)
    return ids


def replay(
    conn: sqlite3.Connection, task_id: str | None = None
) -> list[Event]:
    """重放事件流，跳过被 undone 的事件，返回按时间序的事件列表。

    - task_id 给定时只重放该任务的事件（含 EventUndone，但 undo 跳过逻辑全局生效）。
    - 排序：occurred_at 升序，同时间按 id 升序（保证稳定）。
    """
    if task_id is not None:
        rows = conn.execute(
            """
            SELECT * FROM events WHERE task_id = ?
            ORDER BY occurred_at ASC, id ASC
            """,
            (task_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM events ORDER BY occurred_at ASC, id ASC"
        ).fetchall()
    skipped = _undone_ids(conn)
    out: list[Event] = []
    for row in rows:
        if row["id"] in skipped:
            continue
        if row["kind"] == EVENT_UNDONE:
            continue  # EventUndone 本身不参与重放语义
        out.append(_row_to_event(row))
    return out


def get(conn: sqlite3.Connection, event_id: int) -> Event | None:
    """取单条事件。None 表示不存在。"""
    row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    return _row_to_event(row) if row is not None else None
