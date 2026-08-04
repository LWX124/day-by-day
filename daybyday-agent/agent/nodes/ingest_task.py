"""ingest_task 节点：从用户输入抽取任务结构 → 落库 → 回执。

design.md §6.1 + ADR-0003：LLM 在写入侧把模糊自然语言推断成结构化字段
（schedule 类型、due、weight），物化落库；此后判定全读字段。

两条路径：
- 有 key：调 LLM 抽 Schedule + Weight + due_at（结构化输出）。本里程碑先简化——
  用 prompt 让 LLM 回 JSON，无 key 时回退到规则。完整 `with_structured_output`
  与置信度在后续里程碑补。
- 无 key：规则降级——从文本里识别时间词推 due_at，schedule 默认 deadline（若有
  due）否则 one_shot，weight 默认 M。

落库走 store.events.append(TaskCreated) + projections.rebuild_all。
回执走 PetCommandBus.push(Bubble("记下了：..."))。
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage

from agent.nodes.classify import _last_human_text  # noqa: PLC2701 — 同包内部复用
from api.commands import Bubble
from core.schedule import Schedule, ScheduleKind, Weight
from store import events as event_store
from store.projections import rebuild_all

if TYPE_CHECKING:
    from agent.providers import LLMRouter
    from api.commands import PetCommandBus

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


def _gen_task_id() -> str:
    import secrets

    return f"task_{int(_now().timestamp())}_{secrets.token_hex(4)}"


# ---- 规则降级抽取 ----

_WEEKDAY_MAP = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}


def _next_weekday(today: date, target: int) -> date:
    """从今天算下一个目标星期几的日期。today 已是本周该日则取下周。"""
    delta = (target - today.weekday()) % 7
    if delta == 0:
        delta = 7
    return today + timedelta(days=delta)


def _parse_due_from_text(text: str, now: datetime) -> datetime | None:
    """从中文文本里识别截止时间。覆盖验收用例"下周三前"。

    识别范围有限，够降级路径用——真实抽取由 LLM 负责。
    """
    today = now.date()
    # "下周三前" / "下周五前"
    m = re.search(r"下周([一二三四五六日天])", text)
    if m:
        wd = _WEEKDAY_MAP[m.group(1)]
        # 下周X = 本周的X + 7 天。先取本周X，再加7。
        this_week_x = _next_weekday(today, wd)
        # _next_weekday 在今天就是该日时返回 +7，否则返回最近一个。我们要"下周"，
        # 所以统一在本周X基础上再 +7？不——"下周三"通常指下一个到来的周三之后
        # 的那个周三。简化：取本周X（若已过则下周X），再 +7 保证是"下周"。
        # 但若今天周三，本周X=今天+7=下周三，正确。若今天周一，本周三=本周三，
        # 再 +7 = 下周三，也正确（"下周三"指下个周三）。
        # 综上：直接 _next_weekday 给出的是"最近一个未来X"，要"下周X"就 +7。
        due_date = this_week_x + timedelta(days=7)
        return datetime(due_date.year, due_date.month, due_date.day, 23, 59, tzinfo=UTC)
    # "这周三" / "本周三"
    m = re.search(r"(?:这|本)周([一二三四五六日天])", text)
    if m:
        wd = _WEEKDAY_MAP[m.group(1)]
        due_date = _next_weekday(today, wd)
        return datetime(due_date.year, due_date.month, due_date.day, 23, 59, tzinfo=UTC)
    # "明天"
    if "明天" in text:
        d = today + timedelta(days=1)
        return datetime(d.year, d.month, d.day, 23, 59, tzinfo=UTC)
    # "后天"
    if "后天" in text:
        d = today + timedelta(days=2)
        return datetime(d.year, d.month, d.day, 23, 59, tzinfo=UTC)
    # "今天"
    if "今天" in text:
        return datetime(today.year, today.month, today.day, 23, 59, tzinfo=UTC)
    return None


def _rule_extract(text: str, now: datetime) -> dict[str, Any]:
    """规则降级抽取。返回 TaskCreated payload 所需字段。"""
    due_at = _parse_due_from_text(text, now)
    schedule_kind = ScheduleKind.DEADLINE if due_at is not None else ScheduleKind.ONE_SHOT
    # 标题：取冒号后的部分，否则整句。
    title = text
    if "：" in text:
        title = text.split("：", 1)[1].strip()
    elif ":" in text:
        title = text.split(":", 1)[1].strip()
    title = title or text
    return {
        "title": title[:120],
        "schedule_kind": schedule_kind.value,
        "due_at": due_at.isoformat() if due_at else None,
        "weight": Weight.M.value,
        "status": "pending",
        "inference": {"source": "rule", "confidence": 0.5},
    }


def _llm_extract(router: LLMRouter, text: str) -> dict[str, Any] | None:
    """LLM 抽取任务字段。返回 payload 或 None（失败/降级）。

    本里程碑简化：用 prompt 让 LLM 回 JSON 字符串。完整结构化输出 + 置信度
    在后续里程碑接 `with_structured_output`。
    """
    model = router.get_model()
    if model is None:
        return None
    prompt = (
        "从用户输入抽取任务字段，只回 JSON，字段：\n"
        '{"title": str, "schedule_kind": "one_shot|deadline|recurring|openended", '
        '"due_at": "ISO8601 or null", "weight": "S|M|L|XL"}\n'
        "title 是简短任务名。有明确截止时间用 deadline 并填 due_at；无截止用 one_shot。"
        "weight 按工作量估。只回 JSON，不要解释。\n\n"
        f"用户输入：{text}"
    )
    try:
        resp = router.chat([HumanMessage(prompt)])
    except Exception as e:  # noqa: BLE001 — LLM 异常不可穷举
        logger.warning("ingest llm extract failed, fallback to rule: %s", e)
        return None
    if resp is None:
        return None
    raw = str(resp.content).strip()
    # 容忍 LLM 回 ```json ... ``` 包裹。
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("ingest llm returned non-json, fallback to rule: %r", raw[:120])
        return None
    if not isinstance(data, dict) or "title" not in data:
        return None
    # 规整字段。
    kind_str = str(data.get("schedule_kind", "one_shot"))
    try:
        kind = ScheduleKind(kind_str)
    except ValueError:
        kind = ScheduleKind.ONE_SHOT
    weight_str = str(data.get("weight", "M")).upper()
    try:
        weight = Weight(weight_str)
    except ValueError:
        weight = Weight.M
    due_at = data.get("due_at")
    due_iso: str | None = None
    if isinstance(due_at, str) and due_at:
        due_iso = due_at
    # 校验 schedule 合法组合。
    sched = Schedule(kind=kind, due_at=datetime.fromisoformat(due_iso) if due_iso else None)
    try:
        sched.validate()
    except ValueError:
        # LLM 抽错组合，回退 one_shot 无 due。
        kind = ScheduleKind.ONE_SHOT
        due_iso = None
    return {
        "title": str(data["title"])[:120],
        "schedule_kind": kind.value,
        "due_at": due_iso,
        "weight": weight.value,
        "status": "pending",
        "inference": {"source": "llm", "confidence": 0.8},
    }


def _append_task_created(conn: sqlite3.Connection, task_id: str, payload: dict[str, Any]) -> int:
    """落库：append TaskCreated 事件 + 重建投影。返回事件 id。"""
    now_iso = _now().isoformat()
    eid = event_store.append(
        conn,
        event_store.TASK_CREATED,
        "agent",
        task_id=task_id,
        payload=payload,
        occurred_at=now_iso,
    )
    rebuild_all(conn)
    return eid


def make_ingest_task_node(
    router: LLMRouter, bus: PetCommandBus, conn: sqlite3.Connection
) -> Any:
    """构造 ingest_task 节点。router/bus/conn 闭包注入。"""

    def ingest_task_node(state: dict[str, Any]) -> dict[str, Any]:
        text = _last_human_text(state)
        now = _now()
        # 抽取：有 key 用 LLM，否则规则降级。
        payload = None
        if router.is_available:
            payload = _llm_extract(router, text)
        if payload is None:
            payload = _rule_extract(text, now)

        task_id = _gen_task_id()
        eid = _append_task_created(conn, task_id, payload)
        title = payload["title"]
        due = payload.get("due_at")
        receipt = f"记下了：{title}"
        if due:
            receipt += f"（截止 {due[:10]}）"
        bus.push(Bubble(text=receipt, ttl=6.0))
        logger.info(
            "actor=agent event=task_created task_id=%s kind=%s weight=%s",
            task_id,
            payload["schedule_kind"],
            payload["weight"],
        )
        scratch = dict(state.get("scratch") or {})
        scratch["last_task_id"] = task_id
        scratch["last_event_id"] = eid
        return {"scratch": scratch}

    return ingest_task_node


__all__ = ["make_ingest_task_node"]
