# kernel/quest_handlers.py
"""
SHIM: This module has moved to kernel/quests/quest_handlers.py

This file re-exports all symbols for backward compatibility.
New code should import from kernel.quests.quest_handlers directly.
"""

from kernel.quests.quest_handlers import (
    # Command handlers
    handle_quest,
    handle_next,
    handle_pause,
    handle_quest_log,
    handle_quest_reset,
    handle_quest_compose,
    handle_quest_delete,
    handle_quest_list,
    handle_quest_inspect,
    handle_quest_debug,
    # Registry
    get_quest_handlers,
    # Wizard helpers
    check_quest_compose_wizard,
    route_to_quest_compose_wizard,
    cancel_quest_compose_wizard,
    check_quest_delete_wizard,
    route_to_quest_delete_wizard,
    cancel_quest_delete_wizard_session,
    check_any_quest_wizard,
    route_to_quest_wizard,
    cancel_all_quest_wizards,
)

__all__ = [
    "handle_quest",
    "handle_next",
    "handle_pause",
    "handle_quest_log",
    "handle_quest_reset",
    "handle_quest_compose",
    "handle_quest_delete",
    "handle_quest_list",
    "handle_quest_inspect",
    "handle_quest_debug",
    "get_quest_handlers",
    "check_quest_compose_wizard",
    "route_to_quest_compose_wizard",
    "cancel_quest_compose_wizard",
    "check_quest_delete_wizard",
    "route_to_quest_delete_wizard",
    "cancel_quest_delete_wizard_session",
    "check_any_quest_wizard",
    "route_to_quest_wizard",
    "cancel_all_quest_wizards",
]
