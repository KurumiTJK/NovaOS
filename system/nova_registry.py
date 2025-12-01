"""
Registry utilities for commands and modules.
Handles:
- Loading commands.json
- Normalizing commands
- ModuleRegistry (v0.3 → v0.4.3 with dynamic module files)
"""

from __future__ import annotations

import json
import importlib.util
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
# v0.5.2 — Custom command normalization (prompt + macro)
# ------------------------------------------------------------
def _normalize_custom_command(name: str, meta: dict | None) -> dict:
    """
    Ensure every custom command has:
      - name
      - kind ("prompt" or "macro")
      - handler (handle_prompt_command / handle_macro)
      - sane defaults for prompt/macro fields.
    """
    meta = dict(meta or {})
    meta.setdefault("name", name)

    # kind: prompt or macro
    kind = meta.get("kind") or "prompt"
    if kind not in ("prompt", "macro"):
        kind = "prompt"
    meta["kind"] = kind

    # enabled default
    if "enabled" not in meta:
        meta["enabled"] = True

    if kind == "prompt":
        # Prompt commands are handled by handle_prompt_command
        meta.setdefault("handler", "handle_prompt_command")
        meta.setdefault("prompt_template", "{{full_input}}")
        if not isinstance(meta.get("input_mapping"), dict):
            meta["input_mapping"] = {"full_input": "full_input"}

    elif kind == "macro":
        # Macro commands are handled by handle_macro
        meta.setdefault("handler", "handle_macro")
        steps = meta.get("steps")
        if not isinstance(steps, list):
            meta["steps"] = []

    return meta

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
# Custom Commands loader (v0.5)
# ------------------------------------------------------------
def load_custom_commands(config: Config | None = None) -> Dict[str, Dict[str, Any]]:
    """
    Load commands_custom.json from config.data_dir.
    Returns a dict: {cmd_name: meta_dict}
    """
    if config is None:
        raise ValueError("load_custom_commands() requires a Config instance.")

    path = config.data_dir / "commands_custom.json"
    raw = _load_json(path, fallback={})

    if not isinstance(raw, dict):
        return {}

    # Ensure every entry is a dict and normalized (prompt + macro)
    normalized: Dict[str, Dict[str, Any]] = {}
    for name, meta in raw.items():
        if isinstance(meta, dict):
            normalized[name] = _normalize_custom_command(name, meta)

    return normalized


def save_custom_commands(config: Config, commands: Dict[str, Dict[str, Any]]):
    """
    Persist the given custom command registry to commands_custom.json.
    """
    path = config.data_dir / "commands_custom.json"
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as f:
        json.dump(commands, f, indent=2, ensure_ascii=False)

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
    # v0.4.3: dynamic module file path (relative to root_dir)
    file_path: Optional[str] = None


# ------------------------------------------------------------
# Module Registry (v0.3 → v0.4.3)
# ------------------------------------------------------------

