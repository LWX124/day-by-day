"""结构化抽取：把模糊自然语言推断成 Schedule/due/Weight/Project 结构化字段。

ADR-0003 核心落点：**推断在写入侧**。LLM 只在写入时把模糊自然语言推断成
结构化字段并物化落库（tasks.inference 存置信度 + 原始输入）；此后判定
（该催谁、Tier、统计）全在 core 纯函数，不经过 LLM——所以催办策略与 Tier
都能单测，不 mock LLM。

两条路径：
- 有 key：`router.get_model().with_structured_output(TaskDraft)` 让 LLM 直接
  产出 pydantic 模型，prompt 要求同时返回每字段置信度。
- 无 key：规则降级（复用 ingest_task 的时间词识别 + recurring 识别），
  给合理置信度——规则能确定的字段（"下周三前"→deadline+due）给高置信度直接落库；
  无法确定的（weight）给低置信度触发反问。

抽取后调 `Schedule.validate()` 校验非法组合，违者转 `UserError`（写入层校验语义，
见 common/errors.py 注释：core 不抛业务异常，由调用方转 UserError）。

置信度阈值可配（默认 0.7，PRD Notes）。低于阈值的字段触发反问而非落库——
调用方（ingest_task 节点）据 `low_confidence_fields` 决定推 quick_replies 气泡。
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from common.errors import UserError
from core.schedule import RecurTarget, Schedule, ScheduleKind, Weight

if TYPE_CHECKING:
    from agent.providers import LLMRouter

logger = logging.getLogger(__name__)

# 置信度阈值：>= 视为高置信直接落库；< 触发反问。PRD Notes「置信度阈值可配」。
DEFAULT_CONFIDENCE_THRESHOLD = 0.7# ---- pydantic 模型 ----


class TaskDraft(BaseModel):
    """LLM/规则抽取出的任务草稿。每字段带置信度。

    与 core.Schedule 对齐：schedule_kind + 各 kind 独有字段。非法组合由
    `to_schedule().validate()` 在写入层拒绝（转 UserError）。
    """

    model_config = ConfigDict(extra="forbid")

    title: str = Field(description="简短任务名")
    schedule_kind: ScheduleKind
    due_at: datetime | None = None  # 仅 deadline
    recur_rule: str | None = None  # 仅 recurring（RRULE 子集）
    recur_target: RecurTarget | None = None  # 仅 recurring
    weight: Weight = Weight.M
    project_ref: str | None = None  # 原始引用文本，由调用方解析 Project
    # 每字段 0-1 置信度。键名与字段名对齐：schedule_kind/due_at/recur_rule/
    # recur_target/weight/project_ref/title。缺失字段视为 1.0（已确定）。
    confidence_per_field: dict[str, float] = Field(default_factory=dict)

    @field_validator("confidence_per_field")
    @classmethod
    def _clamp_confidence(cls, v: dict[str, float]) -> dict[str, float]:
        out: dict[str, float] = {}
        for k, val in v.items():
            if not isinstance(val, int | float):
                continue
            out[k] = max(0.0, min(1.0, float(val)))
        return out

    def confidence(self, field: str) -> float:
        """取某字段置信度，缺失视为 1.0（已确定）。"""
        return self.confidence_per_field.get(field, 1.0)

    def to_schedule(self) -> Schedule:
        """转 Schedule 供 validate 校验非法组合。"""
        return Schedule(
            kind=self.schedule_kind,
            due_at=self.due_at,
            recur_rule=self.recur_rule,
            recur_target=self.recur_target,
        )

    def validate_schedule(self) -> None:
        """校验非法组合，违者转 UserError。

        core.Schedule.validate 抛 ValueError；写入层转 UserError（ADR-0003：
        非法组合在写入层拒绝，common/errors.py 注释 core 不抛业务异常）。
        """
        try:
            self.to_schedule().validate()
        except ValueError as e:
            raise UserError(
                str(e),
                detail={
                    "schedule_kind": self.schedule_kind.value,
                    "has_due": self.due_at is not None,
                    "has_recur_rule": self.recur_rule is not None,
                },
            ) from e


# ---- 规则降级抽取（无 key 路径） ----

_WEEKDAY_MAP = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}


def _next_weekday(today: date, target: int) -> date:
    """从今天算下一个目标星期几。today 已是本周该日则取下周。"""
    delta = (target - today.weekday()) % 7
    if delta == 0:
        delta = 7
    return today + timedelta(days=delta)


def _parse_due_from_text(text: str, now: datetime) -> datetime | None:
    """从中文文本里识别截止时间。覆盖验收用例"下周三前/这周五/明天/今天/后天"。

    返回 UTC 23:59 的当日截止。识别范围有限，够降级路径用——真实抽取由 LLM 负责。
    """
    today = now.date()
    # "下周三前" / "下周五"（"前"可选）
    m = re.search(r"下周([一二三四五六日天])(?:前|之内|之前|以前)?", text)
    if m:
        wd = _WEEKDAY_MAP[m.group(1)]
        this_week_x = _next_weekday(today, wd)
        due_date = this_week_x + timedelta(days=7)
        return datetime(due_date.year, due_date.month, due_date.day, 23, 59, tzinfo=UTC)
    # "这周三" / "本周三" / "周三前"
    m = re.search(r"(?:这|本)?周([一二三四五六日天])(?:前|之内|之前|以前)?", text)
    if m:
        wd = _WEEKDAY_MAP[m.group(1)]
        due_date = _next_weekday(today, wd)
        return datetime(due_date.year, due_date.month, due_date.day, 23, 59, tzinfo=UTC)
    if "明天" in text:
        d = today + timedelta(days=1)
        return datetime(d.year, d.month, d.day, 23, 59, tzinfo=UTC)
    if "后天" in text:
        d = today + timedelta(days=2)
        return datetime(d.year, d.month, d.day, 23, 59, tzinfo=UTC)
    if "今天" in text:
        return datetime(today.year, today.month, today.day, 23, 59, tzinfo=UTC)
    return None


def _parse_recur_target(text: str) -> tuple[RecurTarget | None, str | None]:
    """识别"每天读 5 页书"里的目标量。返回 (RecurTarget, 单位) 或 (None, None)。

    覆盖验收"每天读5页书"。识别"每天/每周 ... N <单位>"模式。
    """
    m = re.search(r"(\d+(?:\.\d+)?)\s*(页|篇|章|个|小时|分钟|次|行|道|节|km|米|公里)", text)
    if not m:
        return None, None
    amount = float(m.group(1))
    unit = m.group(2)
    return RecurTarget(amount=amount, unit=unit), unit


def _extract_title(text: str) -> str:
    """从文本提取简短任务名。冒号后取，否则整句去时间词。"""
    title = text
    if "：" in text:
        title = text.split("：", 1)[1].strip()
    elif ":" in text:
        title = text.split(":", 1)[1].strip()
    # 去掉常见时间/频率词，让标题更干净。
    for pat in (
        r"下周[一二三四五六日天](?:前|之内|之前|以前)?",
        r"(?:这|本)?周[一二三四五六日天](?:前|之内|之前|以前)?",
        r"今天|明天|后天",
        r"每天|每周|每周一|工作日",
        r"\d+(?:\.\d+)?\s*(?:页|篇|章|个|小时|分钟|次|行|道|节)",
    ):
        title = re.sub(pat, "", title)
    title = re.sub(r"[，,。；；！!？?]+", " ", title).strip()
    title = re.sub(r"\s+", " ", title)
    return title[:120] or text[:120]


def _rule_extract(text: str, now: datetime) -> TaskDraft:
    """规则降级抽取。给合理置信度：规则能确定的字段高置信，无法确定的低置信。

    - "下周三前..." → deadline + due，高置信（0.9）
    - "每天读5页书" → recurring + recur_target，高置信（0.9）
    - 无时间线索 → openended，weight 低置信（0.5）触发反问
    - weight 规则无法可靠推断 → 一律 0.5 触发反问（除非有强信号）
    """
    confidence: dict[str, float] = {}
    recur_target, _ = _parse_recur_target(text)
    is_recurring = "每天" in text or "每周" in text or "工作日" in text
    due_at: datetime | None = None

    if is_recurring:
        # recurring：从"每天/每周"推 recur_rule。
        schedule_kind = ScheduleKind.RECURRING
        recur_rule = "FREQ=DAILY" if ("每天" in text or "工作日" in text) else "FREQ=WEEKLY"
        confidence["schedule_kind"] = 0.9
        confidence["recur_rule"] = 0.9
        if recur_target is not None:
            confidence["recur_target"] = 0.9
        else:
            confidence["recur_target"] = 0.5
    else:
        due_at = _parse_due_from_text(text, now)
        if due_at is not None:
            schedule_kind = ScheduleKind.DEADLINE
            recur_rule = None
            confidence["schedule_kind"] = 0.9
            confidence["due_at"] = 0.9
        else:
            # 无时间线索 → openended（长期挂着，无时点无节奏）。
            # openended 是确定判断（不是"我不确定"），给高置信直接落库；
            # weight 才是真正低置信触发反问的字段。符合 PRD"落部分"。
            schedule_kind = ScheduleKind.OPENENDED
            recur_rule = None
            confidence["schedule_kind"] = 0.75
            confidence["due_at"] = 1.0  # openended 本就无 due

    # weight 规则无法可靠推断：一律低置信触发反问（除非文本明示 S/M/L/XL）。
    weight = Weight.M
    weight_conf = 0.5
    wm = re.search(r"\b([SMLX][L]?)\b", text.upper())
    if wm and wm.group(1) in {"S", "M", "L", "XL"}:
        weight = Weight(wm.group(1))
        weight_conf = 0.9
    confidence["weight"] = weight_conf

    title = _extract_title(text)
    confidence["title"] = 0.8

    # project_ref：文本里若出现"项目/主站/xxx 项目"则低置信反问（M4 才有 Project 表）。
    project_ref: str | None = None
    pm = re.search(r"([一-龥\w]+)项目", text)
    if pm:
        project_ref = pm.group(1)
        confidence["project_ref"] = 0.4  # 未命中已存在 Project → 反问

    draft = TaskDraft(
        title=title,
        schedule_kind=schedule_kind,
        due_at=due_at,
        recur_rule=recur_rule,
        recur_target=recur_target,
        weight=weight,
        project_ref=project_ref,
        confidence_per_field=confidence,
    )
    draft.validate_schedule()
    return draft


# ---- LLM 抽取（有 key 路径） ----

_EXTRACTION_PROMPT = """\
你是日程助手的任务抽取器。从用户输入推断任务的结构化字段，并给每字段一个 0-1 置信度。

