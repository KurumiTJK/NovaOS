# kernel/quest_v10_integration.py
"""
NovaOS v0.10.0 — Quest System Integration Module

This module provides easy integration of the v0.10.0 quest system features:
1. Quest wizard (#quest with no args)
2. Quest lock mode (conversation + command blocking)
3. #complete command (replaces #next as primary)
4. #halt command (pause and exit quest mode)

USAGE:
------
In your kernel initialization (e.g., nova_kernel.py __init__):

    from kernel.quest_v10_integration import apply_quest_v10_integration
    apply_quest_v10_integration(self)

This will:
1. Register #complete and #halt handlers
2. Update #quest to use the wizard
3. Make #next an alias for #complete
4. Update section definitions

For mode_router.py:
    from kernel.quest_v10_integration import check_quest_mode_routing
    
    # In _handle_novaos_mode_strict(), add at the start:
    quest_result = check_quest_mode_routing(message, state.session_id, kernel, persona, state)
    if quest_result:
        return quest_result
"""

from __future__ import annotations

from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from kernel.nova_kernel import NovaKernel
    from persona.nova_persona import NovaPersona


# =============================================================================
# RE-EXPORTS FOR EASY IMPORTING
# =============================================================================

# Quest lock mode
from .quest_lock_mode import (
    is_quest_active,
    get_quest_lock_state,
    activate_quest_lock,
    deactivate_quest_lock,
    update_quest_lock_step,
    is_command_allowed_in_quest_mode,
    get_quest_mode_blocked_message,
    handle_quest_conversation,
    QuestLockState,
)

# Quest start wizard
from .quest_start_wizard import (
    handle_quest_wizard_start,
    process_quest_wizard_input,
    is_quest_wizard_active,
    cancel_quest_wizard,
)

# Complete/halt handlers
from .quest_complete_halt_handlers import (
    handle_complete,
    handle_halt,
    get_complete_halt_handlers,
)

# Updated quest handlers
from .quest_handlers_v10 import (
    handle_quest_v10,
    handle_next_v10,
    check_and_route_quest_wizard,
)


# =============================================================================
# MODE ROUTER INTEGRATION
# =============================================================================

def check_quest_mode_routing(
    message: str,
    session_id: str,
    kernel: "NovaKernel",
    persona: "NovaPersona",
    state: Any,  # NovaState
) -> Optional[Dict[str, Any]]:
    """
    Check if quest mode should handle this input.
    
    Call this at the START of _handle_novaos_mode_strict() in mode_router.py.
    
    Returns:
    - Dict response if quest mode handled the input
    - None if quest mode is not active or the input should pass through
    
    Logic:
    1. If quest start wizard is active → route to wizard
    2. If quest lock mode is active:
       a. Raw text → quest conversation via GPT-5.1
       b. #complete or #halt → allow through (return None)
       c. Any other #command → block with message
    """
    stripped = message.strip()
    mode_name = getattr(state, 'mode_name', 'novaos')
    
    # ─────────────────────────────────────────────────────────────────────
    # CHECK 1: Quest Start Wizard Active
    # ─────────────────────────────────────────────────────────────────────
    if is_quest_wizard_active(session_id):
        # Only process raw text (not # commands) via wizard
        if not stripped.startswith("#"):
            response = process_quest_wizard_input(session_id, stripped, kernel)
            if response:
                return {
                    "text": response.summary,
                    "ok": response.ok,
                    "command": "quest",
                    "data": response.data if hasattr(response, 'data') else {},
                    "mode": mode_name,
                    "handled_by": "quest_start_wizard",
                }
        # # commands pass through even when wizard is active
    
    # ─────────────────────────────────────────────────────────────────────
    # CHECK 2: Quest Lock Mode Active
    # ─────────────────────────────────────────────────────────────────────
    if is_quest_active(session_id):
        lock_state = get_quest_lock_state(session_id)
        
        if stripped.startswith("#"):
            # Extract command name
            cmd_parts = stripped[1:].split(None, 1)
            cmd_name = cmd_parts[0].lower() if cmd_parts else ""
            
            # Check if command is allowed
            if is_command_allowed_in_quest_mode(cmd_name):
                # Allow #complete and #halt to pass through to normal routing
                return None
            else:
                # Block all other commands
                return {
                    "text": get_quest_mode_blocked_message(),
                    "ok": False,
                    "command": "blocked",
                    "mode": mode_name,
                    "handled_by": "quest_lock_mode",
                    "quest_id": lock_state.quest_id,
                }
        else:
            # Raw text → Quest conversation
            result = handle_quest_conversation(
                session_id=session_id,
                user_message=stripped,
                kernel=kernel,
                persona=persona,
            )
            
            result["mode"] = mode_name
            return result
    
    # Quest mode not active, let normal routing handle it
    return None


