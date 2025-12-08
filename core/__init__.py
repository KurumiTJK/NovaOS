# core/__init__.py
"""
NovaOS Core — Mode routing and state management.

This module provides the dual-mode architecture:
- Persona Mode (default): Pure conversational Nova
- NovaOS Mode (after #boot): Full kernel with syscommands and modules
"""

from .nova_state import NovaState
from .mode_router import handle_user_message, get_or_create_state, get_state, clear_state

__all__ = [
    "NovaState",
    "handle_user_message",
    "get_or_create_state",
    "get_state",
    "clear_state",
]
