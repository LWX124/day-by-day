"""query_status 节点：取任务 + 占位 evidence → 总结成话 → 回执。

design.md §6.1：query_status 取任务 + 拉 Evidence → 总结。
本里程碑 evidence 采集器未接，用占位（空 evidence）。

两条路径：
- 有 key：LLM 把任务列表总结成自然语言。
- 无 key：模板拼接（确定性）。

回执走 PetCommandBus.push(Bubble(...))。
"""

from __future__ import annotations

import logging
import sqlite3
from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage

from api.commands import Bubble

if TYPE_CHECKING:
    from agent.providers import LLMRouter
    from api.commands import PetCommandBus

logger = logging.getLogger(__name__)


def _load_tasks_summary(conn: sqlite3.Connection) -> str:
    """从投影表取任务清单，拼成模板字符串供 LLM/模板用。"""
    rows = conn.execute(
        "SELECT id, title, schedule_kind, status, due_at, weight FROM tasks "
        "WHERE status NOT IN ('abandoned') ORDER BY created_at LIMIT 20"
    ).fetchall()
    if not rows:
        return "（暂无任务）"
    lines = []
    for r in rows:
        due = r["due_at"][:10] if r["due_at"] else "无"
        lines.append(
            f"- [{r['status']}] {r['title']}（{r['schedule_kind']}，{r['weight']}，due {due}）"
        )
    return "\n".join(lines)


def _template_summarize(tasks_text: str) -> str:
    """无 key 时模板拼接。"""
    return f"当前任务：\n{tasks_text}"


def _llm_summarize(router: LLMRouter, tasks_text: str, user_text: str) -> str | None:
    """LLM 总结。失败返回 None 让调用方回退模板。"""
    model = router.get_model()
    if model is None:
        return None
    prompt = (
        "你是日程助手。根据以下任务清单回答用户的查询，简洁自然，不要编造未列出的任务。\n"
        f"任务清单：\n{tasks_text}\n\n"
        f"用户问：{user_text}\n回答："
    )
    try:
        resp = router.chat([HumanMessage(prompt)])
    except Exception as e:  # noqa: BLE001 — LLM 异常不可穷举
        logger.warning("query_status llm failed, fallback to template: %s", e)
        return None
    if resp is None:
        return None
    return str(resp.content).strip() or None


def make_query_status_node(
    router: LLMRouter, bus: PetCommandBus, conn: sqlite3.Connection
) -> Any:
    """构造 query_status 节点。"""

    def query_status_node(state: dict[str, Any]) -> dict[str, Any]:
        # 取用户最后一句作为查询上下文。
        messages = state.get("messages") or []
        user_text = ""
        for m in reversed(messages):
            content = getattr(m, "content", m)
            if isinstance(content, str):
                user_text = content
                break
        tasks_text = _load_tasks_summary(conn)
        summary = None
        if router.is_available:
            summary = _llm_summarize(router, tasks_text, user_text)
        if summary is None:
            summary = _template_summarize(tasks_text)
        bus.push(Bubble(text=summary, ttl=8.0))
        logger.info("actor=agent event=query_status replied")
        scratch = dict(state.get("scratch") or {})
        scratch["last_reply"] = summary
        return {"scratch": scratch}

    return query_status_node


__all__ = ["make_query_status_node"]
