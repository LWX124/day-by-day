"""classify 节点：意图分类 → 路由。

读 state.messages 末尾用户输入，判断意图为 `ingest` / `query` / `freeform`，
写入 state.scratch["intent"]，供条件边分发。

两条路径（ADR-0003 降级）：
- 有 key：让 LLM 判断意图。结构化输出取 intent 枚举。
- 无 key：规则/关键词降级。含"建/做/完成/读"+时间词→ingest；
  含"怎么样/状态/进度"→query；其余→freeform。

降级规则要保证验收"建个任务：下周三前做完重构"在无 key 时也路由到 ingest。
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage

if TYPE_CHECKING:
    from agent.providers import LLMRouter

logger = logging.getLogger(__name__)

# 意图枚举值，与条件边路由表对齐。
INTENT_INGEST = "ingest"
INTENT_QUERY = "query"
INTENT_FREEFORM = "freeform"

VALID_INTENTS = frozenset({INTENT_INGEST, INTENT_QUERY, INTENT_FREEFORM})

# 降级规则的关键词。建/做/完成/读 + 时间词暗示"要建任务"。
# 时间词覆盖"下周三前/今天/明天/月底/这周"等。
_INGEST_ACTION_RE = re.compile(r"(建|做|完成|读|写|搞|弄|整理|推进|开始)")
_INGEST_TIME_RE = re.compile(r"(下周|本周|这周|今天|明天|后天|月底|周[一二三四五六日天]|前\b|之内|之前|以前)")
# 查询意图的关键词。
_QUERY_RE = re.compile(r"(怎么样|状态|进度|如何|怎样|情况|咋样|进度如何|做完了吗|完成了吗|还剩)")


def _last_human_text(state: dict[str, Any]) -> str:
    """取 state.messages 里最后一条 HumanMessage 的文本。"""
    messages = state.get("messages") or []
    for msg in reversed(messages):
        # langchain HumanMessage 或测试里塞的字符串都支持。
        if isinstance(msg, HumanMessage):
            return str(msg.content)
        if isinstance(msg, str):
            return msg
    return ""


def _rule_classify(text: str) -> str:
    """规则降级分类。

    优先级：ingest > query > freeform。ingest 同时要求动作词与时间词——
    纯"做重构"无时间词不一定是建任务（可能是查询"那个重构做怎么样了"），
    但"建个任务：下周三前做完重构"两者都有，命中 ingest。
    """
    if _INGEST_ACTION_RE.search(text) and _INGEST_TIME_RE.search(text):
        return INTENT_INGEST
    if _QUERY_RE.search(text):
        return INTENT_QUERY
    # 兜底：含"建/做"+冒号或"任务"也视作 ingest（"建个任务：..."）。
    if _INGEST_ACTION_RE.search(text) and ("任务" in text or "：" in text or ":" in text):
        return INTENT_INGEST
    return INTENT_FREEFORM


def _llm_classify(router: LLMRouter, text: str) -> str | None:
    """LLM 分类。失败/异常返回 None 让调用方回退到规则。"""
    model = router.get_model()
    if model is None:
        return None
    prompt = (
        "判断用户意图属于以下哪一类，只回一个词：\n"
        "- ingest：用户想新建/记录一个任务或计划\n"
        "- query：用户想查询某个任务/工作的状态或进度\n"
        "- freeform：其他闲聊或通用对话\n\n"
        f"用户输入：{text}\n意图："
    )
    try:
        resp = router.chat([HumanMessage(prompt)])
    except Exception as e:  # noqa: BLE001 — LLM 调用异常类型不可穷举
        logger.warning("classify llm failed, fallback to rule: %s", e)
        return None
    if resp is None:
        return None
    raw = str(resp.content).strip().lower()
    # 容忍 LLM 回完整句子，取首个匹配意图词。
    for intent in VALID_INTENTS:
        if intent in raw:
            return intent
    return None


def make_classify_node(router: LLMRouter) -> Any:
    """构造 classify 节点。router 闭包注入。

    节点函数签名 `(state) -> partial state`。返回 `{"scratch": {...}}`
    合并进 state——scratch 是 last-write-wins，故需保留既有 scratch 字段。
    """

    def classify_node(state: dict[str, Any]) -> dict[str, Any]:
        text = _last_human_text(state)
        intent: str | None = None
        if router.is_available:
            intent = _llm_classify(router, text)
        if intent not in VALID_INTENTS:
            intent = _rule_classify(text)
        scratch = dict(state.get("scratch") or {})
        scratch["intent"] = intent
        scratch["last_input"] = text
        logger.info("actor=agent event=classify intent=%s input=%r", intent, text[:80])
        return {"scratch": scratch}

    return classify_node


def route_after_classify(state: dict[str, Any]) -> str:
    """条件边路由函数。读 state.scratch["intent"] 返回下一节点名。

    用作 `add_conditional_edges("classify", route_after_classify, {...})`。
    """
    scratch = state.get("scratch") or {}
    intent = scratch.get("intent", INTENT_FREEFORM)
    if intent == INTENT_INGEST:
        return "ingest_task"
    if intent == INTENT_QUERY:
        return "query_status"
    return "freeform"


__all__ = [
    "INTENT_FREEFORM",
    "INTENT_INGEST",
    "INTENT_QUERY",
    "VALID_INTENTS",
    "make_classify_node",
    "route_after_classify",
]
