"""ConfigService — get/set agent config (FR-E1/E2).

Local agents are editable; remote agents are **read-only** in v1 → `set_config`
raises `ReadOnlyError` (BR-E1). The exact soul-file read happens here (edge I/O)
before delegating the pure reduction to `ConfigEditor`.
"""

from __future__ import annotations

from pathlib import Path

from caduceus.common.dto import ConfigChange, ConfigResult, ConfigSnapshot
from caduceus.common.errors import invalid_request_error
from caduceus.common.models import AgentKind
from caduceus.config.editor import ConfigEditor, ReadOnlyError


class ConfigService:
    def __init__(self, registry, editor: ConfigEditor):
        self.registry = registry
        self.editor = editor

    def _require(self, name: str):
        rec = self.registry.get(name)
        if rec is None:
            raise invalid_request_error(f"no such agent '{name}'")
        return rec

    async def get_config(self, name: str) -> ConfigSnapshot:
        rec = self._require(name)
        if rec.kind == AgentKind.remote:
            raise ReadOnlyError("remote agent config is not available in v1 (read/observe only)")
        return await self.editor.read(rec)

    async def set_config(self, name: str, change: ConfigChange) -> ConfigResult:
        rec = self._require(name)
        if rec.kind == AgentKind.remote:
            raise ReadOnlyError("remote agent config is read-only in v1; editing is not supported")
        # resolve --soul-file into inline soul text (edge I/O) before pure reduce
        if change.soul_file is not None and change.soul is None:
            change = _with_soul_from_file(change)
        return await self.editor.apply(rec, change)


def _with_soul_from_file(change: ConfigChange) -> ConfigChange:
    text = Path(change.soul_file).read_text(encoding="utf-8")
    return ConfigChange(
        add_skills=change.add_skills, remove_skills=change.remove_skills,
        enable_tools=change.enable_tools, disable_tools=change.disable_tools,
        soul=text, soul_file=None, set_core=change.set_core,
    )
