"""Transport abstraction (FR-C3/C4).

`Transport` is the single streaming port caduceus uses to talk to an agent. Concrete
transports implement `_raw_stream` (protocol-specific) + `open/close/health`; the base
runs every `_raw_stream` through `normalize_stream`, so chat behavior is **identical**
across implementations (FR-C3) and a future `AcpTransport` can plug in behind the same
interface without changing chat UX (FR-C4).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from enum import Enum
from typing import Optional

from caduceus.common.models import AgentRecord, HealthStatus
from caduceus.transport.events import ChatEvent, normalize_stream


class TransportState(str, Enum):
    closed = "closed"
    open = "open"
    broken = "broken"


class TransportKind(str, Enum):
    serve = "serve"  # v1: hermes serve (JSON-RPC/WebSocket)
    acp = "acp"      # designed-for: local stdio optimization (not built)


class NotSupported(Exception):
    """Raised by optional transport capabilities that an implementation lacks."""


class Transport(ABC):
    kind: TransportKind = TransportKind.serve

    def __init__(self, rec: AgentRecord):
        self.rec = rec
        self.state: TransportState = TransportState.closed
        #: current backend session id (set by the transport on resume/recreate)
        self.session_id: Optional[str] = rec.session_id
        self._cancelled: bool = False

    # ---- lifecycle ---------------------------------------------------
    @abstractmethod
    async def open(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    async def health(self) -> HealthStatus:
        """Protocol-level liveness only — never spends an LLM completion (Q5/BR-C11)."""

    # ---- streaming ---------------------------------------------------
    @abstractmethod
    def _raw_stream(self, session_id: Optional[str], message: str) -> AsyncIterator[ChatEvent]:
        """Protocol-specific raw event stream. Wrapped by `chat_stream`."""

    def chat_stream(self, session_id: Optional[str], message: str) -> AsyncIterator[ChatEvent]:
        """Uniform, terminal-guarded event stream (shared by all transports)."""
        return normalize_stream(self._raw_stream(session_id, message))

    def request_cancel(self) -> None:
        """Cooperative cancel (Q6/BR-C10): the raw stream ends with done{cancelled}."""
        self._cancelled = True

    # ---- optional config (local agents only; remote → NotSupported) --
    async def get_config(self):  # noqa: ANN201
        raise NotSupported("get_config not supported by this transport")

    async def set_config(self, change):  # noqa: ANN001, ANN201
        raise NotSupported("set_config not supported by this transport")

    # ---- factory -----------------------------------------------------
    @staticmethod
    def for_agent(rec: AgentRecord) -> "Transport":
        """Select a transport for an agent. v1 = ServeTransport for every agent."""
        from caduceus.transport.serve import ServeTransport

        return ServeTransport(rec)
