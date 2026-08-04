"""freeform 节点：通用对话（占位）。

design.md §6.1：freeform 通用对话 + Note 读写。本里程碑 Note 读写占位（TODO）。

两条路径：
- 有 key：LLM 多轮对话。
- 无 key：回"agent 未接入"确定性提示。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from api.commands import Bubble

if TYPE_CHECKING:
    from agent.providers import LLMRouter
    from api.commands import PetCommandBus

logger = logging.getLogger(__name__)

_DEGRADED_REPLY = "agent 未接入（未配置 LLM key），仅支持建任务/查状态的关键词指令。"


def _llm_reply(router: LLMRouter, messages: list[Any]) -> str | None:
    """LLM 多轮。失败返回 None 让调用方回退。"""
    model = router.get_model()
    if model is None:
        return None
    try:
        resp = router.chat(messages)
    except Exception as e:  # noqa: BLE001 — LLM 异常不可穷举
        logger.warning("freeform llm failed, fallback to degraded: %s", e)
        return None
    if resp is None:
        return None
    return str(resp.content).strip() or None


def make_freeform_node(router: LLMRouter, bus: PetCommandBus) -> Any:
    """构造 freeform 节点。"""

    def freeform_node(state: dict[str, Any]) -> dict[str, Any]:
        messages = state.get("messages") or []
        reply = None
        if router.is_available:
            reply = _llm_reply(router, messages)
        if reply is None:
            reply = _DEGRADED_REPLY
        bus.push(Bubble(text=reply, ttl=6.0))
        logger.info("actor=agent event=freeform replied")
        scratch = dict(state.get("scratch") or {})
        scratch["last_reply"] = reply
        return {"scratch": scratch}

    return freeform_node


__all__ = ["make_freeform_node"]
