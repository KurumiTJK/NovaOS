# kernel/reminders_api.py
"""
SHIM: This module has moved to kernel/reminders/reminders_api.py

This file re-exports all symbols for backward compatibility.
New code should import from kernel.reminders.reminders_api directly.
"""

from kernel.reminders.reminders_api import (
    init_reminders_api,
    get_due_reminders_for_ui,
    dismiss_reminder_notification,
    clear_dismissed,
    quick_snooze,
    quick_done,
)

__all__ = [
    "init_reminders_api",
    "get_due_reminders_for_ui",
    "dismiss_reminder_notification",
    "clear_dismissed",
    "quick_snooze",
    "quick_done",
]
