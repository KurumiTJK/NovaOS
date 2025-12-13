# kernel/quest_lock_mode.py
"""
SHIM: This module has moved to kernel/quests/quest_lock_mode.py

This file re-exports all symbols for backward compatibility.
New code should import from kernel.quests.quest_lock_mode directly.
"""

from kernel.quests.quest_lock_mode import (
    # State class
    QuestLockState,
    # State management
    get_quest_lock_state,
    set_quest_lock_state,
    clear_quest_lock_state,
    is_quest_active,
    # Lock activation
    activate_quest_lock,
    update_quest_lock_step,
    deactivate_quest_lock,
    # Command filtering
    ALLOWED_QUEST_MODE_COMMANDS,
    is_command_allowed_in_quest_mode,
    get_quest_mode_blocked_message,
    # Conversation handling
    build_quest_context_for_llm,
    handle_quest_conversation,
)

__all__ = [
    "QuestLockState",
    "get_quest_lock_state",
    "set_quest_lock_state",
    "clear_quest_lock_state",
    "is_quest_active",
    "activate_quest_lock",
    "update_quest_lock_step",
    "deactivate_quest_lock",
    "ALLOWED_QUEST_MODE_COMMANDS",
    "is_command_allowed_in_quest_mode",
    "get_quest_mode_blocked_message",
    "build_quest_context_for_llm",
    "handle_quest_conversation",
]
