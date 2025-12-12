# council/dashboard_integration.py
"""
Nova Council — Dashboard Integration

Provides council status for dashboard display.

Usage:
    from council.dashboard_integration import get_council_display_status
    
    status = get_council_display_status(session_id)
    # Returns: "OFF" | "QUEST" | "LIVE" | "LIVE-MAX"
"""

from typing import Optional

from council.state import CouncilMode, get_council_state, MODE_DISPLAY


def get_council_display_status(session_id: str) -> str:
    """
    Get council status for dashboard display.
    
    Returns terminal-friendly mode string (no emojis).
    
    Args:
        session_id: Current session ID
        
    Returns:
        Mode string: "OFF" | "QUEST" | "LIVE" | "LIVE-MAX"
    """
    state = get_council_state(session_id)
    return state.get_display_mode()


def get_council_stats(session_id: str) -> dict:
    """
    Get detailed council statistics for debugging.
    
    Args:
        session_id: Current session ID
        
    Returns:
        Dict with council stats
    """
    state = get_council_state(session_id)
    return {
        "mode": state.get_display_mode(),
        "used": state.used,
        "gemini_calls": state.gemini_calls,
        "cache_hits": state.cache_hits,
        "errors": state.errors,
    }


# -----------------------------------------------------------------------------
# Dashboard Renderer Patch
# -----------------------------------------------------------------------------

# This section contains the code to add to dashboard_handlers.py
# to display council status in the MODE section.

DASHBOARD_PATCH_CODE = '''
# Add to _render_system_health() in dashboard_handlers.py:

def _render_system_health(view: ViewMode, kernel: Any, state: Any = None, session_id: str = None) -> str:
    """Render the System/Mode section with Council status."""
    # Get persona status
    persona_on = False
    if state and hasattr(state, "novaos_enabled"):
        persona_on = not state.novaos_enabled
    
    persona_status = "ON" if persona_on else "OFF"
    
    # Get Council status
    council_status = "OFF"
    if session_id:
        try:
            from council.dashboard_integration import get_council_display_status
            council_status = get_council_display_status(session_id)
        except ImportError:
            pass
    
    lines = [_section_border()]
    lines.append(_line("MODE"))
    lines.append(_line(f"  Persona: {persona_status} | Council: {council_status}"))
    
    if view == "full":
        # Full: More system details
        memory_count = _load_memory_count(kernel)
        lines.append(_line(f"  Memories: {memory_count}"))
    
    lines.append(_bottom_border())
    return "\\n".join(lines)
'''


__all__ = [
    "get_council_display_status",
    "get_council_stats",
]
