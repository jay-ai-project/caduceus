"""U3 — ChatEvent + normalize_stream terminal-guard (BR-C5/C6)."""

from __future__ import annotations

from collections.abc import AsyncIterator

from caduceus.transport.events import ChatEvent, ChatEventType, normalize_stream


async def _aiter(items) -> AsyncIterator[ChatEvent]:
    for it in items:
        yield it


async def _collect(agen) -> list[ChatEvent]:
    return [ev async for ev in agen]


def test_chat_event_round_trip():
    for ev in [
        ChatEvent.token_("héllo"),
        ChatEvent(ChatEventType.message, "full"),
        ChatEvent.done_("completed"),
        ChatEvent.error_("boom", code="timeout"),
        # U5 additions
        ChatEvent.thinking_("reasoning…"),
        ChatEvent.tool_("read_file", id="t1", status="completed", input="{}", output="ok"),
        ChatEvent.message_("hi there", role="user"),
    ]:
        assert ChatEvent.from_dict(ev.to_dict()) == ev


def test_meta_omitted_when_none():
    # backward-compat: events without meta serialize without the key
    assert "meta" not in ChatEvent.token_("a").to_dict()
    assert ChatEvent.tool_("x", id="i").to_dict()["meta"]["id"] == "i"


def test_thinking_and_tool_are_non_terminal():
    assert not ChatEvent.thinking_("x").is_terminal()
    assert not ChatEvent.tool_("x", id="i").is_terminal()


async def test_normalize_passes_thinking_and_tool_then_done():
    raw = [ChatEvent.thinking_("plan"), ChatEvent.tool_("ls", id="t1"),
           ChatEvent.token_("ans"), ChatEvent.done_()]
    out = await _collect(normalize_stream(_aiter(raw)))
    assert [e.type for e in out] == [
        ChatEventType.thinking, ChatEventType.tool_call, ChatEventType.token, ChatEventType.done]
    assert sum(e.is_terminal() for e in out) == 1


async def test_normalize_passes_tokens_then_done():
    out = await _collect(normalize_stream(_aiter([ChatEvent.token_("a"), ChatEvent.token_("b"), ChatEvent.done_()])))
    assert [e.type for e in out] == [ChatEventType.token, ChatEventType.token, ChatEventType.done]


async def test_normalize_truncates_after_terminal():
    raw = [ChatEvent.token_("a"), ChatEvent.done_(), ChatEvent.token_("late"), ChatEvent.error_("x")]
    out = await _collect(normalize_stream(_aiter(raw)))
    assert [e.type for e in out] == [ChatEventType.token, ChatEventType.done]


async def test_normalize_appends_done_when_missing():
    out = await _collect(normalize_stream(_aiter([ChatEvent.token_("a")])))
    assert out[-1].type == ChatEventType.done
    assert sum(e.is_terminal() for e in out) == 1


async def test_normalize_maps_exception_to_error():
    async def boom():
        yield ChatEvent.token_("a")
        raise RuntimeError("dropped")

    out = await _collect(normalize_stream(boom()))
    assert out[0].type == ChatEventType.token
    assert out[-1].type == ChatEventType.error
    assert out[-1].code == "transport_error"
    assert sum(e.is_terminal() for e in out) == 1
