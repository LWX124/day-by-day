"""POST /intent 路由与意图解析实现（design.md §4）。

- IntentParser：用 LLM 解析自然语言 → 结构化意图
- SessionManager：内存 session 管理（TTL 10 分钟）
- ToolExecutor：按置信度/级别调度 Tool 执行
"""

from __future__ import annotations

import json
import logging
import secrets
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Request

from agent.tools.registry import ToolLevel, ToolRegistry
from api.models.intent import (
    IntentAction,
    IntentParseResult,
    IntentRequest,
    IntentResponse,
    Message,
)
from common.config import load_config
from common.errors import ProviderUnavailable, UserError

if TYPE_CHECKING:
    import sqlite3

    from agent.providers import LLMRouter
    from api.commands import PetCommandBus

logger = logging.getLogger(__name__)

router = APIRouter()

# Session TTL（秒）
SESSION_TTL_SECONDS = 600  # 10 minutes

# 置信度阈值
CONFIDENCE_THRESHOLD = 0.7

# 意图到 Tool 名的映射
INTENT_TO_TOOL = {
    "create_task": "create_task",
    "query_tasks": "list_tasks",
    "get_task": "get_task",
    "update_task": "update_task",
    "delete_task": "delete_task",
    "complete_task": "complete_task",
    "abandon_task": "abandon_task",
    "checkin_occurrence": "checkin_occurrence",
    "reschedule_task": "reschedule_task",
    "today_view": "today_view",
    "compute_stats": "compute_stats",
    "query_git_evidence": "query_git_evidence",
    "query_gerrit_changes": "query_gerrit_changes",
    "get_project": "get_project",
    "search_notes": "search_notes",
    "upsert_project": "upsert_project",
    "upsert_note": "upsert_note",
}

# 需要 confirm 的 intent（即使 confidence 高也要走确认流）
CONFIRM_INTENTS = {"delete_task"}