Schedule 四态（schedule_kind）：
- one_shot：做完就结束，无约定期限
- deadline：约定了完成时点（due_at 必填，ISO8601 带时区）
- recurring：按规则反复，不存在超期（recur_rule 必填，RRULE 子集如 FREQ=DAILY；recur_target 可选）
- openended：长期挂着，无时点无节奏

weight ∈ S|M|L|XL（按工作量估）。project_ref 是用户提到的项目名（原始文本，未命中则留空）。

confidence_per_field：每个字段一个 0-1 置信度。规则明确的（如"下周三前"→deadline+due）给 0.9+；
模糊需反问的（如 weight 无线索）给 0.5 以下。键名：title, schedule_kind, due_at, recur_rule, \
recur_target, weight, project_ref。

只输出结构化字段，不要解释。当前时间：{now}。

用户输入：{text}"""


def _llm_extract(router: LLMRouter, text: str, now: datetime) -> TaskDraft | None:
    """LLM 结构化抽取。失败/异常返回 None 让调用方回退规则。

    用 `with_structured_output(TaskDraft)` 让 LLM 直接产 pydantic 模型——
    provider 的结构化输出能力（function calling / json schema）由 langchain 适配，
    无需手写 JSON 解析。
    """
    model = router.get_model()
    if model is None:
        return None
    try:
        structured = model.with_structured_output(TaskDraft)
        prompt = _EXTRACTION_PROMPT.format(now=now.isoformat(), text=text)
        draft = structured.invoke(prompt)
    except Exception as e:  # noqa: BLE001 — LLM 异常类型不可穷举
        logger.warning("llm structured extraction failed, fallback to rule: %s", e)
        return None
    if not isinstance(draft, TaskDraft):
        logger.warning("llm returned non-TaskDraft: %r", type(draft))
        return None
    # LLM 也可能产出非法组合（recurring 带 due），同样校验转 UserError。
    try:
        draft.validate_schedule()
    except UserError:
        raise  # 非法组合向上抛，由 ingest 节点决定气泡提示
    return draft


# ---- 对外入口 ----


def extract(
    text: str,
    now: datetime,
    router: LLMRouter | None = None,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> TaskDraft:
    """从自然语言抽取 TaskDraft。

    - router 可用且非 None → 走 LLM；失败回退规则。
    - 否则走规则降级。

    抽取后校验非法 schedule 组合，违者抛 UserError。

    置信度阈值仅记录在返回的 TaskDraft 上供调用方判断（本函数不据阈值改字段）——
    调用方用 `low_confidence_fields(draft, threshold)` 决定是否反问。
    """
    draft: TaskDraft | None = None
    source = "rule"
    if router is not None and router.is_available:
        llm_draft = _llm_extract(router, text, now)
        if llm_draft is not None:
            draft = llm_draft
            source = "llm"
    if draft is None:
        draft = _rule_extract(text, now)
        source = "rule"
    # 标记元信息（私有属性，不改 pydantic 字段值）。
    object.__setattr__(draft, "_source", source)
    object.__setattr__(draft, "_confidence_threshold", confidence_threshold)
    return draft


def extraction_source(draft: TaskDraft) -> str:
    """返回 draft 的抽取来源（"llm" | "rule"）。供调用方记入 inference.source。"""
    return getattr(draft, "_source", "rule")


def low_confidence_fields(
    draft: TaskDraft, threshold: float = DEFAULT_CONFIDENCE_THRESHOLD
) -> list[str]:
    """返回低于阈值的字段名列表。调用方据此推反问气泡。

    只检查影响落库决策的字段：schedule_kind / due_at / recur_rule / recur_target /
    weight / project_ref。title 不反问（抽取失败时整句兜底）。
    """
    checked = ("schedule_kind", "due_at", "recur_rule", "recur_target", "weight", "project_ref")
    out: list[str] = []
    for f in checked:
        # openended 无 due 是正常的，不算低置信。
        if f == "due_at" and draft.schedule_kind is not ScheduleKind.DEADLINE:
            continue
        if f in ("recur_rule", "recur_target") and draft.schedule_kind is not ScheduleKind.RECURRING:
            continue
        if draft.confidence(f) < threshold:
            out.append(f)
    return out


def draft_to_task_created_payload(
    draft: TaskDraft, *, source: str, raw_input: str
) -> dict[str, Any]:
    """把 TaskDraft 转成 TaskCreated 事件 payload。

    inference 字段存置信度 + 原始输入（ADR-0003：推断结果物化落库到 tasks.inference）。
    """
    return {
        "title": draft.title,
        "schedule_kind": draft.schedule_kind.value,
        "due_at": draft.due_at.isoformat() if draft.due_at else None,
        "recur_rule": draft.recur_rule,
        "recur_target": (
            {"amount": draft.recur_target.amount, "unit": draft.recur_target.unit}
            if draft.recur_target
            else None
        ),
        "weight": draft.weight.value,
        "status": "pending",
        "inference": {
            "source": source,  # "llm" | "rule"
            "confidence_per_field": draft.confidence_per_field,
            "raw_input": raw_input,
        },
    }


def parse_recur_target_json(payload: dict[str, Any]) -> RecurTarget | None:
    """从 TaskCreated payload 的 recur_target 字段还原 RecurTarget。"""
    rt = payload.get("recur_target")
    if not rt or not isinstance(rt, dict):
        return None
    try:
        return RecurTarget(amount=float(rt["amount"]), unit=str(rt["unit"]))
    except (KeyError, TypeError, ValueError):
        return None


__all__ = [
    "DEFAULT_CONFIDENCE_THRESHOLD",
    "TaskDraft",
    "draft_to_task_created_payload",
    "extract",
    "extraction_source",
    "low_confidence_fields",
    "parse_recur_target_json",
]
