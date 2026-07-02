"""Registry / StateStore — durable agent registry (BR-A8, RESILIENCY-12).

Single JSON file with atomic writes (temp + os.replace) and an in-process
asyncio.Lock serializing mutations. Provides the synchronous `token_lookup`
used by the U1 AI-Gateway on the request path.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Optional

from caduceus.common.logging import get_logger
from caduceus.common.models import AgentRecord

STATE_VERSION = 1

log = get_logger("caduceus.agents.registry")


class Registry:
    def __init__(self, state_path: str | os.PathLike):
        self._path = Path(state_path)
        self._lock = asyncio.Lock()
        self._agents: dict[str, AgentRecord] = {}
        #: optional broadcast hook (U9): fired after every persisted mutation so the
        #: Web UI event stream reflects create/start/stop/remove/session live.
        self._on_change: Optional[Callable[[], Awaitable[None]]] = None

    def set_on_change(self, cb: Optional[Callable[[], Awaitable[None]]]) -> None:
        self._on_change = cb

    async def _notify(self) -> None:
        # Fired outside the mutation lock; a broadcast failure must never surface to
        # the caller that mutated the registry.
        if self._on_change is None:
            return
        try:
            await self._on_change()
        except Exception as exc:  # noqa: BLE001
            log.debug("registry on_change hook failed: %s", exc)

    # ---- load / save -------------------------------------------------
    def load(self) -> None:
        """Load state from disk (call once at startup; synchronous)."""
        if self._path.exists():
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._agents = {
                name: AgentRecord.from_dict(rec)
                for name, rec in data.get("agents", {}).items()
            }

    def _save_unlocked(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self._path.parent, 0o700)
        except OSError:
            pass  # filesystem may not support chmod (e.g. drvfs)
        doc = {
            "version": STATE_VERSION,
            "agents": {name: rec.to_dict() for name, rec in self._agents.items()},
        }
        fd, tmp = tempfile.mkstemp(dir=str(self._path.parent), prefix=".state-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(doc, f, indent=2, sort_keys=True)
            os.replace(tmp, self._path)  # atomic
            try:
                os.chmod(self._path, 0o600)
            except OSError:
                pass
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    # ---- synchronous reads (hot path) --------------------------------
    def get(self, name: str) -> AgentRecord | None:
        return self._agents.get(name)

    def list(self) -> list[AgentRecord]:
        return list(self._agents.values())

    def token_lookup(self, token: str) -> str | None:
        """Return the agent name for a bearer token, or None. Used by U1."""
        for rec in self._agents.values():
            if rec.token == token:
                return rec.name
        return None

    # ---- async mutators (serialized + persisted) ---------------------
    async def upsert(self, record: AgentRecord) -> None:
        async with self._lock:
            self._agents[record.name] = record
            self._save_unlocked()
        await self._notify()

    async def delete(self, name: str) -> None:
        async with self._lock:
            self._agents.pop(name, None)
            self._save_unlocked()
        await self._notify()

    async def set_session(self, name: str, session_id: str) -> None:
        changed = False
        async with self._lock:
            rec = self._agents.get(name)
            if rec is not None:
                rec.session_id = session_id
                self._save_unlocked()
                changed = True
        if changed:
            await self._notify()
