# Directory Structure

> daybyday-agent（Python 后端）的目录组织。后端是 SwiftUI 外壳的子进程，负责一切决策与数据。

---

## Overview

后端按"判定/数据/IO"三圈分层。**最核心的约束：`core/` 是纯函数域，禁依赖 LLM、网络、IO**——所有"该催谁、断签几天、Tier 档位"的判定住在这里，因此全部可单测、可离线运行、可复现。这条红线用 import-linter 规则钉死（见 quality-guidelines）。

分层依据见 `.trellis/docs/design.md` §1 与 ADR-0003。

---

## Directory Layout

```
daybyday-agent/
├── pyproject.toml
├── core/            # 纯函数域。禁 import 任何 agent/store/api/collectors/scheduler/langchain*
│   ├── schedule.py      # Schedule 四态联合类型 + 非法组合校验
│   ├── occurrence.py    # ensure_occurrences_up_to（幂等、过去冻结）
│   ├── views.py         # today_view
│   ├── nag.py           # 四个 schedule 策略对象 + due_nags()
│   ├── escalation.py    # nag 升级与 Re-decision 终点
│   ├── celebration.py   # celebration_tier()
│   ├── emotion.py       # emotion() 状态推导
│   └── stats.py         # 事件流聚合统计
├── store/           # 事件流 + 投影。唯一事实来源
│   ├── migrations/      # 编号 SQL，顺序执行
│   ├── events.py        # append / 重放 / 撤销(EventUndone)
│   ├── projections.py   # 从 events 重建 tasks/occurrences
│   └── db.py            # 连接、WAL、迁移执行
├── agent/           # LLM 与 LangGraph。只做：解析、组织成文、多轮对话
│   ├── graph.py         # LangGraph 主图 + SqliteSaver
│   ├── nodes/           # classify / ingest_task / query_status / daily_review / ...
│   ├── extraction.py    # 结构化抽取 + 置信度
│   ├── tools/           # Tool 注册表 + 授权分级
│   └── providers.py     # Provider 抽象 + config.toml 路由
├── collectors/      # 外部系统只读采集
│   ├── git.py           # 只读子命令白名单
│   └── gerrit.py        # SSH CLI（2.8.4）
├── scheduler/       # APScheduler 调度
│   └── jobs.py          # hourly_tick / daily_review / weekly_prompt / wake
├── api/             # FastAPI 端点 + SSE
│   ├── app.py
│   ├── routes.py        # /intent /today /tasks /confirm /wake /events(SSE)
│   └── commands.py      # PetCommand 定义与 SSE 推送
├── common/          # 跨层共享：类型、时钟抽象、配置
└── tests/
    ├── core/             # 高覆盖，不 mock LLM
    ├── store/            # 重放与撤销
    └── agent/            # 少量端到端冒烟
```

---

## Module Organization

- **新增功能先问"这是判定还是 IO"**。判定逻辑（算谁该催、算 Tier、算统计）必须进 `core/`，且当前时间作参数传入，不读系统时钟。IO（写库、调 LLM、跑 git）进对应层。
- `core/` 函数签名一律接收**已加载的内存数据 + now 参数**，不接收数据库连接、不接收 LLM 客户端。需要数据由调用方（agent/scheduler）从 store 取好传入。
- `agent/` 调 `core/` 拿判定结果，再用 LLM 把结果组织成人话——**判定不经过 LLM**（ADR-0003）。
- 跨层共享类型放 `common/`，但 `common/` 不许 import 任何业务层。

---

## Naming Conventions

- 文件与目录：`snake_case`。
- 纯函数：动词短语，如 `due_nags(tasks, occurrences, now)`、`celebration_tier(task, now)`。
- 策略对象：`<schedule>_policy`，统一实现 `def candidates(ctx, now) -> list[NagCandidate]` 接口。
- 事件 kind：`PascalCase` 枚举字符串，如 `TaskCreated`、`EventUndone`（见 store）。
- Tool 名：`snake_case` 动词，如 `checkin_occurrence`、`gerrit_review_vote`。

---

## Examples

- `core/nag.py` 是分层范本：四个策略对象都是纯函数，`due_nags()` 聚合它们，整套可脱离数据库单测。
- `store/events.py` 的 append/重放/撤销是事件流范本（ADR-0002）。
