# core/mode_router.py
"""
NovaOS v0.12.0 - Mode Router (Simplified)

v0.12.0 CHANGE: Removed Council and SOLO/QUEST/LIVE/LIVE-MAX modes
- No more @solo, @explore, @live, @max flags
- No more Gemini-based mode detection
- Simple two-mode system: Strict (NovaOS) vs Persona

The single entrypoint for all user messages.
Routes based on NovaState.novaos_enabled:

- novaos_enabled=True (NovaOS Mode / STRICT MODE) - DEFAULT:
    -> Full kernel routing (syscommands, modules, NL router)
    -> NO persona fallback - command shell only
    -> Unrecognized input returns fixed error message
    -> #boot enters Persona mode

- novaos_enabled=False (Persona Mode):
    -> Pure conversational Nova
    -> Only #shutdown is recognized to return to strict mode
    -> Everything else goes directly to persona.chat()

This file is the ONLY place that decides which mode handles input.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Dict, Optional

from .nova_state import NovaState

# Working Memory imports (shared between modes)
from kernel.nova_wm import (
    wm_update,
    wm_record_response,
    wm_get_context_string,
    wm_answer_reference,
    get_wm,
)

# v0.11.0: Memory Helpers (ChatGPT-style memory features)
try:
    from kernel.memory_helpers import (
        handle_remember_intent,
        build_ltm_context_for_persona,
        run_auto_extraction,
    )
    _HAS_MEMORY_HELPERS = True
except ImportError:
    _HAS_MEMORY_HELPERS = False
    def handle_remember_intent(*args, **kwargs): return None
    def build_ltm_context_for_persona(*args, **kwargs): return ""
    def run_auto_extraction(*args, **kwargs): return {}

if TYPE_CHECKING:
    from kernel.nova_kernel import NovaKernel
    from persona.nova_persona import NovaPersona


# -----------------------------------------------------------------------------
# CONSTANTS
# -----------------------------------------------------------------------------

# Fixed error message for unrecognized input in strict/NovaOS mode
STRICT_MODE_ERROR_MESSAGE = (
    "Nova cannot complete this request at this time. "
    "Please exit NovaOS mode to continue."
)


# -----------------------------------------------------------------------------
# STATE MANAGEMENT
# -----------------------------------------------------------------------------

_states: Dict[str, NovaState] = {}


def get_or_create_state(session_id: str) -> NovaState:
    """Get existing state or create new one for session."""
    if session_id not in _states:
        _states[session_id] = NovaState(session_id=session_id)
    return _states[session_id]


def clear_state(session_id: str) -> None:
    """Clear state for a session."""
    if session_id in _states:
        del _states[session_id]


def clear_all_states() -> None:
    """Clear all session states."""
    _states.clear()


# -----------------------------------------------------------------------------
# QUEST MODE HELPERS
# -----------------------------------------------------------------------------

def _check_quest_mode(
    message: str,
    session_id: str,
    kernel: "NovaKernel",
    persona: "NovaPersona",
    state: NovaState,
) -> Optional[Dict[str, Any]]:
    """
    Check if we're in quest mode and handle accordingly.
    
    Quest mode allows:
    - Quest start wizard (selecting quest/lesson by number)
    - Quest lock mode (conversation during active quest)
    - Only #complete and #halt commands during active quest
    """
    # Check if quest module is available
    quest_module = getattr(kernel, '_quest_module', None)
    if not quest_module:
        return None
    
    # Check for active quest lock
    active_quest = quest_module.get_active_quest(session_id) if hasattr(quest_module, 'get_active_quest') else None
    
    if active_quest:
        stripped = message.strip().lower()
        
        # Allow #complete and #halt during quest mode
        if stripped in ('#complete', '#halt'):
            return None  # Let kernel handle it
        
        # Block other commands during quest lock
        if stripped.startswith('#'):
            return {
                "text": f"Quest '{active_quest.get('title', 'Active Quest')}' is in progress. Use #complete to finish current step or #halt to pause the quest.",
                "mode": state.mode_name,
                "handled_by": "quest_lock",
                "ok": False,
                "error": "QUEST_MODE_ERROR",
            }
        
        # Non-command input during quest - route to persona for conversation
        wm_context_string = wm_get_context_string(session_id)
        ltm_context_string = ""
        
        if _HAS_MEMORY_HELPERS:
            try:
                ltm_context_string = build_ltm_context_for_persona(
                    user_text=message,
                    memory_manager=kernel.memory_manager,
                )
            except Exception as e:
                print(f"[ModeRouter] Quest mode LTM error: {e}", flush=True)
        
        response_text = persona.generate_response(
            text=message,
            session_id=session_id,
            wm_context_string=wm_context_string,
            ltm_context_string=ltm_context_string,
        )
        
        if response_text:
            wm_record_response(session_id, response_text)
        
        return {
            "text": response_text,
            "mode": state.mode_name,
            "handled_by": "quest_conversation",
            "ok": True,
        }
    
    # Check for quest start wizard
    quest_wizard_active = quest_module.is_quest_wizard_active(session_id) if hasattr(quest_module, 'is_quest_wizard_active') else False
    
    if quest_wizard_active:
        stripped = message.strip()
        
        # If it's a number, route to quest wizard
        if stripped.isdigit():
            result = quest_module.handle_quest_selection(session_id, int(stripped))
            if result:
                return {
                    "text": result.get("text", ""),
                    "mode": state.mode_name,
                    "handled_by": "quest_wizard",
                    "ok": result.get("ok", True),
                    "data": result.get("data"),
                }
    
    return None


# -----------------------------------------------------------------------------
# INTERACTIVE SESSION HELPERS  
# -----------------------------------------------------------------------------

def _check_interactive_session(session_id: str, kernel: "NovaKernel") -> Optional[str]:
    """
    Check if there's an active interactive wizard session.
    
    Returns the wizard type if active, None otherwise.
    """
    # Check quest-compose wizard
    try:
        from kernel.quest_compose_wizard import get_compose_session
        session = get_compose_session(session_id)
        if session:
            return "quest_compose"
    except ImportError:
        pass
    
    # Check command-wizard
    try:
        from kernel.command_wizard import get_wizard_session
        session = get_wizard_session(session_id)
        if session:
            return "command_wizard"
    except ImportError:
        pass
    
    return None


def _route_to_interactive_session(
    session_id: str,
    wizard_type: str,
    user_input: str,
    kernel: "NovaKernel",
) -> Optional[Dict[str, Any]]:
    """Route input to the appropriate interactive wizard."""
    
    if wizard_type == "quest_compose":
        try:
            from kernel.quest_compose_wizard import handle_wizard_input
            result = handle_wizard_input(
                cmd_name="quest-compose",
                session_id=session_id,
                user_input=user_input,
                kernel=kernel,
            )
            if result:
                return {
                    "text": result.get("text", ""),
                    "ok": result.get("ok", True),
                    "handled_by": "quest_compose_wizard",
                    "data": result.get("data"),
                    "meta": result.get("meta"),
                }
        except Exception as e:
            print(f"[ModeRouter] Quest compose wizard error: {e}", flush=True)
    
    elif wizard_type == "command_wizard":
        try:
            from kernel.command_wizard import handle_wizard_input
            result = handle_wizard_input(session_id, user_input, kernel)
            if result:
                return {
                    "text": result.get("text", ""),
                    "ok": result.get("ok", True),
                    "handled_by": "command_wizard",
                    "data": result.get("data"),
                }
        except Exception as e:
            print(f"[ModeRouter] Command wizard error: {e}", flush=True)
    
    return None


# -----------------------------------------------------------------------------
# COMMAND DETECTION
# -----------------------------------------------------------------------------

def _is_boot_command(message: str) -> bool:
    """Check if message is a #boot command."""
    stripped = message.strip().lower()
    return stripped == "#boot" or stripped.startswith("#boot ")


