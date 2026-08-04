"""API 请求/响应 Pydantic 模型。

与 design.md §3.1 领域模型对齐。这些是 HTTP 边界的 DTO，不直接等于 store/core
的内部类型——路由层负责在 DTO 与内部类型间转换。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from core.schedule import ScheduleKind, Weight

ScheduleKindStr = Literal["one_shot", "deadline", "recurring", "openended"]
WeightStr = Literal["S", "M", "L", "XL"]
TaskStatus = Literal["pending", "in_progress", "done", "deferred", "abandoned"]
OccurrenceStatus = Literal["pending", "partial", "done", "skipped"]


# ---- 请求 ----


class CreateTaskRequest(BaseModel):
    """POST /tasks {action: create}。

    schedule 字段按 kind 携带独有字段（非法组合在写入层拒，见 core.schedule.validate）。
    """

    model_config = ConfigDict(extra="forbid")

    action: Literal["create"] = "create"
    title: str
    detail: str | None = None
    schedule_kind: ScheduleKindStr
    weight: WeightStr = "M"
    due_at: datetime | None = None  # 仅 deadline
    recur_rule: str | None = None  # 仅 recurring
    recur_target: dict[str, float | str] | None = None  # 仅 recurring: {amount, unit}
    project_id: str | None = None


class UpdateTaskRequest(BaseModel):
    """POST /tasks {action: update}。可改 title/detail/weight/due_at/recur_rule。"""

    model_config = ConfigDict(extra="forbid")

    action: Literal["update"] = "update"
    task_id: str
    title: str | None = None
    detail: str | None = None
    weight: WeightStr | None = None
    due_at: datetime | None = None
    recur_rule: str | None = None


class CompleteTaskRequest(BaseModel):
    """POST /tasks {action: complete}。状态转 done。"""

    model_config = ConfigDict(extra="forbid")

    action: Literal["complete"] = "complete"
    task_id: str


class AbandonTaskRequest(BaseModel):
    """POST /tasks {action: abandon}。状态转 abandoned。"""

    model_config = ConfigDict(extra="forbid")

    action: Literal["abandon"] = "abandon"
    task_id: str


class CheckinRequest(BaseModel):
    """POST /tasks {action: checkin}。Recurring 当日打卡。"""

    model_config = ConfigDict(extra="forbid")

    action: Literal["checkin"] = "checkin"
    task_id: str
    occurrence_date: date
    done_amount: float = 0.0
    target_amount: float | None = None
    note: str | None = None
    force_done: bool = False


class RescheduleRequest(BaseModel):
    """POST /tasks {action: reschedule}。Re-decision 改期。"""

    model_config = ConfigDict(extra="forbid")

    action: Literal["reschedule"] = "reschedule"
    task_id: str
    due_at: datetime | None = None
    recur_rule: str | None = None


# action → 请求模型的联合，供路由分发（FastAPI 不直接用 Union 判别，
# 这里作为文档与测试用）。
TaskActionRequest = (
    CreateTaskRequest
    | UpdateTaskRequest
    | CompleteTaskRequest
    | AbandonTaskRequest
    | CheckinRequest
    | RescheduleRequest
)


class IntentRequest(BaseModel):
    """POST /intent {text}。M0 占位，M1 接 LangGraph。"""

    model_config = ConfigDict(extra="forbid")

    text: str


class ConfirmRequest(BaseModel):
    """POST /confirm {action_id}。二次确认回执。M0 占位。"""

    model_config = ConfigDict(extra="forbid")

    action_id: str


# ---- 响应 ----


class TaskOut(BaseModel):
    """任务投影的对外视图。"""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    detail: str | None = None
    schedule_kind: ScheduleKindStr
    due_at: datetime | None = None
    recur_rule: str | None = None
    recur_target: dict[str, float | str] | None = None
    weight: WeightStr
    status: TaskStatus
    project_id: str | None = None
    nag_count: int = 0
    reschedule_count: int = 0
    last_activity_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class OccurrenceOut(BaseModel):
    """Occurrence 投影的对外视图。"""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    occurrence_date: date
    target_amount: float | None = None
    done_amount: float = 0.0
    status: OccurrenceStatus
    note: str | None = None


class DeadlineItemOut(BaseModel):
    """催办区里的 deadline 项。"""

    model_config = ConfigDict(extra="forbid")

    task: TaskOut
    days_until_due: int
    in_window: bool


class TodayViewOut(BaseModel):
    """GET /today 响应：core.today_view 的序列化形式。"""

    model_config = ConfigDict(extra="forbid")

    recurring_today: list[OccurrenceOut] = Field(default_factory=list)
    deadlines: list[DeadlineItemOut] = Field(default_factory=list)
    in_progress: list[TaskOut] = Field(default_factory=list)
    today: date


class CreateTaskResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    event_id: int


class GenericOk(BaseModel):
    """通用成功响应。"""

    model_config = ConfigDict(extra="forbid")

    ok: bool = True
    detail: str | None = None


class IntentResponse(BaseModel):
    """POST /intent 响应。M0 占位：agent 未接入。"""

    model_config = ConfigDict(extra="forbid")

    ok: bool = True
    handled: bool = False
    message: str
    echo: str | None = None


class ConfirmResponse(BaseModel):
    """POST /confirm 响应。M0 占位：登记返回 accepted。"""

    model_config = ConfigDict(extra="forbid")

    ok: bool = True
    action_id: str
    status: Literal["accepted", "unknown", "expired"] = "accepted"


class WakeResponse(BaseModel):
    """POST /wake 响应。M0 占位。"""

    model_config = ConfigDict(extra="forbid")

    ok: bool = True
    detail: str | None = None


# 公开内部枚举别名，方便路由层 mypy 收窄。
__all__ = [
    "AbandonTaskRequest",
    "CheckinRequest",
    "CompleteTaskRequest",
    "ConfirmRequest",
    "ConfirmResponse",
    "CreateTaskRequest",
    "CreateTaskResponse",
    "DeadlineItemOut",
    "GenericOk",
    "IntentRequest",
    "IntentResponse",
    "OccurrenceOut",
    "OccurrenceStatus",
    "RescheduleRequest",
    "ScheduleKindStr",
    "TaskActionRequest",
    "TaskOut",
    "TaskStatus",
    "TodayViewOut",
    "UpdateTaskRequest",
    "WakeResponse",
    "WeightStr",
    # re-export 枚举类型供路由层引用（保持 import 路径稳定）
    "ScheduleKind",
    "Weight",
]
