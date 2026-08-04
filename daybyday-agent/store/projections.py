"""投影重建：从 events 重放得到 tasks / occurrences 当前状态。

这是"删掉投影表能从 events 完整重建"的落点（PRD 验收）。
重建 = 先清空投影表，再按事件序重放，得出当前状态写回。

绝不在重建之外 UPDATE/DELETE 投影表做状态变更——所有写走 events.append，
投影只由本模块重建（database-guidelines）。
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from store.events import (
    NAG_SENT,
    OCCURRENCE_CHECKED_IN,
    REDECISION_MADE,
    TASK_ABANDONED,
    TASK_CREATED,
    TASK_FIELDS_UPDATED,
    TASK_RESCHEDULED,
    TASK_STATUS_CHANGED,
    Event,
    replay,
)


def _payload(e: Event) -> dict[str, Any]:
    return e.payload or {}


def _iso(e: Event) -> str:
    return e.occurred_at


def rebuild_tasks(conn: sqlite3.Connection) -> int:
    """从 events 重建 tasks 投影。返回重建的行数。

    清空 tasks 后按事件序重放：TaskCreated 插入，其余按事件类型更新。
    被 undone 的事件已在 replay 里跳过。
    """
    conn.execute("DELETE FROM tasks")
    events = replay(conn)
    count = 0
    for e in events:
        if e.kind == TASK_CREATED:
            _apply_task_created(conn, e)
            count += 1
        elif e.kind == TASK_FIELDS_UPDATED:
            _apply_fields_updated(conn, e)
        elif e.kind == TASK_STATUS_CHANGED:
            _apply_status_changed(conn, e)
        elif e.kind == TASK_RESCHEDULED:
            _apply_rescheduled(conn, e)
        elif e.kind == TASK_ABANDONED:
            _apply_abandoned(conn, e)
        elif e.kind == NAG_SENT:
            _apply_nag_sent(conn, e)
        elif e.kind == REDECISION_MADE:
            _apply_redecision(conn, e)
        # EvidenceCollected 等不直接改 tasks 投影（last_activity_at 由 Evidence 层补）。
    return count


def _apply_task_created(conn: sqlite3.Connection, e: Event) -> None:
    p = _payload(e)
    conn.execute(
        """
        INSERT INTO tasks (
            id, title, detail, schedule_kind, due_at, recur_rule, recur_target,
            weight, status, project_id, inference, last_activity_at,
            nag_count, last_nagged_at, reschedule_count, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, 0, ?, ?)
        """,
        (
            e.task_id,
            p.get("title", ""),
            p.get("detail"),
            p.get("schedule_kind"),
            p.get("due_at"),
            p.get("recur_rule"),
            json.dumps(p["recur_target"], ensure_ascii=False) if p.get("recur_target") else None,
            p.get("weight"),
            p.get("status", "pending"),
            p.get("project_id"),
            json.dumps(p["inference"], ensure_ascii=False) if p.get("inference") else None,
            _iso(e),
            _iso(e),
            _iso(e),
        ),
    )


def _touch(conn: sqlite3.Connection, task_id: str, occurred_at: str) -> None:
    """更新 last_activity_at / updated_at。若行不存在则忽略（防御）。"""
    conn.execute(
        "UPDATE tasks SET last_activity_at = ?, updated_at = ? WHERE id = ?",
        (occurred_at, occurred_at, task_id),
    )


def _apply_fields_updated(conn: sqlite3.Connection, e: Event) -> None:
    if e.task_id is None:
        return
    p = _payload(e)
    sets: list[str] = []
    vals: list[object] = []
    for key, col in (
        ("title", "title"),
        ("detail", "detail"),
        ("weight", "weight"),
        ("project_id", "project_id"),
        ("due_at", "due_at"),
        ("recur_rule", "recur_rule"),
    ):
        if key in p:
            sets.append(f"{col} = ?")
            vals.append(p[key])
    if "recur_target" in p:
        sets.append("recur_target = ?")
        vals.append(
            json.dumps(p["recur_target"], ensure_ascii=False) if p["recur_target"] else None
        )
    if "inference" in p:
        sets.append("inference = ?")
        vals.append(json.dumps(p["inference"], ensure_ascii=False) if p["inference"] else None)
    if not sets:
        _touch(conn, e.task_id, _iso(e))
        return
    sets.append("updated_at = ?")
    vals.append(_iso(e))
    vals.append(e.task_id)
    conn.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?", vals)


def _apply_status_changed(conn: sqlite3.Connection, e: Event) -> None:
    if e.task_id is None:
        return
    p = _payload(e)
    to = p.get("to", "pending")
    conn.execute(
        "UPDATE tasks SET status = ?, last_activity_at = ?, updated_at = ? WHERE id = ?",
        (to, _iso(e), _iso(e), e.task_id),
    )


def _apply_rescheduled(conn: sqlite3.Connection, e: Event) -> None:
    if e.task_id is None:
        return
    p = _payload(e)
    sets: list[str] = ["reschedule_count = reschedule_count + 1", "updated_at = ?"]
    vals: list[object] = [_iso(e)]
    if "due_at" in p:
        sets.append("due_at = ?")
        vals.append(p["due_at"])
    if "recur_rule" in p:
        sets.append("recur_rule = ?")
        vals.append(p["recur_rule"])
    vals.append(e.task_id)
    conn.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?", vals)


def _apply_abandoned(conn: sqlite3.Connection, e: Event) -> None:
    if e.task_id is None:
        return
    conn.execute(
        "UPDATE tasks SET status = 'abandoned', last_activity_at = ?, updated_at = ? WHERE id = ?",
        (_iso(e), _iso(e), e.task_id),
    )


def _apply_nag_sent(conn: sqlite3.Connection, e: Event) -> None:
    if e.task_id is None:
        return
    conn.execute(
        """
        UPDATE tasks SET nag_count = nag_count + 1, last_nagged_at = ?, updated_at = ?
        WHERE id = ?
        """,
        (_iso(e), _iso(e), e.task_id),
    )


def _apply_redecision(conn: sqlite3.Connection, e: Event) -> None:
    """Re-decision 后 nag_count 归零（design.md §5.2）。"""
    if e.task_id is None:
        return
    p = _payload(e)
    sets: list[str] = ["nag_count = 0", "updated_at = ?"]
    vals: list[object] = [_iso(e)]
    decision = p.get("decision")
    if decision == "abandon":
        sets.append("status = 'abandoned'")
    elif decision == "reschedule" and "due_at" in p:
        sets.append("due_at = ?")
        vals.append(p["due_at"])
    vals.append(e.task_id)
    conn.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?", vals)


def rebuild_occurrences(conn: sqlite3.Connection) -> int:
    """从 events 重建 occurrences 投影。返回重建的行数。

    OccurrenceCheckedIn 是唯一改 occurrence 状态的事件。重建时：
    若 occurrence 行不存在则先建（pending/done_amount=0），再应用 check-in。
    """
    conn.execute("DELETE FROM occurrences")
    events = replay(conn)
    count = 0
    for e in events:
        if e.kind != OCCURRENCE_CHECKED_IN:
            continue
        if e.task_id is None or e.occurrence_date is None:
            continue
        p = _payload(e)
        target = p.get("target_amount")
        done = p.get("done_amount", 0.0)
        note = p.get("note")
        # 先建占位行（若不存在）。
        conn.execute(
            """
            INSERT OR IGNORE INTO occurrences
                (task_id, occurrence_date, target_amount, done_amount, status, note)
            VALUES (?, ?, ?, 0, 'pending', NULL)
            """,
            (e.task_id, e.occurrence_date, target),
        )
        status = "done" if (target is not None and done >= target) or p.get("force_done") else (
            "partial" if done > 0 else "pending"
        )
        conn.execute(
            """
            UPDATE occurrences
            SET done_amount = ?, status = ?, note = ?
            WHERE task_id = ? AND occurrence_date = ?
            """,
            (done, status, note, e.task_id, e.occurrence_date),
        )
        count += 1
    return count


def rebuild_all(conn: sqlite3.Connection) -> None:
    """重建 tasks 与 occurrences 投影。调用方负责 projects/notes 等其余投影。

    顺序关键：occurrences.task_id 外键引用 tasks.id（db.py 开了
    PRAGMA foreign_keys=ON）。rebuild_tasks 内部 `DELETE FROM tasks` 时，若
    occurrences 仍有引用行会触发 FOREIGN KEY constraint failed。故先清空
    occurrences（子表）再调 rebuild_tasks（清空+重建父表），最后
    rebuild_occurrences（此时 tasks 已重建，occurrences 的 FK 校验通过）。

    注：activity_evidence 也引用 tasks，M0 无采集器故为空；后续接入 collectors
    时需在此一并清空或改用 defer_foreign_keys。
    """
    # 先清空子表，避免 rebuild_tasks 的 DELETE FROM tasks 触发 FK 失败。
    conn.execute("DELETE FROM occurrences")
    rebuild_tasks(conn)
    rebuild_occurrences(conn)


__all__ = [
    "rebuild_all",
    "rebuild_occurrences",
    "rebuild_tasks",
]
