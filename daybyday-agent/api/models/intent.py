"""意图解析模型（design.md §4.4）。

POST /intent 的 DTO 与内部结构。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class IntentAction(StrEnum):
    """意图执行动作类型。"""

    EXECUTE = "execute"  # 直接执行
    CONFIRM = "confirm"  # 需 UI 二次确认
    CLARIFY = "clarify"  # 追问用户


class Message(BaseModel):
    """对话上下文中的单条消息。"""

    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str
    timestamp: str  # ISO8601 with timezone


class IntentRequest(BaseModel):
    """POST /intent 请求。

    session_id：多轮对话标识，为空则后端新建。
    text：用户自然语言输入。
    context：对话历史（可选，后端也会根据 session_id 查）。
    """

    model_config = ConfigDict(extra="forbid")

    session_id: str | None = None
    text: str
    context: list[Message] | None = None


class IntentResult(BaseModel):
    """意图解析结果中的 tool 调用描述。"""

    model_config = ConfigDict(extra="forbid")

    tool_name: str
    args: dict[str, Any]


class IntentResponse(BaseModel):
    """POST /intent 响应。

    intent: 识别出的意图类型（如 create_task/query_tasks 等）。
    args: 提取的参数。
    confidence: 置信度 0-1。
    action: execute | confirm | clarify。
    message: 给用户看的回执/追问文本。
    result: execute 时返回 Tool 执行结果快照。
    pending_action_id: confirm 时返回待确认动作 ID。
    session_id: 对话 session 标识。
    """

    model_config = ConfigDict(extra="forbid")

    intent: str | None = None
    args: dict[str, Any] | None = None
    confidence: float = 0.0
    action: Literal["execute", "confirm", "clarify"] = "clarify"
    message: str
    result: dict[str, Any] | None = None
    pending_action_id: str | None = None
    session_id: str


class IntentParseResult(BaseModel):
    """LLM 解析输出的结构化 Schema。

    Pydantic model 用于 with_structured_output 绑定。
    """

    model_config = ConfigDict(extra="forbid")

    intent: str  # create_task | query_tasks | update_task | delete_task | ...
    args: dict[str, Any]  # 提取的参数，与 Tool args_schema 对齐
    confidence: float  # 0-1
    missing_params: list[str] | None = None  # 缺失参数，用于追问


__all__ = [
    "IntentAction",
    "IntentParseResult",
    "IntentRequest",
    "IntentResponse",
    "IntentResult",
    "Message",
]
