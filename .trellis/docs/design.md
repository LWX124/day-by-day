# Day by Day — 设计方案

术语一律以 [`CONTEXT.md`](../../CONTEXT.md) 为准。不可逆的架构决策见 [`adr/`](./adr/)。

---

## 1. 系统形态

```
┌─────────────────────────────── DayByDay.app (Swift) ────────────────────────────────┐
│  PetWindow        BubbleWindow    TaskCardWindow   PanelWindow   CelebrationOverlay │
│  (SpriteKit)      (气泡)          (单击)           (双击)        (全屏/点击穿透)     │
│         │                                                                           │
│  PetRenderer ◄── EmotionState ──┐        BackendSupervisor（spawn / 退避重启 / 日志）│
└─────────────────────────────────┼───────────────────────────┬───────────────────────┘
                                  │ SSE: PetCommand           │ HTTP: 用户意图/查询
                                  │ (127.0.0.1, token)        │
┌─────────────────────────────────┴───────────────────────────┴───────────────────────┐
│                           daybyday-agent (Python)                                   │
│                                                                                     │
│  api/          FastAPI：/intent /today /tasks /events(SSE) /confirm /wake            │
│  agent/        LangGraph 图 + Tool 注册表 + Provider 路由                            │
│  core/         纯函数域：nag 策略 / tier 函数 / 统计 / occurrence 规则  ← 无 LLM 依赖 │
│  store/        events(append-only) + 投影 + 迁移                                     │
│  collectors/   git 只读扫描 / Gerrit SSH CLI                                         │
│  scheduler/    APScheduler：hourly tick / 18:30 复盘 / 唤醒补偿                       │
└─────────────────────────────────────────────────────────────────────────────────────┘
                                  │
                         ~/Library/Application Support/DayByDay/
                         ├── db.sqlite3     (events + 投影 + LangGraph checkpoint)
                         ├── config.toml
                         ├── assets/        (sprite sheets)
                         └── logs/
```

**分层铁律**：`core/` 是纯函数域，不许 import LLM、不许碰网络、不许读时钟以外的 IO（当前时间作参数传入）。所有"判定"住在这里，所以全部可单测。`agent/` 只做三件事：把自然语言解析成结构化命令、把 `core/` 算好的事实组织成人话、多轮对话。

## 2. 进程与通信

- 端口与 token：Swift 启动时生成随机高位端口 + 32 字节 token，以命令行参数传给 Python；后端只 bind `127.0.0.1`，所有请求校验 `Authorization: Bearer <token>`。不落盘、不走环境变量。
- Swift → Python：普通 HTTP。`POST /intent {text}`（用户说的话）、`GET /today`、`POST /confirm {action_id}`（二次确认动作的回执）、`POST /wake`（收到 `NSWorkspace.didWakeNotification` 时通知后端补偿调度）。
- Python → Swift：`GET /events` 的 SSE 长连接，推 **PetCommand**：

  | PetCommand | 载荷 | Swift 侧行为 |
  |---|---|---|
  | `set_emotion` | state | 切 sprite 状态机 |
  | `bubble` | text, ttl, 可选 quick_replies | 弹气泡 |
  | `celebrate` | tier, text | 播 Tier 1–4 特效 |
  | `notify` | title, body | 系统通知 |
  | `open_panel` | section | 打开面板到指定分区 |
  | `request_confirm` | action_id, title, detail | 弹二次确认框 |
  | `badge` | count | 宠物身上的待办徽标 |

  **后端永不直接抢焦点**：能弹的最重的东西是 `request_confirm`，且只在你已经明确要求某个动作之后。
- 后端崩溃：Swift 按 1s→2s→4s→8s→30s 退避重启，连续 5 次失败后宠物切 `worried` 并气泡提示，本地功能（拖动、看缓存的今日任务）仍可用。

## 3. 领域模型

### 3.1 Task 与 Schedule

Schedule 是四态联合类型，`schedule_kind` + 各自独有字段（非法组合在写入层拒绝，例如 recurring 不许有 due）：

