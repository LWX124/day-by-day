"""ingest_task 节点：从用户输入抽取任务结构 → 落库 → 回执。

design.md §6.1 + ADR-0003：LLM 在写入侧把模糊自然语言推断成结构化字段
（schedule 类型、due、weight），物化落库；此后判定全读字段。

三种语义（classify 路由到 ingest 后在此分流）：
1. 建任务：`extract()` 抽 TaskDraft。
   - 高置信字段直接落库（events.append TaskCreated，inference 存置信度+原始输入）
     + 一行回执气泡。
   - 低置信字段触发反问：push Bubble 带 quick_replies（不落库或落部分）。
   - recurring 任务建后补齐当日 occurrence（design.md §3.3）。
2. 完成任务：识别"那个重构做完了" → 匹配现有 in_progress/pending 任务 →
   events.append TaskStatusChanged(to=done)。
3. 改字段：识别"把 due 改到周五" → events.append TaskFieldsUpdated。
   改动本身是一条事件（ADR-0003：推断错了事后一句话可改）。

落库走 store.events.append + projections.rebuild_all。
回执走 PetCommandBus.push(Bubble(...))。
"""

from __future__ import annotations

import logging
import re
import sqlite3
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from agent.extraction import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    draft_to_task_created_payload,
    extract,
    extraction_source,
    low_confidence_fields,
)
from agent.nodes.classify import _last_human_text  # noqa: PLC2701 — 同包内部复用
from api.commands import Bubble
from common.errors import UserError
from core.occurrence import OccurrenceToCreate, RecurringTaskView, ensure_occurrences_up_to
from core.schedule import ScheduleKind
from store import events as event_store
from store.projections import rebuild_all

if TYPE_CHECKING:
    from agent.providers import LLMRouter
    from api.commands import PetCommandBus

logger = logging.getLogger(__name__)

# "做完了/完成了/搞定了" —— 完成意图关键词。
_DONE_KEYWORDS = ("做完了", "完成了", "搞定了", "搞完的", "做完", "完成", "搞定")
# "改 due/重量 到 X" —— 改字段意图关键词。
_UPDATE_KEYWORDS = ("改", "调整", "调到", "改为", "改成")


def _now() -> datetime:
    return datetime.now(UTC)


def _gen_task_id() -> str:
    import secrets

    return f"task_{int(_now().timestamp())}_{secrets.token_hex(4)}"


# ---- 完成意图：匹配现有任务标 done ----


def _is_done_intent(text: str) -> bool:
    return any(kw in text for kw in _DONE_KEYWORDS)


def _match_task_for_completion(conn: sqlite3.Connection, text: str) -> str | None:
    """从文本里匹配一个未完成任务，返回 task_id。None 表示无匹配。

    规则降级：取标题关键词与未完成任务标题做子串匹配，最近活跃优先。
    "那个重构做完了" → 匹配标题含"重构"的任务。
    """
    rows = conn.execute(
        "SELECT id, title FROM tasks WHERE status NOT IN ('done','abandoned') "
        "ORDER BY last_activity_at DESC LIMIT 50"
    ).fetchall()
    # 抽取文本里的关键词候选：去掉完成词与停用词后的剩余片段。
    cleaned = text
    for kw in _DONE_KEYWORDS + ("那个", "这个", "了", "的", "把", "给"):
        cleaned = cleaned.replace(kw, "")
    cleaned = cleaned.strip()
    if cleaned:
        for r in rows:
            title = r["title"] or ""
            if cleaned in title or title in cleaned:
                return str(r["id"])
    # 兜底：只有一个未完成任务时直接匹配。
    if len(rows) == 1:
        return str(rows[0]["id"])
    return None


def _handle_completion(
    conn: sqlite3.Connection, bus: PetCommandBus, text: str
) -> dict[str, Any] | None:
    """处理"做完了"意图。匹配到任务则 append TaskStatusChanged(to=done)。

    返回 scratch 更新或 None（不匹配，交回建任务流程）。
    """
    task_id = _match_task_for_completion(conn, text)
    if task_id is None:
        return None
    title_row = conn.execute("SELECT title FROM tasks WHERE id = ?", (task_id,)).fetchone()
    title = title_row["title"] if title_row else ""
    eid = event_store.append(
        conn,
        event_store.TASK_STATUS_CHANGED,
        "user",
        task_id=task_id,
        payload={"to": "done", "from_intent": text},
        occurred_at=_now().isoformat(),
    )
    rebuild_all(conn)
    bus.push(Bubble(text=f"标记完成：{title}", ttl=6.0))
    logger.info("actor=user event=task_completed task_id=%s", task_id)
    return {"last_task_id": task_id, "last_event_id": eid, "last_reply": f"标记完成：{title}"}


# ---- 改字段意图：append TaskFieldsUpdated ----


def _is_update_intent(text: str) -> bool:
    return any(kw in text for kw in _UPDATE_KEYWORDS)


