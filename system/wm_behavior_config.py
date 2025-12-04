# system/wm_behavior_config.py
"""
NovaOS v0.7.3 — Working Memory & Behavior Layer Configuration

Global toggles and mode settings for NovaWM and Behavior Layer.
"""

from typing import Dict, Any
from enum import Enum


class BehaviorMode(Enum):
    """Behavior Layer operating modes."""
    NORMAL = "normal"      # Full v0.7.2 behavior
    MINIMAL = "minimal"    # Less hand-holding, fewer follow-up questions
    DEBUG = "debug"        # More explicit about goals/questions in responses


# =============================================================================
# GLOBAL TOGGLES (can be set at startup or runtime)
# =============================================================================

# Master kill switches
WM_ENABLED: bool = True
BEHAVIOR_ENABLED: bool = True

# Default behavior mode for new sessions
DEFAULT_BEHAVIOR_MODE: str = "normal"


# =============================================================================
# PER-SESSION CONFIG STORE
# =============================================================================

class WMBehaviorConfigManager:
    """
    Manages per-session configuration for WM and Behavior Layer.
    """
    
    def __init__(self):
        self._session_configs: Dict[str, Dict[str, Any]] = {}
    
    def _ensure_session(self, session_id: str) -> Dict[str, Any]:
        """Ensure a session config exists."""
        if session_id not in self._session_configs:
            self._session_configs[session_id] = {
                "behavior_mode": DEFAULT_BEHAVIOR_MODE,
                "wm_enabled": WM_ENABLED,
                "behavior_enabled": BEHAVIOR_ENABLED,
            }
        return self._session_configs[session_id]
    
    def get_behavior_mode(self, session_id: str) -> str:
        """Get current behavior mode for session."""
        config = self._ensure_session(session_id)
        return config.get("behavior_mode", DEFAULT_BEHAVIOR_MODE)
    
    def set_behavior_mode(self, session_id: str, mode: str) -> bool:
        """
        Set behavior mode for session.
        
        Returns True if mode is valid, False otherwise.
        """
        valid_modes = {"normal", "minimal", "debug"}
        if mode.lower() not in valid_modes:
            return False
        
        config = self._ensure_session(session_id)
        config["behavior_mode"] = mode.lower()
        return True
    
    def is_wm_enabled(self, session_id: str) -> bool:
        """Check if WM is enabled for session."""
        config = self._ensure_session(session_id)
        return config.get("wm_enabled", WM_ENABLED)
    
    def is_behavior_enabled(self, session_id: str) -> bool:
        """Check if Behavior Layer is enabled for session."""
        config = self._ensure_session(session_id)
        return config.get("behavior_enabled", BEHAVIOR_ENABLED)
    
    def set_wm_enabled(self, session_id: str, enabled: bool) -> None:
        """Enable/disable WM for session."""
        config = self._ensure_session(session_id)
        config["wm_enabled"] = enabled
    
    def set_behavior_enabled(self, session_id: str, enabled: bool) -> None:
        """Enable/disable Behavior Layer for session."""
        config = self._ensure_session(session_id)
        config["behavior_enabled"] = enabled
    
    def clear_session(self, session_id: str) -> None:
        """Clear session config."""
        self._session_configs.pop(session_id, None)
    
    def get_session_config(self, session_id: str) -> Dict[str, Any]:
        """Get full session config for debugging."""
        return self._ensure_session(session_id).copy()


# Global instance
_config_manager = WMBehaviorConfigManager()


# =============================================================================
# PUBLIC API
# =============================================================================

def get_behavior_mode(session_id: str) -> str:
    """Get current behavior mode for session."""
    return _config_manager.get_behavior_mode(session_id)


def set_behavior_mode(session_id: str, mode: str) -> bool:
    """Set behavior mode for session. Returns True if valid mode."""
    return _config_manager.set_behavior_mode(session_id, mode)


def is_wm_enabled(session_id: str) -> bool:
    """Check if WM is enabled for session."""
    return _config_manager.is_wm_enabled(session_id)


def is_behavior_enabled(session_id: str) -> bool:
    """Check if Behavior Layer is enabled for session."""
    return _config_manager.is_behavior_enabled(session_id)


def clear_config(session_id: str) -> None:
    """Clear session config."""
    _config_manager.clear_session(session_id)


def get_config_summary(session_id: str) -> Dict[str, Any]:
    """Get config summary for debugging."""
    return _config_manager.get_session_config(session_id)