| schedule_kind | 独有字段 | 语义 | 完成的含义 |
|---|---|---|---|
| `one_shot` | — | 做完就结束，无约定期限 | 状态转 `done` |
| `deadline` | `due_at` | 约定了完成时点 | 状态转 `done`，记录是否逾期 |
| `recurring` | `recur_rule`, `recur_target` | 按规则反复，**不存在超期** | 无终态，只有逐日 Check-in |
| `openended` | — | 长期挂着，无时点无节奏 | 状态转 `done` 或 `abandoned` |

Weight ∈ {S, M, L, XL}，写入时由 LLM 推断（见 ADR-0003），你随时可改。

状态机（仅前三态适用 recurring 之外的 Task）：

```
pending ──► in_progress ──► done
   │              │
   ├──────────────┴──► deferred（Re-decision 改期，带新 due 与改期次数）
   └──────────────┴──► abandoned（Re-decision 放弃）
```

### 3.2 事件流与投影

`events` 是唯一事实来源（ADR-0002）。事件种类：

`TaskCreated` `TaskFieldsUpdated` `TaskStatusChanged` `TaskRescheduled` `TaskAbandoned` `OccurrenceCheckedIn` `EvidenceCollected` `NagSent` `RedecisionMade` `DailyReviewAnswered` `ReportGenerated` `EventUndone`

撤销 = append 一条 `EventUndone{target_event_id}`，重放时跳过被撤销事件。

### 3.3 Occurrence 物化

Recurring 的当日实例落库（`occurrences` 表），生成走幂等函数：

```python
ensure_occurrences_up_to(today, backfill_days=30)
```

在三个时机各跑一次——**后端启动**、**收到 `/wake`**、**每小时 tick**——因为这是桌面应用，凌晨机器在睡觉，"漏生成"是必然事件而不是异常。改 `recur_rule` 只重算**未来**实例，已过去的实例冻结（历史不可被规则变更改写）。

## 4. 数据库

SQLite，WAL 模式，迁移用编号 SQL 文件顺序执行（`store/migrations/0001_*.sql`）。

```sql
-- 唯一事实来源，只增不改
CREATE TABLE events (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  occurred_at   TEXT NOT NULL,              -- ISO8601 带时区
  kind          TEXT NOT NULL,
  task_id       TEXT,                       -- 可空：非任务事件
  occurrence_date TEXT,                     -- 仅 Check-in 类事件
  actor         TEXT NOT NULL,              -- user | agent | scanner | scheduler
  payload       TEXT NOT NULL,              -- JSON
  undone_by     INTEGER REFERENCES events(id)
);
CREATE INDEX idx_events_task ON events(task_id, occurred_at);
CREATE INDEX idx_events_time ON events(occurred_at);

-- 投影：可从 events 重建
CREATE TABLE tasks (
  id              TEXT PRIMARY KEY,
  title           TEXT NOT NULL,
  detail          TEXT,
  schedule_kind   TEXT NOT NULL,            -- one_shot|deadline|recurring|openended
  due_at          TEXT,
  recur_rule      TEXT,                     -- RRULE 子集：FREQ/INTERVAL/BYDAY
  recur_target    TEXT,                     -- JSON: {amount:5, unit:"页"}
  weight          TEXT NOT NULL,            -- S|M|L|XL
  status          TEXT NOT NULL,
  project_id      TEXT REFERENCES projects(id),
  inference       TEXT,                     -- JSON: 各字段置信度与原始输入
  last_activity_at TEXT,                    -- 事件或 Evidence 中的最近活动
  nag_count       INTEGER NOT NULL DEFAULT 0,
  last_nagged_at  TEXT,
  reschedule_count INTEGER NOT NULL DEFAULT 0,
  created_at      TEXT NOT NULL,
  updated_at      TEXT NOT NULL
);

CREATE TABLE occurrences (
  task_id         TEXT NOT NULL REFERENCES tasks(id),
  occurrence_date TEXT NOT NULL,            -- YYYY-MM-DD
  target_amount   REAL,
  done_amount     REAL NOT NULL DEFAULT 0,
  status          TEXT NOT NULL,            -- pending|partial|done|skipped
  note            TEXT,
  PRIMARY KEY (task_id, occurrence_date)
);

CREATE TABLE projects (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  aliases     TEXT NOT NULL DEFAULT '[]',   -- JSON 数组，口语别名（"主站"）
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
  source       TEXT NOT NULL,               -- git | gerrit
  collected_at TEXT NOT NULL,
  window_start TEXT NOT NULL,
  window_end   TEXT NOT NULL,
  payload      TEXT NOT NULL                -- JSON: commit 数/时间分布/分支/message/改动行数
);

CREATE TABLE daily_reviews (
  review_date TEXT PRIMARY KEY,             -- YYYY-MM-DD
  status      TEXT NOT NULL,                -- pending|prompted|in_progress|done|skipped|missed
  thread_id   TEXT,                         -- LangGraph 会话
  summary     TEXT,                         -- JSON: 结构化结论
  updated_at  TEXT NOT NULL
);

CREATE TABLE reports (
  id           TEXT PRIMARY KEY,
  kind         TEXT NOT NULL,               -- weekly|monthly|custom
  period_start TEXT NOT NULL,
  period_end   TEXT NOT NULL,
  stats        TEXT NOT NULL,               -- JSON：确定性算出的数字
  body_md      TEXT NOT NULL,               -- LLM 成文
  generated_at TEXT NOT NULL
);
```

