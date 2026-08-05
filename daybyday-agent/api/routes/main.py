"""FastAPI 路由：/intent /today /tasks /confirm /wake /events(SSE) /health。

设计要点：
- 鉴权复用 api.app._token_dep（Bearer token，token 由 create_app(token=...) 注入到
  app.state，不读环境变量——对应 PRD「不进环境变量」）。
- 只 bind 127.0.0.1 由 uvicorn 启动参数控制（见 __main__.py），不在路由里管。
- 错误响应用 common.errors 的统一格式 {error, message, detail}。
- 写操作走 store.events.append + projections.rebuild_all（M0 手工 CRUD）。
  投影重建是 M0 的简化策略：每次写后全量重建，简单且正确；M2 再优化为增量。
- core/today_view 接收内存数据 + now，路由层从 store 取投影转成 core 视图类型。
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import UTC, date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sse_starlette.event import ServerSentEvent
from sse_starlette.sse import EventSourceResponse

from api.commands import PetCommandBus, serialize
from api.models import (
    AbandonTaskRequest,
    CheckinRequest,
    CompleteTaskRequest,
    ConfirmRequest,
    ConfirmResponse,
    CreateTaskRequest,
    CreateTaskResponse,
    DeadlineItemOut,
    GenericOk,
    OccurrenceOut,
    RescheduleRequest,
    ScheduleKind,
    TaskOut,
    TodayViewOut,
    UpdateTaskRequest,
    WakeResponse,
    Weight,
)
from api.routes.intent import router as intent_router
from common.errors import DayByDayError, UserError, error_payload, http_status
from core.schedule import RecurTarget
from core.schedule import Schedule as ScheduleObj
from core.views import OccurrenceView, TaskView, today_view
from store import events as event_store
from store.db import init_db
from store.projections import rebuild_all

# 模块级路由器。app.create_app 把它挂上去。
router = APIRouter()


# ---- 依赖 ----


def get_conn(request: Request) -> sqlite3.Connection:
    """从 app.state 取共享 DB 连接。create_app 启动时 init_db 注入。

    用依赖注入而非全局，便于测试覆盖（TestClient 可换连接）。
    """
    conn: sqlite3.Connection | None = getattr(request.app.state, "db_conn", None)
    if conn is None:
        raise HTTPException(status_code=503, detail="db not initialized")
    return conn


def get_bus(request: Request) -> PetCommandBus:
    """从 app.state 取 PetCommandBus 单例。"""
    bus: PetCommandBus | None = getattr(request.app.state, "command_bus", None)
    if bus is None:
        raise HTTPException(status_code=503, detail="command bus not initialized")
    return bus


# ---- helpers ----


def _now() -> datetime:
    return datetime.now(UTC)


def _err_response(err: DayByDayError) -> JSONResponse:
    return JSONResponse(status_code=http_status(err), content=error_payload(err))


def _to_task_out(row: sqlite3.Row) -> TaskOut:
    """tasks 投影行 → TaskOut。recur_target/inference 是 JSON 字符串。"""
    rt_raw = row["recur_target"]
    recur_target: dict[str, float | str] | None = None
    if rt_raw:
        try:
            recur_target = json.loads(rt_raw)
        except (json.JSONDecodeError, TypeError):
            recur_target = None
    due_raw = row["due_at"]
    due_at: datetime | None = None
    if due_raw:
        try:
            due_at = datetime.fromisoformat(due_raw)
        except ValueError:
            due_at = None
    last_act_raw = row["last_activity_at"]
    last_activity_at: datetime | None = None
    if last_act_raw:
        try:
            last_activity_at = datetime.fromisoformat(last_act_raw)
        except ValueError:
            last_activity_at = None
    return TaskOut(
        id=row["id"],
        title=row["title"],
        detail=row["detail"],
        schedule_kind=row["schedule_kind"],
        due_at=due_at,
        recur_rule=row["recur_rule"],
        recur_target=recur_target,
        weight=row["weight"],
        status=row["status"],
        project_id=row["project_id"],
        nag_count=row["nag_count"],
        reschedule_count=row["reschedule_count"],
        last_activity_at=last_activity_at,
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _task_view_from_row(row: sqlite3.Row) -> TaskView:
    """tasks 投影行 → core.views.TaskView（供 today_view 用）。"""
    due_raw = row["due_at"]
    due_at: datetime | None = None
    if due_raw:
        try:
            due_at = datetime.fromisoformat(due_raw)
        except ValueError:
            due_at = None
    last_act_raw = row["last_activity_at"]
    last_activity_at: datetime | None = None
    if last_act_raw:
        try:
            last_activity_at = datetime.fromisoformat(last_act_raw)
        except ValueError:
            last_activity_at = None
    return TaskView(
        id=row["id"],
        title=row["title"],
        schedule_kind=ScheduleKind(row["schedule_kind"]),
        weight=Weight(row["weight"]),
        status=row["status"],
        due_at=due_at,
        last_activity_at=last_activity_at,
    )


def _occurrence_out_from_row(row: sqlite3.Row) -> OccurrenceOut:
    return OccurrenceOut(
        task_id=row["task_id"],
        occurrence_date=date.fromisoformat(row["occurrence_date"]),
        target_amount=row["target_amount"],
        done_amount=row["done_amount"],
        status=row["status"],
        note=row["note"],
    )


def _occurrence_view_from_row(row: sqlite3.Row) -> OccurrenceView:
    return OccurrenceView(
        task_id=row["task_id"],
        occurrence_date=date.fromisoformat(row["occurrence_date"]),
        target_amount=row["target_amount"],
        done_amount=row["done_amount"],
        status=row["status"],
    )


def _build_schedule(req: CreateTaskRequest) -> ScheduleObj:
    """从请求构造 Schedule 并校验非法组合。非法抛 UserError。"""
    recur_target: RecurTarget | None = None
    if req.recur_target is not None:
        rt = req.recur_target
        amount = rt.get("amount")
        unit = rt.get("unit")
        if amount is None or unit is None:
            raise UserError("recur_target 需要 amount 与 unit", detail=rt)
        recur_target = RecurTarget(amount=float(amount), unit=str(unit))
    sched = ScheduleObj(
        kind=ScheduleKind(req.schedule_kind),
        due_at=req.due_at,
        recur_rule=req.recur_rule,
        recur_target=recur_target,
    )
    try:
        sched.validate()
    except ValueError as e:
        raise UserError(str(e)) from e
    return sched


def _gen_task_id() -> str:
    """生成任务 id。M0 用时间戳+随机，足够唯一。"""
    import secrets

    return f"task_{int(_now().timestamp())}_{secrets.token_hex(4)}"


# ---- 端点 ----


@router.get("/today")
async def get_today(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
) -> TodayViewOut:
    """今日视图。从投影表取数据，转 core 视图类型，调 today_view。"""
    now = _now()
    today = now.date()
    # 取全部非 done/abandoned 的任务 + 全部 occurrences。
    task_rows = conn.execute(
        "SELECT * FROM tasks WHERE status NOT IN ('done', 'abandoned') ORDER BY created_at"
    ).fetchall()
    occ_rows = conn.execute("SELECT * FROM occurrences").fetchall()
    tasks = [_task_view_from_row(r) for r in task_rows]
    occs = [_occurrence_view_from_row(r) for r in occ_rows]
    view = today_view(tasks, occs, now, today)

    # 转 Out 模型。deadlines/in_progress 里的 task 需要回查完整行（TaskView 字段不全）。
    task_by_id = {r["id"]: r for r in conn.execute("SELECT * FROM tasks").fetchall()}
    deadline_out: list[DeadlineItemOut] = []
    for d in view.deadlines:
        row = task_by_id.get(d.task.id)
        if row is None:
            continue
        deadline_out.append(
            DeadlineItemOut(
                task=_to_task_out(row),
                days_until_due=d.days_until_due,
                in_window=d.in_window,
            )
        )
    in_progress_out = [_to_task_out(task_by_id[t.id]) for t in view.in_progress if t.id in task_by_id]
    recurring_out = [
        _occurrence_out_from_row(
            conn.execute(
                "SELECT * FROM occurrences WHERE task_id = ? AND occurrence_date = ?",
                (o.task_id, o.occurrence_date.isoformat()),
            ).fetchone()
        )
        for o in view.recurring_today
    ]
    # 上面查 None 的兜底（理论上不会，occurrences 行存在才进 recurring_today）。
    recurring_out = [r for r in recurring_out if r is not None]
    return TodayViewOut(
        recurring_today=recurring_out,
        deadlines=deadline_out,
        in_progress=in_progress_out,
        today=today,
    )


def _handle_create(conn: sqlite3.Connection, req: CreateTaskRequest) -> CreateTaskResponse:
    sched = _build_schedule(req)
    task_id = _gen_task_id()
    now_iso = _now().isoformat()
    payload: dict[str, Any] = {
        "title": req.title,
        "detail": req.detail,
        "schedule_kind": sched.kind.value,
        "weight": req.weight,
        "status": "pending",
    }
    if sched.due_at is not None:
        payload["due_at"] = sched.due_at.isoformat()
    if sched.recur_rule is not None:
        payload["recur_rule"] = sched.recur_rule
    if sched.recur_target is not None:
        payload["recur_target"] = {"amount": sched.recur_target.amount, "unit": sched.recur_target.unit}
    if req.project_id is not None:
        payload["project_id"] = req.project_id
    payload["inference"] = {"source": "manual", "confidence": 1.0}
    eid = event_store.append(
        conn, event_store.TASK_CREATED, "user", task_id=task_id, payload=payload, occurred_at=now_iso
    )
    rebuild_all(conn)
    return CreateTaskResponse(task_id=task_id, event_id=eid)


def _handle_update(conn: sqlite3.Connection, req: UpdateTaskRequest) -> GenericOk:
    row = conn.execute("SELECT id FROM tasks WHERE id = ?", (req.task_id,)).fetchone()
    if row is None:
        raise UserError(f"task not found: {req.task_id}")
    payload: dict[str, Any] = {}
    if req.title is not None:
        payload["title"] = req.title
    if req.detail is not None:
        payload["detail"] = req.detail
    if req.weight is not None:
        payload["weight"] = req.weight
    if req.due_at is not None:
        payload["due_at"] = req.due_at.isoformat()
    if req.recur_rule is not None:
        payload["recur_rule"] = req.recur_rule
    if not payload:
        return GenericOk(ok=True, detail="nothing to update")
    event_store.append(
        conn, event_store.TASK_FIELDS_UPDATED, "user", task_id=req.task_id, payload=payload
    )
    rebuild_all(conn)
    return GenericOk(ok=True)


def _handle_complete(conn: sqlite3.Connection, req: CompleteTaskRequest) -> GenericOk:
    row = conn.execute("SELECT id FROM tasks WHERE id = ?", (req.task_id,)).fetchone()
    if row is None:
        raise UserError(f"task not found: {req.task_id}")
    event_store.append(
        conn, event_store.TASK_STATUS_CHANGED, "user", task_id=req.task_id, payload={"to": "done"}
    )
    rebuild_all(conn)
    return GenericOk(ok=True)


def _handle_abandon(conn: sqlite3.Connection, req: AbandonTaskRequest) -> GenericOk:
    row = conn.execute("SELECT id FROM tasks WHERE id = ?", (req.task_id,)).fetchone()
    if row is None:
        raise UserError(f"task not found: {req.task_id}")
    event_store.append(conn, event_store.TASK_ABANDONED, "user", task_id=req.task_id)
    rebuild_all(conn)
    return GenericOk(ok=True)


def _handle_checkin(conn: sqlite3.Connection, req: CheckinRequest) -> GenericOk:
    row = conn.execute("SELECT id, schedule_kind FROM tasks WHERE id = ?", (req.task_id,)).fetchone()
    if row is None:
        raise UserError(f"task not found: {req.task_id}")
    payload: dict[str, Any] = {
        "done_amount": req.done_amount,
    }
    if req.target_amount is not None:
        payload["target_amount"] = req.target_amount
    if req.note is not None:
        payload["note"] = req.note
    if req.force_done:
        payload["force_done"] = True
    event_store.append(
        conn,
        event_store.OCCURRENCE_CHECKED_IN,
        "user",
        task_id=req.task_id,
        occurrence_date=req.occurrence_date.isoformat(),
        payload=payload,
    )
    rebuild_all(conn)
    return GenericOk(ok=True)


def _handle_reschedule(conn: sqlite3.Connection, req: RescheduleRequest) -> GenericOk:
    row = conn.execute("SELECT id FROM tasks WHERE id = ?", (req.task_id,)).fetchone()
    if row is None:
        raise UserError(f"task not found: {req.task_id}")
    payload: dict[str, Any] = {}
    if req.due_at is not None:
        payload["due_at"] = req.due_at.isoformat()
    if req.recur_rule is not None:
        payload["recur_rule"] = req.recur_rule
    if not payload:
        return GenericOk(ok=True, detail="nothing to reschedule")
    event_store.append(conn, event_store.TASK_RESCHEDULED, "user", task_id=req.task_id, payload=payload)
    rebuild_all(conn)
    return GenericOk(ok=True)


@router.post("/tasks")
async def post_tasks(
    req: CreateTaskRequest
    | UpdateTaskRequest
    | CompleteTaskRequest
    | AbandonTaskRequest
    | CheckinRequest
    | RescheduleRequest,
    conn: sqlite3.Connection = Depends(get_conn),
) -> Any:
    """手工 CRUD。按 action 字段分发。写走 events.append + rebuild_all。"""
    try:
        if isinstance(req, CreateTaskRequest):
            return _handle_create(conn, req)
        if isinstance(req, UpdateTaskRequest):
            return _handle_update(conn, req)
        if isinstance(req, CompleteTaskRequest):
            return _handle_complete(conn, req)
        if isinstance(req, AbandonTaskRequest):
            return _handle_abandon(conn, req)
        if isinstance(req, CheckinRequest):
            return _handle_checkin(conn, req)
        if isinstance(req, RescheduleRequest):
            return _handle_reschedule(conn, req)
        raise UserError(f"unknown action: {req.action}")
    except DayByDayError as e:
        return _err_response(e)


# 注册 /intent 路由（由 api/routes/intent.py 实现）
router.include_router(intent_router)


@router.post("/confirm")
async def post_confirm(req: ConfirmRequest) -> ConfirmResponse:
    """占位：M1 接 confirm-action。M0 登记返回 accepted。"""
    return ConfirmResponse(ok=True, action_id=req.action_id, status="accepted")


@router.post("/wake")
async def post_wake() -> WakeResponse:
    """占位：M2 接 scheduler wake_catchup。M0 返回 ok。"""
    return WakeResponse(ok=True, detail="wake received (M0 placeholder)")


@router.get("/events")
async def sse_events(
    bus: PetCommandBus = Depends(get_bus),
) -> EventSourceResponse:
    """SSE 长连接：从 PetCommandBus 取命令推 data: <json>\\n\\n。

    每个连接独立订阅队列，互不抢。客户端断开时 sse_starlette 取消本生成器，
    finally 里取消订阅。不主动调 request.is_disconnected()——它在某些 ASGI 传输下
    行为不稳定，依赖 SSE 库的断连取消即可。
    """
    queue = bus.subscribe()

    async def event_generator() -> Any:
        # 客户端断开时 sse_starlette 会取消本生成器（finally 清理订阅）。
        # 不主动调 request.is_disconnected()——它在某些 ASGI 传输下行为不稳定，
        # 依赖 SSE 库的断连取消即可。
        try:
            while True:
                try:
                    cmd = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield ServerSentEvent(data=serialize(cmd), event="pet_command")
                except TimeoutError:
                    # 发心跳保活，防止中间代理掐连接。
                    yield ServerSentEvent(data="", event="ping")
        finally:
            bus.unsubscribe(queue)

    return EventSourceResponse(event_generator())


# ---- 启动辅助（供 app.py 调用）----


def init_app_state(app: Any) -> None:
    """初始化 app.state：DB 连接 + PetCommandBus 单例。

    放这里而非 app.py，是为了把"路由需要什么"的依赖收在路由模块里。
    create_app 调用本函数。幂等：重复调用不覆盖已初始化的状态（便于测试注入）。
    """
    if getattr(app.state, "db_conn", None) is not None:
        return
    conn = init_db()
    app.state.db_conn = conn
    app.state.command_bus = PetCommandBus()


__all__ = ["get_bus", "get_conn", "init_app_state", "router"]
