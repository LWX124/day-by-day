"""LLM Provider 抽象与 config.toml 路由（design.md §6.5）。

职责：
- Provider 接口：统一 chat / 结构化输出 / tool calling 三能力。直接用 langchain
  的 `BaseChatModel` 作基类——`invoke`(chat)、`with_structured_output`、
  `bind_tools` 三者它都自带，不必另造接口。
- ProviderFactory：按 config 的 `kind` 构造 provider。
    - `openai_compatible` → `ChatOpenAI(base_url=..., model=..., api_key=...)`
    - `wb_internal`：协议待确认，兼容则同上；不兼容预留 `BaseChatModel` 子类位
      （留 TODO，不必实现真实逻辑）。
- LLMRouter：default 失败自动切 fallback 列表；全部失败抛 `ProviderUnavailable`。
- 无 key（`LLMConfig.available == False`）时 `is_available=False`，`chat` 返回
  `None`（降级标记），不抛异常——触发降级模式（ADR-0003）。

key 从环境变量读（`os.environ[api_key_env]`），不落盘不硬编码。
agent 可 import langchain（core 才被 import-linter 禁）。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage

from common.config import LLMConfig, ProviderConfig
from common.errors import ProviderUnavailable

logger = logging.getLogger(__name__)

# 已支持的 provider kind。未知 kind 抛 UserError（写入层校验语义）。
SUPPORTED_KINDS = {"openai_compatible", "wb_internal"}


class ProviderUnavailableMarker:
    """降级模式占位。当 LLM 不可用时，chat() 返回 None 表示降级。"""


def _read_api_key(prov: ProviderConfig) -> str | None:
    """从环境变量读 key。缺失返回 None（触发降级）。"""
    if not prov.api_key_env:
        return None
    val = os.environ.get(prov.api_key_env)
    return val or None


def build_provider(prov: ProviderConfig) -> BaseChatModel:
    """根据 kind 构造一个 provider 实例。

    - `openai_compatible`：ChatOpenAI，key 从 env 读。key 缺失抛 ProviderUnavailable
      （由 LLMRouter 在链路上吞掉/转降级，不会冒泡到 scheduler）。
    - `wb_internal`：微博内部网关。协议待确认——若与 openai_compatible 兼容则走
      ChatOpenAI；不兼容时实现 `WbInternalChatModel(BaseChatModel)`。当前留 TODO。
    """
    if prov.kind == "openai_compatible":
        return _build_openai_compatible(prov)
    if prov.kind == "wb_internal":
        # TODO(protocol): 微博内部网关协议确认前，先按 openai_compatible 兼容处理。
        # 确认不兼容后，在此实现 WbInternalChatModel(BaseChatModel) 子类
        # （自定义 _generate / _agenerate，复用 BaseChatModel 的 invoke/bind_tools/
        # with_structured_output 三能力）。
        logger.warning(
            "wb_internal provider 协议待确认，暂按 openai_compatible 兼容处理"
        )
        return _build_openai_compatible(prov)
    raise ProviderUnavailable(
        f"unsupported provider kind: {prov.kind}",
        detail={"supported": sorted(SUPPORTED_KINDS)},
    )


def _build_openai_compatible(prov: ProviderConfig) -> BaseChatModel:
    """构造 ChatOpenAI。key 缺失抛 ProviderUnavailable（调用方决定降级）。"""
    from langchain_openai import ChatOpenAI  # 局部 import：仅 openai_compatible 需要

    api_key = _read_api_key(prov)
    if api_key is None:
        raise ProviderUnavailable(
            f"provider api key missing: env {prov.api_key_env!r} not set",
            detail={"api_key_env": prov.api_key_env},
        )
    return ChatOpenAI(
        model=prov.model,
        base_url=prov.base_url,
        api_key=api_key,
        # 结构化输出 / tool calling 都走 model 默认能力，不在此覆盖 temperature。
    )


@dataclass
class _ResolvedProvider:
    """LLMRouter 链路中的一个 provider，含名称与构造好的 model。"""

    name: str
    model: BaseChatModel


class LLMRouter:
    """default + fallback 路由。

    用法：
        router = LLMRouter.from_config(cfg.llm)
        if not router.is_available:
            # 降级模式：提醒/统计/打卡/特效照常，仅禁用 NL 录入与成文
            ...
        resp = router.chat([HumanMessage("...")])  # None 表示降级；抛错表示全失败
    """

    def __init__(self, chain: list[_ResolvedProvider]) -> None:
        # chain 已按 [default, *fallback] 顺序排好。
        self._chain = chain

    @classmethod
    def from_config(cls, llm: LLMConfig) -> LLMRouter:
        """从 LLMConfig 构造路由链。

        - 无 default 且无 providers → 空链（is_available=False，降级）。
        - default 缺失但有 providers → 用第一个 provider 作 default。
        - 某 provider 的 key 缺失 → 跳过它（不入链），记 warning。
        - key 全缺 → 空链，is_available=False。
        """
        chain: list[_ResolvedProvider] = []
        # 排序：default 在前，fallback 其次，其余按 providers dict 顺序兜底。
        order: list[str] = []
        if llm.default:
            order.append(llm.default)
        order.extend(n for n in llm.fallback if n not in order)
        for name in llm.providers:
            if name not in order:
                order.append(name)

        for name in order:
            prov = llm.providers.get(name)
            if prov is None:
                logger.warning("provider %r referenced but not configured; skip", name)
                continue
            try:
                model = build_provider(prov)
            except ProviderUnavailable as e:
                # key 缺失等可降级情况：跳过，不入链。
                logger.warning("provider %r unavailable, skipped: %s", name, e.message)
                continue
            chain.append(_ResolvedProvider(name=name, model=model))
        return cls(chain)

    @property
    def is_available(self) -> bool:
        """是否有至少一个可用 provider。False 时走降级模式。"""
        return len(self._chain) > 0

    def default_model(self) -> BaseChatModel | None:
        """返回链首 provider 的 model（供需要直接拿 model 做结构化输出/tool calling
        的调用方使用）。不可用返回 None。"""
        return self._chain[0].model if self._chain else None

    def chat(
        self,
        messages: list[BaseMessage],
        **kwargs: Any,
    ) -> AIMessage | None:
        """同步 chat。先试 default，失败依次试 fallback。

        返回值：
        - AIMessage：成功
        - None：is_available=False（降级模式），不抛异常
        抛：
        - ProviderUnavailable：所有 provider 都失败
        """
        if not self.is_available:
            # 降级模式：不抛，返回 None 让调用方走确定性路径（ADR-0003）。
            return None
        errors: list[str] = []
        for rp in self._chain:
            try:
                resp = rp.model.invoke(messages, **kwargs)
            except Exception as e:  # noqa: BLE001 — 外部 LLM 调用异常类型不可穷举
                errors.append(f"{rp.name}: {type(e).__name__}: {e}")
                logger.warning("provider %r failed, trying fallback: %s", rp.name, e)
                continue
            if isinstance(resp, AIMessage):
                return resp
            # 某些 BaseChatModel 可能返回非 AIMessage（如 AIMessageChunk），转一道。
            if isinstance(resp, BaseMessage) and not isinstance(resp, AIMessage):
                return AIMessage(content=str(resp.content))
            errors.append(f"{rp.name}: unexpected response type {type(resp).__name__}")
        raise ProviderUnavailable(
            "all llm providers failed",
            detail={"errors": errors},
        )

    def get_model(self, name: str | None = None) -> BaseChatModel | None:
        """按名取 model；name=None 取 default。不存在/不可用返回 None。

        供需要拿原始 BaseChatModel 做 `with_structured_output` / `bind_tools` 的
        调用方使用——这两能力不在 router.chat 抽象里，直接用 model 更直接。
        """
        if not self._chain:
            return None
        if name is None:
            return self._chain[0].model
        for rp in self._chain:
            if rp.name == name:
                return rp.model
        return None


__all__ = [
    "LLMRouter",
    "ProviderUnavailableMarker",
    "SUPPORTED_KINDS",
    "build_provider",
]
