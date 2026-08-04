-- 初始化 schema：events（唯一事实来源）+ 全部投影表。
-- 严格按 design.md §4 的列定义。WAL/外键在 db.py 里 PRAGMA 设置。

-- 唯一事实来源，只增不改。撤销 = append EventUndone，不物理删除（ADR-0002）。
CREATE TABLE events (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  occurred_at     TEXT NOT NULL,              -- ISO8601 带时区
  kind            TEXT NOT NULL,
  task_id         TEXT,                       -- 可空：非任务事件
  occurrence_date TEXT,                       -- 仅 Check-in 类事件
  actor           TEXT NOT NULL,              -- user | agent | scanner | scheduler
  payload         TEXT NOT NULL,              -- JSON
  undone_by       INTEGER REFERENCES events(id)
);

CREATE INDEX idx_events_task ON events(task_id, occurred_at);
CREATE INDEX idx_events_time ON events(occurred_at);

-- 投影：可从 events 重建。禁止直接 UPDATE/DELETE（database-guidelines）。
CREATE TABLE tasks (
  id               TEXT PRIMARY KEY,
  title            TEXT NOT NULL,
  detail           TEXT,
  schedule_kind    TEXT NOT NULL,             -- one_shot|deadline|recurring|openended
  due_at           TEXT,
  recur_rule       TEXT,                      -- RRULE 子集：FREQ/INTERVAL/BYDAY
  recur_target     TEXT,                      -- JSON: {amount:5, unit:"页"}
  weight           TEXT NOT NULL,             -- S|M|L|XL
  status           TEXT NOT NULL,
  project_id       TEXT REFERENCES projects(id),
  inference        TEXT,                      -- JSON: 各字段置信度与原始输入
  last_activity_at TEXT,                      -- 事件或 Evidence 中的最近活动
  nag_count        INTEGER NOT NULL DEFAULT 0,
  last_nagged_at   TEXT,
  reschedule_count INTEGER NOT NULL DEFAULT 0,
  created_at       TEXT NOT NULL,
  updated_at       TEXT NOT NULL
);

CREATE TABLE occurrences (
  task_id         TEXT NOT NULL REFERENCES tasks(id),
  occurrence_date TEXT NOT NULL,              -- YYYY-MM-DD
  target_amount   REAL,
  done_amount     REAL NOT NULL DEFAULT 0,
  status          TEXT NOT NULL,              -- pending|partial|done|skipped
  note            TEXT,
  PRIMARY KEY (task_id, occurrence_date)
);

CREATE TABLE projects (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  aliases     TEXT NOT NULL DEFAULT '[]',     -- JSON 数组，口语别名（"主站"）
  local_path  TEXT,
  gerrit_repo TEXT,
  created_at  TEXT NOT NULL
);

CREATE TABLE notes (
  id         TEXT PRIMARY KEY,
  project_id TEXT REFERENCES projects(id),
  tags       TEXT NOT NULL DEFAULT '[]',
  body       TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE activity_evidence (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id      TEXT NOT NULL REFERENCES tasks(id),
  source       TEXT NOT NULL,                 -- git | gerrit
  collected_at TEXT NOT NULL,
  window_start TEXT NOT NULL,
  window_end   TEXT NOT NULL,
  payload      TEXT NOT NULL                  -- JSON: commit 数/时间分布/分支/message/改动行数
);

CREATE TABLE daily_reviews (
  review_date TEXT PRIMARY KEY,               -- YYYY-MM-DD
  status      TEXT NOT NULL,                  -- pending|prompted|in_progress|done|skipped|missed
  thread_id   TEXT,                           -- LangGraph 会话
  summary     TEXT,                           -- JSON: 结构化结论
  updated_at  TEXT NOT NULL
);

CREATE TABLE reports (
  id           TEXT PRIMARY KEY,
  kind         TEXT NOT NULL,                 -- weekly|monthly|custom
  period_start TEXT NOT NULL,
  period_end   TEXT NOT NULL,
  stats        TEXT NOT NULL,                 -- JSON：确定性算出的数字
  body_md      TEXT NOT NULL,                 -- LLM 成文
  generated_at TEXT NOT NULL
);
