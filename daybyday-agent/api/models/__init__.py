"""API 请求/响应 Pydantic 模型。

与 design.md §3.1 领域模型对齐。这些是 HTTP 边界的 DTO，不直接等于 store/core
的内部类型——路由层负责在 DTO 与内部类型间转换。
"""

from __future__ import annotations

from api.models._base import (
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
    ScheduleKindStr,
    TaskOut,
    TodayViewOut,
    UpdateTaskRequest,
    WakeResponse,
    WeightStr,
)
from api.models.intent import (
    IntentAction,
    IntentParseResult,
    IntentRequest,
    IntentResponse,
    IntentResult,
    Message,
)
from core.schedule import ScheduleKind, Weight

__all__ = [
    # base
    "AbandonTaskRequest",
    "CheckinRequest",
    "CompleteTaskRequest",
    "ConfirmRequest",
    "ConfirmResponse",
    "CreateTaskRequest",
    "CreateTaskResponse",
    "DeadlineItemOut",
    "GenericOk",
    "OccurrenceOut",
    "RescheduleRequest",
    "ScheduleKind",
    "ScheduleKindStr",
    "TaskOut",
    "TodayViewOut",
    "UpdateTaskRequest",
    "WakeResponse",
    "Weight",
    "WeightStr",
    # intent
    "IntentAction",
    "IntentParseResult",
    "IntentRequest",
    "IntentResponse",
    "IntentResult",
    "Message",
]
