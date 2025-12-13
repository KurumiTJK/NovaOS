# kernel/quest_complete_halt_handlers.py
"""
SHIM: This module has moved to kernel/quests/quest_complete_halt_handlers.py

This file re-exports all symbols for backward compatibility.
New code should import from kernel.quests.quest_complete_halt_handlers directly.
"""

from kernel.quests.quest_complete_halt_handlers import (
    handle_complete,
    handle_halt,
    get_complete_halt_handlers,
)

__all__ = [
    "handle_complete",
    "handle_halt",
    "get_complete_halt_handlers",
]
