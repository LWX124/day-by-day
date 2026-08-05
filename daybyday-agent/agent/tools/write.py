"""常规写级 Tools（design.md §6.2 表「常规写」级）。

直接执行 + 回执 + 可撤销。封装 store.events.append + projections.rebuild_all，
返回 event_id（撤销走 events.undo）。

- `create_task`：建任务（TaskCreated）。复用 extraction.draft_to_task_created_payload
  的 payload 形状，但参数直接由调用方给（agent 节点已抽好结构）。
- `update_task`：改字段（TaskFieldsUpdated）。
- `complete_task`：标完成（TaskStatusChanged to=done）。
- `checkin_occurrence`：recurring 当日打卡（OccurrenceCheckedIn）。
- `reschedule_task`：改期（TaskRescheduled）。
- `abandon_task`：放弃（TaskAbandoned）。
- `upsert_project`：建/改项目（占位，M4 接 projects 投影）。
- `upsert_note`：建/改笔记（占位，M4 接 notes 投影）。

actor 由 ToolContext.actor 决定（user / agent / scanner / scheduler）。
"""

from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime
from typing import Any

from agent.tools.registry import Tool, ToolArgs, ToolContext, ToolLevel, ToolResult
from core.schedule import ScheduleKind
from store import events as event_store
from store.projections import rebuild_all


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _gen_task_id() -> str:
    return f"task_{int(datetime.now(UTC).timestamp())}_{secrets.token_hex(4)}"


def _gen_id(prefix: str) -> str:
    return f"{prefix}_{int(datetime.now(UTC).timestamp())}_{secrets.token_hex(4)}"


def _task_exists(conn: Any, task_id: str) -> bool:
    row = conn.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return row is not None


# ---- create_task ----


class CreateTaskArgs(ToolArgs):
    title: str
    schedule_kind: str  # one_shot | deadline | recurring | openended
    weight: str = "M"  # S | M | L | XL
    due_at: str | None = None  # ISO8601，仅 deadline
    recur_rule: str | None = None  # 仅 recurring
    recur_target: dict[str, Any] | None = None  # {amount, unit}，仅 recurring
    detail: str | None = None
    project_id: str | None = None


