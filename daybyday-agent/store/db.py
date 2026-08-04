"""SQLite 连接管理与迁移执行。

- WAL 模式 + 外键开启（design.md §4、database-guidelines）。
- 迁移按编号顺序执行，已执行的记入 schema_migrations 表，幂等。
- 迁移失败则拒绝启动（不降级运行，避免 schema 与代码错位）。
- LangGraph 的 SqliteSaver 用同一个 db.sqlite3 的独立表（占位，不实际依赖 langgraph）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from common.config import DB_PATH

# 迁移文件所在目录（本文件同级 migrations/）。
MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def connect(path: Path | str = DB_PATH, *, check_same_thread: bool = True) -> sqlite3.Connection:
    """打开/创建 SQLite 连接，配置 WAL、外键、忙等待。

    用 `sqlite3.Connection` 作上下文管理器时，仅事务提交/回滚，不关闭连接——
    因此提供 `closing` 风格的用法由调用方负责。这里返回原生连接。

    `check_same_thread=False` 仅在连接跨线程共享时用（如 FastAPI TestClient 把
    ASGI 跑在独立线程）。生产单线程 uvicorn 不需要。
    """
    conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=check_same_thread)  # autocommit：迁移内部自己管事务
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _ensure_migrations_table(conn: sqlite3.Connection) -> None:
    """建 schema_migrations 记录表（若不存在）。"""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id           TEXT PRIMARY KEY,     -- 迁移文件名（去 .sql）
            applied_at   TEXT NOT NULL         -- ISO8601
        )
        """
    )


def _list_migration_files() -> list[Path]:
    """列出 migrations/ 下全部 .sql 文件，按文件名升序。"""
    if not MIGRATIONS_DIR.exists():
        return []
    return sorted(MIGRATIONS_DIR.glob("*.sql"), key=lambda p: p.name)


def run_migrations(conn: sqlite3.Connection) -> list[str]:
    """执行未跑过的迁移，返回本次应用的迁移 id 列表（已执行的不重复跑，幂等）。

    失败则抛异常——调用方（后端启动）应让其向上传播，拒绝启动。
    每个迁移文件包在自己的事务里；失败回滚该文件，已应用的之前文件不受影响。

    注意：不能用 executescript——它会在执行前隐式 COMMIT 挂起的事务，
    破坏 BEGIN/ROLLBACK 的原子性。这里手动按 `;` 拆分逐条执行，整文件一个事务。
    迁移 SQL 只含 CREATE TABLE/INDEX 语句，拆分安全。
    """
    _ensure_migrations_table(conn)
    applied: list[str] = []
    for f in _list_migration_files():
        migration_id = f.stem  # 如 0001_init
        row = conn.execute(
            "SELECT id FROM schema_migrations WHERE id = ?", (migration_id,)
        ).fetchone()
        if row is not None:
            continue  # 已执行，跳过（幂等）
        sql = f.read_text(encoding="utf-8")
        try:
            conn.execute("BEGIN")
            for stmt in _split_statements(sql):
                conn.execute(stmt)
            conn.execute(
                "INSERT INTO schema_migrations (id, applied_at) VALUES (?, ?)",
                (migration_id, _now_iso()),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        applied.append(migration_id)
    return applied


def _split_statements(sql: str) -> list[str]:
    """把迁移 SQL 按 `;` 拆成独立语句，去掉空串与注释行。

    迁移文件只含 CREATE TABLE/INDEX，无字符串字面量含 `;`，简单拆分即可。
    """
    out: list[str] = []
    for raw in sql.split(";"):
        # 去掉纯注释/空行
        lines = [ln for ln in raw.splitlines() if not ln.strip().startswith("--")]
        stmt = "\n".join(lines).strip()
        if stmt:
            out.append(stmt)
    return out


def _now_iso() -> str:
    """当前时间 ISO8601 带时区。仅在迁移记录里用（非判定层）。"""
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def init_db(
    path: Path | str = DB_PATH, *, check_same_thread: bool = True
) -> sqlite3.Connection:
    """打开连接并跑迁移。后端启动入口。

    `check_same_thread=False` 仅供跨线程共享连接场景（如 TestClient）。
    """
    conn = connect(path, check_same_thread=check_same_thread)
    run_migrations(conn)
    return conn


def get_sqlite_saver_conn(path: Path | str = DB_PATH) -> sqlite3.Connection:
    """LangGraph SqliteSaver 用的连接（占位）。

    design.md §4：SqliteSaver 用**同一个 db.sqlite3** 的独立表（langgraph 自建表名），
    不另开库。这里只返回一个连接，由 agent 层 `SqliteSaver(conn)` 包装。
    store 不 import langgraph——agent 层负责引入。
    """
    return connect(path)
