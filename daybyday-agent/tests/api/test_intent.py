"""POST /intent 测试。

覆盖：
- 高置信度意图直接执行（mock LLM）
- 低置信度意图返回 clarify
- confirm 级意图返回 pending_action_id
- session 上下文管理（多轮对话）
- session TTL 过期
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from api.models.intent import IntentAction
from api.routes.intent import IntentParser, SessionManager, ToolExecutor

# ---- SessionManager ----


class TestSessionManager:
    def test_create_new_session(self) -> None:
        mgr = SessionManager(ttl_seconds=600)
        sid, msgs = mgr.get_or_create(None)
        assert sid.startswith("sess_")
        assert msgs == []

    def test_get_existing_session(self) -> None:
        mgr = SessionManager(ttl_seconds=600)
        sid1, _ = mgr.get_or_create(None)
        # 追加消息
        mgr.append(sid1, "user", "hello")
        sid2, msgs = mgr.get_or_create(sid1)
        assert sid1 == sid2
        assert len(msgs) == 1
        assert msgs[0].role == "user"
        assert msgs[0].content == "hello"

    def test_session_ttl_expiry(self) -> None:
        mgr = SessionManager(ttl_seconds=0)  # 0 TTL = 立即过期
        sid, _ = mgr.get_or_create(None)
        # 追加消息让 last_at 更新
        mgr.append(sid, "user", "hello")
        # 等待一小段时间确保过期
        time.sleep(0.01)
        # 再获取，应该新建 session（旧的已过期）
        sid2, _ = mgr.get_or_create(sid)
        assert sid != sid2

    def test_append_to_nonexistent_session(self) -> None:
        mgr = SessionManager()
        # 不抛异常
        mgr.append("nonexistent", "user", "test")

    def test_context_roundtrip(self) -> None:
        mgr = SessionManager(ttl_seconds=600)
        sid, _ = mgr.get_or_create(None)
        mgr.append(sid, "user", "create task")
        mgr.append(sid, "assistant", "ok")
        ctx = mgr.get_context(sid)
        assert len(ctx) == 2
        assert ctx[0].role == "user"
        assert ctx[1].role == "assistant"


# ---- IntentParser (mock LLM) ----


class TestIntentParser:
    def test_parse_create_task_high_confidence(self) -> None:
        """mock LLM 返回高置信度 create_task 意图。"""
        mock_router = MagicMock()
        mock_router.is_available = True
        mock_model = MagicMock()
        mock_router.default_model.return_value = mock_model

        # Mock structured output
        from api.models.intent import IntentParseResult

        mock_result = IntentParseResult(
            intent="create_task",
            args={"title": "测试任务", "schedule_kind": "one_shot", "weight": "M"},
            confidence=0.95,
            missing_params=None,
        )
        mock_model.with_structured_output.return_value.invoke.return_value = mock_result

        parser = IntentParser(router=mock_router)
        result = parser.parse("帮我创建一个叫测试任务的任务")

        assert result.intent == "create_task"
        assert result.args["title"] == "测试任务"
        assert result.confidence == 0.95
        assert result.missing_params is None

    def test_parse_low_confidence(self) -> None:
        """mock LLM 返回低置信度意图。"""
        mock_router = MagicMock()
        mock_router.is_available = True
        mock_model = MagicMock()
        mock_router.default_model.return_value = mock_model

        from api.models.intent import IntentParseResult

        mock_result = IntentParseResult(
            intent="create_task",
            args={"title": "不确定的任务"},
            confidence=0.5,
            missing_params=["schedule_kind"],
        )
        mock_model.with_structured_output.return_value.invoke.return_value = mock_result

        parser = IntentParser(router=mock_router)
        result = parser.parse("帮我建个任务")

        assert result.confidence == 0.5
        assert result.missing_params == ["schedule_kind"]

    def test_llm_unavailable_degraded(self) -> None:
        """LLM 不可用时降级。"""
        mock_router = MagicMock()
        mock_router.is_available = False

        parser = IntentParser(router=mock_router)
        result = parser.parse("随便说点啥")

        assert result.intent == "unknown"
        assert result.confidence == 0.0
        assert result.missing_params == ["llm_unavailable"]

    def test_fallback_json_parsing(self) -> None:
        """structured output 失败时 fallback 到 JSON 解析。"""
        mock_router = MagicMock()
        mock_router.is_available = True
        mock_model = MagicMock()
        mock_router.default_model.return_value = mock_model

        # structured output 失败
        mock_model.with_structured_output.side_effect = Exception("structured output failed")

        # raw chat 返回 JSON 字符串
        mock_resp = MagicMock()
        mock_resp.content = '{"intent": "list_tasks", "args": {"status": "pending"}, "confidence": 0.85}'
        mock_router.chat.return_value = mock_resp

        parser = IntentParser(router=mock_router)
        result = parser.parse("列出所有待办任务")

        assert result.intent == "list_tasks"
        assert result.confidence == 0.85


# ---- ToolExecutor ----


class TestToolExecutor:
    def test_execute_read_tool(self, client: TestClient, auth_headers: dict) -> None:
        """高置信度 read 级 Tool 直接执行。"""
        # 先创建一个任务
        r = client.post(
            "/tasks",
            headers=auth_headers,
            json={"action": "create", "title": "测试任务", "schedule_kind": "one_shot", "weight": "S"},
        )
        assert r.status_code == 200

        # 获取 registry 和 conn - lazy init
        from agent.tools.registry import make_default_registry

        registry = getattr(client.app.state, "tool_registry", None)
        if registry is None:
            registry = make_default_registry(bus=getattr(client.app.state, "command_bus", None))
            client.app.state.tool_registry = registry
        conn = client.app.state.db_conn

        executor = ToolExecutor(registry, conn)
        response = executor.execute("today_view", {}, confidence=0.9)

        assert response.action == IntentAction.EXECUTE
        assert response.confidence == 0.9
        assert response.result is not None

    def test_execute_write_tool(self, client: TestClient, auth_headers: dict) -> None:
        """高置信度 write 级 Tool 直接执行。"""
        from agent.tools.registry import make_default_registry

        registry = getattr(client.app.state, "tool_registry", None)
        if registry is None:
            registry = make_default_registry(bus=getattr(client.app.state, "command_bus", None))
            client.app.state.tool_registry = registry
        conn = client.app.state.db_conn

        executor = ToolExecutor(registry, conn)
        response = executor.execute(
            "create_task",
            {"title": "测试任务", "schedule_kind": "one_shot", "weight": "S"},
            confidence=0.9,
        )

        assert response.action == IntentAction.EXECUTE
        assert response.result is not None
        assert response.result.get("data") is not None

    def test_low_confidence_returns_clarify(self, client: TestClient, auth_headers: dict) -> None:
        """低置信度返回 clarify。"""
        from agent.tools.registry import make_default_registry

        registry = getattr(client.app.state, "tool_registry", None)
        if registry is None:
            registry = make_default_registry(bus=getattr(client.app.state, "command_bus", None))
            client.app.state.tool_registry = registry
        conn = client.app.state.db_conn

        executor = ToolExecutor(registry, conn)
        response = executor.execute(
            "create_task",
            {"title": "测试"},
            confidence=0.5,
        )

        assert response.action == IntentAction.CLARIFY
        assert "0.5" in str(response.confidence) or response.message != ""

    def test_unknown_intent(self, client: TestClient, auth_headers: dict) -> None:
        """未知意图返回 clarify。"""
        from agent.tools.registry import make_default_registry

        registry = getattr(client.app.state, "tool_registry", None)
        if registry is None:
            registry = make_default_registry(bus=getattr(client.app.state, "command_bus", None))
            client.app.state.tool_registry = registry
        conn = client.app.state.db_conn

        executor = ToolExecutor(registry, conn)
        response = executor.execute("unknown_intent", {}, confidence=0.9)

        assert response.action == IntentAction.CLARIFY
        assert "未知意图" in response.message


# ---- API 集成测试 ----


class TestIntentAPI:
    def test_post_intent_high_confidence(self, client: TestClient, auth_headers: dict) -> None:
        """高置信度意图：mock LLM 返回高置信度 → 直接执行 Tool。"""
        with patch("api.routes.intent.IntentParser") as MockParser:
            from api.models.intent import IntentParseResult

            mock_parser = MagicMock()
            mock_parser.parse.return_value = IntentParseResult(
                intent="create_task",
                args={"title": "API测试任务", "schedule_kind": "one_shot", "weight": "M"},
                confidence=0.95,
                missing_params=None,
            )
            MockParser.return_value = mock_parser

            r = client.post(
                "/intent",
                headers=auth_headers,
                json={"text": "帮我创建一个叫API测试任务的任务"},
            )
            assert r.status_code == 200
            body = r.json()
            assert body["action"] == "execute"
            assert body["intent"] == "create_task"
            assert body["confidence"] == 0.95
            assert "session_id" in body

    def test_post_intent_low_confidence(self, client: TestClient, auth_headers: dict) -> None:
        """低置信度意图：返回 clarify。"""
        with patch("api.routes.intent.IntentParser") as MockParser:
            from api.models.intent import IntentParseResult

            mock_parser = MagicMock()
            mock_parser.parse.return_value = IntentParseResult(
                intent="create_task",
                args={"title": "模糊任务"},
                confidence=0.5,
                missing_params=["schedule_kind"],
            )
            MockParser.return_value = mock_parser

            r = client.post(
                "/intent",
                headers=auth_headers,
                json={"text": "帮我建个任务"},
            )
            assert r.status_code == 200
            body = r.json()
            assert body["action"] == "clarify"
            assert body["confidence"] == 0.5

    def test_post_intent_confirm_level(self, client: TestClient, auth_headers: dict) -> None:
        """confirm 级意图：返回 confirm + pending_action_id。"""
        with patch("api.routes.intent.IntentParser") as MockParser:
            from api.models.intent import IntentParseResult

            mock_parser = MagicMock()
            mock_parser.parse.return_value = IntentParseResult(
                intent="delete_task",
                args={"task_id": "task_123"},
                confidence=0.95,
                missing_params=None,
            )
            MockParser.return_value = mock_parser

            r = client.post(
                "/intent",
                headers=auth_headers,
                json={"text": "删除任务 task_123"},
            )
            assert r.status_code == 200
            body = r.json()
            # delete_task 是 confirm 级，会返回 pending_action_id
            assert body["action"] == "confirm"
            assert body["pending_action_id"] is not None

    def test_post_intent_session_persistence(self, client: TestClient, auth_headers: dict) -> None:
        """session 持久化：多轮对话保留上下文。"""
        with patch("api.routes.intent.IntentParser") as MockParser:
            from api.models.intent import IntentParseResult

            mock_parser = MagicMock()
            # 第一轮
            mock_parser.parse.return_value = IntentParseResult(
                intent="create_task",
                args={"title": "会话测试", "schedule_kind": "one_shot"},
                confidence=0.9,
                missing_params=None,
            )
            MockParser.return_value = mock_parser

            r1 = client.post(
                "/intent",
                headers=auth_headers,
                json={"text": "创建任务"},
            )
            assert r1.status_code == 200
            session_id = r1.json()["session_id"]

            # 第二轮，带上 session_id
            mock_parser.parse.return_value = IntentParseResult(
                intent="complete_task",
                args={"task_id": "task_123"},
                confidence=0.9,
                missing_params=None,
            )
            r2 = client.post(
                "/intent",
                headers=auth_headers,
                json={"text": "完成它", "session_id": session_id},
            )
            assert r2.status_code == 200
            assert r2.json()["session_id"] == session_id

    def test_post_intent_llm_unavailable(self, client: TestClient, auth_headers: dict) -> None:
        """LLM 不可用时降级为 clarify。"""
        with patch("api.routes.intent.IntentParser") as MockParser:
            mock_parser = MagicMock()
            from common.errors import ProviderUnavailable

            mock_parser.parse.side_effect = ProviderUnavailable("all providers failed")
            MockParser.return_value = mock_parser

            r = client.post(
                "/intent",
                headers=auth_headers,
                json={"text": "随便说"},
            )
            assert r.status_code == 200
            body = r.json()
            assert body["action"] == "clarify"
            assert "LLM" in body["message"] or "不可用" in body["message"]

    def test_post_intent_invalid_args(self, client: TestClient, auth_headers: dict) -> None:
        """Tool 参数错误时返回 clarify。"""
        with patch("api.routes.intent.IntentParser") as MockParser:
            from api.models.intent import IntentParseResult

            mock_parser = MagicMock()
            mock_parser.parse.return_value = IntentParseResult(
                intent="create_task",
                args={"bad_param": "value"},  # 缺少必需参数
                confidence=0.9,
                missing_params=None,
            )
            MockParser.return_value = mock_parser

            r = client.post(
                "/intent",
                headers=auth_headers,
                json={"text": "创建任务"},
            )
            assert r.status_code == 200
            body = r.json()
            # 参数校验失败 → clarify
            assert body["action"] == "clarify"

    def test_post_intent_with_context(self, client: TestClient, auth_headers: dict) -> None:
        """带 context 的请求能正确传递上下文。"""
        with patch("api.routes.intent.IntentParser") as MockParser:
            from api.models.intent import IntentParseResult

            mock_parser = MagicMock()
            mock_parser.parse.return_value = IntentParseResult(
                intent="query_tasks",
                args={"status": "pending"},
                confidence=0.85,
                missing_params=None,
            )
            MockParser.return_value = mock_parser

            r = client.post(
                "/intent",
                headers=auth_headers,
                json={
                    "text": "列出任务",
                    "context": [
                        {"role": "user", "content": "之前说过", "timestamp": "2026-08-05T10:00:00+08:00"}
                    ],
                },
            )
            assert r.status_code == 200
            body = r.json()
            assert body["action"] == "execute"
            assert body["intent"] == "query_tasks"