def _is_shutdown_command(message: str) -> bool:
    """Check if message is a #shutdown command."""
    stripped = message.strip().lower()
    return stripped == "#shutdown" or stripped.startswith("#shutdown ")


# -----------------------------------------------------------------------------
# MAIN ENTRY POINT
# -----------------------------------------------------------------------------

def handle_user_message(
    message: str,
    session_id: str,
    kernel: "NovaKernel",
    persona: "NovaPersona",
) -> Dict[str, Any]:
    """
    Main entry point for all user messages.
    
    Routes based on NovaState.novaos_enabled:
    - True (default): NovaOS strict mode (command shell)
    - False: Persona mode (conversational)
    """
    state = get_or_create_state(session_id)
    
    # Update working memory with user input
    wm_update(session_id, message, role="user")
    
    # v0.11.0: Check for "remember" intent in any mode
    if _HAS_MEMORY_HELPERS and hasattr(kernel, 'memory_manager'):
        remember_result = handle_remember_intent(message, kernel.memory_manager)
        if remember_result and remember_result.get("handled"):
            return {
                "text": remember_result.get("text", "I'll remember that."),
                "mode": state.mode_name,
                "handled_by": "memory_intent",
                "ok": True,
            }
    
    # Route based on mode
    if state.novaos_enabled:
        return _handle_novaos_mode(message, state, kernel, persona)
    else:
        return _handle_persona_mode(message, state, kernel, persona)


