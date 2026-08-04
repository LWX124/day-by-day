"""agent/nodes/ingest_task.py 测试：建任务 / 标完成 / 改字段 三种语义。

无 key（降级）路径验收（PRD acceptance criteria）：
- "下周三前把登录重构做完" → deadline 任务、due 正确、weight 有值、回执一行
- "每天读5页书" → recurring 任务、当日实例（occurrence）出现
- "那个重构做完了" → 正确匹配现有任务并标完成
- 推断错误后"把 due 改到周五" → TaskFieldsUpdated 事件改 due
- Project 别名解析占位（未命中低置信反问）
- 非法 schedule 组合（recurring 带 due）→ UserError → 气泡提示

用临时 DB（tmp_path），不碰真实库。直接构造节点函数测，不走完整图——
ingest 节点是纯函数（state in → scratch out），单测更聚焦。
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage

from agent.nodes.classify import _last_human_text  # noqa: PLC2701 — 测试复用
from agent.nodes.ingest_task import make_ingest_task_node
from agent.providers import LLMRouter
from api.commands import Bubble, PetCommandBus
from common.config import LLMConfig
from store import events as event_store
from store.db import init_db


@pytest.fixture
def router() -> LLMRouter:
    """无 key 降级 router。"""
    return LLMRouter.from_config(LLMConfig())


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    """临时 DB 连接，跑完迁移。"""
    db = tmp_path / "ingest.sqlite3"
    c = init_db(db, check_same_thread=False)
    try:
        yield c
    finally:
        c.close()


@pytest.fixture
def bus() -> PetCommandBus:
    return PetCommandBus()


def _state(text: str) -> dict:
    return {"messages": [HumanMessage(text)]}


def _run(node, bus: PetCommandBus, text: str) -> tuple[dict, list]:
    """跑一次 ingest 节点，返回 (scratch, pushed_bubbles)。

    捕获 bus.push 调用，避免无订阅者时命令丢弃（PetCommandBus 无订阅者 push 是 no-op）。
    """
    pushed: list = []

    def push_spy(cmd):
        pushed.append(cmd)

    bus.push = push_spy  # type: ignore[method-assign]
    out = node(_state(text))
    return out.get("scratch", {}), pushed


def _make_node(router, bus, conn):
    return make_ingest_task_node(router, bus, conn)


# ---- 验收：下周三前把登录重构做完 → deadline + 回执一行 ----


def test_ingest_deadline_creates_task_with_receipt(router, bus, conn):
    """'下周三前把登录重构做完' → TaskCreated(deadline) + 一行回执。"""
    node = _make_node(router, bus, conn)
    scratch, pushed = _run(node, bus, "下周三前把登录重构做完")
    assert scratch.get("last_task_id") is not None
    # 事件流有 TaskCreated
    rows = conn.execute("SELECT kind FROM events").fetchall()
    assert event_store.TASK_CREATED in [r["kind"] for r in rows]
    # tasks 投影是 deadline + 有 due
    t = conn.execute(
        "SELECT schedule_kind, due_at, weight FROM tasks WHERE id = ?",
        (scratch["last_task_id"],),
    ).fetchone()
    assert t["schedule_kind"] == "deadline"
    assert t["due_at"] is not None
    assert t["weight"] in {"S", "M", "L", "XL"}
    # 回执气泡（可能带 quick_replies 因 weight 低置信，但 text 含"记下了"）
    bubbles = [c for c in pushed if isinstance(c, Bubble)]
    assert bubbles
    assert "记下了" in bubbles[0].text


def test_ingest_inference_stored_with_confidence(router, bus, conn):
    """tasks.inference 存置信度 + 原始输入（ADR-0003 物化落库）。"""
    node = _make_node(router, bus, conn)
    scratch, _ = _run(node, bus, "下周三前把登录重构做完")
    row = conn.execute("SELECT inference FROM tasks WHERE id = ?", (scratch["last_task_id"],)).fetchone()
    inf = json.loads(row["inference"])
    assert inf["source"] == "rule"
    assert inf["raw_input"] == "下周三前把登录重构做完"
    assert "confidence_per_field" in inf


# ---- 验收：每天读5页书 → recurring + 当日 occurrence ----


def test_ingest_recurring_creates_today_occurrence(router, bus, conn):
    """'每天读5页书' → recurring 任务 + 当日 occurrence 出现。"""
    node = _make_node(router, bus, conn)
    scratch, pushed = _run(node, bus, "每天读5页书")
    tid = scratch["last_task_id"]
    t = conn.execute(
        "SELECT schedule_kind, recur_rule, recur_target FROM tasks WHERE id = ?", (tid,)
    ).fetchone()
    assert t["schedule_kind"] == "recurring"
    assert t["recur_rule"] == "FREQ=DAILY"
    rt = json.loads(t["recur_target"])
    assert rt == {"amount": 5.0, "unit": "页"}
    # 当日 occurrence 已建（pending, done_amount=0）
    today = datetime.now(UTC).date().isoformat()
    oc = conn.execute(
        "SELECT status, done_amount, target_amount FROM occurrences WHERE task_id = ? AND occurrence_date = ?",
        (tid, today),
    ).fetchone()
    assert oc is not None
    assert oc["status"] == "pending"
    assert oc["done_amount"] == 0
    assert oc["target_amount"] == 5.0
    # 回执提到目标量
    bubbles = [c for c in pushed if isinstance(c, Bubble)]
    assert bubbles
    assert "5页" in bubbles[0].text or "5 页" in bubbles[0].text


# ---- 验收：那个重构做完了 → 匹配任务标完成 ----


def test_ingest_done_matches_existing_task(router, bus, conn):
    """先建一个重构任务，再'那个重构做完了' → TaskStatusChanged(to=done)。"""
    node = _make_node(router, bus, conn)
    # 先建任务
    s1, _ = _run(node, bus, "下周三前做完登录重构")
    tid = s1["last_task_id"]
    # 再标完成
    s2, pushed = _run(node, bus, "那个重构做完了")
    assert s2.get("last_task_id") == tid
    # 事件流有 TaskStatusChanged
    rows = conn.execute(
        "SELECT kind, payload FROM events WHERE task_id = ? ORDER BY id", (tid,)
    ).fetchall()
    kinds = [r["kind"] for r in rows]
    assert event_store.TASK_STATUS_CHANGED in kinds
    # 投影 status = done
    t = conn.execute("SELECT status FROM tasks WHERE id = ?", (tid,)).fetchone()
    assert t["status"] == "done"
    # 回执"标记完成"
    bubbles = [c for c in pushed if isinstance(c, Bubble)]
    assert bubbles
    assert "标记完成" in bubbles[0].text


def test_ingest_done_no_match_falls_back_to_create(router, bus, conn):
    """'做完了'但无匹配任务 → 回退建任务流程（不抛异常）。"""
    node = _make_node(router, bus, conn)
    s, pushed = _run(node, bus, "做完了某件事")
    # 没匹配到任务，回退建任务：应落 TaskCreated（"做完了某件事" 无时间词→openended）
    rows = conn.execute("SELECT kind FROM events").fetchall()
    assert event_store.TASK_CREATED in [r["kind"] for r in rows]


# ---- 验收：把 due 改到周五 → TaskFieldsUpdated ----


def test_ingest_update_due_to_friday(router, bus, conn):
    """先建 deadline 任务，再'把 due 改到周五' → TaskFieldsUpdated 改 due。"""
    node = _make_node(router, bus, conn)
    s1, _ = _run(node, bus, "下周三前做完重构")
    tid = s1["last_task_id"]
    s2, pushed = _run(node, bus, "把 due 改到周五")
    assert s2.get("last_task_id") == tid
    # 事件流有 TaskFieldsUpdated
    rows = conn.execute(
        "SELECT kind, payload FROM events WHERE task_id = ? ORDER BY id", (tid,)
    ).fetchall()
    kinds = [r["kind"] for r in rows]
    assert event_store.TASK_FIELDS_UPDATED in kinds
    upd_row = [r for r in rows if r["kind"] == event_store.TASK_FIELDS_UPDATED][0]
    payload = json.loads(upd_row["payload"])
    assert "due_at" in payload
    # 投影 due_at 已改
    t = conn.execute("SELECT due_at FROM tasks WHERE id = ?", (tid,)).fetchone()
    assert t["due_at"] == payload["due_at"]
    # 回执"改好了"
    bubbles = [c for c in pushed if isinstance(c, Bubble)]
    assert bubbles
    assert "改好了" in bubbles[0].text


def test_ingest_update_weight(router, bus, conn):
    """'把重量改成 L' → TaskFieldsUpdated 改 weight。"""
    node = _make_node(router, bus, conn)
    s1, _ = _run(node, bus, "下周三前做完重构")
    tid = s1["last_task_id"]
    s2, _ = _run(node, bus, "把重量改成 L")
    assert s2.get("last_task_id") == tid
    t = conn.execute("SELECT weight FROM tasks WHERE id = ?", (tid,)).fetchone()
    assert t["weight"] == "L"


def test_ingest_update_due_switches_openended_to_deadline(router, bus, conn):
    """给非 deadline 任务加 due → 切到 deadline + 清 recurring 字段（维持合法性）。

    design.md §3.1：非法组合在写入层拒绝。openended+due 是非法的，故更新 due 时
    一并切 schedule_kind=deadline 并清 recur_rule/recur_target。这也支持 PRD
    "推断错误后一句话能改 schedule/due/weight"——把 openended 改成 deadline。
    """
    node = _make_node(router, bus, conn)
    # 先建 openended 任务（"学Rust" 无时间线索 → openended）
    s1, _ = _run(node, bus, "学Rust")
    tid = s1["last_task_id"]
    before = conn.execute(
        "SELECT schedule_kind FROM tasks WHERE id = ?", (tid,)
    ).fetchone()
    assert before["schedule_kind"] == "openended"
    # 把 due 改到周五 → 应切到 deadline
    s2, _ = _run(node, bus, "把due改到周五")
    assert s2.get("last_task_id") == tid
    t = conn.execute(
        "SELECT schedule_kind, due_at, recur_rule, recur_target FROM tasks WHERE id = ?",
        (tid,),
    ).fetchone()
    assert t["schedule_kind"] == "deadline"
    assert t["due_at"] is not None
    assert t["recur_rule"] is None
    assert t["recur_target"] is None


# ---- 低置信 weight → 落部分 + 反问 ----


def test_ingest_openended_partial_create_with_ask(router, bus, conn):
    """'学Rust' → openended 落库（schedule_kind 高置信）+ weight 低置信 → quick_replies 反问。

    PRD acceptance：学Rust → openended、无时间线索 → weight 置信度低 → 触发反问
    bubble（不落库或落部分）。此处走"落部分"：任务已建，仅 weight 反问。
    """
    node = _make_node(router, bus, conn)
    s, pushed = _run(node, bus, "学Rust")
    assert s.get("last_task_id") is not None
    rows = conn.execute("SELECT kind FROM events").fetchall()
    assert event_store.TASK_CREATED in [r["kind"] for r in rows]
    t = conn.execute("SELECT schedule_kind FROM tasks WHERE id = ?", (s["last_task_id"],)).fetchone()
    assert t["schedule_kind"] == "openended"
    bubbles = [c for c in pushed if isinstance(c, Bubble)]
    assert bubbles
    # weight 低置信 → quick_replies 含 S/M/L/XL
    assert bubbles[0].quick_replies is not None
    assert "S" in bubbles[0].quick_replies and "XL" in bubbles[0].quick_replies


# ---- Project 别名占位 ----


def test_ingest_project_ref_low_confidence_asks(router, bus, conn):
    """提到项目 → project_ref 低置信 → 回执带 quick_replies 反问。"""
    node = _make_node(router, bus, conn)
    s, pushed = _run(node, bus, "下周三前做完主站项目重构")
    # deadline 高置信 → 仍落库，但 project_ref 低置信 → quick_replies
    rows = conn.execute("SELECT kind FROM events").fetchall()
    assert event_store.TASK_CREATED in [r["kind"] for r in rows]
    bubbles = [c for c in pushed if isinstance(c, Bubble)]
    assert bubbles
    # 有 quick_replies（因 project_ref 低置信）
    assert bubbles[0].quick_replies is not None


# ---- 回执气泡 quick_replies ----


def test_ingest_low_confidence_weight_quick_replies(router, bus, conn):
    """'学Rust' weight 低置信 → quick_replies 含 S/M/L/XL。"""
    node = _make_node(router, bus, conn)
    s, pushed = _run(node, bus, "学Rust")
    bubbles = [c for c in pushed if isinstance(c, Bubble)]
    assert bubbles
    qr = bubbles[0].quick_replies
    assert qr is not None
    assert "S" in qr and "XL" in qr


# ---- _last_human_text 复用校验（确保 ingest 取到用户输入） ----


def test_last_human_text_extracts_input():
    """ingest 节点用 _last_human_text 取输入，验证它支持 HumanMessage。"""
    state = {"messages": [HumanMessage("建任务：明天做完报告")]}
    assert _last_human_text(state) == "建任务：明天做完报告"
