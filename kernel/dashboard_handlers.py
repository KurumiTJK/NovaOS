# kernel/dashboard_handlers.py
"""
NovaOS Dashboard — Core System Dashboard

Provides #dashboard and #dashboard-view syscommands for at-a-glance system status.

Dashboard Sections:
1. Header (instance info, mode, date/time)
2. Today Readiness (sleep, energy, stress, focus, mood, HP)
3. Module Status (domain progress overview)
4. Finance Snapshot (static rules/plan)
5. System Health (ops status)

Two view modes:
- compact: Single-line summaries
- full: Expanded multi-line blocks

Config stored in: config/dashboard.json
"""

from __future__ import annotations

import json
import os
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Literal

from .command_types import CommandResponse

ViewMode = Literal["compact", "full"]

# =============================================================================
# CONFIG MANAGEMENT
# =============================================================================

def _get_config_path(data_dir: Optional[Path] = None) -> Path:
    """Get the dashboard config file path."""
    if data_dir:
        config_dir = data_dir.parent / "config"
    else:
        # Fallback: use relative path from project root
        base = Path(__file__).resolve().parent.parent
        config_dir = base / "config"
    return config_dir / "dashboard.json"


def _get_default_config() -> Dict[str, Any]:
    """Return default dashboard configuration."""
    return {
        "auto_show_on_launch": True,
        "default_view": "compact",
        "sections": [
            "header",
            "today_readiness",
            "module_status",
            "finance_snapshot",
            "system_health",
        ],
    }


