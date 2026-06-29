"""Bearer-token authentication (BR-1).

A `token_lookup` callable maps a raw token -> agent_id (or None). It is injected
(owned by the U2 Registry); U1 stays decoupled from storage.
"""

from __future__ import annotations

from collections.abc import Callable

from caduceus.common.errors import authentication_error

TokenLookup = Callable[[str], "str | None"]


def parse_bearer(authorization: str | None) -> str:
    if not authorization:
        raise authentication_error()
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise authentication_error()
    return parts[1].strip()


def authenticate(authorization: str | None, token_lookup: TokenLookup) -> str:
    """Return the agent_id for a valid token, else raise ProxyError(401)."""
    token = parse_bearer(authorization)
    agent_id = token_lookup(token)
    if not agent_id:
        raise authentication_error("Unknown API key")
    return agent_id