# -----------------------------------------------------------------------------
# PERSONA MODE HANDLER
# -----------------------------------------------------------------------------

def _handle_persona_mode(
    message: str,
    state: NovaState,
    kernel: "NovaKernel",
    persona: "NovaPersona",
) -> Dict[str, Any]:
    """
    Handle messages in Persona mode (pure conversation).
    
    Only #shutdown is recognized to return to strict mode.
    Everything else goes to persona.
    """
    
    # Check for #shutdown (return to strict mode)
    if _is_shutdown_command(message):
        return _activate_novaos(state, kernel, persona)
    
    # Get context for persona
    wm_context_string = wm_get_context_string(state.session_id)
    ltm_context_string = ""
    
    if _HAS_MEMORY_HELPERS and hasattr(kernel, 'memory_manager'):
        try:
            ltm_context_string = build_ltm_context_for_persona(
                user_text=message,
                memory_manager=kernel.memory_manager,
            )
        except Exception as e:
            print(f"[ModeRouter] Persona LTM error: {e}", flush=True)
    
    # Generate persona response
    response_text = persona.generate_response(
        text=message,
        session_id=state.session_id,
        wm_context_string=wm_context_string,
        ltm_context_string=ltm_context_string,
    )
    
    # Record response to working memory
    if response_text:
        wm_record_response(state.session_id, response_text)
    
    # v0.11.0: Run auto-extraction for memory
    if _HAS_MEMORY_HELPERS and hasattr(kernel, 'memory_manager'):
        try:
            run_auto_extraction(
                user_text=message,
                assistant_text=response_text,
                memory_manager=kernel.memory_manager,
            )
        except Exception as e:
            print(f"[ModeRouter] Auto-extraction error: {e}", flush=True)
    
    return {
        "text": response_text,
        "mode": state.mode_name,
        "handled_by": "persona",
        "ok": True,
    }


# -----------------------------------------------------------------------------
# NOVAOS MODE HANDLER
# -----------------------------------------------------------------------------