class SessionManager:
    """内存 session 管理（TTL 10 分钟）。

    简单 dict + time.time() 过期。M2 再考虑持久化/Redis。
    """

    def __init__(self, ttl_seconds: int = SESSION_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._sessions: dict[str, dict[str, Any]] = {}  # session_id -> {messages, last_at}

    def _gc(self) -> None:
        """清理过期 session。"""
        now = time.time()
        expired = [
            sid for sid, data in self._sessions.items()
            if now - data["last_at"] > self._ttl
        ]
        for sid in expired:
            del self._sessions[sid]
            logger.debug("session expired: %s", sid)

    def get_or_create(self, session_id: str | None) -> tuple[str, list[Message]]:
        """获取或创建 session，返回 (session_id, messages)。"""
        self._gc()
        if session_id and session_id in self._sessions:
            data = self._sessions[session_id]
            data["last_at"] = time.time()
            return session_id, data["messages"]
        # 新建 session
        new_sid = f"sess_{int(time.time())}_{secrets.token_hex(4)}"
        self._sessions[new_sid] = {"messages": [], "last_at": time.time()}
        return new_sid, []

    def append(self, session_id: str, role: str, content: str) -> None:
        """追加消息到 session。"""
        if session_id not in self._sessions:
            return
        msg = Message(
            role=role,
            content=content,
            timestamp=datetime.now(UTC).isoformat(),
        )
        self._sessions[session_id]["messages"].append(msg)
        self._sessions[session_id]["last_at"] = time.time()

    def get_context(self, session_id: str) -> list[Message]:
        """获取 session 的完整对话上下文。"""
        if session_id not in self._sessions:
            return []
        return list(self._sessions[session_id]["messages"])


class IntentParser:
    """用 LLM 解析自然语言意图。

    复用 providers.py 的 LLMRouter，prompt + structured output。
    """

    INTENT_PROMPT = """你是一个任务管理助手的意图解析器。请分析用户的自然语言输入，提取意图和参数。

可用意图及对应参数：
- create_task: 创建任务。参数：title(必需), schedule_kind(one_shot|deadline|recurring|openended,默认one_shot), weight(S|M|L|XL,默认M), due_at(ISO8601,可选), recur_rule(可选), recur_target({amount,unit},可选), detail(可选), project_id(可选)
- list_tasks: 列出任务。参数：status(可选), schedule_kind(可选), limit(默认50)
- get_task: 获取任务详情。参数：task_id(必需)
- update_task: 更新任务。参数：task_id(必需), title/detail/weight/project_id/due_at/recur_rule(可选)
- delete_task: 删除任务。参数：task_id(必需)
- complete_task: 完成任务。参数：task_id(必需)
- abandon_task: 放弃任务。参数：task_id(必需)
- checkin_occurrence: 打卡。参数：task_id(必需), occurrence_date(YYYY-MM-DD), done_amount, target_amount, note, force_done
- reschedule_task: 改期。参数：task_id(必需), due_at/recur_rule(可选)
- today_view: 今日视图。无参数
- compute_stats: 统计。无参数

请返回 JSON：
{
  "intent": "意图名称",
  "args": {"参数名": "值"},
  "confidence": 0.0-1.0,
  "missing_params": ["缺失的参数名"]
}

注意：
- confidence < 0.7 时会追问用户确认
- missing_params 不为空时会追问缺少的参数
- 时间表达（如"明天下午3点"）要转成 ISO8601 格式

用户输入："""

    def __init__(self, router: LLMRouter | None = None) -> None:
        self._router = router
        self._config = load_config()
        if self._router is None:
            from agent.providers import LLMRouter as _LLMRouter
            self._router = _LLMRouter.from_config(self._config.llm)

    def parse(
        self,
        text: str,
        context: list[Message] | None = None,
    ) -> IntentParseResult:
        """解析用户输入，返回结构化意图。"""
        if self._router is None or not self._router.is_available:
            # 降级模式：返回 clarify 提示用户用结构化方式
            logger.warning("LLM unavailable, intent parsing in degraded mode")
            return IntentParseResult(
                intent="unknown",
                args={},
                confidence=0.0,
                missing_params=["llm_unavailable"],
            )

        model = self._router.default_model()
        if model is None:
            return IntentParseResult(
                intent="unknown",
                args={},
                confidence=0.0,
                missing_params=["llm_unavailable"],
            )

        # 构建 prompt
        messages: list[Any] = []
        # System prompt
        from langchain_core.messages import HumanMessage, SystemMessage

        messages.append(SystemMessage(content=self.INTENT_PROMPT))

        # 添加上下文
        if context:
            for msg in context:
                if msg.role == "user":
                    messages.append(HumanMessage(content=msg.content))
                else:
                    # Assistant message
                    from langchain_core.messages import AIMessage
                    messages.append(AIMessage(content=msg.content))

        # 当前输入
        messages.append(HumanMessage(content=text))

        # 尝试 structured output
        try:
            structured_model = model.with_structured_output(IntentParseResult)
            result = structured_model.invoke(messages)
            if isinstance(result, IntentParseResult):
                return result
        except Exception as e:
            logger.warning("structured output failed, fallback to raw chat: %s", e)

        # Fallback：普通 chat + JSON 解析
        try:
            raw_resp = self._router.chat(messages)
            if raw_resp is None:
                return IntentParseResult(
                    intent="unknown",
                    args={},
                    confidence=0.0,
                    missing_params=["llm_unavailable"],
                )
            content = raw_resp.content if hasattr(raw_resp, "content") else str(raw_resp)
            # 尝试提取 JSON
            json_str = content
            if isinstance(content, str):
                json_str = content
                if "```json" in content:
                    json_str = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    json_str = content.split("```")[1].split("```")[0].strip()

                data = json.loads(json_str)
            else:
                data = {}
            return IntentParseResult(
                intent=data.get("intent", "unknown"),
                args=data.get("args", {}),
                confidence=float(data.get("confidence", 0.0)),
                missing_params=data.get("missing_params") or None,
            )
        except json.JSONDecodeError as e:
            logger.warning("failed to parse LLM response as JSON: %s", e)
            return IntentParseResult(
                intent="unknown",
                args={},
                confidence=0.0,
                missing_params=["parse_failed"],
            )
        except Exception:
            logger.exception("intent parsing failed")
            return IntentParseResult(
                intent="unknown",
                args={},
                confidence=0.0,
                missing_params=["parse_failed"],
            )


class ToolExecutor:
    """意图执行器：按置信度和 Tool 级别调度执行。"""

    def __init__(
        self,
        registry: ToolRegistry,
        conn: sqlite3.Connection,
        bus: PetCommandBus | None = None,
    ) -> None:
        self._registry = registry
        self._conn = conn
        self._bus = bus

    def execute(
        self,
        intent: str,
        args: dict[str, Any],
        confidence: float,
    ) -> IntentResponse:
        """执行意图，返回响应。"""
        # 映射到 tool 名
        tool_name = INTENT_TO_TOOL.get(intent)
        if tool_name is None:
            return IntentResponse(
                intent=intent,
                args=args,
                confidence=confidence,
                action=IntentAction.CLARIFY,
                message=f"未知意图：{intent}。请用以下格式描述：创建任务、查询任务、完成任务等。",
                session_id="",
            )

        tool = self._registry.get(tool_name)
        if tool is None:
            return IntentResponse(
                intent=intent,
                args=args,
                confidence=confidence,
                action=IntentAction.CLARIFY,
                message=f"功能暂未实现：{intent}",
                session_id="",
            )

        # 检查是否需要确认（confirm 级别或强制确认意图）
        needs_confirm = tool.level is ToolLevel.CONFIRM or intent in CONFIRM_INTENTS

        if confidence < CONFIDENCE_THRESHOLD and not needs_confirm:
            # 低置信度且不需要确认：追问
            return IntentResponse(
                intent=intent,
                args=args,
                confidence=confidence,
                action=IntentAction.CLARIFY,
                message=f'我不太确定你想"{intent}"，是指这个吗？请确认或重新描述。',
                session_id="",
            )

        # 构造 ToolContext
        from agent.tools.registry import ToolContext

        ctx = ToolContext(
            conn=self._conn,
            bus=self._bus,
            actor="user",
            now=datetime.now(UTC),
        )

        # 执行（confirm 级别 Tool 内部会生成 pending_action）
        try:
            result = self._registry.invoke(tool_name, ctx, args)
        except UserError as e:
            return IntentResponse(
                intent=intent,
                args=args,
                confidence=confidence,
                action=IntentAction.CLARIFY,
                message=f"参数错误：{e.message}",
                session_id="",
            )
        except Exception as e:
            logger.exception("tool execution failed")
            return IntentResponse(
                intent=intent,
                args=args,
                confidence=confidence,
                action=IntentAction.CLARIFY,
                message=f"执行失败：{e}",
                session_id="",
            )

        if not result.ok:
            return IntentResponse(
                intent=intent,
                args=args,
                confidence=confidence,
                action=IntentAction.CLARIFY,
                message=result.message or "执行失败",
                session_id="",
            )

        # 判断 action 类型
        if result.pending_action_id:
            # confirm 级别
            return IntentResponse(
                intent=intent,
                args=args,
                confidence=confidence,
                action=IntentAction.CONFIRM,
                message=result.message or "请确认执行此操作",
                pending_action_id=result.pending_action_id,
                result={"data": result.data},
                session_id="",
            )

        # write/read 级别直接执行
        return IntentResponse(
            intent=intent,
            args=args,
            confidence=confidence,
            action=IntentAction.EXECUTE,
            message=result.message or "已执行",
            result={"data": result.data, "event_id": result.event_id},
            session_id="",
        )


# 全局 session manager
_session_manager = SessionManager()


def get_session_manager() -> SessionManager:
    return _session_manager


def _get_registry(request: Request) -> ToolRegistry:
    """从 app.state 取 ToolRegistry。"""
    registry = getattr(request.app.state, "tool_registry", None)
    if registry is None:
        from agent.tools.registry import make_default_registry
        registry = make_default_registry(bus=getattr(request.app.state, "command_bus", None))
        request.app.state.tool_registry = registry
    return registry


@router.post("/intent")
async def post_intent(
    req: IntentRequest,
    request: Request,
) -> IntentResponse:
    """POST /intent：解析自然语言意图，执行对应 Tool。

    - session_id：多轮对话标识，为空则新建
    - text：用户输入
    - context：可选的对话历史（后端也会查 session）
    """

    conn: sqlite3.Connection | None = getattr(request.app.state, "db_conn", None)
    if conn is None:
        raise HTTPException(status_code=503, detail="db not initialized")

    bus = getattr(request.app.state, "command_bus", None)
    session_mgr = get_session_manager()

    # 获取/创建 session
    session_id, session_messages = session_mgr.get_or_create(req.session_id)

    # 合并上下文（请求里的 + session 存的）
    all_context = list(req.context or [])
    # session_messages 中不在 all_context 的追加进去
    existing_contents = {(m.role, m.content) for m in all_context}
    for m in session_messages:
        if (m.role, m.content) not in existing_contents:
            all_context.append(m)

    # 解析意图
    parser = IntentParser()
    try:
        parsed = parser.parse(req.text, context=all_context)
    except ProviderUnavailable:
        # 降级：返回 clarify 提示
        return IntentResponse(
            intent=None,
            args=None,
            confidence=0.0,
            action=IntentAction.CLARIFY,
            message="LLM 服务暂不可用，请使用结构化方式创建任务（如 POST /tasks）。",
            session_id=session_id,
        )

    # 执行
    registry = _get_registry(request)
    executor = ToolExecutor(registry, conn, bus)
    response = executor.execute(parsed.intent, parsed.args, parsed.confidence)
    response.session_id = session_id

    # 记录对话
    session_mgr.append(session_id, "user", req.text)
    session_mgr.append(session_id, "assistant", response.message)

    # 推送 PetCommand（intentResponse / clarify）
    if bus is not None:
        _push_intent_command(bus, response)

    return response


def _push_intent_command(bus: PetCommandBus, response: IntentResponse) -> None:
    """根据 IntentResponse action 类型推送对应的 PetCommand。"""
    from api.commands import Bubble, Clarify, IntentResponseCmd

    if response.action == IntentAction.CLARIFY.value:
        # 追问：推 clarify 命令
        bus.push(
            Clarify(
                question=response.message,
            )
        )
        # 同时气泡提示
        bus.push(
            Bubble(
                text=response.message,
                ttl=10.0,
                quick_replies=None,
            )
        )
    elif response.action == IntentAction.EXECUTE.value:
        # 执行成功：推 intentResponse
        bus.push(
            IntentResponseCmd(
                text=response.message,
                actions=[],
            )
        )
        # 同时气泡
        bus.push(
            Bubble(
                text=response.message,
                ttl=8.0,
                quick_replies=None,
            )
        )
    elif response.action == IntentAction.CONFIRM.value:
        # 需确认：推 intentResponse（带 confirm 标记）
        import json

        confirm_action = {"type": "confirm", "payload": {"pending_action_id": response.pending_action_id or ""}}
        bus.push(
            IntentResponseCmd(
                text=f"{response.message} (请确认)",
                actions=[json.dumps(confirm_action)],
            )
        )
        # 气泡提示
        bus.push(
            Bubble(
                text=f"{response.message} (请确认)",
                ttl=15.0,
                quick_replies=["确认", "取消"],
            )
        )


__all__ = [
    "IntentParser",
    "SessionManager",
    "ToolExecutor",
    "router",
]
