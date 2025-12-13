# kernel/dashboard_handlers.py
"""
NovaOS Dashboard — Core System Dashboard

v0.12.2: Fixed alignment, clean clock format, clearer sections.

Provides #dashboard and #dashboard-view syscommands for at-a-glance system status.

Dashboard Sections:
1. Header (mode, date/time with live clock)
2. Today Readiness (sleep, energy, stress, focus, mood, HP)
3. Module Status (domain progress overview)
4. Finance Snapshot (investment rules)
5. System/Mode (persona status)

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
# LAYOUT CONSTANTS — Single source of truth for alignment
# =============================================================================

DASH_WIDTH = 46  # Total width - mobile friendly (fits ~45 chars on iPhone)
CONTENT_WIDTH = DASH_WIDTH - 4  # Width between "║  " and "║" (2 space indent + 1 border each side)

# Box drawing characters
BOX_TL = "╔"  # Top-left
BOX_TR = "╗"  # Top-right
BOX_BL = "╚"  # Bottom-left
BOX_BR = "╝"  # Bottom-right
BOX_H = "═"   # Horizontal
BOX_V = "║"   # Vertical
BOX_ML = "╠"  # Middle-left
BOX_MR = "╣"  # Middle-right


# =============================================================================
# LINE BUILDER HELPERS — Deterministic alignment
# =============================================================================

def _top_border() -> str:
    """Top border of dashboard."""
    return BOX_TL + BOX_H * (DASH_WIDTH - 2) + BOX_TR


def _bottom_border() -> str:
    """Bottom border of dashboard."""
    return BOX_BL + BOX_H * (DASH_WIDTH - 2) + BOX_BR


def _section_border() -> str:
    """Section separator."""
    return BOX_ML + BOX_H * (DASH_WIDTH - 2) + BOX_MR


def _line(content: str) -> str:
    """
    Create a single line with proper padding.
    Content is left-aligned, padded to exactly CONTENT_WIDTH with 1 char right margin.
    """
    # Reserve 1 char margin from right border
    usable_width = CONTENT_WIDTH - 1
    
    # Truncate if needed
    if len(content) > usable_width:
        content = content[:usable_width - 1] + "…"
    
    # Pad to exact width (with 1 char margin)
    padding_needed = CONTENT_WIDTH - len(content)
    padded = content + " " * padding_needed
    
    return BOX_V + "  " + padded + BOX_V


def _line_raw(content: str, extra_pad: int = 0) -> str:
    """
    Create a line with manual padding adjustment for unicode characters.
    extra_pad: negative to reduce padding (for wide unicode), positive to add.
    """
    # Reserve 1 char margin from right border
    usable_width = CONTENT_WIDTH - 1
    
    # Truncate if needed
    if len(content) > usable_width:
        content = content[:usable_width - 1] + "…"
    
    # Pad to exact width, adjusted for unicode display width
    padding_needed = CONTENT_WIDTH - len(content) + extra_pad
    if padding_needed < 0:
        padding_needed = 0
    padded = content + " " * padding_needed
    
    return BOX_V + "  " + padded + BOX_V


def _line_two_col(left: str, right: str) -> str:
    """
    Create a line with left-aligned and right-aligned content.
    Handles {{CLOCK:...}} marker by using display width instead of string length.
    """
    # Calculate display width of right side (clock marker is longer than displayed)
    if "{{CLOCK:" in right:
        right_display_len = _clock_display_width()
    else:
        right_display_len = len(right)
    
    # Reserve 1 char margin from right border
    usable_width = CONTENT_WIDTH - 1
    
    # Calculate space needed
    total_display = len(left) + right_display_len
    
    # If too long, truncate left side
    if total_display > usable_width - 2:  # -2 for minimum gap
        max_left = usable_width - right_display_len - 3
        if max_left > 0:
            left = left[:max_left] + "…"
        else:
            left = ""
    
    # Calculate gap between left and right (using display width)
    gap = usable_width - len(left) - right_display_len
    if gap < 1:
        gap = 1
    
    # Build the content line with 1 char right margin
    content = left + " " * gap + right + " "
    
    return BOX_V + "  " + content + BOX_V


# =============================================================================
# CONFIG MANAGEMENT
# =============================================================================

def _get_config_path(data_dir: Optional[Path] = None) -> Path:
    """Get the dashboard config file path."""
    if data_dir:
        config_dir = data_dir.parent / "config"
    else:
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
        config = _get_default_config()
        save_dashboard_config(config, data_dir)
        return config
    
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
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
# SAFE DATA LOADERS
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
        if hasattr(kernel, "time_rhythm_manager") and kernel.time_rhythm_manager:
            manager = kernel.time_rhythm_manager
            if hasattr(manager, "_load_state"):
                state = manager._load_state()
                if hasattr(state, "today"):
                    return state.today.__dict__ if hasattr(state.today, "__dict__") else {}
        
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
        if hasattr(kernel, "module_store") and kernel.module_store:
            modules = kernel.module_store.list_all(include_archived=False)
            return [m.to_dict() if hasattr(m, "to_dict") else {} for m in modules]
        
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
        if hasattr(kernel, "identity_manager") and kernel.identity_manager:
            return kernel.identity_manager.get_profile_summary()
        
        if hasattr(kernel, "player_profile_manager") and kernel.player_profile_manager:
            profile = kernel.player_profile_manager.get_profile()
            if hasattr(profile, "to_dict"):
                return profile.to_dict()
            return profile.__dict__ if hasattr(profile, "__dict__") else {}
        
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


# =============================================================================
# VISUAL HELPERS
# =============================================================================

def _progress_bar(value: int, max_value: int, width: int = 10) -> str:
    """Generate a progress bar."""
    if max_value <= 0:
        return "░" * width
    percent = min(100, max(0, int((value / max_value) * 100)))
    filled = int((percent / 100) * width)
    return "█" * filled + "░" * (width - filled)


def _status_icon(status: str) -> str:
    """Get status indicator."""
    status_map = {
        "ok": "✓",
        "active": "✓",
        "good": "✓",
        "warning": "⚠",
        "in_progress": "◐",
        "ip": "◐",
        "error": "✗",
        "bad": "✗",
        "ns": "○",
        "none": "○",
    }
    return status_map.get(status.lower(), "○")


def _get_current_time() -> str:
    """
    Get current time formatted as H:MM AM/PM.
    Uses America/Los_Angeles timezone.
    Returns clean time string (no brackets, no labels).
    """
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/Los_Angeles")
    except ImportError:
        tz = timezone.utc
    
    now = datetime.now(tz)
    # Format: 1:45 AM (no leading zero on hour)
    return now.strftime("%I:%M %p").lstrip("0")


def _get_live_clock_marker() -> str:
    """
    Return time wrapped in marker for frontend live clock detection.
    Format: {{CLOCK:1:45 AM}} — frontend replaces with live updating span.
    
    Using double braces to avoid confusion with other bracket patterns.
    """
    time_str = _get_current_time()
    return f"{{{{CLOCK:{time_str}}}}}"


def _clock_display_width() -> int:
    """Return the display width of the clock (what user sees after frontend processes it)."""
    # Clock displays as "H:MM AM" (~7-8 chars) but we use 12 to add left padding
    # This pushes the clock further from the right border
    return 12


# =============================================================================
# SECTION RENDERERS
# =============================================================================

def _render_header(view: ViewMode, kernel: Any, state: Any = None) -> str:
    """Render the header section."""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/Los_Angeles")
    except ImportError:
        tz = timezone.utc
    
    now = datetime.now(tz)
    date_str = now.strftime("%a %b %d")  # e.g. "Fri Dec 12" (10 chars)
    
    # Get mode
    mode = "STRICT"
    if state and hasattr(state, "novaos_enabled"):
        mode = "STRICT" if state.novaos_enabled else "PERSONA"
    
    # Get time string (will be replaced by frontend, but need display width)
    time_display = _get_current_time()  # e.g. "2:37 AM" (7-8 chars)
    clock_marker = _get_live_clock_marker()  # e.g. "{{CLOCK:2:37 AM}}" (longer)
    
    # Calculate shared start column for right-aligned info
    # Both time and date will START at this column (based on display width)
    RIGHT_MARGIN = 2
    max_info_display_len = max(len(time_display), len(date_str))
    INFO_START_COL = CONTENT_WIDTH - RIGHT_MARGIN - max_info_display_len
    
    left_content = f"DASHBOARD: {mode}"
    
    # Truncate left content if it would collide with info column
    max_left_len = INFO_START_COL - 2  # Leave 2 char gap
    if len(left_content) > max_left_len:
        left_content = left_content[:max_left_len - 1] + "…"
    
    lines = [_top_border()]
    
    # Line 1: DASHBOARD: MODE ... time
    # Build line with left content padded, then clock marker appended
    # The marker is longer than display, so we build differently
    left_padded = left_content.ljust(INFO_START_COL)
    line1_content = left_padded + clock_marker
    # Pad to ensure right border aligns (marker will be replaced by shorter text)
    # Add spaces to reach CONTENT_WIDTH based on display width
    extra_spaces = CONTENT_WIDTH - INFO_START_COL - len(time_display)
    line1 = BOX_V + "  " + left_padded + clock_marker + " " * extra_spaces + BOX_V
    lines.append(line1)
    
    # Line 2: (empty left) ... date at same column
    left_empty = " " * INFO_START_COL
    date_padded = date_str.ljust(CONTENT_WIDTH - INFO_START_COL)
    line2 = BOX_V + "  " + left_empty + date_padded + BOX_V
    lines.append(line2)
    
    return "\n".join(lines)


def _render_today_readiness(view: ViewMode, kernel: Any) -> str:
    """Render the State section (HP, Energy, Sleep, Food, Checkin)."""
    tr = _load_timerhythm_state(kernel)
    
    sleep = _safe_get(tr, "sleep")
    energy = _safe_get(tr, "energy")
    hp = _safe_get(tr, "hp")
    
    # Checkboxes - check if completed today
    food_done = _safe_get(tr, "food_completed", False)
    checkin_done = _safe_get(tr, "morning_completed", False) or _safe_get(tr, "evening_completed", False)
    
    food_box = "☑" if food_done else "☐"
    checkin_box = "☑" if checkin_done else "☐"
    
    lines = [_section_border()]
    lines.append(_line("STATE"))
    
    if view == "compact":
        lines.append(_line(f"  HP: {hp}  Energy: {energy}  Sleep: {sleep}"))
        # Checkboxes are wide unicode - subtract 1 from padding
        food_checkin = f"  Food: {food_box}  Checkin: {checkin_box}"
        lines.append(_line_raw(food_checkin, extra_pad=-1))
    else:
        lines.append(_line(f"  HP: {hp}"))
        lines.append(_line(f"  Energy: {energy}"))
        lines.append(_line(f"  Sleep: {sleep}"))
        food_checkin = f"  Food: {food_box}  Checkin: {checkin_box}"
        lines.append(_line_raw(food_checkin, extra_pad=-1))
    
    return "\n".join(lines)


def _render_module_status(view: ViewMode, kernel: Any) -> str:
    """Render the Module Status section."""
    modules = _load_modules_state(kernel)
    identity = _load_identity_state(kernel)
    
    module_xp = identity.get("modules", {})
    if isinstance(module_xp, list):
        module_xp = {m.get("name", ""): {"xp": m.get("xp", 0), "level": m.get("level", 1)} 
                     for m in module_xp if isinstance(m, dict)}
    
    module_info = []
    for m in modules[:6]:
        if isinstance(m, dict):
            name = m.get("name", "?")
            status = m.get("status", "active")
            
            xp_data = module_xp.get(name, {})
            if isinstance(xp_data, dict):
                xp = xp_data.get("xp", 0)
                level = xp_data.get("level", 1)
            else:
                xp = xp_data if isinstance(xp_data, (int, float)) else 0
                level = 1
            
            module_info.append({
                "name": name[:13],  # Show full Cybersecurity (13 chars)
                "status_icon": _status_icon(status),
                "xp": int(xp),
                "level": int(level),
            })
    
    lines = [_section_border()]
    lines.append(_line("MODULES"))
    
    if not module_info:
        lines.append(_line("  (none defined)"))
        return "\n".join(lines)
    
    # Show modules without progress bar
    for m in module_info:
        target = 50 * m["level"]
        # Format: name xp/target L# icon
        line_content = f"  {m['name']} {m['xp']}/{target} L{m['level']} {m['status_icon']}"
        lines.append(_line(line_content))
    
    return "\n".join(lines)


def _render_finance_snapshot(view: ViewMode, kernel: Any) -> str:
    """Render the Finance section with investment rules."""
    lines = [_section_border()]
    lines.append(_line("FINANCE"))
    
    if view == "compact":
        # Compact: Shortened for mobile
        lines.append(_line("  $425 stocks | $200 SPAXX"))
        lines.append(_line("  Wed | LEAPS Q-C | FHA 2027"))
    else:
        # Full: Detailed breakdown
        lines.append(_line("  $425/wk -> Stocks"))
        lines.append(_line("  $200/wk -> SPAXX"))
        lines.append(_line("  Buy: Wednesday"))
        lines.append(_line("  LEAPS: Q-C only"))
        lines.append(_line("  FHA: Apr-Dec 2027"))
    
    return "\n".join(lines)


def _render_system_health(view: ViewMode, kernel: Any, state: Any = None) -> str:
    """Render the System/Mode section."""
    # Get persona status
    persona_on = False
    if state and hasattr(state, "novaos_enabled"):
        persona_on = not state.novaos_enabled
    
    persona_status = "ON" if persona_on else "OFF"
    
    lines = [_section_border()]
    lines.append(_line("MODE"))
    lines.append(_line(f"  Persona: {persona_status}"))
    
    if view == "full":
        # Full: More system details
        memory_count = _load_memory_count(kernel)
        lines.append(_line(f"  Memories: {memory_count}"))
    
    lines.append(_bottom_border())
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
                parts.append(_line(f"[{section}] Error: {str(e)[:30]}"))
    
    return "\n".join(parts)


# =============================================================================
# COMMAND HANDLERS
# =============================================================================

def _base_response(cmd_name: str, summary: str, data: Optional[Dict[str, Any]] = None) -> CommandResponse:
    """Create a standard CommandResponse."""
    return CommandResponse(
        ok=True,
        command=cmd_name,
        summary=summary,
        data=data or {},
        type="syscommand",
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
        #dashboard compact   → one-off render in compact
        #dashboard full      → one-off render in full
    """
    action = None
    if isinstance(args, dict):
        positional = args.get("_", [])
        if positional:
            action = str(positional[0]).lower()
        elif args.get("action"):
            action = str(args["action"]).lower()
    elif isinstance(args, str) and args.strip():
        action = args.strip().lower()
    
    data_dir = getattr(kernel, "config", None)
    if data_dir and hasattr(data_dir, "data_dir"):
        config = load_dashboard_config(data_dir.data_dir)
    else:
        config = load_dashboard_config()
    
    default_view = config.get("default_view", "compact")
    
    if action == "compact":
        view = "compact"
    elif action == "full":
        view = "full"
    elif action == "refresh":
        if hasattr(kernel, "time_rhythm_manager") and kernel.time_rhythm_manager:
            if hasattr(kernel.time_rhythm_manager, "reload"):
                kernel.time_rhythm_manager.reload()
        view = default_view
    else:
        view = default_view
    
    state = None
    if hasattr(kernel, "context_manager"):
        try:
            state = kernel.context_manager.get_context(session_id)
        except Exception:
            pass
    
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
    target_view = None
    if isinstance(args, dict):
        positional = args.get("_", [])
        if positional:
            target_view = str(positional[0]).lower()
        elif args.get("view"):
            target_view = str(args["view"]).lower()
    elif isinstance(args, str) and args.strip():
        target_view = args.strip().lower()
    
    data_dir = getattr(kernel, "config", None)
    if data_dir and hasattr(data_dir, "data_dir"):
        config = load_dashboard_config(data_dir.data_dir)
        save_dir = data_dir.data_dir
    else:
        config = load_dashboard_config()
        save_dir = None
    
    current_view = config.get("default_view", "compact")
    
    if target_view in ("compact", "full"):
        new_view = target_view
    else:
        new_view = "full" if current_view == "compact" else "compact"
    
    config["default_view"] = new_view
    save_dashboard_config(config, save_dir)
    
    state = None
    if hasattr(kernel, "context_manager"):
        try:
            state = kernel.context_manager.get_context(session_id)
        except Exception:
            pass
    
    dashboard_text = render_dashboard(view=new_view, kernel=kernel, state=state)
    full_output = f"View: {new_view.upper()}\n\n{dashboard_text}"
    
    return _base_response(cmd_name, full_output, {"view": new_view})


def get_auto_dashboard_on_launch(kernel: Any = None, state: Any = None) -> Optional[str]:
    """
    Get dashboard string for auto-display on launch.
    Returns None if auto_show_on_launch is False.
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
