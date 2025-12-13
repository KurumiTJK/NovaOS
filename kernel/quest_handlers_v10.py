# kernel/quest_handlers_v10.py
"""
SHIM: This module has moved to kernel/quests/quest_handlers_v10.py

This file re-exports all symbols for backward compatibility.
New code should import from kernel.quests.quest_handlers_v10 directly.
"""

from kernel.quests.quest_handlers_v10 import (
    handle_quest_v10,
    handle_next_v10,
    check_and_route_quest_wizard,
)

__all__ = [
    "handle_quest_v10",
    "handle_next_v10",
    "check_and_route_quest_wizard",
]
