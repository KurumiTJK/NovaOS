# kernel/quest_delete_wizard.py
"""
SHIM: This module has moved to kernel/quests/quest_delete_wizard.py

This file re-exports all symbols for backward compatibility.
New code should import from kernel.quests.quest_delete_wizard directly.
"""

from kernel.quests.quest_delete_wizard import (
    # Session class
    QuestDeleteSession,
    # Session management
    get_delete_session,
    set_delete_session,
    clear_delete_session,
    has_active_delete_session,
    is_delete_wizard_active,
    cancel_delete_wizard,
    # Main handlers
    handle_quest_delete_wizard,
    process_delete_wizard_input,
)

__all__ = [
    "QuestDeleteSession",
    "get_delete_session",
    "set_delete_session",
    "clear_delete_session",
    "has_active_delete_session",
    "is_delete_wizard_active",
    "cancel_delete_wizard",
    "handle_quest_delete_wizard",
    "process_delete_wizard_input",
]
