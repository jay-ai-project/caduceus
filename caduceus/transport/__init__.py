"""U3 Transport & Chat — common streaming transport, chat orchestration, supervision.

Public surface (consumed by U4):
- `ChatService.chat_stream(name, message) -> AsyncIterator[ChatEvent]`
- `Transport` / `Transport.for_agent(rec)` → `HermesApiTransport` (HTTP+SSE, U8)
- `Supervisor` (process supervision; RES-5)
- `ChatEvent` / `ChatEventType`
"""

from caduceus.transport.events import ChatEvent, ChatEventType, normalize_stream
from caduceus.transport.base import Transport, TransportKind, TransportState, NotSupported
from caduceus.transport.chat import ChatService
from caduceus.transport.supervisor import (
    AgentSupervisionState,
    CircuitState,
    Supervisor,
    DEFAULT_BACKOFF,
)

__all__ = [
    "ChatEvent",
    "ChatEventType",
    "normalize_stream",
    "Transport",
    "TransportKind",
    "TransportState",
    "NotSupported",
    "ChatService",
    "Supervisor",
    "AgentSupervisionState",
    "CircuitState",
    "DEFAULT_BACKOFF",
]
