"""Tool 注册表与授权分级（ADR-0004 核心框架）。

三条界线（design.md §6.2 表）：
- `read`：读级，自由调用。接 core 纯函数或投影查询，不落库。
- `write`：常规写，直接执行 + 回执 + 可撤销。封装 store.events.append +
  projections.rebuild_all，返回 event_id（撤销走 events.undo）。
- `confirm`：需 UI 二次确认。**registry 调度时 confirm 级 Tool 不执行真实逻辑**，
  只登记 pending_action + push RequestConfirm PetCommand。真实执行等
  `POST /confirm`（M1 下一个任务 confirm-action）。

Tool schema 用 pydantic 自动生成：每个 Tool 声明一个 `ArgsModel`（pydantic
BaseModel 子类），registry 暴露 `args_schema()` 供 agent 节点 / langchain
`bind_tools` 使用。

ADR-0004 关键约束：confirm 级 Tool 在代码层不可绕过——`ToolRegistry.invoke`
对 confirm 级 Tool 永远走"登记 + 推 confirm"分支，不调 Tool 的 `execute`。
真实执行入口是 `ToolRegistry.invoke_confirmed(action_id)`，仅供 confirm-action
任务调用。
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

if TYPE_CHECKING:
    from api.commands import PetCommandBus

logger = logging.getLogger(__name__)

# pending_action 默认超时（design.md §6.2：超时默认 5 分钟自动作废）。
DEFAULT_PENDING_ACTION_TTL = timedelta(minutes=5)


class ToolLevel(StrEnum):
    """授权级别（ADR-0004 三级）。"""

    READ = "read"
    WRITE = "write"
    CONFIRM = "confirm"


class ToolArgs(BaseModel):
    """所有 Tool 参数模型的基类。

    子类用 pydantic 字段声明参数，registry 据此自动生成 schema
    （`model_json_schema()`）。`extra="forbid"` 防止 agent 传多余字段。
    """

    model_config = {"extra": "forbid"}


@dataclass(frozen=True)
class ToolResult:
    """Tool 执行结果。

    - `ok`：是否成功。
    - `data`：返回数据（read 级是查询结果，write 级含 event_id）。
    - `message`：给人看的回执一行（write 级回执）。
    - `event_id`：write 级返回新事件 id（可撤销）。confirm 级在 pending 阶段为 None，
      真实执行后才有值。
    - `pending_action_id`：仅 confirm 级 pending 阶段返回，供 confirm-action 查找。
    """

    ok: bool
    data: Any = None
    message: str | None = None
    event_id: int | None = None
    pending_action_id: str | None = None


class Tool:
    """Tool 基类。子类声明 `name` / `level` / `ArgsModel` 并实现 `execute`。

    `execute(ctx, args)` 接 `ToolContext`（含 conn/bus/now 等依赖注入）与已校验的
    args dict。返回 `ToolResult`。

    confirm 级 Tool 的 `execute` 只在 `invoke_confirmed` 路径下被调用——
    `ToolRegistry.invoke` 不会调它，因此"confirm 级不可绕过"在 registry 层兜住。
    """

    name: str
    level: ToolLevel
    description: str
    args_model: type[ToolArgs]

    def execute(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        raise NotImplementedError

    def args_schema(self) -> dict[str, Any]:
        """pydantic 自动生成的 JSON schema。供 agent 节点 / bind_tools 用。"""
        return self.args_model.model_json_schema()


@dataclass
class ToolContext:
    """Tool 执行上下文：依赖注入。

    - `conn`：sqlite 连接（write 级落库、read 级查投影）。
    - `bus`：PetCommandBus（confirm 级 push RequestConfirm；write 级可选 push 回执气泡）。
    - `actor`：事件 actor 字段（user / agent / scanner / scheduler）。
    - `now`：当前时间（不读系统时钟，由调用方传入；缺省取 datetime.now(UTC)）。
    """

    conn: Any  # sqlite3.Connection，用 Any 避免 agent 顶层 import sqlite3 的循环
    bus: PetCommandBus | None = None
    actor: str = "agent"
    now: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class PendingAction:
    """需确认动作的登记项。

    - `action_id`：唯一 id，`POST /confirm {action_id}` 据此查找。
    - `tool_name`：要执行的 confirm 级 Tool 名。
    - `args`：已校验的参数（待执行时传给 Tool.execute）。
    - `created_at` / `expires_at`：TTL，超时作废（design.md §6.2 默认 5 分钟）。
    - `status`：pending | confirmed | expired | executed。
    """

    action_id: str
    tool_name: str
    title: str
    detail: str | None
    args: dict[str, Any]
    created_at: datetime
    expires_at: datetime
    status: str = "pending"


class PendingActionStore:
    """pending_action 内存存储 + TTL 过期。

    M1 内存即可（进程内 confirm-action 任务会查同一实例）。若需跨进程持久化，
    后续任务改落库（design.md 未规定持久化，ADR-0004 只要求"登记 + 推 confirm"）。

    `expired()` 标记超时项为 expired（不物理删除，便于审计/测试断言）。
    `get_valid` 取未过期且未确认的项；过期项返回 None。
    """

    def __init__(self, ttl: timedelta = DEFAULT_PENDING_ACTION_TTL) -> None:
        self._ttl = ttl
        self._actions: dict[str, PendingAction] = {}

    def register(
        self,
        tool_name: str,
        *,
        title: str,
        detail: str | None,
        args: dict[str, Any],
        now: datetime | None = None,
    ) -> PendingAction:
        n = now or datetime.now(UTC)
        action_id = f"pa_{int(n.timestamp())}_{secrets.token_hex(4)}"
        pa = PendingAction(
            action_id=action_id,
            tool_name=tool_name,
            title=title,
            detail=detail,
            args=args,
            created_at=n,
            expires_at=n + self._ttl,
        )
        self._actions[action_id] = pa
        return pa

    def get(self, action_id: str) -> PendingAction | None:
        return self._actions.get(action_id)

    def get_valid(self, action_id: str, now: datetime | None = None) -> PendingAction | None:
        """取未过期、未确认/执行的项。过期返回 None 并标记 expired。"""
        pa = self._actions.get(action_id)
        if pa is None:
            return None
        n = now or datetime.now(UTC)
        if pa.status != "pending":
            return None
        if n > pa.expires_at:
            pa.status = "expired"
            return None
        return pa

    def mark(self, action_id: str, status: str) -> None:
        pa = self._actions.get(action_id)
        if pa is not None:
            pa.status = status

    def expire_all(self, now: datetime | None = None) -> int:
        """把所有超时 pending 项标记 expired。返回标记数。"""
        n = now or datetime.now(UTC)
        cnt = 0
        for pa in self._actions.values():
            if pa.status == "pending" and n > pa.expires_at:
                pa.status = "expired"
                cnt += 1
        return cnt

    def all(self) -> list[PendingAction]:
        return list(self._actions.values())


class ToolRegistry:
    """Tool 注册表 + 授权分级调度。

    用法：
        reg = ToolRegistry()
        reg.register(ListTasksTool())
        ...
        result = reg.invoke("list_tasks", ctx, {"status": "pending"})

    授权分级（ADR-0004）：
    - read / write 级：调 `Tool.execute` 直接执行。
    - confirm 级：**不调 execute**，只登记 pending_action + push RequestConfirm。
      真实执行走 `invoke_confirmed(action_id)`（仅 confirm-action 任务调）。
    """

    def __init__(
        self,
        bus: PetCommandBus | None = None,
        pending_store: PendingActionStore | None = None,
    ) -> None:
        self._tools: dict[str, Tool] = {}
        self._bus = bus
        self._pending = pending_store or PendingActionStore()

    @property
    def pending_store(self) -> PendingActionStore:
        return self._pending

    def set_bus(self, bus: PetCommandBus) -> None:
        """后置注入 bus（registry 可先于 bus 构造）。"""
        self._bus = bus

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name!r}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def by_level(self, level: ToolLevel) -> list[Tool]:
        return [t for t in self._tools.values() if t.level is level]

    def args_schema(self, name: str) -> dict[str, Any] | None:
        t = self._tools.get(name)
        return None if t is None else t.args_schema()

    def validate_args(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """用 Tool 的 pydantic 模型校验 args。非法字段抛 ValidationError。"""
        t = self._tools.get(name)
        if t is None:
            raise KeyError(f"unknown tool: {name!r}")
        model = t.args_model.model_validate(args)
        return model.model_dump()

    def invoke(
        self, name: str, ctx: ToolContext, args: dict[str, Any] | None = None
    ) -> ToolResult:
        """按授权级别调度 Tool。

        - read / write：直接执行。
        - confirm：登记 pending_action + push RequestConfirm，不执行真实逻辑。
        """
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(ok=False, message=f"unknown tool: {name}")
        try:
            validated = self.validate_args(name, args or {})
        except Exception as e:  # noqa: BLE001 — pydantic ValidationError 等
            return ToolResult(ok=False, message=f"invalid args: {e}")

        if tool.level is ToolLevel.CONFIRM:
            return self._invoke_confirm_pending(tool, ctx, validated)
        try:
            return tool.execute(ctx, validated)
        except Exception as e:  # noqa: BLE001 — 写入层校验/落库异常
            logger.warning("tool %s execute failed: %s", name, e)
            return ToolResult(ok=False, message=f"execute failed: {e}")

    def _invoke_confirm_pending(
        self, tool: Tool, ctx: ToolContext, args: dict[str, Any]
    ) -> ToolResult:
        """confirm 级 Tool 的 pending 路径：登记 + 推 RequestConfirm，不执行。"""
        title = f"确认执行：{tool.name}"
        detail = tool.description
        pa = self._pending.register(
            tool.name, title=title, detail=detail, args=args, now=ctx.now
        )
        if self._bus is not None:
            from api.commands import RequestConfirm

            self._bus.push(
                RequestConfirm(action_id=pa.action_id, title=title, detail=detail)
            )
        else:
            logger.warning("confirm tool %s invoked without bus; pending only", tool.name)
        logger.info(
            "tool=%s level=confirm action=pending action_id=%s", tool.name, pa.action_id
        )
        return ToolResult(
            ok=True,
            message=f"已登记待确认：{tool.name}（action_id={pa.action_id}）",
            pending_action_id=pa.action_id,
        )

    def invoke_confirmed(
        self, action_id: str, ctx: ToolContext
    ) -> ToolResult:
        """confirm-action 任务入口：校验 pending_action 后执行真实 Tool。

        - action_id 不存在 / 已过期 / 已确认 → 失败。
        - 校验通过 → 标记 confirmed → 调 Tool.execute → 标记 executed。
        """
        pa = self._pending.get_valid(action_id, now=ctx.now)
        if pa is None:
            return ToolResult(ok=False, message=f"pending action not found or expired: {action_id}")
        tool = self._tools.get(pa.tool_name)
        if tool is None:
            self._pending.mark(action_id, "expired")
            return ToolResult(ok=False, message=f"tool gone: {pa.tool_name}")
        self._pending.mark(action_id, "confirmed")
        try:
            result = tool.execute(ctx, pa.args)
        except Exception as e:  # noqa: BLE001
            logger.exception("confirmed tool %s failed", pa.tool_name)
            return ToolResult(ok=False, message=f"execute failed: {e}")
        self._pending.mark(action_id, "executed")
        return result


def make_default_registry(
    bus: PetCommandBus | None = None,
    pending_store: PendingActionStore | None = None,
) -> ToolRegistry:
    """构造含全部读/常规写/需确认 Tool 的注册表。

    agent 节点 / api 路由共用同一实例。bus 后置注入也可（`registry.set_bus`）。
    """
    from agent.tools.confirm import (
        DeleteTaskTool,
        GerritAbandonTool,
        GerritRebaseTool,
        GerritReviewVoteTool,
    )
    from agent.tools.read import (
        ComputeStatsTool,
        GetProjectTool,
        GetTaskTool,
        ListTasksTool,
        QueryGerritChangesTool,
        QueryGitEvidenceTool,
        SearchNotesTool,
        TodayViewTool,
    )
    from agent.tools.write import (
        AbandonTaskTool,
        CheckinOccurrenceTool,
        CompleteTaskTool,
        CreateTaskTool,
        RescheduleTaskTool,
        UpdateTaskTool,
        UpsertNoteTool,
        UpsertProjectTool,
    )

    reg = ToolRegistry(bus=bus, pending_store=pending_store)
    # read
    for t in (
        ListTasksTool(),
        GetTaskTool(),
        TodayViewTool(),
        ComputeStatsTool(),
        QueryGitEvidenceTool(),
        QueryGerritChangesTool(),
        GetProjectTool(),
        SearchNotesTool(),
    ):
        reg.register(t)
    # write
    for t in (
        CreateTaskTool(),
        UpdateTaskTool(),
        CompleteTaskTool(),
        CheckinOccurrenceTool(),
        RescheduleTaskTool(),
        AbandonTaskTool(),
        UpsertProjectTool(),
        UpsertNoteTool(),
    ):
        reg.register(t)
    # confirm
    for t in (
        DeleteTaskTool(),
        GerritReviewVoteTool(),
        GerritAbandonTool(),
        GerritRebaseTool(),
    ):
        reg.register(t)
    return reg


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
