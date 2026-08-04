"""common/errors.py 测试。

锁死统一 API 错误响应格式（spec/backend/error-handling.md）：
    {"error": "<machine_code>", "message": "<human readable>", "detail": null|object}

并回归 mypy 曾误报的基类缺 message/detail 问题——error_payload 接收
DayByDayError 基类类型，必须能静态访问 .message/.detail。
"""

from __future__ import annotations

import pytest

from common.errors import (
    CollectorError,
    DayByDayError,
    InvariantError,
    ProviderUnavailable,
    UserError,
    error_payload,
    http_status,
)


@pytest.mark.parametrize(
    "exc, code, status",
    [
        (UserError("bad", detail={"f": 1}), "user_error", 400),
        (ProviderUnavailable("all failed"), "provider_unavailable", 503),
        (CollectorError("gerrit down"), "collector_error", 500),
        (InvariantError("proj mismatch"), "invariant_error", 500),
    ],
)
def test_error_payload_and_status(exc: DayByDayError, code: str, status: int) -> None:
    """每种错误类型 → 正确 error_code + http_status + 透传 message/detail。"""
    payload = error_payload(exc)
    assert payload["error"] == code
    assert payload["message"] == exc.message
    assert payload["detail"] == exc.detail
    assert http_status(exc) == status


def test_error_payload_default_detail_none() -> None:
    """未传 detail 时 detail=None（前端契约：字段恒在）。"""
    payload = error_payload(UserError("oops"))
    assert payload["detail"] is None


def test_base_class_attribute_access() -> None:
    """DayByDayError 基类类型变量能访问 message/detail（mypy 回归点）。"""
    err: DayByDayError = ProviderUnavailable("x", detail={"k": "v"})
    # 这两行若基类没声明字段，mypy 报 attr-defined
    assert err.message == "x"
    assert err.detail == {"k": "v"}
