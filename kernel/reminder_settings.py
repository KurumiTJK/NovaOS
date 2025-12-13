# kernel/reminder_settings.py
"""
SHIM: This module has moved to kernel/reminders/reminder_settings.py

This file re-exports all symbols for backward compatibility.
New code should import from kernel.reminders.reminder_settings directly.
"""

from kernel.reminders.reminder_settings import (
    DEFAULT_SETTINGS,
    ReminderSettings,
    get_reminder_settings,
    init_reminder_settings,
)

__all__ = [
    "DEFAULT_SETTINGS",
    "ReminderSettings",
    "get_reminder_settings",
    "init_reminder_settings",
]
