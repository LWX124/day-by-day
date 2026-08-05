"""读级 Tools（design.md §6.2 表「读」级）。

自由调用，不落库。接 core 纯函数或直接查投影表。

- `list_tasks`：列任务（可按 status 过滤）。
- `get_task`：取单个任务详情。
- `today_view`：今日视图（接 core.views.today_view）。
- `compute_stats`：确定性聚合统计（任务数/完成数/逾期等）。
- `query_git_evidence`：占位（M4 接 collectors.git）。
- `query_gerrit_changes`：占位（M4 接 collectors.gerrit）。
- `get_project`：占位（M4 接 projects 投影）。
- `search_notes`：占位（M4 接 notes 投影）。

读级 Tool 不返回 event_id（无可撤销语义）。
"""

from __future__ import annotations

import contextlib
import json
from datetime import date, datetime
from typing import Any

from agent.tools.registry import Tool, ToolArgs, ToolContext, ToolLevel, ToolResult
from core.schedule import ScheduleKind, Weight
from core.views import OccurrenceView, TaskView, today_view

# ---- list_tasks ----


class ListTasksArgs(ToolArgs):
    status: str | None = None  # pending | in_progress | done | deferred | abandoned
    schedule_kind: str | None = None
    limit: int = 50


class ListTasksTool(Tool):
    name = "list_tasks"
    level = ToolLevel.READ
    description = "列出任务，可按 status / schedule_kind 过滤。"
    args_model = ListTasksArgs

    def execute(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        sql = "SELECT id, title, schedule_kind, status, due_at, weight FROM tasks WHERE 1=1"
        params: list[Any] = []
        if args.get("status"):
            sql += " AND status = ?"
            params.append(args["status"])
        if args.get("schedule_kind"):
            sql += " AND schedule_kind = ?"
            params.append(args["schedule_kind"])
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(int(args.get("limit") or 50))
        rows = ctx.conn.execute(sql, params).fetchall()
        tasks = [dict(r) for r in rows]
        return ToolResult(ok=True, data={"tasks": tasks, "count": len(tasks)})


# ---- get_task ----


class GetTaskArgs(ToolArgs):
    task_id: str


class GetTaskTool(Tool):
    name = "get_task"
    level = ToolLevel.READ
    description = "取单个任务详情（含 inference / nag_count 等）。"
    args_model = GetTaskArgs

    def execute(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        row = ctx.conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (args["task_id"],)
        ).fetchone()
        if row is None:
            return ToolResult(ok=False, message=f"task not found: {args['task_id']}")
        data = dict(row)
        # inference / recur_target 是 JSON 字符串，解码便于消费。
        for k in ("inference", "recur_target"):
            v = data.get(k)
            if isinstance(v, str) and v:
                with contextlib.suppress(json.JSONDecodeError):
                    data[k] = json.loads(v)
        return ToolResult(ok=True, data=data)


# ---- today_view ----


class TodayViewArgs(ToolArgs):
    today: str | None = None  # YYYY-MM-DD，缺省取 now 的日期


class TodayViewTool(Tool):
    name = "today_view"
    level = ToolLevel.READ
    description = "今日视图：recurring 当日 occurrence + 进入催办窗口的 deadline + in_progress。"
    args_model = TodayViewArgs

    def execute(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        today = date.fromisoformat(args["today"]) if args.get("today") else ctx.now.date()

        task_rows = ctx.conn.execute(
            "SELECT id, title, schedule_kind, due_at, weight, status, last_activity_at "
            "FROM tasks WHERE status NOT IN ('done','abandoned')"
        ).fetchall()
        tasks: list[TaskView] = []
        for r in task_rows:
            tasks.append(
                TaskView(
                    id=r["id"],
                    title=r["title"],
                    schedule_kind=ScheduleKind(r["schedule_kind"]),
                    weight=Weight(r["weight"]),
                    status=r["status"],
                    due_at=datetime.fromisoformat(r["due_at"]) if r["due_at"] else None,
                    last_activity_at=(
                        datetime.fromisoformat(r["last_activity_at"])
                        if r["last_activity_at"]
                        else None
                    ),
                )
            )

        oc_rows = ctx.conn.execute(
            "SELECT task_id, occurrence_date, target_amount, done_amount, status "
            "FROM occurrences WHERE occurrence_date = ?",
            (today.isoformat(),),
        ).fetchall()
        occurrences = [
            OccurrenceView(
                task_id=r["task_id"],
                occurrence_date=date.fromisoformat(r["occurrence_date"]),
                target_amount=r["target_amount"],
                done_amount=r["done_amount"],
                status=r["status"],
            )
            for r in oc_rows
        ]
        view = today_view(tasks, occurrences, ctx.now, today=today)
        return ToolResult(
            ok=True,
            data={
                "recurring_today": [v.__dict__ for v in view.recurring_today],
                "deadlines": [
                    {
                        "task": d.task.__dict__,
                        "days_until_due": d.days_until_due,
                        "in_window": d.in_window,
                    }
                    for d in view.deadlines
                ],
                "in_progress": [t.__dict__ for t in view.in_progress],
            },
        )


# ---- compute_stats ----


class ComputeStatsArgs(ToolArgs):
    pass


class ComputeStatsTool(Tool):
    name = "compute_stats"
    level = ToolLevel.READ
    description = "确定性聚合统计：任务总数/各状态数/逾期数/今日待打卡数。"
    args_model = ComputeStatsArgs

    def execute(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        today = ctx.now.date().isoformat()
        total = ctx.conn.execute("SELECT COUNT(*) AS c FROM tasks").fetchone()["c"]
        by_status: dict[str, int] = {}
        for r in ctx.conn.execute(
            "SELECT status, COUNT(*) AS c FROM tasks GROUP BY status"
        ).fetchall():
            by_status[r["status"]] = int(r["c"])
        overdue = ctx.conn.execute(
            "SELECT COUNT(*) AS c FROM tasks WHERE due_at IS NOT NULL "
            "AND due_at < ? AND status NOT IN ('done','abandoned')",
            (today,),
        ).fetchone()["c"]
        recurring_today_pending = ctx.conn.execute(
            "SELECT COUNT(*) AS c FROM occurrences WHERE occurrence_date = ? "
            "AND status IN ('pending','partial')",
            (today,),
        ).fetchone()["c"]
        return ToolResult(
            ok=True,
            data={
                "total": int(total),
                "by_status": by_status,
                "overdue": int(overdue),
                "recurring_today_pending": int(recurring_today_pending),
            },
        )


# ---- 占位读 Tools（M4 接真实逻辑） ----


class QueryGitEvidenceArgs(ToolArgs):
    project_id: str | None = None
    task_id: str | None = None
    window_hours: int = 24


class QueryGitEvidenceTool(Tool):
    name = "query_git_evidence"
    level = ToolLevel.READ
    description = "查 git activity evidence（占位，M4 接 collectors.git）。"
    args_model = QueryGitEvidenceArgs

    def execute(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        # M4 才接真实采集。当前返回已有 activity_evidence 行（若有）或空。
        rows = ctx.conn.execute(
            "SELECT id, task_id, source, collected_at, window_start, window_end, payload "
            "FROM activity_evidence WHERE source = 'git' ORDER BY collected_at DESC LIMIT 50"
        ).fetchall()
        return ToolResult(
            ok=True,
            data={
                "placeholder": True,
                "evidence": [dict(r) for r in rows],
                "note": "git collector not wired until M4",
            },
        )


class QueryGerritChangesArgs(ToolArgs):
    status: str | None = None  # open | merged | abandoned
    owner_self: bool = True


class QueryGerritChangesTool(Tool):
    name = "query_gerrit_changes"
    level = ToolLevel.READ
    description = "查 Gerrit changes（占位，M4 接 collectors.gerrit SSH CLI）。"
    args_model = QueryGerritChangesArgs

    def execute(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        return ToolResult(
            ok=True,
            data={"placeholder": True, "changes": [], "note": "gerrit collector not wired until M4"},
        )


class GetProjectArgs(ToolArgs):
    project_id: str | None = None
    name: str | None = None


class GetProjectTool(Tool):
    name = "get_project"
    level = ToolLevel.READ
    description = "取项目信息（占位，M4 接 projects 投影）。"
    args_model = GetProjectArgs

    def execute(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        if args.get("project_id"):
            row = ctx.conn.execute(
                "SELECT * FROM projects WHERE id = ?", (args["project_id"],)
            ).fetchone()
        elif args.get("name"):
            row = ctx.conn.execute(
                "SELECT * FROM projects WHERE name = ?", (args["name"],)
            ).fetchone()
        else:
            return ToolResult(ok=False, message="project_id 或 name 必填其一")
        if row is None:
            return ToolResult(ok=False, message="project not found")
        data = dict(row)
        if isinstance(data.get("aliases"), str):
            with contextlib.suppress(json.JSONDecodeError):
                data["aliases"] = json.loads(data["aliases"])
        return ToolResult(ok=True, data=data)


class SearchNotesArgs(ToolArgs):
    query: str
    project_id: str | None = None
    limit: int = 20


class SearchNotesTool(Tool):
    name = "search_notes"
    level = ToolLevel.READ
    description = "搜笔记（占位，M4 接 notes 投影）。当前按 body 子串匹配。"
    args_model = SearchNotesArgs

    def execute(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        q = args["query"]
        sql = "SELECT id, project_id, tags, body, created_at, updated_at FROM notes WHERE body LIKE ?"
        params: list[Any] = [f"%{q}%"]
        if args.get("project_id"):
            sql += " AND project_id = ?"
            params.append(args["project_id"])
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(int(args.get("limit") or 20))
        rows = ctx.conn.execute(sql, params).fetchall()
        notes = []
        for r in rows:
            d = dict(r)
            if isinstance(d.get("tags"), str):
                with contextlib.suppress(json.JSONDecodeError):
                    d["tags"] = json.loads(d["tags"])
            notes.append(d)
        return ToolResult(ok=True, data={"notes": notes, "count": len(notes)})


__all__ = [
    "ComputeStatsArgs",
    "ComputeStatsTool",
    "GetProjectArgs",
    "GetProjectTool",
    "GetTaskArgs",
    "GetTaskTool",
    "ListTasksArgs",
    "ListTasksTool",
    "QueryGerritChangesArgs",
    "QueryGerritChangesTool",
    "QueryGitEvidenceArgs",
    "QueryGitEvidenceTool",
    "SearchNotesArgs",
    "SearchNotesTool",
    "TodayViewArgs",
    "TodayViewTool",
]
