# council/state.py
"""
Nova Council — Session State Management

Maintains per-session council state tracking.

v1.0.0: Initial implementation
- Session-level state object
- Mode tracking: OFF | QUEST | LIVE | LIVE-MAX
- Used flag to track if Gemini was invoked
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


# -----------------------------------------------------------------------------
# Council Modes
# -----------------------------------------------------------------------------

class CouncilMode(Enum):
    """Council operating modes."""
    OFF = "OFF"           # GPT-5 only, no Gemini
    QUEST = "QUEST"       # Gemini Flash ideation → GPT-5 synthesis
    LIVE = "LIVE"         # Gemini Pro research → GPT-5 final
    LIVE_MAX = "LIVE-MAX" # Full pipeline for command design


# Mode display names (terminal-friendly, no emojis)
MODE_DISPLAY = {
    CouncilMode.OFF: "OFF",
    CouncilMode.QUEST: "QUEST",
    CouncilMode.LIVE: "LIVE",
    CouncilMode.LIVE_MAX: "LIVE-MAX",
}


# -----------------------------------------------------------------------------
# Session State
# -----------------------------------------------------------------------------

@dataclass
class CouncilState:
    """
    Per-session council state.
    
    Attributes:
        used: True if Gemini was successfully invoked this session
        mode: Current/last mode used
        gemini_calls: Count of Gemini API calls this session
        last_gemini_result: Last successful Gemini result (ephemeral, not stored to LTM)
        cache_hits: Count of cache hits (QUEST mode)
        errors: Count of Gemini errors
    """
    used: bool = False
    mode: CouncilMode = CouncilMode.OFF
    gemini_calls: int = 0
    cache_hits: int = 0
    errors: int = 0
    last_gemini_result: Optional[Dict[str, Any]] = field(default=None, repr=False)
    
    def mark_used(self, mode: CouncilMode) -> None:
        """Mark council as used with specified mode."""
        self.used = True
        self.mode = mode
        self.gemini_calls += 1
    
    def mark_cache_hit(self, mode: CouncilMode) -> None:
        """Mark a cache hit (still counts as used)."""
        self.used = True
        self.mode = mode
        self.cache_hits += 1
    
    def mark_error(self) -> None:
        """Mark a Gemini error."""
        self.errors += 1
    
    def reset(self) -> None:
        """Reset state (for new session or app restart)."""
        self.used = False
        self.mode = CouncilMode.OFF
        self.gemini_calls = 0
        self.cache_hits = 0
        self.errors = 0
        self.last_gemini_result = None
    
    def get_display_mode(self) -> str:
        """Get terminal-friendly mode display string."""
        return MODE_DISPLAY.get(self.mode, "OFF")
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict (excluding ephemeral data)."""
        return {
            "used": self.used,
            "mode": self.mode.value,
            "gemini_calls": self.gemini_calls,
            "cache_hits": self.cache_hits,
            "errors": self.errors,
        }


# -----------------------------------------------------------------------------
# Session Registry
# -----------------------------------------------------------------------------

# Per-session state storage
_session_states: Dict[str, CouncilState] = {}


def get_council_state(session_id: str) -> CouncilState:
    """Get or create council state for session."""
    if session_id not in _session_states:
        _session_states[session_id] = CouncilState()
    return _session_states[session_id]


def reset_council_state(session_id: str) -> None:
    """Reset council state for session."""
    if session_id in _session_states:
        _session_states[session_id].reset()
    else:
        _session_states[session_id] = CouncilState()


def clear_all_states() -> None:
    """Clear all session states (app restart)."""
    global _session_states
    _session_states = {}


def get_all_sessions() -> Dict[str, CouncilState]:
    """Get all session states (for debugging)."""
    return _session_states.copy()


# -----------------------------------------------------------------------------
# Module Exports
# -----------------------------------------------------------------------------

__all__ = [
    "CouncilMode",
    "CouncilState",
    "get_council_state",
    "reset_council_state",
    "clear_all_states",
    "get_all_sessions",
    "MODE_DISPLAY",
]
