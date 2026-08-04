# Database Guidelines

> SQLite 作为唯一存储。事件流是事实来源，投影可随时重建（ADR-0002）。

---

## Overview

- **引擎**：SQLite，WAL 模式（`PRAGMA journal_mode=WAL`），单文件 `~/Library/Application Support/DayByDay/db.sqlite3`。
- **无 ORM**。用 `sqlite3` 标准库 + pydantic 做行↔模型映射。投影重建频繁，ORM 的 session/identity 语义是负债。
- **迁移**：`store/migrations/` 下编号 SQL 文件（`0001_init.sql`、`0002_*.sql`），`store/db.py` 按编号顺序执行，已执行的记入 `schema_migrations` 表，幂等。
- **LangGraph 持久化**：`SqliteSaver` 用**同一个库文件**的独立表，不另开库。

> **SqliteSaver 连接坑**：`SqliteSaver` 内部裸 INSERT，连接**必须**配 `isolation_level=None`（autocommit，否则连续 INSERT 触发 "cannot start a transaction within a transaction"）+ `check_same_thread=False`（节点在线程池跑）+ `PRAGMA journal_mode=WAL` + `PRAGMA busy_timeout=10000`（避免 "database is locked"）。`store.db.connect` 的默认 `check_same_thread=True` 对 SqliteSaver 是错的——agent 层的 `build_graph` 自带 `_open_conn` 设这四项，**不要**在 store 里加 `get_sqlite_saver_conn` helper 引诱错用（曾有过死代码 helper，已删）。

---

## Query Patterns

- 读投影（tasks/occurrences 等当前状态）走普通 SELECT。
- 写**永远**走 `store/events.py` 的 append 函数——直接 UPDATE/DELETE 投影表是**禁止的**，投影由重放生成。
- 撤销 = append 一条 `EventUndone{target_event_id}`，重放时跳过被撤销事件；**不**物理删除原事件。
- 批量插入 occurrence（ensure_occurrences）用 `executemany`，但仍在事务内。

```python
# 正确：写事件
store.events.append(conn, kind="TaskStatusChanged", task_id=tid,
                    actor="user", payload={"to": "done"})

# 错误：直接改投影表
conn.execute("UPDATE tasks SET status='done' WHERE id=?", (tid,))  # 禁止
```

---

## Migrations

- 新增迁移：取 `migrations/` 下最大编号 +1，写新 `.sql` 文件。
- 迁移**必须可前向应用、不可逆**（事件流系统不需要回滚迁移，撤销在事件层）。
- 启动时 `store/db.py` 自动跑未执行的迁移，失败则后端拒绝启动（不降级运行，避免 schema 与代码错位）。

---

## Naming Conventions

- 表名：复数 `snake_case`（`events`、`tasks`、`occurrences`）。
- 列名：`snake_case`，时间戳列以 `_at` 结尾（`created_at`、`occurred_at`），布尔状态用 `is_`/`has_` 前缀。
- 事件 kind：`PascalCase` 字符串（`TaskCreated`、`EventUndone`），存 `events.kind` 列。
- 外键：`<表名单数>_id`（`task_id`、`project_id`）。
- JSON 列（`payload`、`aliases`、`stats`）：存 TEXT，读时 pydantic 解析。

---

## Common Mistakes

- **直接改投影表**——会让投影与事件流不一致，重建时数据丢失。所有写都走 events.append。
- **在 `core/` 里开数据库连接**——`core/` 不许碰 IO，数据由调用方传入。
- **物理删除事件做撤销**——撤销必须可追溯，用 `EventUndone`。
- **迁移里写回填逻辑**——历史事件不可改写（Recurring 改规则只重算未来 occurrence，过去冻结）。