def load_dashboard_config(data_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Load dashboard configuration from disk."""
    config_path = _get_config_path(data_dir)
    
    if not config_path.exists():
        # Create default config
        config = _get_default_config()
        save_dashboard_config(config, data_dir)
        return config
    
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        # Ensure all required keys exist
        default = _get_default_config()
        for key, value in default.items():
            if key not in config:
                config[key] = value
        return config
    except (json.JSONDecodeError, IOError):
        return _get_default_config()


def save_dashboard_config(config: Dict[str, Any], data_dir: Optional[Path] = None) -> bool:
    """Save dashboard configuration to disk."""
    config_path = _get_config_path(data_dir)
    
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        return True
    except IOError:
        return False


# =============================================================================
# SAFE DATA LOADERS (no crashes on missing data)
# =============================================================================

def _safe_get(data: Any, *keys: str, default: Any = "--") -> Any:
    """Safely traverse nested dicts, returning default if any key missing."""
    current = data
    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return default
    return current if current is not None else default


def _load_timerhythm_state(kernel: Any) -> Dict[str, Any]:
    """Load timerhythm state safely."""
    try:
        # Try kernel's time_rhythm_manager
        if hasattr(kernel, "time_rhythm_manager") and kernel.time_rhythm_manager:
            manager = kernel.time_rhythm_manager
            if hasattr(manager, "_load_state"):
                state = manager._load_state()
                if hasattr(state, "today"):
                    return state.today.__dict__ if hasattr(state.today, "__dict__") else {}
        
        # Fallback: load from file directly
        data_dir = getattr(kernel, "config", None)
        if data_dir and hasattr(data_dir, "data_dir"):
            tr_path = data_dir.data_dir / "timerhythm.json"
        else:
            tr_path = Path(__file__).resolve().parent.parent / "data" / "timerhythm.json"
        
        if tr_path.exists():
            with open(tr_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("today", {})
    except Exception:
        pass
    return {}


def _load_modules_state(kernel: Any) -> list:
    """Load modules state safely."""
    try:
        # Try kernel's module store
        if hasattr(kernel, "module_store") and kernel.module_store:
            modules = kernel.module_store.list_all(include_archived=False)
            return [m.to_dict() if hasattr(m, "to_dict") else {} for m in modules]
        
        # Fallback: load from file directly
        data_dir = getattr(kernel, "config", None)
        if data_dir and hasattr(data_dir, "data_dir"):
            mod_path = data_dir.data_dir / "modules.json"
        else:
            mod_path = Path(__file__).resolve().parent.parent / "data" / "modules.json"
        
        if mod_path.exists():
            with open(mod_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "modules" in data:
                return data["modules"]
            elif isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def _load_identity_state(kernel: Any) -> Dict[str, Any]:
    """Load identity/player profile state safely."""
    try:
        # Try kernel's identity manager
        if hasattr(kernel, "identity_manager") and kernel.identity_manager:
            return kernel.identity_manager.get_profile_summary()
        
        # Try legacy player_profile_manager
        if hasattr(kernel, "player_profile_manager") and kernel.player_profile_manager:
            profile = kernel.player_profile_manager.get_profile()
            if hasattr(profile, "to_dict"):
                return profile.to_dict()
            return profile.__dict__ if hasattr(profile, "__dict__") else {}
        
        # Fallback: load from file directly
        data_dir = getattr(kernel, "config", None)
        if data_dir and hasattr(data_dir, "data_dir"):
            id_path = data_dir.data_dir / "identity.json"
        else:
            id_path = Path(__file__).resolve().parent.parent / "data" / "identity.json"
        
        if id_path.exists():
            with open(id_path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _load_memory_count(kernel: Any) -> int:
    """Get count of long-term memories."""
    try:
        if hasattr(kernel, "memory_manager") and kernel.memory_manager:
            if hasattr(kernel.memory_manager, "count"):
                return kernel.memory_manager.count()
            if hasattr(kernel.memory_manager, "list_all"):
                return len(kernel.memory_manager.list_all())
    except Exception:
        pass
    return 0


def _get_last_error(kernel: Any) -> Optional[str]:
    """Get last logged error if available."""
    try:
        if hasattr(kernel, "logger") and kernel.logger:
            if hasattr(kernel.logger, "last_error"):
                return kernel.logger.last_error
    except Exception:
        pass
    return None


def _get_last_save_time(kernel: Any) -> str:
    """Get last save timestamp."""
    try:
        data_dir = getattr(kernel, "config", None)
        if data_dir and hasattr(data_dir, "data_dir"):
            # Check most recent data file modification
            for fname in ["timerhythm.json", "identity.json", "modules.json"]:
                fpath = data_dir.data_dir / fname
                if fpath.exists():
                    mtime = datetime.fromtimestamp(fpath.stat().st_mtime)
                    return mtime.strftime("%H:%M")
    except Exception:
        pass
    return "--"


def _check_data_integrity(kernel: Any) -> str:
    """Check if core data files exist and are valid."""
    try:
        data_dir = getattr(kernel, "config", None)
        if data_dir and hasattr(data_dir, "data_dir"):
            required = ["commands.json"]
            for fname in required:
                fpath = data_dir.data_dir / fname
                if not fpath.exists():
                    return f"Missing:{fname}"
                try:
                    with open(fpath, "r") as f:
                        json.load(f)
                except json.JSONDecodeError:
                    return f"Corrupt:{fname}"
        return "OK"
    except Exception as e:
        return f"Err:{str(e)[:10]}"


# =============================================================================
# SECTION RENDERERS
# =============================================================================

def _render_header(view: ViewMode, kernel: Any, state: Any = None) -> str:
    """Render the header section."""
    # Get current time in LA timezone
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/Los_Angeles")
    except ImportError:
        tz = timezone.utc
    
    now = datetime.now(tz)
    date_str = now.strftime("%A, %B %d %Y")
    time_str = now.strftime("%I:%M %p")
    
    # Get hostname
    try:
        hostname = socket.gethostname()
        if len(hostname) > 15:
            hostname = hostname[:15] + "..."
    except Exception:
        hostname = "local"
    
    # Get mode
    mode = "STRICT"
    if state and hasattr(state, "novaos_enabled"):
        mode = "STRICT" if state.novaos_enabled else "PERSONA"
    elif kernel:
        env = getattr(kernel, "env_state", {})
        mode = env.get("mode", "STRICT").upper()
    
    # Get version/branch
    version = "--"
    branch = "--"
    try:
        # Check for version file
        base = Path(__file__).resolve().parent.parent
        version_file = base / "VERSION"
        if version_file.exists():
            version = version_file.read_text().strip()
        # Check git branch
        git_head = base / ".git" / "HEAD"
        if git_head.exists():
            head_content = git_head.read_text().strip()
            if head_content.startswith("ref: refs/heads/"):
                branch = head_content.replace("ref: refs/heads/", "")
    except Exception:
        pass
    
    if view == "compact":
        return f"|==== NOVAOS DASHBOARD ====| Mode: {mode} | {date_str} {time_str}"
    
    # Full view
    lines = [
        "|==================== NOVAOS DASHBOARD ====================|",
        f"Instance: {hostname:<20} Mode: {mode}",
        f"Date: {date_str:<20} Time: {time_str} (America/Los_Angeles)",
        f"Build: {version:<20} Branch: {branch}",
        "|==========================================================|",
    ]
    return "\n".join(lines)


def _render_today_readiness(view: ViewMode, kernel: Any) -> str:
    """Render the Today Readiness section."""
    tr = _load_timerhythm_state(kernel)
    
    sleep = _safe_get(tr, "sleep")
    energy = _safe_get(tr, "energy")
    stress = _safe_get(tr, "stress")
    mood = _safe_get(tr, "mood")
    hp = _safe_get(tr, "hp")
    
    # Derive focus from energy if not present
    focus = _safe_get(tr, "focus")
    if focus == "--" and energy != "--":
        try:
            focus = int(energy) * 20  # Simple derivation
        except (ValueError, TypeError):
            focus = "--"
    
    if view == "compact":
        return f"[Readiness] Sleep {sleep} | Energy {energy} | Stress {stress} | Focus {focus} | Mood {mood} | HP {hp}"
    
    # Full view
    morning_at = _safe_get(tr, "morning_completed_at")
    evening_at = _safe_get(tr, "evening_completed_at")
    
    last_checkin = "--"
    next_checkin = "Morning"
    
    morning_done = _safe_get(tr, "morning_completed", False)
    evening_done = _safe_get(tr, "evening_completed", False)
    night_done = _safe_get(tr, "night_completed", False)
    
    if night_done:
        next_checkin = "Tomorrow Morning"
        last_checkin = _safe_get(tr, "night_completed_at", "--")
    elif evening_done:
        next_checkin = "Night"
        last_checkin = evening_at if evening_at else "--"
    elif morning_done:
        next_checkin = "Evening"
        last_checkin = morning_at if morning_at else "--"
    
    lines = [
        "┌─ Today Readiness ─────────────────────────────────────────┐",
        f"│  Sleep: {str(sleep):<8}  Energy: {str(energy):<8}  Stress: {str(stress):<8}│",
        f"│  Focus: {str(focus):<8}  Mood: {str(mood):<10}  HP: {str(hp):<8}│",
        f"│  Last Check-in: {str(last_checkin):<15}  Next: {next_checkin:<12}│",
        "└──────────────────────────────────────────────────────────┘",
    ]
    return "\n".join(lines)


def _render_module_status(view: ViewMode, kernel: Any) -> str:
    """Render the Module Status section."""
    modules = _load_modules_state(kernel)
    identity = _load_identity_state(kernel)
    
    # Get module XP from identity
    module_xp = identity.get("modules", {})
    if isinstance(module_xp, list):
        # Handle list format from get_profile_summary
        module_xp = {m.get("name", ""): {"xp": m.get("xp", 0), "level": m.get("level", 1)} for m in module_xp if isinstance(m, dict)}
    
    # Build module info list
    module_info = []
    for m in modules[:6]:  # Limit to 6 for display
        if isinstance(m, dict):
            name = m.get("name", "?")
            status = m.get("status", "active")
            phase = m.get("phase", "planning")
            
            # Get XP info
            xp_data = module_xp.get(name, {})
            if isinstance(xp_data, dict):
                xp = xp_data.get("xp", 0)
                level = xp_data.get("level", 1)
            else:
                xp = xp_data if isinstance(xp_data, (int, float)) else 0
                level = 1
            
            # Abbreviate status
            status_abbr = "OK" if status == "active" else "IP" if status == "in_progress" else "NS"
            
            module_info.append({
                "name": name[:12],  # Truncate long names
                "status": status_abbr,
                "phase": phase[0].upper() if phase else "P",
                "xp": xp,
                "level": level,
            })
    
    if not module_info:
        if view == "compact":
            return "[Modules] No modules defined"
        return "┌─ Module Status ─┐\n│  No modules     │\n└─────────────────┘"
    
    if view == "compact":
        parts = []
        for m in module_info[:4]:  # Max 4 in compact
            # Format: Name P_xp/target(status)
            target = 50 * m["level"]  # XP to next level
            parts.append(f"{m['name'][:6]} {m['phase']}{m['xp']}/{target}({m['status']})")
        return f"[Modules] {' | '.join(parts)}"
    
    # Full view
    lines = ["┌─ Module Status ────────────────────────────────────────────┐"]
    for m in module_info:
        target = 50 * m["level"]
        progress = min(100, int((m["xp"] / max(target, 1)) * 100))
        bar = "█" * (progress // 10) + "░" * (10 - progress // 10)
        lines.append(f"│  {m['name']:<12} [{bar}] {m['xp']:>4}/{target:<4} L{m['level']} ({m['status']})  │")
    lines.append("└───────────────────────────────────────────────────────────┘")
    return "\n".join(lines)


def _render_finance_snapshot(view: ViewMode, kernel: Any) -> str:
    """Render the Finance Snapshot section with static rules."""
    # These are user-specific static rules as specified
    if view == "compact":
        return "[Finance] $425 stocks/wk | $200 SPAXX/wk | Wed buys | LEAPS only Q-C | FHA Apr-Dec 2027"
    
    # Full view
    lines = [
        "┌─ Finance Snapshot ─────────────────────────────────────────┐",
        "│  Weekly Plan:                                              │",
        "│    • $425 → Stocks                                         │",
        "│    • $200 → SPAXX                                          │",
        "│  Buy Day: Wednesday                                        │",
        "│  LEAPS: Quadrant C only (Apr-Sep 2026 target)              │",
        "│  FHA Purchase: Apr-Dec 2027                                │",
        "│  Liquidation Order:                                        │",
        "│    SPAXX → SCHD/GLDM/some VTI → META/TSM → MSFT/AVUV → NVDA│",
        "└───────────────────────────────────────────────────────────┘",
    ]
    return "\n".join(lines)


def _render_system_health(view: ViewMode, kernel: Any, state: Any = None) -> str:
    """Render the System Health section."""
    # Get persona fallback status
    pf_status = "Off"
    if state and hasattr(state, "novaos_enabled"):
        pf_status = "Off" if state.novaos_enabled else "On"
    
    memory_count = _load_memory_count(kernel)
    data_status = _check_data_integrity(kernel)
    last_save = _get_last_save_time(kernel)
    last_error = _get_last_error(kernel)
    
    err_str = "None" if not last_error else last_error[:20]
    
    if view == "compact":
        return f"[System] PF:{pf_status} | Memory:{memory_count} | Data:{data_status} | LastSave:{last_save} | Err:{err_str}"
    
    # Full view
    mode = "STRICT" if state and state.novaos_enabled else "PERSONA"
    lines = [
        "┌─ System Health ────────────────────────────────────────────┐",
        f"│  Mode: {mode:<12}  Persona Fallback: {pf_status:<8}           │",
        f"│  Memory Count: {memory_count:<6}  Data Integrity: {data_status:<10}      │",
        f"│  Last Save: {last_save:<10}  Last Error: {err_str:<18}    │",
        "└───────────────────────────────────────────────────────────┘",
    ]
    return "\n".join(lines)


# =============================================================================
# MAIN RENDER FUNCTION
# =============================================================================

def render_dashboard(
    view: ViewMode = "compact",
    kernel: Any = None,
    state: Any = None,
    sections: Optional[list] = None,
) -> str:
    """
    Render the full dashboard.
    
    Args:
        view: "compact" or "full"
        kernel: NovaKernel instance (for data access)
        state: NovaState instance (for mode info)
        sections: List of section names to include (uses config if None)
    
    Returns:
        Complete dashboard string
    """
    if sections is None:
        config = load_dashboard_config()
        sections = config.get("sections", [
            "header",
            "today_readiness",
            "module_status",
            "finance_snapshot",
            "system_health",
        ])
    
    renderers = {
        "header": lambda: _render_header(view, kernel, state),
        "today_readiness": lambda: _render_today_readiness(view, kernel),
        "module_status": lambda: _render_module_status(view, kernel),
        "finance_snapshot": lambda: _render_finance_snapshot(view, kernel),
        "system_health": lambda: _render_system_health(view, kernel, state),
    }
    
    parts = []
    for section in sections:
        renderer = renderers.get(section)
        if renderer:
            try:
                parts.append(renderer())
            except Exception as e:
                parts.append(f"[{section}] Error: {str(e)[:30]}")
    
    separator = "\n" if view == "compact" else "\n\n"
    return separator.join(parts)


# =============================================================================
# COMMAND HANDLERS
# =============================================================================

def _base_response(cmd_name: str, summary: str, data: Optional[Dict[str, Any]] = None) -> CommandResponse:
    """Create a standard CommandResponse."""
    return CommandResponse(
        ok=True,
        command=cmd_name,
        summary=summary,
        content={"command": cmd_name, "summary": summary},
        data=data,
    )


def handle_dashboard(
    cmd_name: str,
    args: Any,
    session_id: str,
    context: Any,
    kernel: Any,
    meta: Any,
) -> CommandResponse:
    """
    Handle #dashboard command.
    
    Usage:
        #dashboard           → render using stored default view
        #dashboard refresh   → reload state from disk then render
        #dashboard compact   → one-off render in compact (doesn't change default)
        #dashboard full      → one-off render in full (doesn't change default)
    """
    # Parse args
    action = None
    if isinstance(args, dict):
        positional = args.get("_", [])
        if positional:
            action = str(positional[0]).lower()
        elif args.get("action"):
            action = str(args["action"]).lower()
    elif isinstance(args, str) and args.strip():
        action = args.strip().lower()
    
    # Load config
    data_dir = getattr(kernel, "config", None)
    if data_dir and hasattr(data_dir, "data_dir"):
        config = load_dashboard_config(data_dir.data_dir)
    else:
        config = load_dashboard_config()
    
    default_view = config.get("default_view", "compact")
    
    # Determine view mode
    if action == "compact":
        view = "compact"
    elif action == "full":
        view = "full"
    elif action == "refresh":
        # Reload state (trigger any state loaders to re-read from disk)
        if hasattr(kernel, "time_rhythm_manager") and kernel.time_rhythm_manager:
            if hasattr(kernel.time_rhythm_manager, "reload"):
                kernel.time_rhythm_manager.reload()
        if hasattr(kernel, "identity_manager") and kernel.identity_manager:
            if hasattr(kernel.identity_manager, "reload"):
                kernel.identity_manager.reload()
        view = default_view
    else:
        view = default_view
    
    # Get state from context manager if available
    state = None
    if hasattr(kernel, "context_manager"):
        try:
            state = kernel.context_manager.get_context(session_id)
        except Exception:
            pass
    
    # Render dashboard
    dashboard_text = render_dashboard(view=view, kernel=kernel, state=state)
    
    return _base_response(cmd_name, dashboard_text, {"view": view})


def handle_dashboard_view(
    cmd_name: str,
    args: Any,
    session_id: str,
    context: Any,
    kernel: Any,
    meta: Any,
) -> CommandResponse:
    """
    Handle #dashboard-view command.
    
    Usage:
        #dashboard-view          → toggle stored view compact ↔ full
        #dashboard-view compact  → set stored view to compact
        #dashboard-view full     → set stored view to full
    """
    # Parse args
    target_view = None
    if isinstance(args, dict):
        positional = args.get("_", [])
        if positional:
            target_view = str(positional[0]).lower()
        elif args.get("view"):
            target_view = str(args["view"]).lower()
    elif isinstance(args, str) and args.strip():
        target_view = args.strip().lower()
    
    # Load config
    data_dir = getattr(kernel, "config", None)
    if data_dir and hasattr(data_dir, "data_dir"):
        config = load_dashboard_config(data_dir.data_dir)
        save_dir = data_dir.data_dir
    else:
        config = load_dashboard_config()
        save_dir = None
    
    current_view = config.get("default_view", "compact")
    
    # Determine new view
    if target_view in ("compact", "full"):
        new_view = target_view
    else:
        # Toggle
        new_view = "full" if current_view == "compact" else "compact"
    
    # Update and save config
    config["default_view"] = new_view
    save_dashboard_config(config, save_dir)
    
    # Confirmation message
    confirmation = f"Dashboard view set: {new_view.upper()}"
    
    # Get state
    state = None
    if hasattr(kernel, "context_manager"):
        try:
            state = kernel.context_manager.get_context(session_id)
        except Exception:
            pass
    
    # Render dashboard with new view
    dashboard_text = render_dashboard(view=new_view, kernel=kernel, state=state)
    
    full_output = f"{confirmation}\n\n{dashboard_text}"
    
    return _base_response(cmd_name, full_output, {"view": new_view})


def get_auto_dashboard_on_launch(kernel: Any = None, state: Any = None) -> Optional[str]:
    """
    Get dashboard string for auto-display on launch.
    
    Returns None if auto_show_on_launch is False.
    
    This is called during app initialization, before the first prompt.
    It is deterministic and does NOT call any LLM.
    """
    data_dir = None
    if kernel:
        data_dir_obj = getattr(kernel, "config", None)
        if data_dir_obj and hasattr(data_dir_obj, "data_dir"):
            data_dir = data_dir_obj.data_dir
    
    config = load_dashboard_config(data_dir)
    
    if not config.get("auto_show_on_launch", True):
        return None
    
    view = config.get("default_view", "compact")
    return render_dashboard(view=view, kernel=kernel, state=state)


# =============================================================================
# HANDLER REGISTRY
# =============================================================================

DASHBOARD_HANDLERS = {
    "handle_dashboard": handle_dashboard,
    "handle_dashboard_view": handle_dashboard_view,
}


def get_dashboard_handlers() -> Dict[str, Any]:
    """Get dashboard handlers for registration in SYS_HANDLERS."""
    return DASHBOARD_HANDLERS


# =============================================================================
# MODULE EXPORTS
# =============================================================================

__all__ = [
    "handle_dashboard",
    "handle_dashboard_view",
    "get_dashboard_handlers",
    "load_dashboard_config",
    "save_dashboard_config",
    "render_dashboard",
    "get_auto_dashboard_on_launch",
    "DASHBOARD_HANDLERS",
]
