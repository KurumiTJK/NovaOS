# kernel/reminders_handlers.py
"""
SHIM: This module has moved to kernel/reminders/reminders_handlers.py

This file re-exports all symbols for backward compatibility.
New code should import from kernel.reminders.reminders_handlers directly.
"""

from kernel.reminders.reminders_handlers import (
    handle_reminders_list,
    handle_reminders_due,
    handle_reminders_show,
    handle_reminders_add,
    handle_reminders_update,
    handle_reminders_delete,
    handle_reminders_done,
    handle_reminders_snooze,
    handle_reminders_pin,
    handle_reminders_unpin,
    handle_reminders_settings,
    get_reminders_handlers,
)

__all__ = [
    "handle_reminders_list",
    "handle_reminders_due",
    "handle_reminders_show",
    "handle_reminders_add",
    "handle_reminders_update",
    "handle_reminders_delete",
    "handle_reminders_done",
    "handle_reminders_snooze",
    "handle_reminders_pin",
    "handle_reminders_unpin",
    "handle_reminders_settings",
    "get_reminders_handlers",
]
