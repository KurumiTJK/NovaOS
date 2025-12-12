# kernel/reminders_integration.py
"""
NovaOS Reminders v2.0 Integration

This module provides kernel-level integration for the reminders wizard.
Import and call apply_reminders_wizard_routing() in nova_kernel.py
to enable wizard support for reminders commands.

Usage in nova_kernel.py:
    
    # At the top, add import:
    from .reminders_integration import check_reminders_wizard
    
    # In nova_kernel.process() method, add this BEFORE the syscommand routing:
    # Check for active reminders wizard
    wizard_result = check_reminders_wizard(session_id, text, self)
    if wizard_result:
        return wizard_result
"""

from typing import Any, Dict, Optional

from .reminders_wizard import (
    has_active_wizard,
    process_reminders_wizard_input,
    clear_wizard_session,
)


def check_reminders_wizard(session_id: str, text: str, kernel) -> Optional[Dict[str, Any]]:
    """
    Check if there's an active reminders wizard and process input.
    
    Call this BEFORE syscommand routing in nova_kernel.process().
    
    Returns:
        Dict response if wizard handled the input
        None if no active wizard (continue normal routing)
    """
    # Skip if no active wizard
    if not has_active_wizard(session_id):
        return None
    
    # Skip if user is typing a # command (they want to exit wizard)
    text_stripped = text.strip()
    if text_stripped.startswith("#"):
        clear_wizard_session(session_id)
        return None
    
    # Process wizard input
    response = process_reminders_wizard_input(session_id, text_stripped, kernel)
    
    if response:
        return {
            "ok": response.ok,
            "command": response.command,
            "summary": response.summary,
            "text": response.summary,
            "content": {
                "command": response.command,
                "summary": response.summary,
            },
            "data": response.data or {},
            "handled_by": "reminders_wizard",
        }
    
    return None


__all__ = ["check_reminders_wizard"]
