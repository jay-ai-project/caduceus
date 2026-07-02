"""Hermes agent-config codec (U10/R9): ConfigSnapshot ↔ the agent's on-disk state.

Mapping (confirmed against hermes 0.17.0 source — see the U10 plan's Spike Notes):
  * **soul**   ↔ `/opt/data/SOUL.md` (plain file; hermes re-reads it every prompt
    build, so changes apply next turn with no restart).
  * **skills** ↔ directories under `/opt/data/skills/` (re-scanned per prompt build).
    Listing/removal are supported; **adding** needs authored SKILL.md content a name
    can't provide, so `--add-skill` is rejected with guidance.
  * **tools**  ↔ the `platform_toolsets.api_server` list in config.yaml (the same key
    caduceus renders at provision time). Toolsets resolve at process start → restart.
  * **core**   ↔ free config.yaml scalars addressed as dotted keys
    (`agent.max_turns=100`). Values are parsed with yaml.safe_load on write and
    stringified with yaml.safe_dump on read, so read-back verification is consistent.

Caduceus-owned keys are protected: they are rejected from `--set` AND excluded from
the core view (`model.api_key` is a secret that must never be projected).
"""

from __future__ import annotations

import re

import yaml

from caduceus.agents.hermes_config import API_SERVER_TOOLSETS
from caduceus.common.dto import ConfigChange, ConfigSnapshot

#: config keys caduceus owns — breaking them bricks the agent (and model.* holds
#: the inline api_key secret). Matched as exact key or dotted prefix.
PROTECTED_CORE_KEYS = ("model", "approvals", "platform_toolsets", "terminal.cwd")

#: toolsets hermes 0.17.0 knows for the api_server platform: our rendered default
#: set plus the interactive-only / default-off ones a user may deliberately enable.
KNOWN_TOOLSETS = frozenset(API_SERVER_TOOLSETS) | {
    "clarify", "tts", "computer_use", "homeassistant", "spotify", "moa",
    "video", "x_search",
}

_SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _is_protected(key: str) -> bool:
    return any(key == p or key.startswith(p + ".") for p in PROTECTED_CORE_KEYS)


# ---- change validation (called by ConfigEditor before reducing) ----
def validate_change(change: ConfigChange) -> str | None:
    """Return a human error detail when the change can't be applied, else None."""
    if change.add_skills:
        return ("adding skills is not supported: a skill needs authored content "
                "(SKILL.md). Ask the agent to create/save the skill instead; "
                "caduceus can list and remove skills.")
    for name in change.remove_skills:
        if not _SKILL_NAME_RE.match(name or ""):
            return f"invalid skill name '{name}'"
    unknown = [t for t in (*change.enable_tools, *change.disable_tools)
               if t not in KNOWN_TOOLSETS]
    if unknown:
        return (f"unknown toolset(s): {', '.join(sorted(set(unknown)))} — valid: "
                f"{', '.join(sorted(KNOWN_TOOLSETS))}")
    protected = [k for k in change.set_core if _is_protected(k)]
    if protected:
        return (f"key(s) managed by caduceus and not settable: "
                f"{', '.join(sorted(protected))}")
    return None


# ---- yaml doc helpers ----------------------------------------------
def parse_config(text: str | None) -> dict:
    try:
        doc = yaml.safe_load(text or "")
    except yaml.YAMLError:
        return {}
    return doc if isinstance(doc, dict) else {}


def dump_config(doc: dict) -> str:
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)


def _scalar_str(v) -> str:
    """Stringify a config scalar the same way `--set` values are parsed, so
    write→read-back verification compares equal (true↔true, 100↔100)."""
    return yaml.safe_dump(v, default_flow_style=True).strip().removesuffix("\n...").strip()


def flatten_core(doc: dict) -> dict[str, str]:
    """Top-level scalars + one level of nested scalars as dotted keys, excluding
    caduceus-owned keys (which include the model.api_key secret)."""
    out: dict[str, str] = {}
    for key, value in doc.items():
        if _is_protected(str(key)):
            continue
        if isinstance(value, dict):
            for sub, sv in value.items():
                dotted = f"{key}.{sub}"
                if not _is_protected(dotted) and not isinstance(sv, (dict, list)):
                    out[dotted] = _scalar_str(sv)
        elif not isinstance(value, list):
            out[str(key)] = _scalar_str(value)
    return out


def _set_dotted(doc: dict, dotted: str, raw: str) -> None:
    try:
        value = yaml.safe_load(raw) if raw != "" else ""
    except yaml.YAMLError:
        value = raw
    parts = dotted.split(".")
    node = doc
    for p in parts[:-1]:
        nxt = node.get(p)
        if not isinstance(nxt, dict):
            nxt = {}
            node[p] = nxt
        node = nxt
    node[parts[-1]] = value


# ---- snapshot codec -------------------------------------------------
def snapshot_of(config_text: str | None, soul_text: str | None,
                skill_names: list[str]) -> ConfigSnapshot:
    doc = parse_config(config_text)
    pts = doc.get("platform_toolsets")
    enabled = (pts or {}).get("api_server") if isinstance(pts, dict) else None
    enabled = [str(t) for t in enabled] if isinstance(enabled, list) else []
    disabled = sorted(KNOWN_TOOLSETS - set(enabled))
    return ConfigSnapshot(
        skills=list(skill_names),
        tools_enabled=enabled,
        tools_disabled=disabled,
        soul=soul_text or "",
        core=flatten_core(doc),
    )


def merge_snapshot(config_text: str | None, snapshot: ConfigSnapshot) -> str:
    """Merge the snapshot's config-borne fields (tools, core) into config.yaml,
    preserving every other key (incl. the caduceus-owned protected ones)."""
    doc = parse_config(config_text)
    pts = doc.setdefault("platform_toolsets", {})
    if isinstance(pts, dict):
        pts["api_server"] = sorted(set(snapshot.tools_enabled))
    for dotted, raw in snapshot.core.items():
        if not _is_protected(dotted):
            _set_dotted(doc, dotted, raw)
    return dump_config(doc)
