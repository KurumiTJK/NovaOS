# system/nova_registry.py
"""
Registry utilities for commands and modules.
Handles:
- Loading commands.json
- Normalizing commands
- ModuleRegistry (v0.3)
"""

from __future__ import annotations
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, List, Optional

from system.config import Config


# ------------------------------------------------------------
# Internal JSON loader
# ------------------------------------------------------------
def _load_json(path: Path, fallback: Any) -> Any:
    """
    Load JSON safely; if the file does not exist or is invalid,
    return the fallback.
    """
    if not path.exists():
        return fallback
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return fallback


# ------------------------------------------------------------
# Commands loader (v0.3)
# ------------------------------------------------------------
def load_commands(config: Config | None = None) -> Dict[str, Dict[str, Any]]:
    """
    Load commands.json from config.data_dir/commands.json.
    Always returns a dict {cmd_name: meta_dict}.
    """
    if config is None:
        raise ValueError("load_commands() requires a Config instance.")

    commands_path = config.data_dir / "commands.json"
    default_commands: Dict[str, Dict[str, Any]] = {}

    raw = _load_json(commands_path, fallback=default_commands)

    if isinstance(raw, dict):
        return raw

    # Handle old v0.2 list formats
    normalized: Dict[str, Dict[str, Any]] = {}
    if isinstance(raw, list):
        for entry in raw:
            if not isinstance(entry, dict):
                continue

            # Case 1: {"name": "boot", "handler": "...", ...}
            name = entry.get("name") or entry.get("command") or entry.get("cmd")
            if name:
                meta = {
                    k: v
                    for k, v in entry.items()
                    if k not in ("name", "command", "cmd")
                }
                normalized[name] = meta
                continue

            # Case 2: {"boot": {...}}
            if len(entry) == 1:
                k, v = next(iter(entry.items()))
                if isinstance(v, dict):
                    normalized[k] = v
                    continue

    return normalized


# ------------------------------------------------------------
# Module metadata
# ------------------------------------------------------------

@dataclass
class ModuleMeta:
    key: str
    name: str
    mission: str
    state: str = "inactive"
    workflows: List[Dict[str, Any]] = field(default_factory=list)
    routines: List[Dict[str, Any]] = field(default_factory=list)
    bindings: List[str] = field(default_factory=list)


# ------------------------------------------------------------
# Module Registry (v0.3)
# ------------------------------------------------------------

class ModuleRegistry:
    """
    Handles reading/writing data/modules.json and providing
    high-level operations: list, forge, dismantle, inspect,
    bind-module, export/import.
    """

    def __init__(self, config: Config):
        self.config = config
        self.modules_file = config.data_dir / "modules.json"
        self._modules: Dict[str, ModuleMeta] = {}

        self._load()

    # --------------------------------------------------------

    def _load(self):
        raw = _load_json(self.modules_file, fallback={})

        if isinstance(raw, dict):
            # v0.3 dict format
            self._modules = {
                key: ModuleMeta(
                    key=key,
                    name=val.get("name", key),
                    mission=val.get("mission", ""),
                    state=val.get("state", "inactive"),
                    workflows=val.get("workflows", []),
                    routines=val.get("routines", []),
                    bindings=val.get("bindings", []),
                )
                for key, val in raw.items()
                if isinstance(val, dict)
            }
            return

        # v0.2 list format fallback
        if isinstance(raw, list):
            temp = {}
            for entry in raw:
                if not isinstance(entry, dict):
                    continue

                key = entry.get("key")
                if not key:
                    continue

                temp[key] = ModuleMeta(
                    key=key,
                    name=entry.get("name", key),
                    mission=entry.get("mission", ""),
                    state=entry.get("state", "inactive"),
                    workflows=entry.get("workflows", []),
                    routines=entry.get("routines", []),
                    bindings=entry.get("bindings", []),
                )
            self._modules = temp

    # --------------------------------------------------------
    # Save helper
    # --------------------------------------------------------

    def _save(self):
        serializable = {
            key: {
                "name": meta.name,
                "mission": meta.mission,
                "state": meta.state,
                "workflows": meta.workflows,
                "routines": meta.routines,
                "bindings": meta.bindings,
            }
            for key, meta in self._modules.items()
        }

        self.modules_file.parent.mkdir(parents=True, exist_ok=True)
        with self.modules_file.open("w", encoding="utf-8") as f:
            json.dump(serializable, f, indent=2)

    # --------------------------------------------------------
    # Public API
    # --------------------------------------------------------

    def list_modules(self) -> List[ModuleMeta]:
        return list(self._modules.values())

    def forge_module(
        self,
        key: str,
        name: str,
        mission: str,
        state: str = "inactive",
        workflows: Optional[List[dict]] = None,
        routines: Optional[List[dict]] = None,
    ) -> ModuleMeta:

        if key in self._modules:
            # update existing
            meta = self._modules[key]
            meta.name = name
            meta.mission = mission
            meta.state = state
            if workflows is not None:
                meta.workflows = workflows
            if routines is not None:
                meta.routines = routines
        else:
            meta = ModuleMeta(
                key=key,
                name=name,
                mission=mission,
                state=state,
                workflows=workflows or [],
                routines=routines or [],
            )
            self._modules[key] = meta

        self._save()
        return meta

    def dismantle_module(self, key: str) -> bool:
        if key in self._modules:
            del self._modules[key]
            self._save()
            return True
        return False

    def inspect_module(self, key: str) -> Optional[ModuleMeta]:
        return self._modules.get(key)

    def bind_modules(self, key_a: str, key_b: str) -> bool:
        a = self._modules.get(key_a)
        b = self._modules.get(key_b)
        if not a or not b:
            return False

        if key_b not in a.bindings:
            a.bindings.append(key_b)
        if key_a not in b.bindings:
            b.bindings.append(key_a)

        self._save()
        return True

    # --------------------------------------------------------
    # Backwards-compatible convenience aliases (v0.3)
    # --------------------------------------------------------

    def forge(
        self,
        *,
        key: str,
        name: str,
        mission: str,
        state: str = "inactive",
        workflows: Optional[List[dict]] = None,
        routines: Optional[List[dict]] = None,
    ) -> ModuleMeta:
        """Alias for forge_module to match syscommand handlers."""
        return self.forge_module(
            key=key,
            name=name,
            mission=mission,
            state=state,
            workflows=workflows,
            routines=routines,
        )

    def dismantle(self, key: str) -> bool:
        """Alias for dismantle_module to match syscommand handlers."""
        return self.dismantle_module(key)

    def get(self, key: str) -> Optional[ModuleMeta]:
        """Alias for inspect_module to match syscommand handlers."""
        return self.inspect_module(key)

    # --------------------------------------------------------
    # Snapshot support
    # --------------------------------------------------------

    def export_state(self) -> dict:
        return {
            key: {
                "name": meta.name,
                "mission": meta.mission,
                "state": meta.state,
                "workflows": meta.workflows,
                "routines": meta.routines,
                "bindings": meta.bindings,
            }
            for key, meta in self._modules.items()
        }

    def import_state(self, state: dict):
        self._modules = {
            key: ModuleMeta(
                key=key,
                name=val.get("name", key),
                mission=val.get("mission", ""),
                state=val.get("state", "inactive"),
                workflows=val.get("workflows", []),
                routines=val.get("routines", []),
                bindings=val.get("bindings", []),
            )
            for key, val in state.items()
            if isinstance(val, dict)
        }
        self._save()
