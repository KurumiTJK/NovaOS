# core/nova_state.py
"""
NovaOS v0.11.1 — Unified State Object

v0.11.1 CHANGE: Default mode swapped
- novaos_enabled now defaults to True (Strict/NovaOS mode)
- #boot enables Persona/conversation mode
- #shutdown returns to Strict/NovaOS mode

NovaState is the single source of truth for:
- Whether NovaOS is active (novaos_enabled)
- Session identification
- Cross-layer context

This object is passed through all layers and persists across turns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Any, Optional


@dataclass
class NovaState:
    """
    Unified state object for the dual-mode architecture.
    
    Attributes:
        session_id: Unique identifier for this conversation session.
        novaos_enabled: Whether NovaOS kernel is active.
                        False = Persona mode (default)
                        True = NovaOS mode (after #boot)
        context: Optional cross-layer context dictionary.
    
    Usage:
        state = NovaState(session_id="user-123")
        # Default: state.novaos_enabled = False (Persona mode)
        
        state.enable_novaos()   # After #boot
        state.disable_novaos()  # After #shutdown
    """
    
    session_id: str
    novaos_enabled: bool = True  # v0.11.1: Default ON → Strict/NovaOS mode
    context: Dict[str, Any] = field(default_factory=dict)
    
    # ─────────────────────────────────────────────────────────────────────
    # Mode Control
    # ─────────────────────────────────────────────────────────────────────
    
    def enable_novaos(self) -> None:
        """Activate NovaOS mode (called by #boot)."""
        self.novaos_enabled = True
    
    def disable_novaos(self) -> None:
        """Deactivate NovaOS mode (called by #shutdown)."""
        self.novaos_enabled = False
    
    @property
    def mode_name(self) -> str:
        """Human-readable mode name."""
        return "NovaOS" if self.novaos_enabled else "Persona"
    
    # ─────────────────────────────────────────────────────────────────────
    # Context Helpers
    # ─────────────────────────────────────────────────────────────────────
    
    def set_context(self, key: str, value: Any) -> None:
        """Set a context value."""
        self.context[key] = value
    
    def get_context(self, key: str, default: Any = None) -> Any:
        """Get a context value with optional default."""
        return self.context.get(key, default)
    
    def clear_context(self) -> None:
        """Clear all context (but preserve mode state)."""
        self.context.clear()
    
    # ─────────────────────────────────────────────────────────────────────
    # Serialization (for persistence if needed)
    # ─────────────────────────────────────────────────────────────────────
    
    def to_dict(self) -> Dict[str, Any]:
        """Export state to dictionary."""
        return {
            "session_id": self.session_id,
            "novaos_enabled": self.novaos_enabled,
            "context": self.context.copy(),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NovaState":
        """Create NovaState from dictionary."""
        return cls(
            session_id=data.get("session_id", "unknown"),
            novaos_enabled=data.get("novaos_enabled", True),  # v0.11.1: default True
            context=data.get("context", {}),
        )
    
    def __repr__(self) -> str:
        return f"NovaState(session='{self.session_id}', mode='{self.mode_name}')"
