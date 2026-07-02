"""HermesApiTransport — the single caduceus↔agent transport (U8).

Replaces both `AcpTransport` (local stdio) and `ServeTransport` (remote JSON-RPC/WS):
every agent — local Docker container **or** remote registered endpoint — is driven over
the **hermes API server** (HTTP + SSE). Confirmed against hermes 0.17.0
(`gateway/platforms/api_server.py`); see the U8 spike artifact.

Turn flow (Sessions API, richest events + persistent session):
  ensure session (`POST /api/sessions`, reuse `rec.session_id`) →
  `POST /api/sessions/{sid}/chat/stream` (SSE) → map events → terminal.
`run_id` is surfaced on every session-stream event and powers cooperative cancel via the
Runs API (`POST /v1/runs/{run_id}/stop`). History replays `GET /api/sessions/{sid}/messages`.
Health is a plain `GET /health` (no LLM spend). Tool approval is auto (Q8): approval events
are surfaced for visibility but caduceus never blocks a turn.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Optional

import httpx

from caduceus.common.logging import get_logger, redact
from caduceus.common.models import AgentRecord, HealthLevel, HealthStatus
from caduceus.common.settings import Timeouts
from caduceus.common.util import now_iso as _now
from caduceus.transport.base import Transport, TransportKind, TransportState
from caduceus.transport.events import ChatEvent, HistoryTurn

log = get_logger("caduceus.transport.hermes_api")

#: per-field cap for tool_call input/output projected into a ChatEvent (BR-W7)
TOOL_FIELD_CAP = 4096
#: the pseudo tool_name hermes uses to stream reasoning as tool.progress
THINKING_TOOL = "_thinking"


def _truncate(s: str) -> str:
    return s if len(s) <= TOOL_FIELD_CAP else s[:TOOL_FIELD_CAP] + "…"


def _stringify(v) -> str:
    """Best-effort compact string for tool args/results (never raises)."""
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    try:
        return json.dumps(v, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(v)


def _session_id_of(data: dict) -> Optional[str]:
    """Extract the session id from a create/get-session response.

    hermes 0.17.0 returns `{"object": "hermes.session", "session": {"id": ...}}`
    (confirmed live, Build & Test); also accept a flat `id`/`session_id`/`sessionId`.
    """
    if not isinstance(data, dict):
        return None
    inner = data.get("session")
    if isinstance(inner, dict):
        for k in ("id", "session_id", "sessionId"):
            if inner.get(k):
                return str(inner[k])
    for k in ("id", "session_id", "sessionId"):
        if data.get(k):
            return str(data[k])
    return None


def _map_event(name: str, data: dict) -> Optional[ChatEvent]:
    """Map one hermes session chat/stream SSE event → ChatEvent. None = ignore.
    Defensive: never raises (BR-T4)."""
    if not isinstance(data, dict):
        data = {}
    if name == "assistant.delta":
        text = str(data.get("delta") or "")
        return ChatEvent.token_(text) if text else None
    if name == "tool.progress":
        tool = str(data.get("tool_name") or "")
        text = str(data.get("delta") or data.get("preview") or "")
        if tool == THINKING_TOOL or not tool:
            return ChatEvent.thinking_(text) if text else None
        return ChatEvent.tool_(tool, id=tool, name=tool, status="in_progress",
                               output=_truncate(text))
    if name in ("tool.started", "tool.completed", "tool.failed"):
        tool = str(data.get("tool_name") or "tool")
        status = {"tool.started": "in_progress", "tool.completed": "completed",
                  "tool.failed": "failed"}[name]
        return ChatEvent.tool_(
            tool, id=tool, name=tool, status=status,
            input=_truncate(_stringify(data.get("args"))),
            output=_truncate(_stringify(data.get("preview") or data.get("output"))),
        )
    if name in ("run.completed", "done"):
        return ChatEvent.done_("completed")
    if name == "error":
        return ChatEvent.error_(str(data.get("message") or "agent error"), code="agent_error")
    # run.started / message.started / assistant.completed → handled inline / ignored
    return None


class HermesApiTransport(Transport):
    kind = TransportKind.http

    def __init__(self, rec: AgentRecord, timeouts: Optional[Timeouts] = None):
        super().__init__(rec)
        self._timeouts = timeouts or Timeouts()
        self._client: Optional[httpx.AsyncClient] = None
        self._run_id: Optional[str] = None

    # ---- client ------------------------------------------------------
    def _new_client(self) -> httpx.AsyncClient:
        base = (self.rec.endpoint or "").rstrip("/")
        # A registered remote may keep its own API-server key (`register --auth`);
        # otherwise the single caduceus-minted token doubles as the bearer (BR-N2).
        bearer = self.rec.serve_auth or self.rec.token
        headers = {"Authorization": f"Bearer {bearer}"} if bearer else {}
        timeout = httpx.Timeout(
            connect=self._timeouts.connect, read=self._timeouts.read,
            write=self._timeouts.connect, pool=self._timeouts.connect,
        )
        return httpx.AsyncClient(base_url=base, headers=headers, timeout=timeout)

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = self._new_client()
        return self._client

    # ---- lifecycle ---------------------------------------------------
    async def open(self) -> None:
        if self.state == TransportState.open and self._client is not None:
            return
        self._ensure_client()
        try:
            if not self.session_id:
                self.session_id = await self._create_session()
            self.state = TransportState.open
        except Exception:
            self.state = TransportState.broken
            await self.close()
            raise

    async def _create_session(self) -> str:
        client = self._ensure_client()
        resp = await client.post("/api/sessions", json={})
        resp.raise_for_status()
        sid = _session_id_of(_safe_json(resp))
        if not sid:
            raise RuntimeError("hermes did not return a session id")
        return sid

    async def close(self) -> None:
        self.state = TransportState.closed
        client, self._client = self._client, None
        if client is not None:
            try:
                await client.aclose()
            except Exception as exc:  # noqa: BLE001 — best-effort
                log.debug("hermes_api close error: %s", exc)

    async def is_alive(self) -> bool:
        # HTTP is stateless; a transport with an open client is reusable across turns.
        return self.state == TransportState.open and self._client is not None

    # ---- health (no LLM spend; BR-T6) --------------------------------
    async def health(self) -> HealthStatus:
        try:
            client = self._ensure_client()
            resp = await client.get("/health")
            ok = resp.status_code == 200
        except Exception as exc:  # noqa: BLE001
            return HealthStatus(HealthLevel.unhealthy, shallow=False,
                                detail=f"api unreachable: {redact(str(exc))}", checked_at=_now())
        level = HealthLevel.healthy if ok else HealthLevel.unhealthy
        return HealthStatus(level, shallow=ok,
                            detail="" if ok else f"/health status {resp.status_code}",
                            checked_at=_now())

    # ---- streaming ---------------------------------------------------
    async def _raw_stream(self, message: str) -> AsyncIterator[ChatEvent]:
        await self.open()
        self._run_id = None
        try:
            async for ev in self._read_stream(self.session_id, message, allow_recreate=True):
                yield ev
        finally:
            self._cancelled = False  # reset for a reused transport

    async def _read_stream(self, sid: Optional[str], message: str,
                           allow_recreate: bool = False) -> AsyncIterator[ChatEvent]:
        client = self._ensure_client()
        url = f"/api/sessions/{sid}/chat/stream"
        try:
            async with client.stream("POST", url, json={"message": message}) as resp:
                if resp.status_code == 404 and allow_recreate:
                    # stale session → transparent recreate once (U3 Q1=A / BR-T2)
                    await resp.aread()
                    self.session_id = await self._create_session()
                    async for ev in self._read_stream(self.session_id, message, allow_recreate=False):
                        yield ev
                    return
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode("utf-8", "replace")
                    yield ChatEvent.error_(f"chat failed ({resp.status_code}): {redact(body[:300])}",
                                           code="upstream_error")
                    return
                async for ev in self._iter_sse(resp):
                    yield ev
        except httpx.TimeoutException:
            yield ChatEvent.error_("agent response timed out", code="timeout")
        except httpx.HTTPError as exc:
            self.state = TransportState.broken
            yield ChatEvent.error_(f"agent connection error: {redact(str(exc))}",
                                   code="transport_broken")

    async def _iter_sse(self, resp: "httpx.Response") -> AsyncIterator[ChatEvent]:
        name: Optional[str] = None
        data_buf: list[str] = []

        async for line in resp.aiter_lines():
            if self._cancelled:
                await self._stop_run()
                yield ChatEvent.done_("cancelled", code="cancelled")
                return
            if line == "":  # frame boundary → dispatch
                ev = self._dispatch(name, data_buf)
                name, data_buf = None, []
                if ev is not None:
                    yield ev
                    if ev.is_terminal():
                        return
                continue
            if line.startswith(":"):
                continue  # SSE comment / keep-alive
            if line.startswith("event:"):
                name = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data_buf.append(line[len("data:"):].lstrip())
        # flush a trailing frame with no terminating blank line
        ev = self._dispatch(name, data_buf)
        if ev is not None:
            yield ev

    def _dispatch(self, name: Optional[str], data_buf: list[str]) -> Optional[ChatEvent]:
        if not name:
            return None
        data = {}
        if data_buf:
            try:
                data = json.loads("\n".join(data_buf))
            except ValueError:
                data = {}
        if name == "run.started":
            rid = (data or {}).get("run_id")
            if rid:
                self._run_id = str(rid)
            return None
        # every event carries run_id; capture it opportunistically for stop
        if isinstance(data, dict) and data.get("run_id") and not self._run_id:
            self._run_id = str(data["run_id"])
        return _map_event(name, data)

    async def _stop_run(self) -> None:
        if not self._run_id:
            return  # no run to stop → the SSE disconnect (context exit) cancels server-side
        try:
            client = self._ensure_client()
            await client.post(f"/v1/runs/{self._run_id}/stop")
        except Exception as exc:  # noqa: BLE001 — best-effort cooperative cancel
            log.debug("stop run %s failed: %s", self._run_id, exc)

    # ---- history (best-effort; BR-T7) --------------------------------
    async def load_history(self, session_id: Optional[str]) -> list[HistoryTurn]:
        if not session_id:
            return []
        try:
            client = self._ensure_client()
            resp = await client.get(f"/api/sessions/{session_id}/messages")
            if resp.status_code != 200:
                return []
            return _parse_history(_safe_json(resp))
        except Exception as exc:  # noqa: BLE001 — best-effort; never surface to the UI
            log.info("history load failed for %s: %s", session_id, redact(str(exc)))
            return []


def _safe_json(resp: "httpx.Response") -> dict:
    try:
        return resp.json()
    except (ValueError, json.JSONDecodeError):
        return {}


def _parse_history(payload) -> list[HistoryTurn]:
    """Map `/api/sessions/{id}/messages` → [HistoryTurn]. Defensive over shape.

    hermes 0.17.0 returns `{"object":"list","data":[{role,content,...}]}` (confirmed live);
    also accept `{"messages":[...]}` or a bare list.
    """
    if isinstance(payload, dict):
        items = payload.get("data")
        if not isinstance(items, list):
            items = payload.get("messages")
    else:
        items = payload
    if not isinstance(items, list):
        return []
    turns: list[HistoryTurn] = []
    for m in items:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role") or "")
        if role not in ("user", "assistant"):
            continue
        content = m.get("content")
        if isinstance(content, list):  # OpenAI-style parts
            text = "".join(
                str(p.get("text", "")) for p in content if isinstance(p, dict)
            )
        else:
            text = str(content or m.get("text") or "")
        if text:
            turns.append(HistoryTurn(role=role, text=text))
    return turns
