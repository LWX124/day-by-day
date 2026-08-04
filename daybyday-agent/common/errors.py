"""错误类型与统一 API 错误响应。

按 spec/backend/error-handling.md：
- UserError：用户输入/配置问题 → 400
- ProviderUnavailable：LLM provider 全部失败 → 503
- CollectorError：git/Gerrit 采集失败 → 记日志，不阻断（evidence 缺失）
- InvariantError：内部不变式违反 → 500，快速失败

core/ 不抛业务异常（纯函数域）。本模块被 api/agent/collectors/scheduler 使用，
core 不 import 本模块——core 的非法 schedule 组合在写入层由调用方转 UserError。

统一 API JSON 响应格式：
    {"error": "<machine_code>", "message": "<human readable>", "detail": null|object}
"""

from __future__ import annotations

from typing import Any


class DayByDayError(Exception):
    """基类。所有自定义错误继承自此。"""


class UserError(DayByDayError):
    """用户输入或配置问题。返回 4xx，气泡提示用户。

    例：非法 schedule 组合（recurring 带 due）、找不到 Project。
    """

    def __init__(self, message: str, detail: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


class ProviderUnavailable(DayByDayError):
    """LLM provider 全部失败。触发降级模式（ADR-0003），不崩。返回 503。"""

    def __init__(self, message: str, detail: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


class CollectorError(DayByDayError):
    """git/Gerrit 采集失败（断内网、权限）。记日志，evidence 缺失，不阻断复盘。"""

    def __init__(self, message: str, detail: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


class InvariantError(DayByDayError):
    """内部不变式违反（如投影与事件流对不上）。快速失败，记 error 日志。返回 500。"""

    def __init__(self, message: str, detail: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


# 错误类型 → (error_code, http_status)
_ERROR_STATUS: dict[type[DayByDayError], tuple[str, int]] = {
    UserError: ("user_error", 400),
    ProviderUnavailable: ("provider_unavailable", 503),
    CollectorError: ("collector_error", 500),
    InvariantError: ("invariant_error", 500),
}


def error_payload(err: DayByDayError) -> dict[str, Any]:
    """构造统一 JSON 错误响应体。"""
    code = "internal_error"
    for cls, (c, _) in _ERROR_STATUS.items():
        if isinstance(err, cls):
            code = c
            break
    return {"error": code, "message": err.message, "detail": err.detail}


def http_status(err: DayByDayError) -> int:
    """错误类型对应的 HTTP 状态码。未匹配的子类返回 500。"""
    for cls, (_, status) in _ERROR_STATUS.items():
        if isinstance(err, cls):
            return status
    return 500


__all__ = [
    "CollectorError",
    "DayByDayError",
    "InvariantError",
    "ProviderUnavailable",
    "UserError",
    "error_payload",
    "http_status",
]
