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
    token = "token"      # incremental output chunk
    message = "message"  # a whole assistant message
    error = "error"      # terminal failure (carries a machine `code`)
    done = "done"        # terminal normal/cancel end (carries optional reason)


TERMINAL = (ChatEventType.error, ChatEventType.done)


@dataclass
class ChatEvent:
    type: ChatEventType
    data: str = ""
    code: Optional[str] = None

    def is_terminal(self) -> bool:
        return self.type in TERMINAL

    def to_dict(self) -> dict:
        return {"type": self.type.value, "data": self.data, "code": self.code}

    @classmethod
    def from_dict(cls, d: dict) -> "ChatEvent":
        return cls(
            type=ChatEventType(d["type"]),
            data=d.get("data", ""),
            code=d.get("code"),
        )

    # convenience constructors
    @staticmethod
    def token_(text: str) -> "ChatEvent":
        return ChatEvent(ChatEventType.token, text)

    @staticmethod
    def done_(reason: str = "completed", code: Optional[str] = None) -> "ChatEvent":
        return ChatEvent(ChatEventType.done, reason, code=code)

    @staticmethod
    def error_(message: str, code: str = "transport_error") -> "ChatEvent":
        return ChatEvent(ChatEventType.error, message, code=code)


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
