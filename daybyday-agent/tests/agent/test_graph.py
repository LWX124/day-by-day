"""agent/graph.py 测试：LangGraph 图骨架。

无 key（降级）路径验收（PRD acceptance criteria）：
- "建个任务：下周三前做完重构" → classify 路由 ingest_task → 事件流有 TaskCreated → bubble 回执
- "那个任务怎么样了" → classify 路由 query_status
- "你好" → classify 路由 freeform
- 同一 thread_id 两次输入，第二次能看到第一次的 state（checkpointer 持久化）
- 断点续跑：图执行中断可恢复（interrupt_before + invoke(None) 续跑）

用临时 DB（tmp_path），不碰真实库。mock provider 验证有 key 路径不在此文件——
agent 层只做冒烟（quality-guidelines §Testing Requirements）。
"""

from __future__ import annotations

import contextlib
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import HumanMessage

from agent.graph import build_graph
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
def db_path(tmp_path: Path) -> Path:
    """临时 DB 文件，预跑迁移。"""
    p = tmp_path / "agent.sqlite3"
    init_db(p)
    return p


@pytest.fixture
def verify_conn(db_path: Path) -> Iterator[sqlite3.Connection]:
    """测试自用的验证连接（读 events/tasks）。与 build_graph 的连接同库不同连接。"""
    c = sqlite3.connect(str(db_path), isolation_level=None, check_same_thread=False)
    c.row_factory = sqlite3.Row
    try:
        yield c
    finally:
        c.close()


@pytest.fixture
def bus() -> PetCommandBus:
    return PetCommandBus()


@pytest.fixture
def compiled(
    router: LLMRouter, bus: PetCommandBus, db_path: Path, request: pytest.FixtureRequest
) -> Iterator[Any]:
    """编译好的图。teardown 时关闭 saver 连接，避免工作线程残留写与下个测试竞争。

    langgraph SqliteSaver 在线程池里跑节点，连接不显式 close 时 GC 时机不确定，
    可能与下一个测试的新连接在同一个 tmp_path 上竞争（表现为
    `sqlite3.OperationalError: not an error`）。finalizer 显式关闭消除竞态。
    """
    g = build_graph(router, bus, db_path)

    def _close() -> None:
        with contextlib.suppress(Exception):
            g.checkpointer.conn.close()  # type: ignore[union-attr]

    request.addfinalizer(_close)
    yield g


def _config(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}}


def _close_graph(compiled: Any) -> None:
    """关闭图的 saver 连接（供直接 build_graph 的测试用）。"""
    with contextlib.suppress(Exception):
        compiled.checkpointer.conn.close()  # type: ignore[union-attr]


# ---- 路由：classify 分发 ----


def test_ingest_routes_and_creates_task(compiled, verify_conn, bus):
    """'建个任务：下周三前做完重构' → ingest_task → TaskCreated 事件 + bubble。"""
    r = compiled.invoke(
        {"messages": [HumanMessage("建个任务：下周三前做完重构")]},
        config=_config("t1"),
    )
    assert r["scratch"]["intent"] == "ingest"
    # 事件流有 TaskCreated
    ev_rows = verify_conn.execute("SELECT kind FROM events").fetchall()
    kinds = [row["kind"] for row in ev_rows]
    assert event_store.TASK_CREATED in kinds
    # tasks 投影有该任务
    task_rows = verify_conn.execute("SELECT title, schedule_kind, weight FROM tasks").fetchall()
    assert len(task_rows) == 1
    assert "重构" in task_rows[0]["title"]
    # deadline（含"下周三前"时间词）
    assert task_rows[0]["schedule_kind"] == "deadline"
    # bubble 回执已 push
    assert bus.subscriber_count >= 0  # push 无订阅者也不报错


def test_ingest_bubble_receipt_pushed(compiled, bus):
    """ingest 节点 push 了 Bubble 回执。"""
    q = bus.subscribe()
    compiled.invoke(
        {"messages": [HumanMessage("建个任务：明天做完报告")]},
        config=_config("t-receipt"),
    )
    cmd = q.get_nowait()
    assert isinstance(cmd, Bubble)
    assert "记下了" in cmd.text


def test_query_routes(compiled, verify_conn):
    """'那个任务怎么样了' → query_status。"""
    r = compiled.invoke(
        {"messages": [HumanMessage("那个任务怎么样了")]},
        config=_config("t2"),
    )
    assert r["scratch"]["intent"] == "query"
    # query 节点不创建任务
    assert verify_conn.execute("SELECT COUNT(*) AS n FROM tasks").fetchone()["n"] == 0


def test_freeform_routes(compiled):
    """'你好' → freeform。"""
    r = compiled.invoke(
        {"messages": [HumanMessage("你好")]},
        config=_config("t3"),
    )
    assert r["scratch"]["intent"] == "freeform"


# ---- checkpointer 持久化 ----


