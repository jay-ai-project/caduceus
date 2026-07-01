"""ControlAPIClient — loopback HTTP client to the daemon (C2).

Synchronous (httpx.Client) over TCP to `127.0.0.1:9700`; SSE consumption for
`chat`/`logs`. Real transport is exercised in Build & Test; CLI unit tests use a
fake client with this same method surface.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Optional

from caduceus.common.dto import (
    AgentView,
    ConfigChange,
    ConfigResult,
    ConfigSnapshot,
    CreateSpec,
    GatewayConfigChange,
    GatewayConfigView,
    GatewayStatus,
    RegisterSpec,
)
from caduceus.transport.events import ChatEvent


class ControlError(Exception):
    def __init__(self, message: str, exit_code: int = 1):
        super().__init__(message)
        self.exit_code = exit_code


class ControlAPIClient:
    def __init__(self, base_url: str = "http://127.0.0.1:9700", client=None, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = client  # injected httpx.Client (or None → lazy)

    def _c(self):
        if self._client is None:
            import httpx

            self._client = httpx.Client(base_url=self.base_url, timeout=self._timeout)
        return self._client

    def _json(self, resp):
        if resp.status_code >= 400:
            raise ControlError(_err_message(resp))
        return resp.json()

    def is_daemon_up(self) -> bool:
        try:
            r = self._c().get("/healthz")
            return r.status_code == 200
        except Exception:  # noqa: BLE001
            return False

    def status(self) -> GatewayStatus:
        return GatewayStatus.from_dict(self._json(self._c().get("/status")))

    #: provisioning (image build + sandbox create) can take minutes — well past
    #: the default per-call timeout (Build & Test, Finding E, 2026-06-30).
    PROVISION_TIMEOUT = 1800.0

    def create_agent(self, spec: CreateSpec, wait: bool = False) -> Iterator[dict]:
        """Create an agent. Default (`wait=False`) yields a single
        `{"event": "accepted", ...}` and provisioning continues in the background.
        `wait=True` streams `{"event": "progress"|"done", ...}` until ready. Raises
        ControlError on failure."""
        with self._c().stream("POST", "/agents", json=spec.to_dict(),
                              params={"wait": wait}, timeout=self.PROVISION_TIMEOUT) as resp:
            if resp.status_code >= 400:
                resp.read()
                raise ControlError(_err_message(resp))
            for line in resp.iter_lines():
                obj = _parse_sse_data(line)
                if obj is None:
                    continue
                if obj.get("event") == "error":
                    raise ControlError(obj.get("message", "create failed"))
                yield obj

    def register_agent(self, spec: RegisterSpec) -> dict:
        return self._json(self._c().post("/agents/register", json=spec.to_dict()))

    def list_agents(self, deep: bool = False) -> list[AgentView]:
        data = self._json(self._c().get("/agents", params={"deep": deep}))
        return [AgentView.from_dict(d) for d in data]

    def remove_agent(self, name: str, force: bool = False) -> None:
        r = self._c().delete(f"/agents/{name}", params={"force": force})
        if r.status_code >= 400:
            raise ControlError(_err_message(r))

    def stop_agent(self, name: str) -> AgentView:
        return AgentView.from_dict(self._json(self._c().post(f"/agents/{name}/stop")))

    def start_agent(self, name: str) -> AgentView:
        return AgentView.from_dict(self._json(self._c().post(f"/agents/{name}/start")))

    def get_config(self, name: str) -> ConfigSnapshot:
        return ConfigSnapshot.from_dict(self._json(self._c().get(f"/agents/{name}/config")))

    def set_config(self, name: str, change: ConfigChange) -> ConfigResult:
        return ConfigResult.from_dict(self._json(self._c().put(f"/agents/{name}/config", json=change.to_dict())))

    def get_gateway_config(self) -> GatewayConfigView:
        return GatewayConfigView.from_dict(self._json(self._c().get("/gateway/config")))

    def set_gateway_config(self, change: GatewayConfigChange) -> GatewayConfigView:
        r = self._c().post("/gateway/config", json=change.to_dict())
        if r.status_code == 400:  # validation error → usage exit code (BR-GC2/GC3)
            raise ControlError(_err_message(r), exit_code=2)
        return GatewayConfigView.from_dict(self._json(r))

    def chat(self, name: str, message: str) -> Iterator[ChatEvent]:
        with self._c().stream("POST", f"/agents/{name}/chat", json={"message": message}) as resp:
            if resp.status_code >= 400:
                raise ControlError(f"chat failed (HTTP {resp.status_code})")
            for line in resp.iter_lines():
                ev = _parse_sse_event(line)
                if ev is not None:
                    yield ev

    def logs(self, name: str, follow: bool = False) -> Iterator[str]:
        with self._c().stream("GET", f"/agents/{name}/logs", params={"follow": follow}) as resp:
            if resp.status_code >= 400:
                raise ControlError(_err_message(resp))
            for line in resp.iter_lines():
                obj = _parse_sse_data(line)
                if obj is not None and "line" in obj:
                    yield obj["line"]


def _err_message(resp) -> str:
    try:
        body = resp.json()
        if isinstance(body, dict) and "error" in body:
            return body["error"].get("message", str(body))
    except Exception:  # noqa: BLE001
        pass
    return f"HTTP {resp.status_code}"


def _parse_sse_data(line: str) -> Optional[dict]:
    if not line or not line.startswith("data:"):
        return None
    payload = line[len("data:"):].strip()
    try:
        return json.loads(payload)
    except (ValueError, TypeError):
        return None


def _parse_sse_event(line: str) -> Optional[ChatEvent]:
    obj = _parse_sse_data(line)
    if obj is None or "type" not in obj:
        return None
    return ChatEvent.from_dict(obj)
