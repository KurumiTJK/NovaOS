# kernel/reminders_wizard.py
"""
SHIM: This module has moved to kernel/reminders/reminders_wizard.py

This file re-exports all symbols for backward compatibility.
New code should import from kernel.reminders.reminders_wizard directly.
"""

from kernel.reminders.reminders_wizard import (
    # Session class
    RemindersWizardSession,
    # Session management
    get_wizard_session,
    set_wizard_session,
    clear_wizard_session,
    has_active_wizard,
    # Wizard functions
    start_reminders_wizard,
    process_reminders_wizard_input,
    is_reminders_wizard_command,
    WIZARD_COMMANDS,
)

__all__ = [
    "RemindersWizardSession",
    "get_wizard_session",
    "set_wizard_session",
    "clear_wizard_session",
    "has_active_wizard",
    "start_reminders_wizard",
    "process_reminders_wizard_input",
    "is_reminders_wizard_command",
    "WIZARD_COMMANDS",
]
