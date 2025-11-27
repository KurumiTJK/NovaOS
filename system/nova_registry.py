# system/nova_registry.py
import json
from pathlib import Path
from typing import Dict, Any, List
from system.config import CONFIG_DIR  # Import CONFIG_DIR, not DATA_DIR

COMMANDS_FILE = CONFIG_DIR / "commands.json"
MODULES_FILE = CONFIG_DIR / "modules.json"

def _load_json(path: Path, default):
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(default, f, indent=2)
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def _save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def load_commands() -> Dict[str, Dict[str, Any]]:
    """
    Dynamic syscommand registry.
    commands.json is the single source of truth.
    """
    # Minimal v0.1 default ONLY for first boot.
    default_commands = {
        "why": {
            "handler": "handle_why",
            "category": "core",
            "description": "State NovaOS purpose, philosophy, and identity"
        },
        "boot": {
            "handler": "handle_boot",
            "category": "core",
            "description": "Initialize NovaOS kernel and persona"
        },
        "reset": {
            "handler": "handle_reset",
            "category": "core",
            "description": "Reload system memory and modules"
        },
        "status": {
            "handler": "handle_status",
            "category": "core",
            "description": "Display system state"
        },
        "help": {
            "handler": "handle_help",
            "category": "core",
            "description": "List all syscommands"
        }
    }

    # After first run, whatever is in commands.json *is* the registry.
    return _load_json(COMMANDS_FILE, default_commands)

def save_commands(commands: Dict[str, Dict[str, Any]]):
    _save_json(COMMANDS_FILE, commands)

def load_modules() -> List[Dict[str, Any]]:
    return _load_json(MODULES_FILE, [])

def save_modules(modules: List[Dict[str, Any]]):
    _save_json(MODULES_FILE, modules)
