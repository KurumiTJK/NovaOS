# kernel/reminders_integration.py
"""
SHIM: This module has moved to kernel/reminders/reminders_integration.py

This file re-exports all symbols for backward compatibility.
New code should import from kernel.reminders.reminders_integration directly.
"""

from kernel.reminders.reminders_integration import check_reminders_wizard

__all__ = ["check_reminders_wizard"]
