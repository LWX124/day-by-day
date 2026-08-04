"""PetCommand 模型与推送总线。

这是 Python 后端 → Swift 前端的**唯一主动通道**（design.md §2）。Swift 侧
`PetCommand.swift` 的解码必须与本模块的序列化对齐——字段名、type 判别值
是前后端契约。

7 种命令（design.md §2 表）：
    set_emotion(state)
    bubble(text, ttl, optional quick_replies)
    celebrate(tier, text)
    notify(title, body)
    open_panel(section)
    request_confirm(action_id, title, detail)
    badge(count)

PetCommandBus：后端内部模块（scheduler/agent）调 `bus.push(cmd)`，
SSE 端点 `await bus.poll()` 取出推给前端。简单的 asyncio.Queue + 多订阅者
fan-out（每个 SSE 连接独立消费，不互相抢）。
"""

from __future__ import annotations

import asyncio
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ---- 各命令模型 ----
# type 字段是 Swift 侧解码的判别字段，固定字符串，与 design.md §2 表对齐。


class SetEmotion(BaseModel):
    """切 sprite 状态机。state 见 design.md §5.4。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal["set_emotion"] = "set_emotion"
    state: str  # idle | happy | focused | worried | grumpy | sleeping


class Bubble(BaseModel):
    """弹气泡。ttl 到点自动消失，可带快捷回复按钮。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal["bubble"] = "bubble"
    text: str
    ttl: float = Field(default=5.0, description="气泡存活秒数")
    quick_replies: list[str] | None = None


class Celebrate(BaseModel):
    """播 Tier 1-4 特效。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal["celebrate"] = "celebrate"
    tier: int = Field(ge=1, le=4)
    text: str


class Notify(BaseModel):
    """系统通知。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal["notify"] = "notify"
    title: str
    body: str


class OpenPanel(BaseModel):
    """打开面板到指定分区。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal["open_panel"] = "open_panel"
    section: str  # chat | today | tasks | reviews | gerrit | notes | settings


class RequestConfirm(BaseModel):
    """弹二次确认框。后端不直接抢焦点，只在你要求某动作之后推这个。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal["request_confirm"] = "request_confirm"
    action_id: str
    title: str
    detail: str | None = None


class Badge(BaseModel):
    """宠物身上的待办徽标。count=0 清除。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal["badge"] = "badge"
    count: int = Field(ge=0)


# 判别联合：Swift 侧按 `type` 字段分发。alias 防止 Pydantic 对 Literal 的窄化。
PetCommand = (
    SetEmotion
    | Bubble
    | Celebrate
    | Notify
    | OpenPanel
    | RequestConfirm
    | Badge
)

# type 字符串 → 模型，供手动反序列化/测试往返用。
COMMAND_BY_TYPE: dict[str, type[BaseModel]] = {
    "set_emotion": SetEmotion,
    "bubble": Bubble,
    "celebrate": Celebrate,
    "notify": Notify,
    "open_panel": OpenPanel,
    "request_confirm": RequestConfirm,
    "badge": Badge,
}


def serialize(cmd: BaseModel) -> str:
    """序列化为 SSE data 行用的 JSON。type 字段保留。"""
    return cmd.model_dump_json()


def deserialize(data: str) -> BaseModel:
    """从 JSON 反序列化为对应命令模型。未知 type 抛 ValueError。

    供测试往返与未来 Swift 侧契约校验用。
    """
    obj = json.loads(data)
    if not isinstance(obj, dict) or "type" not in obj:
        raise ValueError(f"invalid pet command json: {data!r}")
    ctype = obj["type"]
    model = COMMAND_BY_TYPE.get(ctype)
    if model is None:
        raise ValueError(f"unknown pet command type: {ctype!r}")
    return model.model_validate(obj)


# ---- PetCommandBus ----


class PetCommandBus:
    """命令总线：后端模块 push，SSE 连接 poll。

    每个订阅者（SSE 连接）拿到独立队列，push 时 fan-out 到全部订阅者——
    这样不同 SSE 连接不会互相抢命令（虽然 M0 通常只有一个 Swift 连接）。

    push 是同步方法（scheduler/agent 不必是 async），内部 schedule 到队列。
    若无订阅者，命令丢弃（M0 行为：前端没连就先不攒，避免历史命令回放）。
    """

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[BaseModel]] = set()

    def push(self, cmd: BaseModel) -> None:
        """推一条命令到所有订阅者。无订阅者则丢弃。"""
        for q in self._subscribers:
            q.put_nowait(cmd)

    def subscribe(self) -> asyncio.Queue[BaseModel]:
        """注册一个订阅队列。返回的队列由调用方 poll。"""
        q: asyncio.Queue[BaseModel] = asyncio.Queue()
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[BaseModel]) -> None:
        """取消订阅。重复 unsubscribe 安全（discard 幂等）。"""
        self._subscribers.discard(q)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


__all__ = [
    "Badge",
    "Bubble",
    "Celebrate",
    "COMMAND_BY_TYPE",
    "Notify",
    "OpenPanel",
    "PetCommand",
    "PetCommandBus",
    "RequestConfirm",
    "SetEmotion",
    "deserialize",
    "serialize",
]
