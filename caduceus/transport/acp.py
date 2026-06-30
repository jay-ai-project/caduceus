"""AcpTransport — local-agent transport over `hermes acp` (stdio JSON-RPC).

caduceus drives each local sandboxed agent through the Agent Client Protocol
(newline-delimited JSON-RPC 2.0) spoken by `hermes acp`, spawned per chat via
`sbx exec -i <sandbox> hermes acp`. This replaced the `hermes serve` (web
dashboard) transport: Build & Test (2026-06-30) showed `hermes serve` requires a
full Node-built web dist, whereas ACP needs only the lightweight `[acp]` extra
and no network port. Validated end-to-end by spike (agent → AI-Gateway → LLM).

Protocol (confirmed against agent-client-protocol 0.9.0 / hermes 0.17.0):
  initialize → session/new (or session/load to resume) → session/prompt, with
  streamed `session/update` notifications (`agent_message_chunk` = output).
  The agent may call back: `session/request_permission` (auto-approved here),
  `fs/read_text_file` / `fs/write_text_file`.

The exact spawn command is injectable (`spawn`) so the unit suite can drive a
fake ACP agent without Docker; the default targets `sbx exec`.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime, timezone
from typing import Optional

from caduceus.common.logging import get_logger, redact
from caduceus.common.models import AgentRecord, HealthLevel, HealthStatus
from caduceus.common.settings import Timeouts
from caduceus.transport.base import Transport, TransportKind, TransportState
from caduceus.transport.events import ChatEvent

log = get_logger("caduceus.transport.acp")

ACP_PROTOCOL_VERSION = 1
Spawn = Callable[[], Awaitable["asyncio.subprocess.Process"]]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text_of(content: Optional[dict]) -> str:
    if not isinstance(content, dict):
        return ""
    return content.get("text", "") or ""


def _pick_allow(options: list[dict]) -> Optional[str]:
    """Choose a permissive option from a request_permission options list."""
    for o in options:
        oid = (o.get("optionId") or "").lower()
        kind = (o.get("kind") or "").lower()
        if "allow" in oid or "yes" in oid or "allow" in kind:
            return o.get("optionId")
    return options[0].get("optionId") if options else None


class AcpTransport(Transport):
    kind = TransportKind.acp

    def __init__(self, rec: AgentRecord, timeouts: Optional[Timeouts] = None, spawn: Optional[Spawn] = None):
        super().__init__(rec)
        self._timeouts = timeouts or Timeouts()
        self._spawn = spawn or self._default_spawn
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._id = 0
        self._initialized = False

    # ---- spawn -------------------------------------------------------
    async def _default_spawn(self) -> "asyncio.subprocess.Process":
        # stderr → DEVNULL: hermes logs verbosely there; an undrained PIPE would
        # block the agent once the OS buffer fills.
        return await asyncio.create_subprocess_exec(
            "sbx", "exec", "-i", "-e", f"OPENAI_API_KEY={self.rec.token}",
            self.rec.sandbox_name or "", "hermes", "acp",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )

    def _next(self) -> int:
        self._id += 1
        return self._id

    # ---- lifecycle ---------------------------------------------------
    async def open(self) -> None:
        if self.state == TransportState.open and self._proc is not None:
            return
        try:
            self._proc = await self._spawn()
            await asyncio.wait_for(self._initialize(), timeout=max(self._timeouts.connect, 30.0))
            self.state = TransportState.open
        except Exception:
            self.state = TransportState.broken
            await self._kill()
            raise

    async def _initialize(self) -> None:
        await self._rpc("initialize", {
            "protocolVersion": ACP_PROTOCOL_VERSION,
            "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False},
        })
        sid: Optional[str] = None
        if self.rec.session_id:
            sid = await self._try_load(self.rec.session_id)
        if sid is None:
            res = await self._rpc("session/new", {"cwd": "/root", "mcpServers": []})
            sid = res.get("sessionId")
        self.session_id = sid
        self._initialized = True

    async def _try_load(self, session_id: str) -> Optional[str]:
        """Resume an existing session (Q1); None if the agent can't load it."""
        try:
            await self._rpc("session/load", {"sessionId": session_id, "cwd": "/root", "mcpServers": []})
            return session_id
        except Exception as exc:  # noqa: BLE001 — stale session → transparent recreate
            log.info("acp: session/load failed (%s); creating a new session", exc)
            return None

    async def close(self) -> None:
        self.state = TransportState.closed
        await self._kill()

    async def _kill(self) -> None:
        proc, self._proc = self._proc, None
        self._initialized = False
        if proc is None:
            return
        try:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except (ProcessLookupError, asyncio.TimeoutError):
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        except Exception as exc:  # noqa: BLE001 — best-effort
            log.debug("acp kill error: %s", exc)

    async def _ensure_open(self) -> None:
        if self.state != TransportState.open or self._proc is None:
            await self.open()

    # ---- streaming ---------------------------------------------------
    async def _raw_stream(self, session_id: Optional[str], message: str) -> AsyncIterator[ChatEvent]:
        await self._ensure_open()
        rid = self._next()
        await self._send({"jsonrpc": "2.0", "id": rid, "method": "session/prompt",
                          "params": {"sessionId": self.session_id,
                                     "prompt": [{"type": "text", "text": message}]}})
        while True:
            if self._cancelled:
                await self._cancel()
                yield ChatEvent.done_("cancelled", code="cancelled")
                return
            try:
                msg = await asyncio.wait_for(self._read_json(), timeout=self._timeouts.read)
            except asyncio.TimeoutError:
                yield ChatEvent.error_("agent response timed out", code="timeout")
                return
            if msg is None:
                self.state = TransportState.broken
                yield ChatEvent.error_("agent connection closed mid-stream", code="transport_broken")
                return
            if "id" in msg and ("result" in msg or "error" in msg):
                if msg.get("id") == rid:
                    if "error" in msg:
                        yield ChatEvent.error_(str(msg["error"].get("message", "agent error")), code="upstream_error")
                    else:
                        yield ChatEvent.done_("completed")
                    return
                continue  # response to a different request
            if "method" in msg and "id" in msg:
                await self._handle_agent_request(msg)
                continue
            if msg.get("method") == "session/update":
                upd = (msg.get("params") or {}).get("update", {})
                if upd.get("sessionUpdate") == "agent_message_chunk":
                    text = _text_of(upd.get("content"))
                    if text:
                        yield ChatEvent.token_(text)
            # other notifications (thoughts/usage/commands) are ignored

    async def _cancel(self) -> None:
        try:
            await self._send({"jsonrpc": "2.0", "method": "session/cancel",
                              "params": {"sessionId": self.session_id}})
        except Exception as exc:  # noqa: BLE001 — best-effort cancel
            log.debug("acp cancel send failed: %s", exc)

    # ---- agent -> client requests ------------------------------------
    async def _handle_agent_request(self, msg: dict) -> None:
        method = msg.get("method")
        rid = msg.get("id")
        if method == "session/request_permission":
            options = (msg.get("params") or {}).get("options", [])
            choice = _pick_allow(options)
            result = {"outcome": {"outcome": "selected", "optionId": choice}}
        elif method == "fs/read_text_file":
            result = {"content": ""}
        else:  # fs/write_text_file and any other agent request → acknowledge
            result = {}
        await self._send({"jsonrpc": "2.0", "id": rid, "result": result})

    # ---- health (protocol handshake only; no LLM completion) ---------
    async def health(self) -> HealthStatus:
        try:
            await self._ensure_open()
        except Exception as exc:  # noqa: BLE001
            return HealthStatus(HealthLevel.unhealthy, shallow=False,
                                detail=f"acp unavailable: {redact(str(exc))}", checked_at=_now())
        ok = self._initialized and self._proc is not None
        level = HealthLevel.healthy if ok else HealthLevel.unhealthy
        return HealthStatus(level, shallow=ok, detail="", checked_at=_now())

    # ---- JSON-RPC plumbing -------------------------------------------
    async def _rpc(self, method: str, params: dict) -> dict:
        """Send a request and pump messages until its response (handling
        interleaved agent→client requests). Used for non-streaming verbs."""
        rid = self._next()
        await self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        while True:
            msg = await asyncio.wait_for(self._read_json(), timeout=max(self._timeouts.connect, 30.0))
            if msg is None:
                raise RuntimeError(f"acp connection closed awaiting '{method}'")
            if "id" in msg and ("result" in msg or "error" in msg):
                if msg.get("id") == rid:
                    if "error" in msg:
                        raise RuntimeError(str(msg["error"].get("message", method + " failed")))
                    return msg.get("result", {}) or {}
                continue
            if "method" in msg and "id" in msg:
                await self._handle_agent_request(msg)

    async def _send(self, obj: dict) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        self._proc.stdin.write((json.dumps(obj) + "\n").encode("utf-8"))
        await self._proc.stdin.drain()

    async def _read_json(self) -> Optional[dict]:
        """Read one JSON message line, skipping blank/non-JSON noise; None on EOF."""
        assert self._proc is not None and self._proc.stdout is not None
        while True:
            line = await self._proc.stdout.readline()
            if not line:
                return None
            s = line.strip()
            if not s:
                continue
            try:
                return json.loads(s)
            except ValueError:
                continue  # hermes prints non-JSON warnings to stdout; ignore
