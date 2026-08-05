"""需确认级 Tools（design.md §6.2 表「需 UI 二次确认」级）。

不直接执行——`ToolRegistry.invoke` 对 confirm 级 Tool 永远走 pending 路径
（登记 pending_action + push RequestConfirm），不调 `execute`。真实执行入口是
`ToolRegistry.invoke_confirmed(action_id)`，仅供 confirm-action 任务调。

- `delete_task`：删任务（M4 才有真删语义；当前用 EventUndone 撤销最近 TaskCreated
  作为占位执行——但 confirm 级 Tool 在 pending 阶段不会执行，仅登记）。
- `gerrit_review_vote`：Gerrit 打分（+1/-1 等）。M4 接 SSH CLI。
- `gerrit_abandon`：abandon 一个 Gerrit change。M4 接 SSH CLI。
- `gerrit_rebase`：rebase 一个 Gerrit change。M4 接 SSH CLI。

execute 实现是「确认后真实执行」的逻辑；pending 阶段由 registry 兜住不调。
"""

from __future__ import annotations

from typing import Any

from agent.tools.registry import Tool, ToolArgs, ToolContext, ToolLevel, ToolResult
from store import events as event_store
from store.projections import rebuild_all

# ---- delete_task ----


class DeleteTaskArgs(ToolArgs):
    task_id: str


class DeleteTaskTool(Tool):
    name = "delete_task"
    level = ToolLevel.CONFIRM
    description = "删任务（需确认）。确认后执行真实删除。"
    args_model = DeleteTaskArgs

    def execute(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        """确认后执行：当前用「撤销该任务的 TaskCreated 事件」作为删除占位。

        M4 会换成软删/硬删语义（design.md 未定删任务的最终形态，本里程碑只
        保证 confirm 级不可绕过 + 确认后能执行）。
        """
        rows = ctx.conn.execute(
            "SELECT id FROM events WHERE task_id = ? AND kind = ? ORDER BY id ASC LIMIT 1",
            (args["task_id"], event_store.TASK_CREATED),
        ).fetchall()
        if not rows:
            return ToolResult(ok=False, message=f"task not found: {args['task_id']}")
        target_eid = int(rows[0]["id"])
        undo_id = event_store.undo(ctx.conn, target_eid, ctx.actor)
        rebuild_all(ctx.conn)
        return ToolResult(
            ok=True,
            data={"task_id": args["task_id"], "undone_event_id": target_eid},
            message=f"已删除任务：{args['task_id']}",
            event_id=undo_id,
        )


# ---- gerrit_review_vote ----


class GerritReviewVoteArgs(ToolArgs):
    change: str  # change number
    patchset: int
    label: str = "Code-Review"  # Code-Review | Verified
    score: int  # +1 | -1 | +2 | -2


class GerritReviewVoteTool(Tool):
    name = "gerrit_review_vote"
    level = ToolLevel.CONFIRM
    description = "Gerrit 打分（需确认）。M4 接 SSH CLI `gerrit review`。"
    args_model = GerritReviewVoteArgs

    def execute(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        # M4 才接真实 SSH CLI。当前返回占位成功（confirm 级不可绕过已由 registry 兜住）。
        return ToolResult(
            ok=True,
            data={"placeholder": True, **args},
            message=f"[占位] Gerrit 打分：{args['change']}/{args['patchset']} {args['label']} {args['score']:+d}",
        )


# ---- gerrit_abandon ----


class GerritAbandonArgs(ToolArgs):
    change: str
    message: str | None = None


class GerritAbandonTool(Tool):
    name = "gerrit_abandon"
    level = ToolLevel.CONFIRM
    description = "abandon 一个 Gerrit change（需确认）。M4 接 SSH CLI。"
    args_model = GerritAbandonArgs

    def execute(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        return ToolResult(
            ok=True,
            data={"placeholder": True, **args},
            message=f"[占位] Gerrit abandon：{args['change']}",
        )


# ---- gerrit_rebase ----


class GerritRebaseArgs(ToolArgs):
    change: str
    base: str | None = None  # 缺省 rebase 到 parent


class GerritRebaseTool(Tool):
    name = "gerrit_rebase"
    level = ToolLevel.CONFIRM
    description = "rebase 一个 Gerrit change（需确认）。M4 接 SSH CLI。"
    args_model = GerritRebaseArgs

    def execute(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        return ToolResult(
            ok=True,
            data={"placeholder": True, **args},
            message=f"[占位] Gerrit rebase：{args['change']}",
        )


__all__ = [
    "DeleteTaskArgs",
    "DeleteTaskTool",
    "GerritAbandonArgs",
    "GerritAbandonTool",
    "GerritRebaseArgs",
    "GerritRebaseTool",
    "GerritReviewVoteArgs",
    "GerritReviewVoteTool",
]