class ModuleRegistry:
    """
    Handles reading/writing data/modules.json and providing
    high-level operations: list, forge, dismantle, inspect,
    bind-module, export/import.

    v0.4.3:
    - Adds dynamic module file creation and deletion.
    - Stores `file_path` in modules.json.
    - Provides a helper to dynamically import module code at runtime.
    """

    def __init__(self, config: Config):
        self.config = config
        self.modules_file = config.data_dir / "modules.json"

        # Try to use an explicit root_dir if Config exposes it; fall back
        # to data_dir's parent to remain backwards compatible.
        self.root_dir: Path = getattr(config, "root_dir", config.data_dir.parent)

        self._modules: Dict[str, ModuleMeta] = {}

        self._load()

    # --------------------------------------------------------
    # Load helpers
    # --------------------------------------------------------

    def _load(self):
        raw = _load_json(self.modules_file, fallback={})

        if isinstance(raw, dict):
            # v0.3+ dict format with optional file_path
            self._modules = {
                key: ModuleMeta(
                    key=key,
                    name=val.get("name", key),
                    mission=val.get("mission", ""),
                    state=val.get("state", "inactive"),
                    workflows=val.get("workflows", []),
                    routines=val.get("routines", []),
                    bindings=val.get("bindings", []),
                    file_path=val.get("file_path"),
                )
                for key, val in raw.items()
                if isinstance(val, dict)
            }
            return

        # v0.2 list format fallback
        if isinstance(raw, list):
            temp: Dict[str, ModuleMeta] = {}
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
                    file_path=entry.get("file_path"),
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
                "file_path": meta.file_path,
            }
            for key, meta in self._modules.items()
        }

        self.modules_file.parent.mkdir(parents=True, exist_ok=True)
        with self.modules_file.open("w", encoding="utf-8") as f:
            json.dump(serializable, f, indent=2, ensure_ascii=False)

    # --------------------------------------------------------
    # Internal helpers for file-based modules
    # --------------------------------------------------------

    def _modules_dir(self) -> Path:
        """
        Return the absolute path to the modules directory under the root.
        """
        return self.root_dir / "modules"

    def _default_module_filename(self, key: str) -> Path:
        """
        Default filename convention for generated module files.
        Example: finance -> modules/finance_module.py
        """
        return self._modules_dir() / f"{key}_module.py"

    def _ensure_module_file(self, key: str, name: str, mission: str) -> str:
        """
        Ensure a Python module file exists for the given module key.
        Returns the relative file path to store in ModuleMeta.file_path.
        """
        modules_dir = self._modules_dir()
        modules_dir.mkdir(parents=True, exist_ok=True)

        full_path = self._default_module_filename(key)

        if not full_path.exists():
            template = f'''"""
Auto-generated NovaOS module: {name}

Mission:
    {mission}

You can customize these functions. NovaOS will dynamically import and execute them.
"""

def init():
    \"\"\"Optional initialization hook for module '{key}'.\"\"\"
    return "Module {key} initialized."

def main():
    \"\"\"Main entry point placeholder for module '{key}'.\"\"\"
    return "Module {key} main() placeholder."

def info():
    \"\"\"Return basic metadata for module '{key}'.\"\"\"
    return {{
        "key": "{key}",
        "mission": "{mission}",
        "status": "ok",
    }}
'''
            with full_path.open("w", encoding="utf-8") as f:
                f.write(template)

        # Store file path relative to root_dir so NovaOS can be moved
        rel_path = full_path.relative_to(self.root_dir)
        return str(rel_path)

    def _delete_module_file(self, file_path: Optional[str]) -> None:
        """
        Delete the module file if it exists. Fail-safe: never raise.
        """
        if not file_path:
            return

        try:
            full_path = self.root_dir / file_path
            if full_path.exists():
                full_path.unlink()
        except Exception:
            # Deliberately swallow errors here; we don't want file deletion
            # to crash dismantle().
            pass

    # --------------------------------------------------------
    # Public API
    # --------------------------------------------------------

    def list(self) -> Dict[str, Dict[str, Any]]:
        return {
            key: {
                "name": meta.name,
                "mission": meta.mission,
                "state": meta.state,
                "workflows": meta.workflows,
                "routines": meta.routines,
                "bindings": meta.bindings,
                "file_path": meta.file_path,
            }
            for key, meta in self._modules.items()
        }

    def forge_module(
        self,
        key: str,
        name: str,
        mission: str,
        state: str = "inactive",
        workflows: Optional[List[dict]] = None,
        routines: Optional[List[dict]] = None,
        *,
        create_file: bool = True,
    ) -> ModuleMeta:
        """
        Create or update module metadata and (optionally) generate
        a backing Python module file on disk.

        v0.4.3:
        - If create_file is True, ensure a file exists under modules/.
        - Set meta.file_path accordingly.
        """
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

        # v0.4.3: dynamic module file creation
        if create_file:
            meta.file_path = self._ensure_module_file(key=key, name=name, mission=mission)

        self._save()
        return meta

    def dismantle_module(self, key: str) -> bool:
        """
        Remove a module and (if present) delete its backing Python file.
        """
        if key in self._modules:
            meta = self._modules[key]

            # v0.4.3: delete associated module file, if any
            self._delete_module_file(meta.file_path)

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
                "file_path": meta.file_path,
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
                file_path=val.get("file_path"),
            )
            for key, val in state.items()
            if isinstance(val, dict)
        }
        self._save()

    # --------------------------------------------------------
    # Runtime dynamic import (v0.4.3)
    # --------------------------------------------------------

    def load_module_runtime(self, key: str):
        """
        Dynamically import the Python module for the given key, if any.

        Returns:
            - Imported module object on success.
            - None if no module or file not found.

        Usage example:
            mod = kernel.module_registry.load_module_runtime("finance")
            if mod and hasattr(mod, "main"):
                result = mod.main()
        """
        meta = self._modules.get(key)
        if not meta or not meta.file_path:
            return None

        full_path = self.root_dir / meta.file_path
        if not full_path.exists():
            return None

        spec = importlib.util.spec_from_file_location(key, full_path)
        if spec is None or spec.loader is None:
            return None

        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception:
            return None

        return module

# ------------------------------------------------------------
# Custom Command Registry (v0.5)
# ------------------------------------------------------------

class CustomCommandRegistry:
    """
    Reads/writes custom commands (prompt + macro).
    Integrated with nova_registry, but separate from module registry.
    """

    def __init__(self, config: Config):
        self.config = config
        self.file = config.data_dir / "commands_custom.json"
        self._commands = load_custom_commands(config)

    # Public API
    def list(self) -> Dict[str, Dict[str, Any]]:
        return dict(self._commands)

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        meta = self._commands.get(name)
        if meta is None:
            return None

        # Re-normalize in case it was edited on disk or missing fields
        norm = _normalize_custom_command(name, meta)
        self._commands[name] = norm
        save_custom_commands(self.config, self._commands)
        return norm

    def add(self, name: str, meta: Dict[str, Any]):
        norm = _normalize_custom_command(name, meta)
        self._commands[name] = norm
        save_custom_commands(self.config, self._commands)

    def remove(self, name: str) -> bool:
        if name in self._commands:
            del self._commands[name]
            save_custom_commands(self.config, self._commands)
            return True
        return False

    def toggle(self, name: str) -> bool:
        cmd = self._commands.get(name)
        if not cmd:
            return False
        enabled = cmd.get("enabled", True)
        cmd["enabled"] = not enabled
        save_custom_commands(self.config, self._commands)
        return True