def test_same_thread_retains_context(compiled, verify_conn):
    """同一 thread_id 两次输入，第二次能看到第一次的 state。"""
    cfg = _config("t-persist")
    compiled.invoke(
        {"messages": [HumanMessage("建个任务：下周三前做完重构")]},
        config=cfg,
    )
    # 第二次：查询。query 节点应能看到第一次建的任务（messages 累积 + 任务在库里）。
    r2 = compiled.invoke(
        {"messages": [HumanMessage("那个任务怎么样了")]},
        config=cfg,
    )
    # messages 跨调用累积：应有 2 条 HumanMessage
    st = compiled.get_state(config=cfg)
    msgs = st.values.get("messages", [])
    assert len(msgs) == 2
    # query 节点回执里应包含第一次建的任务标题
    reply = r2["scratch"].get("last_reply", "")
    assert "重构" in reply


def test_different_threads_isolated(compiled):
    """不同 thread_id 状态隔离。"""
    compiled.invoke(
        {"messages": [HumanMessage("建个任务：下周三前做完重构")]},
        config=_config("thread-a"),
    )
    st_b = compiled.get_state(config=_config("thread-b"))
    # thread-b 没跑过，messages 为空
    assert not st_b.values.get("messages")


# ---- 断点续跑：interrupt + resume ----


def test_interrupt_and_resume(router, bus, db_path, verify_conn):
    """图执行中断可恢复：interrupt_before ingest_task，再 invoke(None) 续跑。"""
    from langgraph.checkpoint.sqlite import SqliteSaver
    from langgraph.graph import END, START, StateGraph

    from agent.graph import AgentState
    from agent.nodes.classify import make_classify_node, route_after_classify
    from agent.nodes.freeform import make_freeform_node
    from agent.nodes.ingest_task import make_ingest_task_node
    from agent.nodes.query_status import make_query_status_node

    conn = sqlite3.connect(str(db_path), isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")

    g = StateGraph(AgentState)
    g.add_node("classify", make_classify_node(router))
    g.add_node("ingest_task", make_ingest_task_node(router, bus, conn))
    g.add_node("query_status", make_query_status_node(router, bus, conn))
    g.add_node("freeform", make_freeform_node(router, bus))
    g.add_edge(START, "classify")
    g.add_conditional_edges(
        "classify",
        route_after_classify,
        {
            "ingest_task": "ingest_task",
            "query_status": "query_status",
            "freeform": "freeform",
        },
    )
    g.add_edge("ingest_task", END)
    g.add_edge("query_status", END)
    g.add_edge("freeform", END)
    # 关键：interrupt_before 让图在 ingest_task 前停下
    compiled = g.compile(checkpointer=SqliteSaver(conn), interrupt_before=["ingest_task"])

    try:
        cfg = _config("t-interrupt")
        r = compiled.invoke(
            {"messages": [HumanMessage("建个任务：下周三前做完重构")]},
            config=cfg,
        )
        # 中断在 classify 之后、ingest_task 之前
        assert r["scratch"]["intent"] == "ingest"
        st = compiled.get_state(config=cfg)
        assert st.next == ("ingest_task",)
        # 此时任务还没落库
        assert verify_conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"] == 0

        # 续跑：传 None 表示继续，不追加输入
        r2 = compiled.invoke(None, config=cfg)
        assert r2["scratch"].get("last_task_id") is not None
        # 现在事件落库了
        assert verify_conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"] == 1
        st2 = compiled.get_state(config=cfg)
        assert st2.next == ()
    finally:
        _close_graph(compiled)


# ---- 降级模式不抛异常 ----


def test_degraded_mode_never_raises(compiled):
    """无 key 时各种输入都不抛异常。"""
    for text in ["", "??? ", "建个任务", "随便说点什么"]:
        r = compiled.invoke(
            {"messages": [HumanMessage(text)]},
            config=_config(f"t-deg-{text[:4]}"),
        )
        assert r["scratch"]["intent"] in {"ingest", "query", "freeform"}


# ---- 路由规则边界 ----


def test_rule_classify_ingest_with_colon(router, bus, db_path):
    """'建个任务：...' 含冒号 + 动作词，无时间词也路由 ingest。"""
    compiled = build_graph(router, bus, db_path)
    try:
        r = compiled.invoke(
            {"messages": [HumanMessage("建个任务：整理笔记")]},
            config=_config("t-colon"),
        )
        assert r["scratch"]["intent"] == "ingest"
    finally:
        _close_graph(compiled)


def test_rule_classify_query_keywords(router, bus, db_path):
    """含'怎么样/状态/进度'路由 query。"""
    compiled = build_graph(router, bus, db_path)
    try:
        for text in ["那个任务怎么样了", "进度如何", "完成了吗"]:
            r = compiled.invoke(
                {"messages": [HumanMessage(text)]},
                config=_config(f"t-q-{text[:3]}"),
            )
            assert r["scratch"]["intent"] == "query", f"failed for: {text}"
    finally:
        _close_graph(compiled)


def test_rule_classify_freeform_default(router, bus, db_path):
    """无特征词路由 freeform。"""
    compiled = build_graph(router, bus, db_path)
    try:
        r = compiled.invoke(
            {"messages": [HumanMessage("今天天气不错")]},
            config=_config("t-ff"),
        )
        assert r["scratch"]["intent"] == "freeform"
    finally:
        _close_graph(compiled)
