"""agent/providers.py 测试。

用 mock provider，不调真实 LLM。验收项见 PRD：
- openai_compatible 配置正确时构造 ChatOpenAI（mock api_key_env）
- default 成功不走 fallback
- default 失败自动用 fallback 重试
- 全部失败抛 ProviderUnavailable
- 无 key（available=False）时 is_available 返回 False，chat 返回 None 不抛
- config.toml 示例解析往返正确
"""

from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from agent.providers import LLMRouter, build_provider
from common.config import LLMConfig, ProviderConfig, load_config
from common.errors import ProviderUnavailable


def _prov(
    name: str = "bailian",
    kind: str = "openai_compatible",
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
    model: str = "qwen-max",
    api_key_env: str = "DASHSCOPE_API_KEY",
) -> ProviderConfig:
    return ProviderConfig(
        kind=kind, base_url=base_url, model=model, api_key_env=api_key_env
    )


def _cfg(
    providers: dict[str, ProviderConfig] | None = None,
    default: str | None = "bailian",
    fallback: list[str] | None = None,
) -> LLMConfig:
    return LLMConfig(
        default=default,
        fallback=fallback or [],
        providers=providers or {"bailian": _prov()},
    )


# ---- build_provider ----


def test_build_openai_compatible_constructs_chat_openai(monkeypatch):
    """api_key_env 已设置时构造 ChatOpenAI，base_url/model 正确传入。"""
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test-xxx")
    prov = _prov()
    model = build_provider(prov)
    # ChatOpenAI 是 BaseChatModel 子类
    from langchain_core.language_models.chat_models import BaseChatModel

    assert isinstance(model, BaseChatModel)
    assert model.model_name == "qwen-max"
    assert model.openai_api_base == (
        "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )


def test_build_openai_compatible_missing_key_raises(monkeypatch):
    """key 缺失时 build_provider 抛 ProviderUnavailable（由 router 转降级）。"""
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    prov = _prov()
    with pytest.raises(ProviderUnavailable):
        build_provider(prov)


# ---- LLMRouter.is_available / 降级 ----


def test_router_unavailable_when_no_key(monkeypatch):
    """清空所有 key 后 is_available=False，chat 返回 None 不抛。"""
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    cfg = _cfg()
    router = LLMRouter.from_config(cfg)
    assert router.is_available is False
    resp = router.chat([HumanMessage("hi")])
    assert resp is None  # 降级标记


def test_router_unavailable_when_no_providers():
    """无任何 provider 配置 → 降级。"""
    cfg = LLMConfig(default=None, fallback=[], providers={})
    router = LLMRouter.from_config(cfg)
    assert router.is_available is False
    assert router.chat([HumanMessage("hi")]) is None


def test_router_available_when_key_set(monkeypatch):
    """有 key 时 is_available=True。"""
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test-xxx")
    cfg = _cfg()
    router = LLMRouter.from_config(cfg)
    assert router.is_available is True


# ---- fallback 链 ----


class _FakeModel:
    """假 model，可控抛错/返回。替掉 build_provider 的返回值。

    不继承 BaseChatModel——router.chat 只用 .invoke，duck typing 足够单测。
    """

    def __init__(self, name: str, *, raise_exc: Exception | None = None,
                 content: str = "ok") -> None:
        self.name = name
        self._raise = raise_exc
        self._content = content
        self.invoked = False

    def invoke(self, messages, **kwargs):  # noqa: ANN001 — 测试桩
        self.invoked = True
        if self._raise is not None:
            raise self._raise
        return AIMessage(content=self._content)


def _make_router_with_models(models: list[tuple[str, _FakeModel]]) -> LLMRouter:
    """直接拼装 _ResolvedProvider 链，绕过 build_provider。"""
    from agent.providers import _ResolvedProvider

    chain = [_ResolvedProvider(name=n, model=m) for n, m in models]
    return LLMRouter(chain)


def test_default_success_no_fallback():
    """default 成功时不走 fallback。"""
    default = _FakeModel("bailian", content="hello")
    fb = _FakeModel("deepseek", content="should-not-be-used")
    router = _make_router_with_models([("bailian", default), ("deepseek", fb)])
    resp = router.chat([HumanMessage("hi")])
    assert resp is not None
    assert resp.content == "hello"
    assert default.invoked is True
    assert fb.invoked is False


def test_default_failure_falls_back():
    """default 失败自动用 fallback 重试。"""
    default = _FakeModel("bailian", raise_exc=RuntimeError("boom"))
    fb = _FakeModel("deepseek", content="recovered")
    router = _make_router_with_models([("bailian", default), ("deepseek", fb)])
    resp = router.chat([HumanMessage("hi")])
    assert resp is not None
    assert resp.content == "recovered"
    assert default.invoked is True
    assert fb.invoked is True


def test_all_failures_raise_provider_unavailable():
    """所有 provider 都失败 → ProviderUnavailable，detail 含各错误。"""
    default = _FakeModel("bailian", raise_exc=RuntimeError("boom1"))
    fb = _FakeModel("deepseek", raise_exc=RuntimeError("boom2"))
    router = _make_router_with_models([("bailian", default), ("deepseek", fb)])
    with pytest.raises(ProviderUnavailable) as ei:
        router.chat([HumanMessage("hi")])
    assert "all llm providers failed" in ei.value.message
    assert len(ei.value.detail["errors"]) == 2


def test_router_skips_provider_with_missing_key(monkeypatch):
    """key 缺失的 provider 被跳过，不阻塞链上其他可用 provider。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds")
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    cfg = LLMConfig(
        default="bailian",
        fallback=["deepseek"],
        providers={
            "bailian": _prov(name="bailian", api_key_env="DASHSCOPE_API_KEY"),
            "deepseek": _prov(
                name="deepseek",
                base_url="https://api.deepseek.com/v1",
                model="deepseek-chat",
                api_key_env="DEEPSEEK_API_KEY",
            ),
        },
    )
    router = LLMRouter.from_config(cfg)
    # bailian key 缺 → 跳过；deepseek key 有 → 入链
    assert router.is_available is True
    assert router.get_model("bailian") is None
    assert router.get_model("deepseek") is not None
    # default_model 应是链首（deepseek）
    assert router.default_model() is router.get_model("deepseek")


# ---- get_model / default_model ----


def test_get_model_returns_none_when_unavailable(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    router = LLMRouter.from_config(_cfg())
    assert router.default_model() is None
    assert router.get_model("bailian") is None
    assert router.get_model("nonexistent") is None


# ---- config.toml 往返 ----


_TOML_EXAMPLE = """\
[llm]
default = "bailian"
fallback = ["deepseek"]

[llm.providers.bailian]
kind = "openai_compatible"
base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
model = "qwen-max"
api_key_env = "DASHSCOPE_API_KEY"

[llm.providers.deepseek]
kind = "openai_compatible"
base_url = "https://api.deepseek.com/v1"
model = "deepseek-chat"
api_key_env = "DEEPSEEK_API_KEY"

[llm.routing]
# ingest = "wb_internal"
"""


def test_config_toml_roundtrip(tmp_path: Path):
    """design.md §6.5 的 config.toml 示例解析往返正确。"""
    p = tmp_path / "config.toml"
    p.write_text(_TOML_EXAMPLE)
    cfg = load_config(p)
    assert cfg.llm.default == "bailian"
    assert cfg.llm.fallback == ["deepseek"]
    assert set(cfg.llm.providers) == {"bailian", "deepseek"}
    bailian = cfg.llm.providers["bailian"]
    assert bailian.kind == "openai_compatible"
    assert bailian.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert bailian.model == "qwen-max"
    assert bailian.api_key_env == "DASHSCOPE_API_KEY"
    assert cfg.llm.routing == {}  # 注释行不解析


def test_config_toml_missing_file_returns_default(tmp_path: Path):
    """文件不存在 → 默认配置（降级模式）。"""
    cfg = load_config(tmp_path / "nope.toml")
    assert cfg.llm.default is None
    assert cfg.llm.providers == {}
    assert cfg.llm.available is False


def test_config_available_reflects_env(monkeypatch, tmp_path: Path):
    """LLMConfig.available 反映 env 实际有值（验收：清空 key 后 unavailable）。"""
    p = tmp_path / "config.toml"
    p.write_text(_TOML_EXAMPLE)
    cfg = load_config(p)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert cfg.llm.available is False
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-x")
    assert cfg.llm.available is True


# ---- wb_internal 占位 ----


def test_wb_internal_builds_as_openai_compatible_for_now(monkeypatch):
    """wb_internal 协议待确认前按 openai_compatible 兼容处理。"""
    monkeypatch.setenv("WB_LLM_KEY", "sk-wb")
    prov = ProviderConfig(
        kind="wb_internal",
        base_url="https://internal.example.com/v1",
        model="wb-llm",
        api_key_env="WB_LLM_KEY",
    )
    model = build_provider(prov)
    from langchain_core.language_models.chat_models import BaseChatModel

    assert isinstance(model, BaseChatModel)


def test_unsupported_kind_raises(monkeypatch):
    monkeypatch.setenv("X_KEY", "sk-x")
    prov = ProviderConfig(
        kind="unknown_kind",
        base_url="x",
        model="x",
        api_key_env="X_KEY",
    )
    with pytest.raises(ProviderUnavailable):
        build_provider(prov)
