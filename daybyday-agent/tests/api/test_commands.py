"""PetCommand 序列化/反序列化往返 + PetCommandBus 行为。"""

from __future__ import annotations

import asyncio

import pytest

from api.commands import (
    Badge,
    Bubble,
    Celebrate,
    Notify,
    OpenPanel,
    PetCommandBus,
    RequestConfirm,
    SetEmotion,
    deserialize,
    serialize,
)

ALL_COMMANDS = [
    SetEmotion(state="happy"),
    Bubble(text="hi", ttl=3.0, quick_replies=["ok", "no"]),
    Bubble(text="simple"),
    Celebrate(tier=3, text="done!"),
    Notify(title="t", body="b"),
    OpenPanel(section="today"),
    RequestConfirm(action_id="a1", title="确认", detail="d"),
    Badge(count=5),
    Badge(count=0),
]


@pytest.mark.parametrize("cmd", ALL_COMMANDS)
def test_roundtrip(cmd) -> None:
    """每个命令 serialize → deserialize 得到等价模型。"""
    s = serialize(cmd)
    back = deserialize(s)
    assert back == cmd
    # type 字段保留
    assert cmd.type == back.type  # type: ignore[attr-defined]


def test_serialize_has_type_field() -> None:
    s = serialize(SetEmotion(state="idle"))
    assert '"type":"set_emotion"' in s
    assert '"state":"idle"' in s


def test_deserialize_rejects_unknown_type() -> None:
    with pytest.raises(ValueError, match="unknown pet command type"):
        deserialize('{"type":"bogus"}')


def test_deserialize_rejects_missing_type() -> None:
    with pytest.raises(ValueError, match="invalid pet command json"):
        deserialize('{"state":"idle"}')


def test_deserialize_rejects_bad_json() -> None:
    with pytest.raises(ValueError):
        deserialize("not json")


def test_extra_field_forbidden() -> None:
    """extra=forbid：多余字段应被拒。"""
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        SetEmotion.model_validate({"type": "set_emotion", "state": "idle", "extra": "x"})


def test_celebrate_tier_bounds() -> None:
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        Celebrate(tier=5, text="x")
    with pytest.raises(pydantic.ValidationError):
        Celebrate(tier=0, text="x")


def test_bus_push_no_subscribers_drops() -> None:
    """无订阅者时 push 不报错（命令丢弃）。"""
    bus = PetCommandBus()
    bus.push(Badge(count=1))  # 不应抛
    assert bus.subscriber_count == 0


def test_bus_subscribe_and_push() -> None:
    """订阅后 push，队列能收到。"""
    bus = PetCommandBus()
    q = bus.subscribe()
    assert bus.subscriber_count == 1
    cmd = Badge(count=3)
    bus.push(cmd)
    got = q.get_nowait()
    assert got == cmd


def test_bus_fanout_to_multiple_subscribers() -> None:
    """多个订阅者各自收到同一命令。"""
    bus = PetCommandBus()
    q1 = bus.subscribe()
    q2 = bus.subscribe()
    cmd = SetEmotion(state="focused")
    bus.push(cmd)
    assert q1.get_nowait() == cmd
    assert q2.get_nowait() == cmd


def test_bus_unsubscribe_stops_receiving() -> None:
    bus = PetCommandBus()
    q = bus.subscribe()
    bus.unsubscribe(q)
    assert bus.subscriber_count == 0
    bus.push(Badge(count=1))
    assert q.empty()


def test_bus_unsubscribe_idempotent() -> None:
    bus = PetCommandBus()
    q = bus.subscribe()
    bus.unsubscribe(q)
    bus.unsubscribe(q)  # 重复取消不抛
    assert bus.subscriber_count == 0


def test_async_poll_gets_command() -> None:
    """asyncio.Queue.get 在 event loop 里能取到 push 的命令。"""
    bus = PetCommandBus()
    q = bus.subscribe()

    async def main() -> object:
        bus.push(Notify(title="t", body="b"))
        return await asyncio.wait_for(q.get(), timeout=1.0)

    got = asyncio.run(main())
    assert isinstance(got, Notify)
    assert got.title == "t"
