# kernel/reminder_service.py
"""
SHIM: This module has moved to kernel/reminders/reminder_service.py

This file re-exports all symbols for backward compatibility.
New code should import from kernel.reminders.reminder_service directly.
"""

from kernel.reminders.reminder_service import (
    # Backends
    NotificationBackend,
    NtfyBackend,
    WebhookBackend,
    EmailBackend,
    ConsoleBackend,
    # Service
    ReminderService,
    get_reminder_service,
    init_reminder_service,
    stop_reminder_service,
)

__all__ = [
    "NotificationBackend",
    "NtfyBackend",
    "WebhookBackend",
    "EmailBackend",
    "ConsoleBackend",
    "ReminderService",
    "get_reminder_service",
    "init_reminder_service",
    "stop_reminder_service",
]
