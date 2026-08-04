"""agent/extraction.py 测试：结构化抽取 + 置信度。

无 key（规则）路径验收（PRD acceptance criteria）：
- "下周三前把登录重构做完" → deadline、due 正确（下周三）、weight 有值、confidence 高
- "每天读5页书" → recurring、recur_target={5,页}
- "学Rust" → openended、无时间线索 → weight 置信度低 → 触发反问
- 非法 schedule 组合（recurring 带 due）→ UserError
- Project 别名解析占位（未命中低置信反问）

agent 层只做冒烟（quality-guidelines §Testing Requirements），不 mock LLM——
有 key 路径的真实 LLM 调用不在此测，只测规则降级与模型契约。
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agent.extraction import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    TaskDraft,
    draft_to_task_created_payload,
    extract,
    low_confidence_fields,
    parse_recur_target_json,
)
from agent.providers import LLMRouter
from common.config import LLMConfig
from common.errors import UserError
from core.schedule import ScheduleKind, Weight

# 固定"今天"=2026-08-04（周二），使"下周三"可复现。
NOW = datetime(2026, 8, 4, 10, 0, tzinfo=UTC)


@pytest.fixture
def router() -> LLMRouter:
    """无 key 降级 router，强制走规则路径。"""
    return LLMRouter.from_config(LLMConfig())


# ---- 验收：下周三前把登录重构做完 ----


def test_deadline_extraction_next_week(router):
    """'下周三前把登录重构做完' → deadline + due（下周三）+ weight 有值 + 高置信。"""
    draft = extract("下周三前把登录重构做完", NOW, router)
    assert draft.schedule_kind is ScheduleKind.DEADLINE
    assert draft.due_at is not None
    # 2026-08-04 是周二，下周三 = 2026-08-12
    assert draft.due_at.date().isoformat() == "2026-08-12"
    assert draft.weight in {Weight.S, Weight.M, Weight.L, Weight.XL}
    # schedule_kind 与 due 高置信（规则能确定）→ 直接落库
    assert draft.confidence("schedule_kind") >= DEFAULT_CONFIDENCE_THRESHOLD
    assert draft.confidence("due_at") >= DEFAULT_CONFIDENCE_THRESHOLD


def test_deadline_payload_roundtrip(router):
    """draft_to_task_created_payload 含 inference（置信度+原始输入）。"""
    draft = extract("下周三前把登录重构做完", NOW, router)
    payload = draft_to_task_created_payload(draft, source="rule", raw_input="下周三前把登录重构做完")
    assert payload["schedule_kind"] == "deadline"
    assert payload["due_at"] is not None
    assert payload["weight"] in {"S", "M", "L", "XL"}
    assert payload["inference"]["source"] == "rule"
    assert payload["inference"]["raw_input"] == "下周三前把登录重构做完"
    assert "confidence_per_field" in payload["inference"]


# ---- 验收：每天读5页书 ----


def test_recurring_extraction_daily_target(router):
    """'每天读5页书' → recurring + recur_target={5,页} + 当日 occurrence 可建。"""
    draft = extract("每天读5页书", NOW, router)
    assert draft.schedule_kind is ScheduleKind.RECURRING
    assert draft.recur_rule == "FREQ=DAILY"
    assert draft.recur_target is not None
    assert draft.recur_target.amount == 5.0
    assert draft.recur_target.unit == "页"
    assert draft.confidence("schedule_kind") >= DEFAULT_CONFIDENCE_THRESHOLD
    assert draft.confidence("recur_target") >= DEFAULT_CONFIDENCE_THRESHOLD


def test_recurring_no_due(router):
    """recurring 不应有 due（design.md §3.1）。"""
    draft = extract("每天读5页书", NOW, router)
    assert draft.due_at is None
    assert draft.recur_rule is not None


# ---- 验收：学Rust → openended + 低置信 weight → 反问 ----


def test_openended_low_confidence_weight(router):
    """'学Rust' 无时间线索 → openended，weight 置信度低 → 触发反问。"""
    draft = extract("学Rust", NOW, router)
    assert draft.schedule_kind is ScheduleKind.OPENENDED
    assert draft.due_at is None
    # weight 规则无法确定 → 低置信
    assert draft.confidence("weight") < DEFAULT_CONFIDENCE_THRESHOLD
    low = low_confidence_fields(draft)
    assert "weight" in low


def test_low_confidence_fields_excludes_due_for_openended(router):
    """openended 无 due 是正常的，不算低置信。"""
    draft = extract("学Rust", NOW, router)
    low = low_confidence_fields(draft)
    assert "due_at" not in low


# ---- 非法组合 → UserError ----


def test_illegal_schedule_recurring_with_due_raises():
    """recurring 带 due → Schedule.validate 拒绝 → UserError。

    手工构造非法 TaskDraft（规则路径不会产出这种），验证 validate_schedule 转 UserError。
    """
    draft = TaskDraft(
        title="x",
        schedule_kind=ScheduleKind.RECURRING,
        recur_rule="FREQ=DAILY",
        due_at=NOW,
    )
    with pytest.raises(UserError):
        draft.validate_schedule()


def test_illegal_schedule_one_shot_with_due_raises():
    """one_shot 带 due → UserError（应改用 deadline）。"""
    draft = TaskDraft(
        title="x",
        schedule_kind=ScheduleKind.ONE_SHOT,
        due_at=NOW,
    )
    with pytest.raises(UserError):
        draft.validate_schedule()


def test_deadline_without_due_raises():
    """deadline 缺 due → UserError。"""
    draft = TaskDraft(title="x", schedule_kind=ScheduleKind.DEADLINE)
    with pytest.raises(UserError):
        draft.validate_schedule()


# ---- Project 别名解析占位 ----


def test_project_ref_low_confidence_when_mentioned(router):
    """文本提到项目 → project_ref 存原值，未命中已存在 Project（M4 占位）→ 低置信反问。"""
    draft = extract("下周三前做完主站项目重构", NOW, router)
    assert draft.project_ref is not None
    assert draft.confidence("project_ref") < DEFAULT_CONFIDENCE_THRESHOLD
    low = low_confidence_fields(draft)
    assert "project_ref" in low


def test_no_project_ref_when_not_mentioned(router):
    """无项目提及 → project_ref=None。"""
    draft = extract("学Rust", NOW, router)
    assert draft.project_ref is None


# ---- 置信度钳制 ----


def test_confidence_clamped_to_0_1():
    """confidence_per_field 超界值被钳到 [0,1]。"""
    draft = TaskDraft(
        title="x",
        schedule_kind=ScheduleKind.ONE_SHOT,
        confidence_per_field={"weight": 1.5, "title": -0.3},
    )
    assert draft.confidence("weight") == 1.0
    assert draft.confidence("title") == 0.0


def test_confidence_missing_defaults_to_1():
    """缺失字段置信度视为 1.0（已确定）。"""
    draft = TaskDraft(title="x", schedule_kind=ScheduleKind.ONE_SHOT)
    assert draft.confidence("weight") == 1.0


# ---- parse_recur_target_json ----


def test_parse_recur_target_json_roundtrip(router):
    """payload recur_target → RecurTarget 还原。"""
    draft = extract("每天读5页书", NOW, router)
    payload = draft_to_task_created_payload(draft, source="rule", raw_input="每天读5页书")
    rt = parse_recur_target_json(payload)
    assert rt is not None
    assert rt.amount == 5.0
    assert rt.unit == "页"


def test_parse_recur_target_json_none():
    assert parse_recur_target_json({"recur_target": None}) is None
    assert parse_recur_target_json({}) is None
    assert parse_recur_target_json({"recur_target": "not-a-dict"}) is None


# ---- extract 无 router 走规则 ----


def test_extract_without_router_uses_rule():
    """router=None 时直接走规则降级。"""
    draft = extract("下周三前做完重构", NOW, None)
    assert draft.schedule_kind is ScheduleKind.DEADLINE
    assert draft.due_at is not None


# ---- 标题抽取 ----


def test_title_extraction_strips_time_words(router):
    """标题去掉时间词后保留任务主体。"""
    draft = extract("下周三前做完登录重构", NOW, router)
    assert "登录重构" in draft.title or "重构" in draft.title
    assert "下周三" not in draft.title
