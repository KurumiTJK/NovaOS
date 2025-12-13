# kernel/quest_v10_integration.py
"""
SHIM: This module has moved to kernel/quests/quest_v10_integration.py

This file re-exports all symbols for backward compatibility.
New code should import from kernel.quests.quest_v10_integration directly.
"""

from kernel.quests.quest_v10_integration import (
    # Main integration
    apply_quest_v10_integration,
    check_quest_mode_routing,
    register_quest_commands,
    get_quest_v10_info,
    # Re-exports from quest_lock_mode
    is_quest_active,
    get_quest_lock_state,
    activate_quest_lock,
    deactivate_quest_lock,
    update_quest_lock_step,
    is_command_allowed_in_quest_mode,
    get_quest_mode_blocked_message,
    handle_quest_conversation,
    QuestLockState,
    # Re-exports from quest_start_wizard
    handle_quest_wizard_start,
    process_quest_wizard_input,
    is_quest_wizard_active,
    cancel_quest_wizard,
    # Re-exports from quest_complete_halt_handlers
    handle_complete,
    handle_halt,
    get_complete_halt_handlers,
    # Re-exports from quest_handlers_v10
    handle_quest_v10,
    handle_next_v10,
    check_and_route_quest_wizard,
)

__all__ = [
    "apply_quest_v10_integration",
    "check_quest_mode_routing",
    "register_quest_commands",
    "get_quest_v10_info",
    "is_quest_active",
    "get_quest_lock_state",
    "activate_quest_lock",
    "deactivate_quest_lock",
    "update_quest_lock_step",
    "is_command_allowed_in_quest_mode",
    "get_quest_mode_blocked_message",
    "handle_quest_conversation",
    "QuestLockState",
    "handle_quest_wizard_start",
    "process_quest_wizard_input",
    "is_quest_wizard_active",
    "cancel_quest_wizard",
    "handle_complete",
    "handle_halt",
    "get_complete_halt_handlers",
    "handle_quest_v10",
    "handle_next_v10",
    "check_and_route_quest_wizard",
]