_WEEKDAY_MAP = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}


def _parse_target_date(text: str, now: datetime) -> datetime | None:
    """从"改到周五"识别目标日期。"""
    today = now.date()
    m = re.search(r"周([一二三四五六日天])", text)
    if m:
        wd = _WEEKDAY_MAP[m.group(1)]
        delta = (wd - today.weekday()) % 7
        if delta == 0:
            delta = 7
        d = today + timedelta(days=delta)
        return datetime(d.year, d.month, d.day, 23, 59, tzinfo=UTC)
    if "周五" in text or "星期五" in text:
        delta = (4 - today.weekday()) % 7 or 7
        d = today + timedelta(days=delta)
        return datetime(d.year, d.month, d.day, 23, 59, tzinfo=UTC)
    return None


def _parse_weight(text: str) -> str | None:
    m = re.search(r"\b([SMLX][L]?)\b", text.upper())
    if m and m.group(1) in {"S", "M", "L", "XL"}:
        return m.group(1)
    return None


def _handle_update_fields(
    conn: sqlite3.Connection, bus: PetCommandBus, text: str, now: datetime
) -> dict[str, Any] | None:
    """处理"把 due 改到周五/把重量改成 L"意图。append TaskFieldsUpdated。

    匹配最近未完成任务。改动本身是一条事件（ADR-0003）。

    合法性维护（design.md §3.1：非法组合在写入层拒绝）：给非 deadline 任务加
    due_at 会产出非法组合（openended+due / one_shot+due / recurring+due）。
    此时一并把 schedule_kind 切到 deadline 并清掉 recurring 字段——既维持合法性，
    又支持"推断错了事后一句话改"（把 openended 任务改成 deadline）。
    """
    # 找目标任务：取最近未完成任务（规则降级，无 key 路径）。
    row = conn.execute(
        "SELECT id, schedule_kind FROM tasks WHERE status NOT IN ('done','abandoned') "
        "ORDER BY updated_at DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    task_id = row["id"]
    cur_kind = row["schedule_kind"]

    payload: dict[str, Any] = {}
    due = _parse_target_date(text, now)
    if ("due" in text.lower() or "截止" in text or "期限" in text) and due is not None:
        payload["due_at"] = due.isoformat()
        # 给非 deadline 任务加 due → 切到 deadline 维持合法性（清 recurring 字段）。
        if cur_kind != "deadline":
            payload["schedule_kind"] = "deadline"
            payload["recur_rule"] = None
            payload["recur_target"] = None
    weight = _parse_weight(text)
    if weight is not None and ("重量" in text or "weight" in text.lower() or "大小" in text):
        payload["weight"] = weight
    if not payload:
        return None  # 识别不出改什么字段，交回建任务流程

    eid = event_store.append(
        conn,
        event_store.TASK_FIELDS_UPDATED,
        "user",
        task_id=task_id,
        payload={**payload, "reason": text},
        occurred_at=now.isoformat(),
    )
    rebuild_all(conn)
    summary = "、".join(f"{k}={v}" for k, v in payload.items() if k != "reason")
    bus.push(Bubble(text=f"改好了：{summary}", ttl=6.0))
    logger.info("actor=user event=task_fields_updated task_id=%s fields=%s", task_id, list(payload))
    return {"last_task_id": task_id, "last_event_id": eid, "last_reply": f"改好了：{summary}"}


# ---- recurring 当日 occurrence 补齐 ----


def _ensure_today_occurrence(conn: sqlite3.Connection, task_id: str, today: date) -> None:
    """recurring 任务建后补齐当日 occurrence（design.md §3.3）。

    用 core.ensure_occurrences_up_to 算缺失，直接 INSERT occurrences 占位行。
    投影重建会从 events 重建 occurrences，但 TaskCreated 不产 occurrence 事件，
    故此处物理插入当日 occurrence 行（pending/done_amount=0）。
    """
    row = conn.execute(
        "SELECT recur_rule, recur_target, created_at FROM tasks WHERE id = ?", (task_id,)
    ).fetchone()
    if row is None or row["recur_rule"] is None:
        return
    import json

    recur_target = None
    if row["recur_target"]:
        try:
            rt = json.loads(row["recur_target"])
            from core.schedule import RecurTarget

            recur_target = RecurTarget(amount=float(rt["amount"]), unit=str(rt["unit"]))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            recur_target = None
    created_at = datetime.fromisoformat(row["created_at"]).date()
    existing_rows = conn.execute(
        "SELECT occurrence_date FROM occurrences WHERE task_id = ?", (task_id,)
    ).fetchall()
    existing = frozenset(
        datetime.fromisoformat(r["occurrence_date"]).date() for r in existing_rows
    )
    view = RecurringTaskView(
        id=task_id,
        recur_rule=row["recur_rule"],
        recur_target=recur_target,
        created_at=created_at,
        existing_dates=existing,
    )
    to_create: list[OccurrenceToCreate] = ensure_occurrences_up_to([view], today, backfill_days=30)
    for oc in to_create:
        conn.execute(
            """
            INSERT OR IGNORE INTO occurrences
                (task_id, occurrence_date, target_amount, done_amount, status, note)
            VALUES (?, ?, ?, 0, 'pending', NULL)
            """,
            (oc.task_id, oc.occurrence_date.isoformat(), oc.target_amount),
        )


# ---- 落库 ----


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


def _quick_replies_for(low_fields: list[str]) -> list[str]:
    """据低置信字段生成 quick_replies 选项。"""
    replies: list[str] = []
    if "weight" in low_fields:
        replies.extend(["S", "M", "L", "XL"])
    if "project_ref" in low_fields:
        replies.extend(["不关联项目", "新建项目"])
    if "recur_target" in low_fields:
        replies.append("不设目标量")
    return replies or ["S", "M", "L", "XL"]


def make_ingest_task_node(
    router: LLMRouter, bus: PetCommandBus, conn: sqlite3.Connection
) -> Any:
    """构造 ingest_task 节点。router/bus/conn 闭包注入。"""

    def ingest_task_node(state: dict[str, Any]) -> dict[str, Any]:
        text = _last_human_text(state)
        now = _now()
        scratch = dict(state.get("scratch") or {})

        # 1. 完成意图：识别"做完了" → 标 done。
        if _is_done_intent(text):
            done = _handle_completion(conn, bus, text)
            if done is not None:
                scratch.update(done)
                return {"scratch": scratch}

        # 2. 改字段意图：识别"把 due 改到周五" → TaskFieldsUpdated。
        if _is_update_intent(text):
            upd = _handle_update_fields(conn, bus, text, now)
            if upd is not None:
                scratch.update(upd)
                return {"scratch": scratch}

        # 3. 建任务：结构化抽取。
        try:
            draft = extract(text, now, router, DEFAULT_CONFIDENCE_THRESHOLD)
        except UserError as e:
            # 非法 schedule 组合（recurring 带 due 等）→ 气泡提示，不落库。
            bus.push(Bubble(text=f"任务描述有点矛盾：{e.message}", ttl=8.0))
            scratch["last_reply"] = e.message
            return {"scratch": scratch}

        low_fields = low_confidence_fields(draft, DEFAULT_CONFIDENCE_THRESHOLD)

        # 低置信字段触发反问：不落库，push bubble 带 quick_replies。
        # 但 schedule_kind 高置信时仍可落库（只反问 weight/project_ref）。
        kind_confident = draft.confidence("schedule_kind") >= DEFAULT_CONFIDENCE_THRESHOLD
        if not kind_confident:
            # 连 schedule_kind 都低置信 → 整体反问，不落库。
            replies = _quick_replies_for(low_fields)
            bus.push(
                Bubble(
                    text=f"没太明白这个任务的节奏，能补充下吗？（{draft.title}）",
                    ttl=10.0,
                    quick_replies=replies,
                )
            )
            scratch["last_reply"] = "反问：补充任务节奏"
            scratch["pending_draft"] = draft.model_dump(mode="json")
            return {"scratch": scratch}

        # 落库：高置信字段直接写。
        source = extraction_source(draft)
        payload = draft_to_task_created_payload(draft, source=source, raw_input=text)
        task_id = _gen_task_id()
        eid = _append_task_created(conn, task_id, payload)

        # recurring 任务补齐当日 occurrence（design.md §3.3）。
        if draft.schedule_kind is ScheduleKind.RECURRING:
            _ensure_today_occurrence(conn, task_id, now.date())

        receipt = f"记下了：{draft.title}"
        if draft.due_at:
            receipt += f"（截止 {draft.due_at.date().isoformat()}）"
        elif draft.schedule_kind is ScheduleKind.RECURRING and draft.recur_target:
            amt = (
                int(draft.recur_target.amount)
                if draft.recur_target.amount == int(draft.recur_target.amount)
                else draft.recur_target.amount
            )
            receipt += f"（每天 {amt}{draft.recur_target.unit}）"

        # 仍有低置信次要字段（weight/project_ref）→ 回执后追问一句。
        if low_fields:
            replies = _quick_replies_for(low_fields)
            bus.push(Bubble(text=receipt + " 顺便确认下：", ttl=10.0, quick_replies=replies))
        else:
            bus.push(Bubble(text=receipt, ttl=6.0))

        logger.info(
            "actor=agent event=task_created task_id=%s kind=%s weight=%s low=%s",
            task_id,
            draft.schedule_kind.value,
            draft.weight.value,
            low_fields,
        )
        scratch["last_task_id"] = task_id
        scratch["last_event_id"] = eid
        scratch["last_reply"] = receipt
        return {"scratch": scratch}

    return ingest_task_node


__all__ = ["make_ingest_task_node"]