class CreateTaskTool(Tool):
    name = "create_task"
    level = ToolLevel.WRITE
    description = "建任务。落 TaskCreated 事件，返回 event_id（可撤销）。"
    args_model = CreateTaskArgs

    def execute(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        kind = ScheduleKind(args["schedule_kind"])
        # 写入层校验非法组合（design.md §3.1）。
        _validate_schedule_combination(kind, args)

        task_id = _gen_task_id()
        payload: dict[str, Any] = {
            "title": args["title"],
            "schedule_kind": args["schedule_kind"],
            "due_at": args.get("due_at"),
            "recur_rule": args.get("recur_rule"),
            "recur_target": args.get("recur_target"),
            "weight": args.get("weight", "M"),
            "status": "pending",
            "detail": args.get("detail"),
            "project_id": args.get("project_id"),
            "inference": {"source": "tool", "raw_input": None},
        }
        eid = event_store.append(
            ctx.conn,
            event_store.TASK_CREATED,
            ctx.actor,
            task_id=task_id,
            payload=payload,
            occurred_at=ctx.now.isoformat(),
        )
        rebuild_all(ctx.conn)
        return ToolResult(
            ok=True,
            data={"task_id": task_id},
            message=f"已建任务：{args['title']}",
            event_id=eid,
        )


def _validate_schedule_combination(kind: ScheduleKind, args: dict[str, Any]) -> None:
    """写入层拒绝非法组合（与 core.Schedule.validate 同语义）。"""
    has_due = args.get("due_at") is not None
    has_recur = args.get("recur_rule") is not None
    if kind is ScheduleKind.DEADLINE and not has_due:
        raise ValueError("deadline 必须有 due_at")
    if kind is ScheduleKind.RECURRING and not has_recur:
        raise ValueError("recurring 必须有 recur_rule")
    if kind is ScheduleKind.RECURRING and has_due:
        raise ValueError("recurring 不允许有 due_at")
    if kind is ScheduleKind.ONE_SHOT and has_due:
        raise ValueError("one_shot 不应有 due_at（用 deadline）")
    if kind is ScheduleKind.OPENENDED and has_due:
        raise ValueError("openended 不应有 due_at")
    if kind is not ScheduleKind.RECURRING and (has_recur or args.get("recur_target")):
        raise ValueError(f"{kind.value} 不允许有 recur_rule/recur_target")


# ---- update_task ----


class UpdateTaskArgs(ToolArgs):
    task_id: str
    title: str | None = None
    detail: str | None = None
    weight: str | None = None
    project_id: str | None = None
    due_at: str | None = None
    recur_rule: str | None = None
    recur_target: dict[str, Any] | None = None


class UpdateTaskTool(Tool):
    name = "update_task"
    level = ToolLevel.WRITE
    description = "改任务字段。落 TaskFieldsUpdated，返回 event_id（可撤销）。"
    args_model = UpdateTaskArgs

    def execute(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        if not _task_exists(ctx.conn, args["task_id"]):
            return ToolResult(ok=False, message=f"task not found: {args['task_id']}")
        payload: dict[str, Any] = {}
        for k in ("title", "detail", "weight", "project_id", "due_at", "recur_rule"):
            if args.get(k) is not None:
                payload[k] = args[k]
        if args.get("recur_target") is not None:
            payload["recur_target"] = args["recur_target"]
        if not payload:
            return ToolResult(ok=False, message="no fields to update")
        eid = event_store.append(
            ctx.conn,
            event_store.TASK_FIELDS_UPDATED,
            ctx.actor,
            task_id=args["task_id"],
            payload=payload,
            occurred_at=ctx.now.isoformat(),
        )
        rebuild_all(ctx.conn)
        return ToolResult(
            ok=True,
            data={"task_id": args["task_id"]},
            message=f"已改字段：{', '.join(payload.keys())}",
            event_id=eid,
        )


# ---- complete_task ----


class CompleteTaskArgs(ToolArgs):
    task_id: str


class CompleteTaskTool(Tool):
    name = "complete_task"
    level = ToolLevel.WRITE
    description = "标任务完成。落 TaskStatusChanged(to=done)，返回 event_id。"
    args_model = CompleteTaskArgs

    def execute(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        if not _task_exists(ctx.conn, args["task_id"]):
            return ToolResult(ok=False, message=f"task not found: {args['task_id']}")
        eid = event_store.append(
            ctx.conn,
            event_store.TASK_STATUS_CHANGED,
            ctx.actor,
            task_id=args["task_id"],
            payload={"to": "done"},
            occurred_at=ctx.now.isoformat(),
        )
        rebuild_all(ctx.conn)
        return ToolResult(
            ok=True,
            data={"task_id": args["task_id"]},
            message=f"已标记完成：{args['task_id']}",
            event_id=eid,
        )


# ---- checkin_occurrence ----


class CheckinOccurrenceArgs(ToolArgs):
    task_id: str
    occurrence_date: str  # YYYY-MM-DD
    done_amount: float = 0.0
    target_amount: float | None = None
    note: str | None = None
    force_done: bool = False


class CheckinOccurrenceTool(Tool):
    name = "checkin_occurrence"
    level = ToolLevel.WRITE
    description = "recurring 当日打卡。落 OccurrenceCheckedIn，返回 event_id。"
    args_model = CheckinOccurrenceArgs

    def execute(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        if not _task_exists(ctx.conn, args["task_id"]):
            return ToolResult(ok=False, message=f"task not found: {args['task_id']}")
        payload: dict[str, Any] = {
            "done_amount": float(args.get("done_amount") or 0.0),
        }
        if args.get("target_amount") is not None:
            payload["target_amount"] = float(args["target_amount"])
        if args.get("note"):
            payload["note"] = args["note"]
        if args.get("force_done"):
            payload["force_done"] = True
        eid = event_store.append(
            ctx.conn,
            event_store.OCCURRENCE_CHECKED_IN,
            ctx.actor,
            task_id=args["task_id"],
            occurrence_date=args["occurrence_date"],
            payload=payload,
            occurred_at=ctx.now.isoformat(),
        )
        rebuild_all(ctx.conn)
        return ToolResult(
            ok=True,
            data={"task_id": args["task_id"], "occurrence_date": args["occurrence_date"]},
            message=f"已打卡：{args['task_id']} @ {args['occurrence_date']}",
            event_id=eid,
        )


# ---- reschedule_task ----


class RescheduleTaskArgs(ToolArgs):
    task_id: str
    due_at: str | None = None
    recur_rule: str | None = None


class RescheduleTaskTool(Tool):
    name = "reschedule_task"
    level = ToolLevel.WRITE
    description = "改期。落 TaskRescheduled（reschedule_count +1），返回 event_id。"
    args_model = RescheduleTaskArgs

    def execute(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        if not _task_exists(ctx.conn, args["task_id"]):
            return ToolResult(ok=False, message=f"task not found: {args['task_id']}")
        payload: dict[str, Any] = {}
        if args.get("due_at") is not None:
            payload["due_at"] = args["due_at"]
        if args.get("recur_rule") is not None:
            payload["recur_rule"] = args["recur_rule"]
        if not payload:
            return ToolResult(ok=False, message="no due_at or recur_rule given")
        eid = event_store.append(
            ctx.conn,
            event_store.TASK_RESCHEDULED,
            ctx.actor,
            task_id=args["task_id"],
            payload=payload,
            occurred_at=ctx.now.isoformat(),
        )
        rebuild_all(ctx.conn)
        return ToolResult(
            ok=True,
            data={"task_id": args["task_id"]},
            message=f"已改期：{args['task_id']}",
            event_id=eid,
        )


# ---- abandon_task ----


class AbandonTaskArgs(ToolArgs):
    task_id: str


class AbandonTaskTool(Tool):
    name = "abandon_task"
    level = ToolLevel.WRITE
    description = "放弃任务。落 TaskAbandoned，返回 event_id。"
    args_model = AbandonTaskArgs

    def execute(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        if not _task_exists(ctx.conn, args["task_id"]):
            return ToolResult(ok=False, message=f"task not found: {args['task_id']}")
        eid = event_store.append(
            ctx.conn,
            event_store.TASK_ABANDONED,
            ctx.actor,
            task_id=args["task_id"],
            payload={},
            occurred_at=ctx.now.isoformat(),
        )
        rebuild_all(ctx.conn)
        return ToolResult(
            ok=True,
            data={"task_id": args["task_id"]},
            message=f"已放弃：{args['task_id']}",
            event_id=eid,
        )


# ---- upsert_project（占位） ----


class UpsertProjectArgs(ToolArgs):
    name: str
    project_id: str | None = None  # 缺省新建
    aliases: list[str] | None = None
    local_path: str | None = None
    gerrit_repo: str | None = None


class UpsertProjectTool(Tool):
    name = "upsert_project"
    level = ToolLevel.WRITE
    description = "建/改项目（占位，M4 接 projects 投影持久化）。当前直接写 projects 表。"
    args_model = UpsertProjectArgs

    def execute(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        pid = args.get("project_id") or _gen_id("proj")
        existing = ctx.conn.execute(
            "SELECT id FROM projects WHERE id = ?", (pid,)
        ).fetchone()
        aliases_json = json.dumps(args.get("aliases") or [], ensure_ascii=False)
        now_iso = _now_iso()
        if existing:
            ctx.conn.execute(
                "UPDATE projects SET name=?, aliases=?, local_path=?, gerrit_repo=? WHERE id=?",
                (
                    args["name"],
                    aliases_json,
                    args.get("local_path"),
                    args.get("gerrit_repo"),
                    pid,
                ),
            )
            msg = f"已改项目：{args['name']}"
        else:
            ctx.conn.execute(
                "INSERT INTO projects (id, name, aliases, local_path, gerrit_repo, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (pid, args["name"], aliases_json, args.get("local_path"), args.get("gerrit_repo"), now_iso),
            )
            msg = f"已建项目：{args['name']}"
        return ToolResult(ok=True, data={"project_id": pid}, message=msg)


# ---- upsert_note（占位） ----


class UpsertNoteArgs(ToolArgs):
    body: str
    note_id: str | None = None  # 缺省新建
    project_id: str | None = None
    tags: list[str] | None = None


class UpsertNoteTool(Tool):
    name = "upsert_note"
    level = ToolLevel.WRITE
    description = "建/改笔记（占位，M4 接 notes 投影持久化）。当前直接写 notes 表。"
    args_model = UpsertNoteArgs

    def execute(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        nid = args.get("note_id") or _gen_id("note")
        existing = ctx.conn.execute("SELECT id FROM notes WHERE id = ?", (nid,)).fetchone()
        tags_json = json.dumps(args.get("tags") or [], ensure_ascii=False)
        now_iso = _now_iso()
        if existing:
            ctx.conn.execute(
                "UPDATE notes SET project_id=?, tags=?, body=?, updated_at=? WHERE id=?",
                (args.get("project_id"), tags_json, args["body"], now_iso, nid),
            )
            msg = "已改笔记"
        else:
            ctx.conn.execute(
                "INSERT INTO notes (id, project_id, tags, body, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (nid, args.get("project_id"), tags_json, args["body"], now_iso, now_iso),
            )
            msg = "已建笔记"
        return ToolResult(ok=True, data={"note_id": nid}, message=msg)


__all__ = [
    "AbandonTaskArgs",
    "AbandonTaskTool",
    "CheckinOccurrenceArgs",
    "CheckinOccurrenceTool",
    "CompleteTaskArgs",
    "CompleteTaskTool",
    "CreateTaskArgs",
    "CreateTaskTool",
    "RescheduleTaskArgs",
    "RescheduleTaskTool",
    "UpdateTaskArgs",
    "UpdateTaskTool",
    "UpsertNoteArgs",
    "UpsertNoteTool",
    "UpsertProjectArgs",
    "UpsertProjectTool",
]