LangGraph 的 `SqliteSaver` 用同一个库文件的独立表，互不干扰。

## 5. `core/` 纯函数域

### 5.1 Nag 策略（每个 schedule 一个策略对象）

```python
def due_nags(tasks, occurrences, now) -> list[NagCandidate]
```

| schedule | 触发条件 | 不触发的情况 |
|---|---|---|
| `one_shot` | `now - last_activity_at > idle_threshold(weight)`（S 7d / M 14d / L 21d / XL 30d，可配） | 有近期活动 |
| `deadline` | due 前 `lead_days(weight)` 天、due 当天、逾期后每日一次 | **未到提醒窗口就一声不出**——这直接对应"订好 1 个月完成、没到期限不用提醒" |
| `recurring` | 连续断签 ≥ 2 个应有 Occurrence | **永不因"总时长"触发**——"每天读几页书"不存在超期 |
| `openended` | 距上次 review > 30 天 | 本月已 review 过 |

### 5.2 Nag 升级与终点

```
nag_count 0 → 1 : 轻推   "X 有一阵没动了，还在推进吗？"
          1 → 2 : 认真问 "X 已经 N 天没进展，卡在哪了？"
          2 → 3 : 鞭策   （语气最重，LLM 生成，允许扎心）
          == 3  : 停止催"快做"，改为 Re-decision：改期 / 降级 / 放弃
```

`RedecisionMade` 事件写入后 `nag_count` 归零。这条规则是产品存活的前提（ADR-0004）。

### 5.3 Tier 函数

```python
def celebration_tier(task, now) -> int:
    tier = {"S": 1, "M": 2, "L": 3, "XL": 4}[task.weight]
    if age_days(task) > 30:  tier += 1     # 拖了一个月终于干掉，情绪价值峰值
    if is_last_of_day_or_week: tier += 1   # 清空里程碑
    return min(tier, 4)
```

| Tier | 表现 |
|---|---|
| 1 微 | 宠物点头 + 粒子一闪 + 轻音 |
| 2 中 | 宠物欢呼动作 + 彩带从宠物窗口喷出 |
| 3 大 | 全屏 overlay 烟花 ~3s |
| 4 史诗 | 全屏烟花 ~8s + 大字文案 + 长音效 + 宠物专属动作 |

逾期完成**不降档**（完成了就该庆祝），逾期事实只写进复盘与报告。

### 5.4 Emotion State

```python
def emotion(today_view, overdue_count, broken_streaks, recent_celebration, clock) -> EmotionState
```

