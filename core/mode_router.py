# core/mode_router.py
"""
NovaOS v0.10.0 — Mode Router

The single entrypoint for all user messages.
Routes based on NovaState.novaos_enabled:

- novaos_enabled=False (Persona Mode):
    → Pure conversational Nova
    → Only #boot is recognized to switch modes
    → Everything else goes directly to persona.chat()

- novaos_enabled=True (NovaOS Mode / STRICT MODE):
    → Full kernel routing (syscommands, modules, NL router)
    → NO persona fallback - command shell only
    → Unrecognized input returns fixed error message
    → #shutdown returns to Persona mode
    
v0.10.0 CHANGES:
    → Added quest lock mode support
    → When a quest is active, raw text goes to Nova for conversation
    → Only #complete and #halt are allowed during quest mode
    → Quest start wizard allows selecting quests by number
    
v0.9.2 CHANGES:
    → Added support for interactive wizard sessions (e.g., #quest-compose)
    → When a wizard is active, raw text input is routed to the wizard handler
      instead of returning the strict-mode error

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


# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

# Fixed error message for unrecognized input in strict/NovaOS mode
STRICT_MODE_ERROR_MESSAGE = (
    "Nova cannot complete this request at this time. "
    "Please exit NovaOS mode to continue."
)


# ─────────────────────────────────────────────────────────────────────────────
# BOOT / SHUTDOWN DETECTION
# ─────────────────────────────────────────────────────────────────────────────

BOOT_PATTERNS = re.compile(r"^#boot\b", re.IGNORECASE)
SHUTDOWN_PATTERNS = re.compile(r"^#shutdown\b", re.IGNORECASE)
# v0.11.0-fix5: Session-end pattern for persona mode support
SESSION_END_PATTERNS = re.compile(r"^#session-end\b", re.IGNORECASE)


def _is_boot_command(message: str) -> bool:
    """Check if message is a boot command."""
    return bool(BOOT_PATTERNS.match(message.strip()))


def _is_shutdown_command(message: str) -> bool:
    """Check if message is a shutdown command."""
    return bool(SHUTDOWN_PATTERNS.match(message.strip()))


def _is_session_end_command(message: str) -> bool:
    """Check if message is a session-end command."""
    return bool(SESSION_END_PATTERNS.match(message.strip()))


# ─────────────────────────────────────────────────────────────────────────────
# v0.10.0: QUEST LOCK MODE CHECK
# ─────────────────────────────────────────────────────────────────────────────

def _check_quest_mode(
    message: str,
    session_id: str,
    kernel: "NovaKernel",
    persona: "NovaPersona",
    state: "NovaState",
) -> Optional[Dict[str, Any]]:
    """
    v0.10.0: Check if quest mode should handle this input.
    
    Returns a response dict if quest mode handled it, None otherwise.
    
    Quest mode has TWO states:
    1. Quest START wizard active (choosing quest/lesson)
       - Raw text and numbers route to wizard
    2. Quest LOCK mode active (during a lesson)
       - Raw text routes to Nova conversation
       - #complete and #halt are allowed
       - Other # commands are blocked
    """
    try:
        from kernel.quest_v10_integration import check_quest_mode_routing
        result = check_quest_mode_routing(message, session_id, kernel, persona, state)
        if result:
            # Add mode info
            result["mode"] = state.mode_name
            return result
        return None
    except ImportError as e:
        print(f"[ModeRouter] quest mode ImportError: {e}", flush=True)
        return None
    except Exception as e:
        # Log the FULL error - this is critical for debugging Lightsail issues
        print(f"[ModeRouter] quest mode check error: {e}", flush=True)
        import traceback
        traceback.print_exc()
        
        # Return a clear error instead of falling through to strict mode error
        return {
            "text": f"⚠️ Quest mode error: {e}\n\nPlease check server logs for details.",
            "mode": state.mode_name,
            "handled_by": "quest_mode_error",
            "ok": False,
            "error": "QUEST_MODE_ERROR",
        }


# ─────────────────────────────────────────────────────────────────────────────
# INTERACTIVE SESSION CHECK
# ─────────────────────────────────────────────────────────────────────────────

def _check_interactive_session(session_id: str, kernel: "NovaKernel") -> Optional[str]:
    """
    Check if any interactive wizard session is active.
    
    Returns the wizard type name if active, None otherwise.
    
    This allows raw text to bypass strict mode when a wizard is waiting for input.
    """
    # Check quest-compose wizard
    try:
        from kernel.quest_compose_wizard import has_active_compose_session
        if has_active_compose_session(session_id):
            return "quest-compose"
    except ImportError:
        pass
    
    # Check command-add wizard
    try:
        from kernel.command_add_wizard import is_command_add_wizard_active
        if is_command_add_wizard_active(session_id):
            return "command-add"
    except ImportError:
        pass
    
    # Check generic wizard_mode wizards
    try:
        from kernel.wizard_mode import is_wizard_active
        if is_wizard_active(session_id):
            return "generic-wizard"
    except ImportError:
        pass
    
    return None


def _route_to_interactive_session(
    session_id: str,
    wizard_type: str,
    message: str,
    kernel: "NovaKernel",
) -> Optional[Dict[str, Any]]:
    """
    Route input to the active interactive wizard.
    
    Returns the wizard response dict, or None if routing failed.
    """
    if wizard_type == "quest-compose":
        try:
            from kernel.quest_compose_wizard import (
                process_compose_wizard_input,
                get_compose_session,
            )
            session = get_compose_session(session_id)
            if session:
                response = process_compose_wizard_input(session_id, message, kernel)
                if response:
                    return {
                        "text": response.summary,
                        "ok": response.ok,
                        "command": "quest-compose",
                        "data": response.data,
                        "handled_by": "quest-compose-wizard",
                    }
        except Exception as e:
            print(f"[ModeRouter] quest-compose wizard error: {e}", flush=True)
            return None
    
    elif wizard_type == "command-add":
        try:
            from kernel.command_add_wizard import process_wizard_stage
            response = process_wizard_stage(session_id, message, kernel)
            if response:
                return {
                    "text": response.summary,
                    "ok": response.ok,
                    "command": "command-add",
                    "data": response.data,
                    "handled_by": "command-add-wizard",
                }
        except Exception as e:
            print(f"[ModeRouter] command-add wizard error: {e}", flush=True)
            return None
    
    elif wizard_type == "generic-wizard":
        try:
            from kernel.wizard_mode import process_wizard_input, build_command_args_from_wizard
            result = process_wizard_input(session_id, message)
            if result:
                # v1.0.0: Check if wizard completed - if so, execute the command
                if result.get("extra", {}).get("wizard_complete"):
                    target_cmd = result["extra"]["target_command"]
                    collected = result["extra"]["collected_args"]
                    args_dict = build_command_args_from_wizard(target_cmd, collected)
                    
                    print(f"[ModeRouter] Wizard complete, executing: {target_cmd} with args={args_dict}", flush=True)
                    
                    # Execute the command through the kernel
                    from kernel.command_types import CommandRequest
                    request = CommandRequest(
                        cmd_name=target_cmd,
                        args=args_dict,
                        session_id=session_id,
                        raw_text=message,
                        meta=kernel.commands.get(target_cmd),
                    )
                    response = kernel.router.route(request, kernel=kernel)
                    
                    return {
                        "text": response.summary if response.summary else "Command executed.",
                        "ok": response.ok,
                        "command": target_cmd,
                        "data": response.data if hasattr(response, 'data') else {},
                        "handled_by": "generic-wizard-complete",
                    }
                
                # Wizard still in progress
                return {
                    "text": result.get("summary", ""),
                    "ok": result.get("ok", True),
                    "command": result.get("command", "wizard"),
                    "data": result.get("extra", {}),
                    "handled_by": "generic-wizard",
                }
        except Exception as e:
            print(f"[ModeRouter] generic wizard error: {e}", flush=True)
            import traceback
            traceback.print_exc()
            return None
    
    return None


# ─────────────────────────────────────────────────────────────────────────────
# MAIN ENTRYPOINT
# ─────────────────────────────────────────────────────────────────────────────

def handle_user_message(
    message: str,
    state: NovaState,
    kernel: "NovaKernel",
    persona: "NovaPersona",
) -> Dict[str, Any]:
    """
    Main entrypoint for all user messages.
    
    Routing logic:
    1. If NovaOS is OFF (Persona mode):
       - Check for #boot → activate NovaOS
       - Else → persona chat
    
    2. If NovaOS is ON (Strict mode):
       - Check for #shutdown → deactivate NovaOS
       - Check for active interactive wizard → route to wizard
       - Route through kernel
       - If kernel falls back to persona → return strict error
       - Else → return kernel result
    """
    
    if state.novaos_enabled:
        return _handle_novaos_mode_strict(message, state, kernel, persona)
    else:
        return _handle_persona_mode(message, state, kernel, persona)


# ─────────────────────────────────────────────────────────────────────────────
# PERSONA MODE HANDLER (unchanged)
# ─────────────────────────────────────────────────────────────────────────────

def _handle_persona_mode(
    message: str,
    state: NovaState,
    kernel: "NovaKernel",
    persona: "NovaPersona",
) -> Dict[str, Any]:
    """
    Handle input when NovaOS is OFF (Persona mode).
    
    Only #boot is recognized. Everything else is pure persona chat.
    
    v0.11.0: Added memory features (remember this, auto-extraction, LTM injection)
    v0.11.0-fix5: Added #session-end support in persona mode
    """
    
    # Check for #boot command
    if _is_boot_command(message):
        return _activate_novaos(state, kernel, persona)
    
    # ─────────────────────────────────────────────────────────────────────
    # v0.11.0-fix5: #session-end support in persona mode
    # ─────────────────────────────────────────────────────────────────────
    if _is_session_end_command(message):
        return _handle_session_end_in_persona_mode(state, kernel, persona)
    
    # ─────────────────────────────────────────────────────────────────────
    # v0.11.0: "REMEMBER THIS" CHECK (short-circuit if detected)
    # ─────────────────────────────────────────────────────────────────────
    if _HAS_MEMORY_HELPERS:
        try:
            remember_response = handle_remember_intent(
                user_text=message,
                memory_manager=kernel.memory_manager,
                session_id=state.session_id,
                wm=get_wm(state.session_id),
            )
            if remember_response:
                return {
                    "text": remember_response,
                    "mode": state.mode_name,
                    "handled_by": "memory_remember_intent",
                }
        except Exception as e:
            print(f"[ModeRouter] remember_intent error: {e}", flush=True)
    
    # ─────────────────────────────────────────────────────────────────────
    # v0.11.0: AUTO-EXTRACTION (profile, procedural, episodic)
    # v0.11.0-fix1: Removed session_id param (not accepted by function)
    # ─────────────────────────────────────────────────────────────────────
    if _HAS_MEMORY_HELPERS:
        try:
            run_auto_extraction(
                user_text=message,
                memory_manager=kernel.memory_manager,
            )
        except Exception as e:
            print(f"[ModeRouter] auto_extraction error: {e}", flush=True)
    
    # Working Memory updates
    direct_answer = wm_answer_reference(state.session_id, message)
    wm_update(state.session_id, message)
    wm_context_string = wm_get_context_string(state.session_id)
    
    # ─────────────────────────────────────────────────────────────────────
    # v0.11.0: BUILD LTM CONTEXT (profile + relevant semantic memories)
    # v0.11.0-fix1: Fixed parameter name (module_tag, not current_module)
    # v0.11.0-fix6: Added logging to verify LTM injection
    # ─────────────────────────────────────────────────────────────────────
    ltm_context_string = ""
    if _HAS_MEMORY_HELPERS:
        try:
            ltm_context_string = build_ltm_context_for_persona(
                memory_manager=kernel.memory_manager,
                module_tag=None,      # FIXED: correct parameter name
                user_text=message,    # Now accepted by patched function
            )
            # v0.11.0-fix6: Log LTM injection for debugging
            if ltm_context_string:
                # Count memories injected (rough count by looking for markers)
                mem_count = ltm_context_string.count("•") or ltm_context_string.count("-")
                print(f"[ModeRouter] LTM injected: {len(ltm_context_string)} chars, ~{mem_count} memories", flush=True)
            else:
                print("[ModeRouter] LTM context empty (no memories retrieved)", flush=True)
        except Exception as e:
            print(f"[ModeRouter] LTM context build error: {e}", flush=True)
    
    # Persona chat (normal conversational fallback)
    response_text = persona.generate_response(
        text=message,
        session_id=state.session_id,
        wm_context_string=wm_context_string,
        ltm_context_string=ltm_context_string,  # v0.11.0: LTM injection
        direct_answer=direct_answer,
    )
    
    if response_text:
        wm_record_response(state.session_id, response_text)
    
    return {
        "text": response_text,
        "mode": state.mode_name,
        "handled_by": "persona",
    }


# ─────────────────────────────────────────────────────────────────────────────
# NOVAOS MODE HANDLER - STRICT (with interactive session support)
# ─────────────────────────────────────────────────────────────────────────────

def _handle_novaos_mode_strict(
    message: str,
    state: NovaState,
    kernel: "NovaKernel",
    persona: "NovaPersona",
) -> Dict[str, Any]:
    """
    Handle input when NovaOS is ON (STRICT mode).
    
    v0.10.0 STRICT MODE BEHAVIOR:
    
    FOUR things are allowed:
    1. Valid syscommands (e.g., #status, #help, #quest)
    2. Natural language inputs successfully mapped to a syscommand via NL router
    3. Raw text input when an interactive wizard is active (e.g., #quest-compose)
    4. Raw text input when quest lock mode is active (conversation with Nova)
    
    If none of these match:
    - NO persona fallback
    - NO open conversation
    - Returns fixed error message
    
    This is a COMMAND SHELL, not a chat mode.
    (Exception: Quest lock mode allows conversation during active quests)
    """
    
    # Check for #shutdown
    if _is_shutdown_command(message):
        return _deactivate_novaos(state, kernel, persona)
    
    # ─────────────────────────────────────────────────────────────────────
    # v0.10.0: QUEST MODE CHECK (MUST BE FIRST)
    # ─────────────────────────────────────────────────────────────────────
    # Quest mode handles:
    # - Quest start wizard (selecting quest/lesson by number)
    # - Quest lock mode (conversation during active quest)
    # - Command blocking (only #complete and #halt allowed)
    
    quest_result = _check_quest_mode(message, state.session_id, kernel, persona, state)
    if quest_result:
        return quest_result
    
    # ─────────────────────────────────────────────────────────────────────
    # v0.9.2: CHECK FOR ACTIVE INTERACTIVE WIZARD
    # ─────────────────────────────────────────────────────────────────────
    # If a wizard is active and input doesn't start with #, route to wizard
    
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
    
    # ─────────────────────────────────────────────────────────────────────
    # ROUTE THROUGH KERNEL
    # ─────────────────────────────────────────────────────────────────────
    
    kernel_result = kernel.handle_input(message, state.session_id)
    
    # Normalize to dict
    if hasattr(kernel_result, "to_dict"):
        result_dict = kernel_result.to_dict()
    elif hasattr(kernel_result, "__dict__"):
        result_dict = kernel_result.__dict__
    else:
        result_dict = dict(kernel_result) if kernel_result else {}
    
    # ─────────────────────────────────────────────────────────────────────
    # CHECK IF KERNEL HANDLED IT OR FELL BACK TO PERSONA
    # ─────────────────────────────────────────────────────────────────────
    
    # The kernel returns these indicators when it falls back to persona:
    # 1. "command": "persona" — the kernel's persona fallback path
    # 2. "type": "fallback" or "persona" or "error_fallback" — explicit fallback types
    # 3. meta.source == "persona_fallback" — from the kernel's fallback metadata
    
    kernel_command = result_dict.get("command", "")
    kernel_type = result_dict.get("type", "")
    meta_source = (result_dict.get("meta") or {}).get("source", "")
    
    # Detect persona fallback by ANY of these signals
    is_persona_fallback = (
        kernel_command == "persona" or
        kernel_command == "natural_language" or
        kernel_type in ("fallback", "persona", "error_fallback") or
        meta_source == "persona_fallback"
    )
    
    if is_persona_fallback:
        # ─────────────────────────────────────────────────────────────────
        # STRICT MODE: Return fixed error message, NO persona fallback
        # ─────────────────────────────────────────────────────────────────
        return {
            "text": STRICT_MODE_ERROR_MESSAGE,
            "mode": state.mode_name,
            "handled_by": "strict_mode_error",
            "ok": False,
            "error": "UNRECOGNIZED_INPUT",
        }
    
    # ─────────────────────────────────────────────────────────────────────
    # KERNEL HANDLED IT - Return the result
    # ─────────────────────────────────────────────────────────────────────
    
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


# ─────────────────────────────────────────────────────────────────────────────
# MODE TRANSITIONS
# ─────────────────────────────────────────────────────────────────────────────

def _activate_novaos(
    state: NovaState,
    kernel: "NovaKernel",
    persona: "NovaPersona",
) -> Dict[str, Any]:
    """Activate NovaOS mode (strict command shell)."""
    state.enable_novaos()
    
    boot_result = kernel.handle_input("#boot", state.session_id)
    
    boot_message = (
        "NovaOS is now running in strict mode. "
        "Only syscommands and recognized command phrases are accepted. "
        "Type #help to see available commands, or #shutdown to exit."
    )
    
    response_text = persona.generate_response(
        text="[SYSTEM: Acknowledge that NovaOS has booted in strict mode]",
        session_id=state.session_id,
        direct_answer=boot_message,
    )
    
    return {
        "text": response_text,
        "mode": state.mode_name,
        "handled_by": "mode_router",
        "event": "boot",
        "ok": True,
    }


def _deactivate_novaos(
    state: NovaState,
    kernel: "NovaKernel",
    persona: "NovaPersona",
) -> Dict[str, Any]:
    """Deactivate NovaOS mode (return to Persona mode)."""
    kernel.handle_input("#shutdown", state.session_id)
    state.disable_novaos()
    
    shutdown_message = (
        "NovaOS is now offline. "
        "We're back to normal conversation mode. "
        "Say #boot whenever you want to enter command mode again."
    )
    
    response_text = persona.generate_response(
        text="[SYSTEM: Acknowledge that NovaOS has shut down]",
        session_id=state.session_id,
        direct_answer=shutdown_message,
    )
    
    return {
        "text": response_text,
        "mode": state.mode_name,
        "handled_by": "mode_router",
        "event": "shutdown",
        "ok": True,
    }


def _handle_session_end_in_persona_mode(
    state: NovaState,
    kernel: "NovaKernel",
    persona: "NovaPersona",
) -> Dict[str, Any]:
    """
    Handle #session-end in persona mode.
    
    v0.11.0-fix5: Added to allow session snapshots without entering strict mode.
    
    This routes directly to the kernel's session-end handler.
    """
    # Route to kernel to handle the session-end syscommand
    kernel_result = kernel.handle_input("#session-end", state.session_id)
    
    # Extract response text
    if hasattr(kernel_result, "to_dict"):
        result_dict = kernel_result.to_dict()
    elif hasattr(kernel_result, "__dict__"):
        result_dict = kernel_result.__dict__
    else:
        result_dict = dict(kernel_result) if kernel_result else {}
    
    text = (
        result_dict.get("text") or
        result_dict.get("summary") or
        (result_dict.get("content", {}).get("summary") 
         if isinstance(result_dict.get("content"), dict) else None) or
        "Session ended."
    )
    
    return {
        "text": text,
        "mode": state.mode_name,
        "handled_by": "session_end_persona",
        "ok": result_dict.get("ok", True),
    }


# ─────────────────────────────────────────────────────────────────────────────
# STATE MANAGEMENT HELPERS
# ─────────────────────────────────────────────────────────────────────────────

_session_states: Dict[str, NovaState] = {}


def get_or_create_state(session_id: str) -> NovaState:
    """Get existing state for session or create a new one."""
    if session_id not in _session_states:
        _session_states[session_id] = NovaState(session_id=session_id)
    return _session_states[session_id]


def get_state(session_id: str) -> Optional[NovaState]:
    """Get state for session if it exists."""
    return _session_states.get(session_id)


def clear_state(session_id: str) -> None:
    """Clear state for a session."""
    _session_states.pop(session_id, None)