def _handle_novaos_mode(
    message: str,
    state: NovaState,
    kernel: "NovaKernel",
    persona: "NovaPersona",
) -> Dict[str, Any]:
    """
    Handle messages in NovaOS/Strict mode (command shell).
    
    Routes through kernel for syscommands.
    Unrecognized input returns error (no persona fallback).
    
    This is a COMMAND SHELL, not a chat mode.
    (Exception: Quest lock mode allows conversation during active quests)
    """
    
    # Check for #boot (enters persona mode)
    if _is_boot_command(message):
        return _deactivate_novaos(state, kernel, persona)
    
    # Quest mode check (must be first)
    quest_result = _check_quest_mode(message, state.session_id, kernel, persona, state)
    if quest_result:
        return quest_result
    
    # Check for active interactive wizard
    stripped = message.strip()
    if not stripped.startswith("#"):
        wizard_type = _check_interactive_session(state.session_id, kernel)
        if wizard_type:
            wizard_result = _route_to_interactive_session(
                state.session_id,
                wizard_type,
                stripped,
                kernel,
            )
            if wizard_result:
                wizard_result["mode"] = state.mode_name
                return wizard_result
    
    # Route through kernel
    kernel_result = kernel.handle_input(message, state.session_id)
    
    # Normalize to dict
    if hasattr(kernel_result, "to_dict"):
        result_dict = kernel_result.to_dict()
    elif hasattr(kernel_result, "__dict__"):
        result_dict = kernel_result.__dict__
    else:
        result_dict = dict(kernel_result) if kernel_result else {}
    
    # Check if kernel handled it or fell back to persona
    kernel_command = result_dict.get("command", "")
    kernel_type = result_dict.get("type", "")
    meta_source = (result_dict.get("meta") or {}).get("source", "")
    
    # Detect persona fallback
    is_persona_fallback = (
        kernel_command == "persona" or
        kernel_command == "natural_language" or
        kernel_type in ("fallback", "persona", "error_fallback") or
        meta_source == "persona_fallback"
    )
    
    if is_persona_fallback:
        # STRICT MODE: Return fixed error message, NO persona fallback
        return {
            "text": STRICT_MODE_ERROR_MESSAGE,
            "mode": state.mode_name,
            "handled_by": "strict_mode_error",
            "ok": False,
            "error": "UNRECOGNIZED_INPUT",
        }
    
    # Kernel handled it - return the result
    text = (
        result_dict.get("text") or
        result_dict.get("summary") or
        (result_dict.get("content", {}).get("summary") 
         if isinstance(result_dict.get("content"), dict) else None) or
        ""
    )
    
    return {
        "text": text,
        "mode": state.mode_name,
        "handled_by": "kernel",
        "ok": result_dict.get("ok", True),
        "command": result_dict.get("command"),
        "type": kernel_type,
        "data": result_dict.get("data") or result_dict.get("extra") or result_dict.get("content"),
    }


# -----------------------------------------------------------------------------
# MODE TRANSITIONS
# -----------------------------------------------------------------------------

def _activate_novaos(
    state: NovaState,
    kernel: "NovaKernel",
    persona: "NovaPersona",
) -> Dict[str, Any]:
    """
    Activate NovaOS/Strict mode (return to command shell).
    Called by #shutdown.
    """
    state.enable_novaos()
    
    # Call kernel's shutdown handler for cleanup
    kernel.handle_input("#shutdown", state.session_id)
    
    shutdown_message = (
        "NovaOS is now running in strict mode. "
        "Only syscommands and recognized command phrases are accepted. "
        "Type #help to see available commands, or #boot to enter conversation mode."
    )
    
    response_text = persona.generate_response(
        text="[SYSTEM: Acknowledge that NovaOS has returned to strict mode]",
        session_id=state.session_id,
        direct_answer=shutdown_message,
    )
    
    return {
        "text": response_text,
        "mode": state.mode_name,
        "handled_by": "mode_router",
        "ok": True,
        "transition": "persona_to_novaos",
    }


def _deactivate_novaos(
    state: NovaState,
    kernel: "NovaKernel",
    persona: "NovaPersona",
) -> Dict[str, Any]:
    """
    Deactivate NovaOS/Strict mode (enter persona/conversation mode).
    Called by #boot.
    """
    state.disable_novaos()
    
    # Call kernel's boot handler
    kernel.handle_input("#boot", state.session_id)
    
    boot_message = (
        "Nova is now in conversation mode. "
        "I can help you with questions, tasks, and general conversation. "
        "Type #shutdown to return to NovaOS strict mode."
    )
    
    response_text = persona.generate_response(
        text="[SYSTEM: Acknowledge that Nova has entered conversation mode]",
        session_id=state.session_id,
        direct_answer=boot_message,
    )
    
    return {
        "text": response_text,
        "mode": state.mode_name,
        "handled_by": "mode_router",
        "ok": True,
        "transition": "novaos_to_persona",
    }


# -----------------------------------------------------------------------------
# EXPORTS
# -----------------------------------------------------------------------------

__all__ = [
    "handle_user_message",
    "get_or_create_state",
    "clear_state",
    "clear_all_states",
    "NovaState",
]