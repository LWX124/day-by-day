"""迁移与连接管理测试：幂等、WAL、外键。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from store.db import init_db, run_migrations


def test_init_creates_all_tables(conn: sqlite3.Connection) -> None:
    names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for t in (
        "events",
        "tasks",
        "occurrences",
        "projects",
        "notes",
        "activity_evidence",
        "daily_reviews",
        "reports",
        "schema_migrations",
    ):
        assert t in names, f"missing table: {t}"


def test_migration_idempotent(conn: sqlite3.Connection) -> None:
    """跑两次迁移不重复执行、不报错。"""
    applied = run_migrations(conn)
    assert applied == []  # 已全部应用
    rows = conn.execute("SELECT id FROM schema_migrations ORDER BY id").fetchall()
    assert [r["id"] for r in rows] == ["0001_init"]


def test_wal_mode(tmp_path: Path) -> None:
    db = tmp_path / "x.sqlite3"
    c = init_db(db)
    mode = c.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"
    c.close()


def test_foreign_keys_on(conn: sqlite3.Connection) -> None:
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_indexes_exist(conn: sqlite3.Connection) -> None:
    idx = {
        r["name"]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
    }
    assert "idx_events_task" in idx
    assert "idx_events_time" in idx