`idle` / `happy` / `focused` / `worried` / `grumpy` / `sleeping`（夜间或锁屏）。由积压情况推导，**不由 LLM 决定**——否则宠物表情会随机漂移。

## 6. Agent 层

### 6.1 LangGraph 图

```
        ┌──────────────┐
entry ─►│ classify     │─┬─► ingest_task      结构化抽取 → 落库 → 回执
        └──────────────┘ ├─► query_status     取任务 + 拉 Evidence → 总结
                         ├─► daily_review     候选清单 → 逐项问 → 写回（可中断数小时）
                         ├─► period_report    core 算数字 → 成文
                         ├─► redecision       催办终点对话
                         ├─► gerrit_ops       查询；写操作 → request_confirm
                         └─► freeform         通用对话 + Note 读写
```

Checkpointer 用 `SqliteSaver`。Daily Review 的 `thread_id = "review-YYYY-MM-DD"`，所以"18:30 问一句 → 你 21:00 才回 → 接着上文继续"是天然支持的，这也是选 LangGraph 而非裸 tool loop 的主要收益。

### 6.2 Tool 清单与授权分级（ADR-0004）

| 级别 | Tools |
|---|---|
| 读（自由调用） | `list_tasks` `get_task` `today_view` `compute_stats` `query_git_evidence` `query_gerrit_changes` `get_project` `search_notes` |
| 常规写（直接执行 + 回执 + 可撤销） | `create_task` `update_task` `complete_task` `checkin_occurrence` `reschedule_task` `abandon_task` `upsert_project` `upsert_note` |
| 需 UI 二次确认 | `delete_task` `gerrit_review_vote` `gerrit_abandon` `gerrit_rebase` |

需确认的 tool 不直接执行，而是登记一个 `pending_action`、推 `request_confirm`，等 `POST /confirm` 才落地；超时（默认 5 分钟）自动作废。

### 6.3 git 采集（只读白名单）

```python
GIT_ALLOWED = {"log", "status", "diff", "branch", "rev-list", "show", "shortlog"}
```

以参数数组 exec、**不经 shell**；拒绝 `-c` / `--exec` / `--upload-pack` 等注入向量；工作目录必须落在某个 Project 的 `local_path` 之内。写子命令不可达。

采集产出 `EvidenceCollected` 事件，payload 形如：

```json
{"commits": 7, "first_at": "...", "last_at": "...", "branches": ["feature/x"],
 "messages": ["fix: ...", "..."], "insertions": 412, "deletions": 88}
```

### 6.4 Gerrit（SSH CLI）

环境已验证：`gerrit.client.weibo.cn`，**2.8.4**，端口 29419，用户 `weixi1`，老算法已在 `~/.ssh/config` 配好，`BatchMode` 免交互通过。这个版本 REST API 残缺，因此**只走 SSH CLI**：

```bash
ssh gerrit.client.weibo.cn gerrit query --format=JSON --current-patch-set \
    'owner:self status:open'
ssh gerrit.client.weibo.cn gerrit review <change>,<patchset> --code-review +1   # 需确认
```

Change 已 merge 是比本地 commit 强得多的完成证据，因此 Gerrit Evidence 在复盘里的权重高于 git Evidence。"待我评审"堆积超过阈值时也会触发一次 Nag。

### 6.5 Provider 配置与路由

```toml
[llm]
default  = "bailian"
fallback = ["deepseek"]

[llm.providers.bailian]
kind = "openai_compatible"
base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
model = "qwen-max"
api_key_env = "DASHSCOPE_API_KEY"

[llm.providers.deepseek]
kind = "openai_compatible"
base_url = "https://api.deepseek.com/v1"
model = "deepseek-chat"
api_key_env = "DEEPSEEK_API_KEY"

# 微博内部网关：协议待确认，兼容则同上，不兼容则实现 BaseChatModel 子类
[llm.providers.wb_internal]
kind = "openai_compatible"
base_url = "TBD"

# 数据边界当前不设限（ADR-0004），此段是保留的收紧位，留空即不路由
[llm.routing]
# ingest = "wb_internal"
# report = "bailian"
```

