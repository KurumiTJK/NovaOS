# kernel/reminders_manager.py
"""
SHIM: This module has moved to kernel/reminders/reminders_manager.py

This file re-exports all symbols for backward compatibility.
New code should import from kernel.reminders.reminders_manager directly.
"""

from kernel.reminders.reminders_manager import (
    # Constants
    DEFAULT_TIMEZONE,
    WEEKDAY_MAP,
    WEEKDAY_ABBREV,
    # Classes
    RepeatWindow,
    RepeatConfig,
    Reminder,
    RemindersManager,
)

__all__ = [
    "DEFAULT_TIMEZONE",
    "WEEKDAY_MAP",
    "WEEKDAY_ABBREV",
    "RepeatWindow",
    "RepeatConfig",
    "Reminder",
    "RemindersManager",
]
