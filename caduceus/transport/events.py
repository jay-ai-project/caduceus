"""Chat events + the terminal-guard stream relay (BR-C5/C6).

`ChatEvent` is the uniform streaming token caduceus relays regardless of transport
(FR-C3). `normalize_stream` wraps a transport's raw event iterator and enforces the
**terminal-event invariant**: a turn yields zero or more `token`/`message` events
followed by **exactly one** terminal (`done` XOR `error`); nothing follows a terminal.
This is the shared relay all transports run through, so behavior is identical across
implementations (PBT-U3-1).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ChatEventType(str, Enum):
    token = "token"        # incremental output chunk
    message = "message"    # a whole message (assistant; or a replayed history turn)
    thinking = "thinking"  # incremental reasoning/thought chunk (non-terminal; U5)
    tool_call = "tool_call"  # a tool invocation start/update, structured in `meta` (U5)
    error = "error"        # terminal failure (carries a machine `code`)
    done = "done"          # terminal normal/cancel end (carries optional reason)


TERMINAL = (ChatEventType.error, ChatEventType.done)


@dataclass
class ChatEvent:
    type: ChatEventType
    data: str = ""
    code: Optional[str] = None
    #: structured payload for `tool_call` (ToolCallMeta: id/name/status/input/output)
    #: and replayed `message` turns ({"role": ..., "replay": True}); omitted when None.
    meta: Optional[dict] = None

    def is_terminal(self) -> bool:
        return self.type in TERMINAL

    def to_dict(self) -> dict:
        d = {"type": self.type.value, "data": self.data, "code": self.code}
        if self.meta is not None:
            d["meta"] = self.meta
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ChatEvent":
        return cls(
            type=ChatEventType(d["type"]),
            data=d.get("data", ""),
            code=d.get("code"),
            meta=d.get("meta"),
        )

    # convenience constructors
    @staticmethod
    def token_(text: str) -> "ChatEvent":
        return ChatEvent(ChatEventType.token, text)

    @staticmethod
    def thinking_(text: str) -> "ChatEvent":
        return ChatEvent(ChatEventType.thinking, text)

    @staticmethod
    def tool_(title: str, *, id: str, name: str = "", status: str = "in_progress",
              input: str = "", output: str = "") -> "ChatEvent":  # noqa: A002
        return ChatEvent(ChatEventType.tool_call, title, meta={
            "id": id, "name": name or title, "status": status,
            "input": input, "output": output,
        })

    @staticmethod
    def message_(text: str, role: str = "assistant", replay: bool = True) -> "ChatEvent":
        return ChatEvent(ChatEventType.message, text, meta={"role": role, "replay": replay})

    @staticmethod
    def done_(reason: str = "completed", code: Optional[str] = None) -> "ChatEvent":
        return ChatEvent(ChatEventType.done, reason, code=code)

    @staticmethod
    def error_(message: str, code: str = "transport_error") -> "ChatEvent":
        return ChatEvent(ChatEventType.error, message, code=code)


@dataclass
class HistoryTurn:
    """A prior conversation turn reconstructed from an agent session (FR-W10)."""
    role: str   # "user" | "assistant"
    text: str

    def to_dict(self) -> dict:
        return {"role": self.role, "text": self.text}


async def normalize_stream(raw: AsyncIterator[ChatEvent]) -> AsyncIterator[ChatEvent]:
    """Yield events from `raw` enforcing exactly one terminal event.

    - `token`/`message` pass through in order.
    - the first terminal (`done`/`error`) is yielded and iteration stops.
    - if `raw` ends with no terminal, a synthetic `done` is appended.
    - if `raw` raises, a single `error` is emitted (unless already terminated).
    """
    terminated = False
    try:
        async for ev in raw:
            if terminated:
                break  # never emit anything after a terminal
            yield ev
            if ev.is_terminal():
                terminated = True
                return
    except Exception as exc:  # noqa: BLE001 — surface as a terminal error, never leak
        if not terminated:
            yield ChatEvent.error_(f"{type(exc).__name__}: {exc}", code="transport_error")
        return
    if not terminated:
        yield ChatEvent.done_()