所有 `openai_compatible` 走 `ChatOpenAI(base_url=..., model=...)`。**无 key 时降级为纯确定性模式**：提醒、统计、打卡、特效全部照常，仅禁用自然语言录入与成文。

## 7. 调度与主动性

APScheduler（AsyncIO）：

| Job | 触发 | 动作 |
|---|---|---|
| `hourly_tick` | 每小时 | `ensure_occurrences_up_to(today)` → 扫 Nag 候选 → 推送 |
| `daily_review` | 18:30 | 见下方补偿逻辑 |
| `wake_catchup` | `POST /wake` | 立即跑一次 `hourly_tick` + 检查复盘补偿窗口 |
| `weekly_prompt` | 周日 20:00 | 气泡提示"要不要出周报"，**不自动生成** |

**Daily Review 触发协议**：

```
18:30  宠物做动作 + 气泡 + 一条系统通知，绝不抢焦点
       ↓ 30 分钟无响应
       降级为宠物身上的待办徽标，当天不再追
       ↓ 睡眠/关机导致错过
       唤醒后若仍在 18:30–23:00 窗口内 → 补触发
       超出窗口 → 标记 missed，并入次日早报开场
周末    默认跳过（可配）
```

## 8. UI 层

| 窗口 | 关键配置 | 触发 |
|---|---|---|
| `PetWindow` | `NSPanel`, `.floating`, `[.canJoinAllSpaces, .stationary]`, 透明无边框，SpriteKit 渲染 | 常驻 |
| `BubbleWindow` | 跟随宠物，`ttl` 到点自动消失，可带快捷回复按钮 | 悬停 / 后端推送 |
| `TaskCardWindow` | ~360×480，Esc 关闭 | **单击** |
| `PanelWindow` | ~900×600，分区：对话 / 今日 / 全部任务 / 复盘历史 / Gerrit / 知识 / 设置 | **双击** |
| `CelebrationOverlay` | 全屏，`.screenSaver` level，`ignoresMouseEvents = true`，跨 Space | Tier 3–4 |

手势分配：**悬停**→气泡摘要，**单击**→任务卡，**双击**→面板，**右键**→菜单（暂停提醒/设置/退出），**拖拽**→挪位置。不用长按，因为按住鼠标在桌面宠物上就是拖拽的起手式，两者会抢同一个手势。

`LSUIElement = true` 隐藏 Dock 图标；开机自启用 `SMAppService.loginItem` 注册。

`PetRenderer` 是协议（输入 = Emotion State + 动作事件，输出 = 渲染），sprite sheet 实现与开发期占位实现可互换，避免素材未就位时整条链路阻塞。

## 9. 需求追溯

| 需求 | 落点 |
|---|---|
| 1 桌面宠物做日程/工作管理 | §1 系统形态、§3 领域模型 |
| 2 后台常驻 + 快看近期与当天任务 | §7 常驻调度、§8 单击 TaskCard |
| 3 任务可选关联目录、扫描看状态 | §3.1 `project_id` 可空、§6.3 git 采集、ADR-0004 第 1 条 |
| 4 agent 实现 | §6 LangGraph 图与 Tool 清单 |
| 5 每晚 18:30 复盘并主动询问 | §7 Daily Review 触发协议 |
| 6 时间段复盘、周报月报 | §4 `reports`、§6.1 `period_report`、ADR-0002 |
| 7 展开面板的功能扩展（Gerrit） | §8 PanelWindow 分区、§6.4 |
| 8 基础知识记忆（源码路径） | §4 `projects` / `notes`（结构化 + 自由文本双轨） |
| 9 多 LLM provider 可配置 | §6.5 |
| 10 主动标记完成、久未完成追问、长期/习惯任务不误报 | §5.1 四策略表、§5.2 升级与终点 |
| 11 完成特效分级、超时鞭策 | §5.3 Tier 函数、§5.2 鞭策语气递增 |
