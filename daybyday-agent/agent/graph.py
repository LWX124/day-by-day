"""LangGraph 主图与 SqliteSaver checkpointer（design.md §6.1）。

图结构：
    START → classify → {ingest_task | query_status | freeform} → END

classify 节点判断意图写 state.scratch["intent"]，条件边按 intent 分发。
三叶节点各自落库/回执后到 END。

State（TypedDict）：
- messages: Annotated[list, add_messages]——跨调用累积（reducer），同一 thread_id
  多次输入能看到历史消息。这是 checkpointer 的主要收益点（daily_review 跨小时中断
  续跑靠这个）。
- scratch: dict——节点间传递数据（intent / last_task_id / last_reply 等），
  last-write-wins，不触碰则跨调用持久。

checkpointer：SqliteSaver 用同库文件独立表（design.md §4）。langgraph 自建表名
（checkpoint / checkpoint_blobs 等），与 store 的 events/tasks 不冲突。
连接策略：SqliteSaver 与 store 节点共享同一个 check_same_thread=False 连接，
langgraph SqliteSaver 内部有锁保证线程安全。

降级（ADR-0003）：router.is_available=False 时 classify 走规则、ingest 走规则抽取、
query 走模板、freeform 回"未接入"。全程不抛异常，验收路径仍通。
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, cast

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from agent.nodes.classify import make_classify_node, route_after_classify
from agent.nodes.freeform import make_freeform_node
from agent.nodes.ingest_task import make_ingest_task_node
from agent.nodes.query_status import make_query_status_node

if TYPE_CHECKING:
    from agent.providers import LLMRouter
    from api.commands import PetCommandBus

logger = logging.getLogger(__name__)


class AgentState(TypedDict, total=False):
    """图状态。

    `total=False` 让首次 invoke 可只传部分字段（messages），scratch 缺省为 {}。
    """

    messages: Annotated[list[Any], add_messages]
    scratch: dict[str, Any]


_ROUTE_MAP: dict[str, str] = {
    "ingest_task": "ingest_task",
    "query_status": "query_status",
    "freeform": "freeform",
}


def build_graph(
    router: LLMRouter,
    bus: PetCommandBus,
    db_path: Path | str | None = None,
) -> Any:
    """构造编译好的 agent 图。

    返回类型标注为 Any——CompiledStateGraph 有 4 个类型参数，精确标注收益低
    且 langgraph 版本间签名会变。调用方按 CompiledStateGraph 的 invoke/get_state
    协议使用即可。

    Args:
        router: LLM 路由（含降级标记）。
        bus: PetCommand 总线，节点回执通过它 push。
        db_path: DB 文件路径。None 时用默认库（common.config.DB_PATH）。

    连接策略：单一连接，check_same_thread=False，SqliteSaver 与 store 节点
    共享。langgraph SqliteSaver 内部有锁序列化写操作，WAL + busy_timeout
    保护并发。

    返回的 CompiledStateGraph 上调用方应：
        compiled.invoke({"messages": [HumanMessage(...)]},
                        config={"configurable": {"thread_id": "..."}})
    """
    path = str(db_path) if db_path is not None else _default_db_path()
    conn = _open_conn(path)
    saver = SqliteSaver(conn)

    graph = StateGraph(AgentState)
    graph.add_node("classify", make_classify_node(router))
    graph.add_node("ingest_task", make_ingest_task_node(router, bus, conn))
    graph.add_node("query_status", make_query_status_node(router, bus, conn))
    graph.add_node("freeform", make_freeform_node(router, bus))

    graph.add_edge(START, "classify")
    # path_map 期望 dict[Hashable, str]；str 是 Hashable 子类，cast 安抚 mypy。
    graph.add_conditional_edges("classify", route_after_classify, cast(Any, _ROUTE_MAP))
    graph.add_edge("ingest_task", END)
    graph.add_edge("query_status", END)
    graph.add_edge("freeform", END)

    compiled = graph.compile(checkpointer=saver)
    logger.info("actor=agent event=graph_built available=%s", router.is_available)
    return compiled


def _open_conn(path: str) -> sqlite3.Connection:
    """开连接：WAL + 外键 + check_same_thread=False + busy_timeout。

    isolation_level=None（autocommit）——SqliteSaver 的 put/put_writes 用裸 INSERT，
    不自管事务；若用 sqlite3 默认隔离级别（隐式事务），连续 INSERT 会触发
    "cannot start a transaction within a transaction"。
    """
    c = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("PRAGMA busy_timeout=10000")
    return c


def _default_db_path() -> str:
    from common.config import DB_PATH

    return str(DB_PATH)


__all__ = ["AgentState", "build_graph"]
