# kernel/quest_start_wizard.py
"""
SHIM: This module has moved to kernel/quests/quest_start_wizard.py

This file re-exports all symbols for backward compatibility.
New code should import from kernel.quests.quest_start_wizard directly.
"""

from kernel.quests.quest_start_wizard import (
    # Session class
    QuestStartWizardSession,
    # Session management
    get_wizard_session,
    set_wizard_session,
    clear_wizard_session,
    has_active_wizard_session,
    is_quest_wizard_active,
    cancel_quest_wizard,
    # Main handlers
    handle_quest_wizard_start,
    process_quest_wizard_input,
)

__all__ = [
    "QuestStartWizardSession",
    "get_wizard_session",
    "set_wizard_session",
    "clear_wizard_session",
    "has_active_wizard_session",
    "is_quest_wizard_active",
    "cancel_quest_wizard",
    "handle_quest_wizard_start",
    "process_quest_wizard_input",
]