# =============================================================================
# KERNEL INTEGRATION
# =============================================================================

def apply_quest_v10_integration(kernel: "NovaKernel") -> bool:
    """
    Apply v0.10.0 quest system integration to a NovaKernel instance.
    
    This:
    1. Registers #complete and #halt handlers
    2. Updates #quest handler to use wizard
    3. Makes #next an alias for #complete
    4. Updates the kernel's commands dict
    5. Patches the router's handlers dict (since it copies SYS_HANDLERS at init)
    
    Call this in NovaKernel.__init__() after the router is set up.
    
    Returns True if successful, False otherwise.
    """
    try:
        # Get the syscommand handlers dict
        from .syscommands import SYS_HANDLERS
        
        # Register new handlers in SYS_HANDLERS (for future use)
        SYS_HANDLERS["handle_complete"] = handle_complete
        SYS_HANDLERS["handle_halt"] = handle_halt
        SYS_HANDLERS["handle_quest"] = handle_quest_v10
        SYS_HANDLERS["handle_next"] = handle_next_v10
        
        print("[v0.10.0] Registered quest handlers: complete, halt", flush=True)
        print("[v0.10.0] Updated quest handler with wizard support", flush=True)
        print("[v0.10.0] Updated next as alias for complete", flush=True)
        
        # CRITICAL: Also patch the router's handlers dict
        # The router copies SYS_HANDLERS at init, so we need to patch it directly
        if hasattr(kernel, 'router') and hasattr(kernel.router, 'handlers'):
            kernel.router.handlers["handle_complete"] = handle_complete
            kernel.router.handlers["handle_halt"] = handle_halt
            kernel.router.handlers["handle_quest"] = handle_quest_v10
            kernel.router.handlers["handle_next"] = handle_next_v10
            print("[v0.10.0] Patched router.handlers dict", flush=True)
        else:
            print("[v0.10.0] WARNING: Could not patch router.handlers", flush=True)
        
        # Update kernel's commands dict to include the new commands
        if hasattr(kernel, 'commands') and isinstance(kernel.commands, dict):
            kernel.commands["complete"] = {
                "handler": "handle_complete",
                "category": "workflow",
                "description": "Finish today's lesson, save progress, and preview tomorrow's lesson."
            }
            kernel.commands["halt"] = {
                "handler": "handle_halt",
                "category": "workflow",
                "description": "Pause quest mode and return to normal NovaOS."
            }
            # Update quest description
            if "quest" in kernel.commands:
                kernel.commands["quest"]["description"] = "Open quest wizard to choose and start a quest."
            # Update next description
            if "next" in kernel.commands:
                kernel.commands["next"]["description"] = "Legacy alias for #complete."
            
            print("[v0.10.0] Updated kernel.commands dict", flush=True)
        
        # Update section definitions
        try:
            from .section_defs_v10_patch import apply_v10_section_updates
            apply_v10_section_updates()
        except ImportError:
            print("[v0.10.0] Could not load section_defs patch", flush=True)
        
        return True
        
    except Exception as e:
        print(f"[v0.10.0] Error applying quest integration: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return False


def register_quest_commands(commands_dict: Dict[str, Any]) -> None:
    """
    Register v0.10.0 quest commands in a commands dictionary.
    
    Call this if you need to manually update the commands registry.
    
    Args:
        commands_dict: The commands dictionary (e.g., from commands.json)
    """
    commands_dict["complete"] = {
        "handler": "handle_complete",
        "category": "workflow",
        "description": "Finish today's lesson, save progress, and preview tomorrow's lesson."
    }
    
    commands_dict["halt"] = {
        "handler": "handle_halt",
        "category": "workflow",
        "description": "Pause quest mode and return to normal NovaOS."
    }
    
    # Update next description
    if "next" in commands_dict:
        commands_dict["next"]["description"] = "Legacy alias for #complete. Use #complete instead."


# =============================================================================
# VERSION INFO
# =============================================================================

QUEST_V10_VERSION = "0.10.0"
QUEST_V10_FEATURES = [
    "Quest wizard (#quest with no args)",
    "Quest lock mode with conversation",
    "#complete command to finish lessons",
    "#halt command to pause quest mode",
    "Command blocking while quest is active",
    "Tomorrow preview after completing a lesson",
]


def get_quest_v10_info() -> Dict[str, Any]:
    """Get information about the v0.10.0 quest system."""
    return {
        "version": QUEST_V10_VERSION,
        "features": QUEST_V10_FEATURES,
        "commands": {
            "new": ["#complete", "#halt"],
            "updated": ["#quest", "#next"],
            "unchanged": [
                "#quest-log", "#quest-compose", "#quest-delete",
                "#quest-list", "#quest-inspect", "#quest-debug", "#pause"
            ],
        },
    }
