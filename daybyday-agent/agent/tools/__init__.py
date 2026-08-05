"""agent/tools：Tool 注册表与授权分级（ADR-0004）。

三级：read（自由调用）/ write（直接执行+可撤销）/ confirm（需 UI 二次确认）。
confirm 级 Tool 在 registry 层不可绕过——`invoke` 永远走 pending 路径，
真实执行走 `invoke_confirmed`。
"""

from agent.tools.registry import (
    DEFAULT_PENDING_ACTION_TTL,
    PendingAction,
    PendingActionStore,
    Tool,
    ToolArgs,
    ToolContext,
    ToolLevel,
    ToolRegistry,
    ToolResult,
    make_default_registry,
)

__all__ = [
    "DEFAULT_PENDING_ACTION_TTL",
    "PendingAction",
    "PendingActionStore",
    "Tool",
    "ToolArgs",
    "ToolContext",
    "ToolLevel",
    "ToolRegistry",
    "ToolResult",
    "make_default_registry",
]
