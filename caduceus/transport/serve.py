"""ServeTransport — v1 transport over the agent's `hermes serve` (FR-C3).

Talks to a published `hermes serve` endpoint over WebSocket (JSON-RPC). Connection
management (lazy open, reconnect-on-broken), per-call timeouts (RES-4/BR-C13), and
cooperative cancel (Q6) are implemented here; the **wire codec** — exact connect URL,
auth handshake, request/response frames, and session/cancel verbs — is isolated in the
clearly-marked `_WIRE` methods and **validated in Build & Test** (U3 Infra Design
§validation). Like U2's `SbxProvisioner`, this real implementation is exercised in
integration, not in the unit suite (which uses a FakeTransport).

`websockets` is imported lazily so the package (and the unit suite) import cleanly even
when the optional dependency is absent.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Optional

from caduceus.common.logging import get_logger, redact
from caduceus.common.models import AgentRecord, HealthLevel, HealthStatus
from caduceus.common.settings import Timeouts
from caduceus.transport.base import Transport, TransportKind, TransportState
from caduceus.transport.events import ChatEvent, ChatEventType

log = get_logger("caduceus.transport.serve")

#: in-sandbox serve port is fixed; the host-published port lives in AgentRecord.serve_port
SERVE_PORT = 9119


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ServeTransport(Transport):
    kind = TransportKind.serve

    def __init__(self, rec: AgentRecord, timeouts: Optional[Timeouts] = None):
        super().__init__(rec)
        self._timeouts = timeouts or Timeouts()
        self._ws = None  # live websocket connection (lazy)

    # ---- lifecycle ---------------------------------------------------
    async def open(self) -> None:
        if self.state == TransportState.open and self._ws is not None:
            return
        url = self._WIRE_url(self.rec)
        try:
            self._ws = await asyncio.wait_for(
                self._WIRE_connect(url, self.rec.serve_auth),
                timeout=self._timeouts.connect,
            )
            self.state = TransportState.open
        except Exception:
            self.state = TransportState.broken
            raise

    async def close(self) -> None:
        ws, self._ws = self._ws, None
        self.state = TransportState.closed
        if ws is not None:
            try:
                await ws.close()
            except Exception as exc:  # noqa: BLE001 — best-effort close
                log.debug("serve close error: %s", exc)

    async def _ensure_open(self) -> None:
        if self.state != TransportState.open or self._ws is None:
            await self.open()

    # ---- streaming ---------------------------------------------------
    async def _raw_stream(self, session_id: Optional[str], message: str) -> AsyncIterator[ChatEvent]:
        await self._ensure_open()
        # Resolve/resume the session (transparent recreate handled by the wire layer; Q1).
        self.session_id = await self._WIRE_ensure_session(session_id)
        await self._WIRE_send(self.session_id, message)
        idle = self._timeouts.read
        while True:
            if self._cancelled:
                await self._WIRE_cancel(self.session_id)
                yield ChatEvent.done_("cancelled", code="cancelled")
                return
            try:
                frame = await asyncio.wait_for(self._WIRE_recv(), timeout=idle)
            except asyncio.TimeoutError:
                yield ChatEvent.error_("agent response timed out", code="timeout")
                return
            except Exception as exc:  # noqa: BLE001 — connection dropped mid-stream
                self.state = TransportState.broken
                yield ChatEvent.error_(f"transport broken: {exc}", code="transport_broken")
                return
            ev = self._WIRE_decode(frame)
            if ev is None:
                continue  # keepalive / non-content frame
            yield ev
            if ev.is_terminal():
                return

    # ---- health (protocol handshake only; no LLM spend) --------------
    async def health(self) -> HealthStatus:
        try:
            await self._ensure_open()
            ok = await asyncio.wait_for(self._WIRE_ping(), timeout=self._timeouts.connect)
        except Exception as exc:  # noqa: BLE001
            self.state = TransportState.broken
            return HealthStatus(HealthLevel.unhealthy, shallow=False,
                                detail=f"serve unreachable: {redact(str(exc))}", checked_at=_now())
        level = HealthLevel.healthy if ok else HealthLevel.unhealthy
        return HealthStatus(level, shallow=bool(ok), detail="", checked_at=_now())

    # =================================================================
    # _WIRE_* : exact hermes serve protocol — VALIDATED IN BUILD & TEST
    # (JSON-RPC/WebSocket frames, auth handshake, session + cancel verbs).
    # Kept isolated so the surrounding streaming/timeout/cancel logic above
    # is protocol-agnostic and the codec can be confirmed/adjusted in one place.
    # =================================================================
    def _WIRE_url(self, rec: AgentRecord) -> str:
        if rec.kind.value == "remote" and rec.endpoint:
            base = rec.endpoint
        else:
            base = rec.endpoint or f"http://127.0.0.1:{rec.serve_port or SERVE_PORT}"
        # ws(s) scheme; exact path confirmed in Build & Test.
        return base.replace("http://", "ws://").replace("https://", "wss://").rstrip("/") + "/ws"

    async def _WIRE_connect(self, url: str, serve_auth: Optional[str]):
        import websockets  # lazy: optional dependency

        headers = {"Authorization": f"Bearer {serve_auth}"} if serve_auth else {}
        # NOTE: header arg name / handshake confirmed in Build & Test.
        return await websockets.connect(url, additional_headers=headers)

    async def _WIRE_ensure_session(self, session_id: Optional[str]) -> Optional[str]:
        # Build & Test: send a create/resume request; on "session not found",
        # transparently create a new one (Q1) and return its id.
        return session_id

    async def _WIRE_send(self, session_id: Optional[str], message: str) -> None:
        import json

        await self._ws.send(json.dumps({"method": "chat", "session": session_id, "message": message}))

    async def _WIRE_recv(self) -> str:
        return await self._ws.recv()

    def _WIRE_decode(self, frame: str) -> Optional[ChatEvent]:
        import json

        try:
            obj = json.loads(frame)
        except (ValueError, TypeError):
            return None
        kind = obj.get("type") or obj.get("event")
        if kind in ("delta", "token", "output"):
            return ChatEvent.token_(obj.get("text") or obj.get("chunk") or "")
        if kind in ("message",):
            return ChatEvent(ChatEventType.message, obj.get("text", ""))
        if kind in ("end", "complete", "done"):
            return ChatEvent.done_("completed")
        if kind in ("error",):
            return ChatEvent.error_(obj.get("message", "agent error"), code=obj.get("code") or "upstream_error")
        return None

    async def _WIRE_cancel(self, session_id: Optional[str]) -> None:
        import json

        try:
            await self._ws.send(json.dumps({"method": "cancel", "session": session_id}))
        except Exception as exc:  # noqa: BLE001 — best-effort cancel
            log.debug("serve cancel send failed: %s", exc)

    async def _WIRE_ping(self) -> bool:
        import json

        await self._ws.send(json.dumps({"method": "ping"}))
        await self._ws.recv()
        return True
