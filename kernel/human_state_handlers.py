# kernel/human_state_handlers.py
"""
NovaOS Human State Command Handlers — v2.0.0

Implements ONLY these commands:
1. human-show - Show today's state + derived readiness info
2. human-checkin - Main daily check-in (guided or param mode)
3. human-event - Log quick events that modify state
4. human-clear - Reset today's snapshot

No other human_state commands should exist.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# Import response type
try:
    from .command_types import CommandResponse
except ImportError:
    # Fallback if CommandResponse not available
    CommandResponse = Dict[str, Any]

# Import the new Human State manager
from .human_state import (
    HumanStateManagerV2,
    HumanStateSnapshot,
    get_human_state_manager,
)


# =============================================================================
# RESPONSE HELPERS
# =============================================================================

def _base_response(
    cmd_name: str,
    summary: str,
    data: Optional[Dict[str, Any]] = None,
) -> CommandResponse:
    """Build a standard CommandResponse object."""
    try:
        from .command_types import CommandResponse as CR
        return CR(
            ok=True,
            command=cmd_name,
            summary=summary,
            data=data or {},
            type="syscommand",
        )
    except ImportError:
        return {
            "ok": True,
            "command": cmd_name,
            "summary": summary,
            "data": data or {},
            "type": "syscommand",
        }


def _error_response(
    cmd_name: str,
    message: str,
    code: str = "ERROR",
) -> CommandResponse:
    """Build an error CommandResponse object."""
    try:
        from .command_types import CommandResponse as CR
        return CR(
            ok=False,
            command=cmd_name,
            summary=message,
            error_code=code,
            error_message=message,
            type="error",
        )
    except ImportError:
        return {
            "ok": False,
            "command": cmd_name,
            "summary": message,
            "error_code": code,
            "error_message": message,
            "type": "error",
        }


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _get_manager(kernel: Any) -> HumanStateManagerV2:
    """Get the HumanStateManager from kernel or create one."""
    if hasattr(kernel, "human_state_manager"):
        return kernel.human_state_manager
    
    # Fallback: create manager with kernel's data_dir
    data_dir = Path("data")
    if hasattr(kernel, "config") and hasattr(kernel.config, "data_dir"):
        data_dir = kernel.config.data_dir
    
    return get_human_state_manager(data_dir)


def _format_tier_emoji(tier: str) -> str:
    """Get emoji for readiness tier."""
    return {
        "Green": "🟢",
        "Yellow": "🟡",
        "Red": "🔴",
    }.get(tier, "⚪")


def _format_mode_emoji(mode: str) -> str:
    """Get emoji for recommended mode."""
    return {
        "Push": "🚀",
        "Maintain": "⚖️",
        "Recover": "🛌",
    }.get(mode, "")


def _format_mood(mood: int) -> str:
    """Format mood with visual indicator."""
    if mood >= 3:
        return f"+{mood} 😊"
    elif mood >= 1:
        return f"+{mood} 🙂"
    elif mood == 0:
        return "0 😐"
    elif mood >= -2:
        return f"{mood} 😕"
    else:
        return f"{mood} 😔"


def _parse_tags(value: Any) -> List[str]:
    """Parse tags from various input formats."""
    if isinstance(value, list):
        return [str(t).strip() for t in value if t]
    elif isinstance(value, str):
        # Handle comma-separated or space-separated
        return [t.strip() for t in value.replace(",", " ").split() if t.strip()]
    return []


# =============================================================================
# COMMAND HANDLERS
# =============================================================================

def handle_human_show(
    cmd_name: str,
    args: Any,
    session_id: str,
    context: Any,
    kernel: Any,
    meta: Any,
) -> CommandResponse:
    """
    Show today's human state + derived readiness info.
    
    Usage: #human-show
    
    Displays:
    - HP, readiness tier, recommended mode, load modifier
    - Core metrics: stamina, stress, mood, focus, sleep_quality, soreness
    - Notes and tags (if any)
    - Last check-in time
    """
    manager = _get_manager(kernel)
    snapshot = manager.get_today_human_state()
    
    tier_emoji = _format_tier_emoji(snapshot.readiness_tier)
    mode_emoji = _format_mode_emoji(snapshot.recommended_mode)
    
    lines = [
        "╔════════════════════════════════════════════╗",
        "║          HUMAN STATE — TODAY               ║",
        "╚════════════════════════════════════════════╝",
        "",
        f"  Date: {snapshot.today_date}",
        "",
        "─── READINESS ───────────────────────────────",
        "",
        f"  HP:          {snapshot.hp}/100",
        f"  Tier:        {tier_emoji} {snapshot.readiness_tier}",
        f"  Mode:        {mode_emoji} {snapshot.recommended_mode}",
        f"  Load Mod:    {snapshot.load_modifier:.2f}x",
        "",
        "─── CORE METRICS ────────────────────────────",
        "",
        f"  Stamina:       {snapshot.stamina}/100",
        f"  Stress:        {snapshot.stress}/100",
        f"  Mood:          {_format_mood(snapshot.mood)}",
        f"  Focus:         {snapshot.focus}/100",
        f"  Sleep Quality: {snapshot.sleep_quality}/100",
        f"  Soreness:      {snapshot.soreness}/100",
        "",
    ]
    
    # Notes and tags
    if snapshot.notes or snapshot.tags:
        lines.append("─── NOTES & TAGS ────────────────────────────")
        lines.append("")
        if snapshot.notes:
            lines.append(f"  Notes: {snapshot.notes}")
        if snapshot.tags:
            lines.append(f"  Tags:  {', '.join(snapshot.tags)}")
        lines.append("")
    
    # Events today
    if snapshot.events:
        lines.append("─── TODAY'S EVENTS ──────────────────────────")
        lines.append("")
        for evt in snapshot.events[-5:]:  # Show last 5
            evt_type = evt.get("type", "unknown")
            lines.append(f"  • {evt_type}")
        lines.append("")
    
    # Last check-in
    if snapshot.last_check_in_at:
        try:
            dt = datetime.fromisoformat(snapshot.last_check_in_at.replace("Z", "+00:00"))
            time_str = dt.strftime("%H:%M")
            lines.append(f"  Last check-in: {time_str}")
        except:
            lines.append(f"  Last check-in: {snapshot.last_check_in_at}")
    else:
        lines.append("  ⚠️ No check-in today yet. Run #human-checkin")
    
    lines.append("")
    lines.append("─────────────────────────────────────────────")
    lines.append("Commands: #human-checkin | #human-event | #human-clear")
    
    return _base_response(cmd_name, "\n".join(lines), {
        "hp": snapshot.hp,
        "readiness_tier": snapshot.readiness_tier,
        "load_modifier": snapshot.load_modifier,
        "recommended_mode": snapshot.recommended_mode,
        "snapshot": snapshot.to_dict(),
    })


def handle_human_checkin(
    cmd_name: str,
    args: Any,
    session_id: str,
    context: Any,
    kernel: Any,
    meta: Any,
) -> CommandResponse:
    """
    Main daily check-in.
    
    Supports:
    1. Guided prompt flow (no args) - asks quick questions
    2. Parameter mode - provide values directly
    
    Usage:
        #human-checkin                          — Start guided flow
        #human-checkin stamina=70 stress=40     — Direct params
        #human-checkin stamina=70 mood=2 notes="feeling good" tags="coffee,workout"
    
    Valid ranges:
        stamina, stress, focus, sleep_quality, soreness: 0-100
        mood: -5 to +5
    """
    manager = _get_manager(kernel)
    
    # Parse arguments
    params = {}
    if isinstance(args, dict):
        params = args.copy()
        # Handle positional args
        positional = params.pop("_", [])
        if positional and len(positional) == 1 and positional[0] == "guided":
            # Explicit guided mode request
            pass
    elif isinstance(args, str) and args.strip():
        # Parse key=value pairs from string
        for part in args.split():
            if "=" in part:
                key, val = part.split("=", 1)
                params[key.strip()] = val.strip().strip('"').strip("'")
    
    # Check if this is guided mode (no params provided)
    metric_keys = {"stamina", "stress", "mood", "focus", "sleep_quality", "soreness"}
    has_metrics = any(k in params for k in metric_keys)
    
    if not has_metrics:
        # Return guided prompt
        snapshot = manager.get_today_human_state()
        
        lines = [
            "╔════════════════════════════════════════════╗",
            "║       DAILY CHECK-IN — Quick Entry         ║",
            "╚════════════════════════════════════════════╝",
            "",
            "How are you feeling today? Rate each 0-100 (mood: -5 to +5):",
            "",
            f"  Current values (from yesterday or last check-in):",
            f"  • stamina={snapshot.stamina}  stress={snapshot.stress}  mood={snapshot.mood}",
            f"  • focus={snapshot.focus}  sleep_quality={snapshot.sleep_quality}  soreness={snapshot.soreness}",
            "",
            "─────────────────────────────────────────────",
            "",
            "Reply with your values, for example:",
            "",
            '  #human-checkin stamina=75 stress=30 mood=2 focus=70 sleep_quality=80 soreness=10 notes="slept well"',
            "",
            "Or update just some values:",
            "",
            "  #human-checkin stamina=60 stress=50",
            "",
            "Tip: Takes <60 seconds once you know your numbers!",
        ]
        
        return _base_response(cmd_name, "\n".join(lines), {
            "mode": "guided",
            "current": snapshot.to_dict(),
        })
    
    # Parameter mode - process check-in
    checkin_params = {}
    
    # Parse and validate each metric
    for key in metric_keys:
        if key in params:
            try:
                val = int(params[key])
                if key == "mood":
                    val = max(-5, min(5, val))
                else:
                    val = max(0, min(100, val))
                checkin_params[key] = val
            except ValueError:
                return _error_response(
                    cmd_name,
                    f"Invalid value for {key}: must be a number",
                    "INVALID_VALUE",
                )
    
    # Parse notes
    if "notes" in params:
        checkin_params["notes"] = str(params["notes"])
    
    # Parse tags
    if "tags" in params:
        checkin_params["tags"] = _parse_tags(params["tags"])
    
    # Perform check-in
    snapshot = manager.do_checkin(**checkin_params)
    
    tier_emoji = _format_tier_emoji(snapshot.readiness_tier)
    mode_emoji = _format_mode_emoji(snapshot.recommended_mode)
    
    lines = [
        "✓ Check-in recorded!",
        "",
        f"  HP: {snapshot.hp}/100   {tier_emoji} {snapshot.readiness_tier}",
        f"  Mode: {mode_emoji} {snapshot.recommended_mode}  (Load: {snapshot.load_modifier:.2f}x)",
        "",
    ]
    
    # Show updated values
    updated = []
    for key in metric_keys:
        if key in checkin_params:
            val = getattr(snapshot, key)
            if key == "mood":
                updated.append(f"{key}={_format_mood(val)}")
            else:
                updated.append(f"{key}={val}")
    
    if updated:
        lines.append(f"  Updated: {', '.join(updated)}")
    
    if snapshot.notes:
        lines.append(f"  Notes: {snapshot.notes}")
    
    return _base_response(cmd_name, "\n".join(lines), {
        "mode": "param",
        "hp": snapshot.hp,
        "readiness_tier": snapshot.readiness_tier,
        "load_modifier": snapshot.load_modifier,
        "recommended_mode": snapshot.recommended_mode,
        "updated_fields": list(checkin_params.keys()),
    })


def handle_human_event(
    cmd_name: str,
    args: Any,
    session_id: str,
    context: Any,
    kernel: Any,
    meta: Any,
) -> CommandResponse:
    """
    Log a quick event that modifies today's state without full check-in.
    
    Usage:
        #human-event type=workout intensity=medium
        #human-event type=walk minutes=20
        #human-event type=caffeine servings=2
        #human-event type=nap minutes=30
        #human-event type=meditation minutes=10
        #human-event type=bad_sleep
    
    Event types and their effects:
        workout:    soreness↑, stress↓, stamina↓ (intensity: low/medium/high)
        walk:       stress↓, focus↑, mood↑ (minutes)
        caffeine:   stamina↑, stress↑ (servings, max 3)
        nap:        stamina↑, focus↑ (minutes)
        meditation: stress↓, focus↑ (minutes)
        bad_sleep:  sleep_quality↓, stamina↓, stress↑
    """
    manager = _get_manager(kernel)
    
    # Parse arguments
    params = {}
    if isinstance(args, dict):
        params = args.copy()
        params.pop("_", None)
    elif isinstance(args, str) and args.strip():
        for part in args.split():
            if "=" in part:
                key, val = part.split("=", 1)
                params[key.strip()] = val.strip().strip('"').strip("'")
    
    # Get event type
    event_type = params.get("type", "").lower()
    
    valid_types = ["workout", "walk", "caffeine", "nap", "meditation", "bad_sleep"]
    
    if not event_type:
        # Show help
        lines = [
            "╔════════════════════════════════════════════╗",
            "║          HUMAN-EVENT — Quick Log           ║",
            "╚════════════════════════════════════════════╝",
            "",
            "Log an event that affects your state:",
            "",
            "  #human-event type=workout intensity=medium",
            "  #human-event type=walk minutes=20",
            "  #human-event type=caffeine servings=1",
            "  #human-event type=nap minutes=30",
            "  #human-event type=meditation minutes=10",
            "  #human-event type=bad_sleep",
            "",
            "Effects:",
            "  workout    → soreness↑, stress↓, stamina↓",
            "  walk       → stress↓, focus↑, mood↑",
            "  caffeine   → stamina↑, stress↑",
            "  nap        → stamina↑, focus↑",
            "  meditation → stress↓, focus↑",
            "  bad_sleep  → sleep↓, stamina↓, stress↑",
        ]
        return _base_response(cmd_name, "\n".join(lines), {"mode": "help"})
    
    if event_type not in valid_types:
        return _error_response(
            cmd_name,
            f"Unknown event type '{event_type}'. Valid: {', '.join(valid_types)}",
            "INVALID_EVENT_TYPE",
        )
    
    # Parse event-specific parameters
    intensity = params.get("intensity", "medium").lower()
    minutes = None
    servings = None
    
    if "minutes" in params:
        try:
            minutes = int(params["minutes"])
        except ValueError:
            return _error_response(cmd_name, "minutes must be a number", "INVALID_VALUE")
    
    if "servings" in params:
        try:
            servings = int(params["servings"])
        except ValueError:
            return _error_response(cmd_name, "servings must be a number", "INVALID_VALUE")
    
    # Log the event
    result = manager.log_event(
        event_type=event_type,
        intensity=intensity if event_type == "workout" else None,
        minutes=minutes,
        servings=servings,
    )
    
    tier_emoji = _format_tier_emoji(result["readiness_tier"])
    
    lines = [
        f"✓ Event logged: {event_type}",
        "",
        f"  HP: {result['hp']}/100  {tier_emoji} {result['readiness_tier']}",
        f"  Mode: {result['recommended_mode']}",
    ]
    
    return _base_response(cmd_name, "\n".join(lines), result)


def handle_human_clear(
    cmd_name: str,
    args: Any,
    session_id: str,
    context: Any,
    kernel: Any,
    meta: Any,
) -> CommandResponse:
    """
    Clear/reset today's human state.
    
    Usage:
        #human-clear           — Soft reset (neutral defaults, keep history)
        #human-clear hard=true — Also clear history log
    
    Soft reset sets all metrics to neutral:
        stamina=50, stress=50, mood=0, focus=50, sleep_quality=50, soreness=0
    """
    manager = _get_manager(kernel)
    
    # Parse arguments
    hard = False
    if isinstance(args, dict):
        hard = str(args.get("hard", "")).lower() in ("true", "yes", "1")
    elif isinstance(args, str) and args.strip():
        hard = "hard=true" in args.lower() or "hard=yes" in args.lower()
    
    result = manager.clear_today(hard=hard)
    
    if hard:
        lines = [
            "✓ Human state cleared (hard reset)",
            "",
            "  • Today's snapshot reset to neutral defaults",
            "  • History log cleared",
            "",
            "Run #human-checkin to log your state.",
        ]
    else:
        lines = [
            "✓ Today's state cleared (soft reset)",
            "",
            "  • Metrics reset to neutral defaults",
            "  • History preserved",
            "",
            "Run #human-checkin to log your state.",
        ]
    
    return _base_response(cmd_name, "\n".join(lines), result)


# =============================================================================
# HANDLER REGISTRY
# =============================================================================

def get_human_state_handlers() -> Dict[str, Callable]:
    """
    Return handler registry for Human State commands.
    
    Call this from syscommands.py to register handlers.
    """
    return {
        "handle_human_show": handle_human_show,
        "handle_human_checkin": handle_human_checkin,
        "handle_human_event": handle_human_event,
        "handle_human_clear": handle_human_clear,
    }


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    "handle_human_show",
    "handle_human_checkin",
    "handle_human_event",
    "handle_human_clear",
    "get_human_state_handlers",
]
