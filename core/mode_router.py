# core/mode_router.py
"""
NovaOS v0.9.1 — Mode Router

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
)

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


def _is_boot_command(message: str) -> bool:
    """Check if message is a boot command."""
    return bool(BOOT_PATTERNS.match(message.strip()))


def _is_shutdown_command(message: str) -> bool:
    """Check if message is a shutdown command."""
    return bool(SHUTDOWN_PATTERNS.match(message.strip()))


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
    
    Routes based on state.novaos_enabled:
    - False: Persona mode (pure chat, except #boot)
    - True: NovaOS mode (strict command shell, NO persona fallback)
    """
    message = message.strip()
    
    if not message:
        return {
            "text": "",
            "mode": state.mode_name,
            "error": "EMPTY_INPUT",
        }
    
    # ─────────────────────────────────────────────────────────────────────
    # PERSONA MODE (NovaOS OFF) - Normal conversational behavior
    # ─────────────────────────────────────────────────────────────────────
    
    if not state.novaos_enabled:
        return _handle_persona_mode(message, state, kernel, persona)
    
    # ─────────────────────────────────────────────────────────────────────
    # NOVAOS MODE (NovaOS ON) - STRICT command shell, NO persona fallback
    # ─────────────────────────────────────────────────────────────────────
    
    return _handle_novaos_mode_strict(message, state, kernel, persona)


# ─────────────────────────────────────────────────────────────────────────────
# PERSONA MODE HANDLER (unchanged behavior)
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
    This behavior is UNCHANGED.
    """
    
    # Check for #boot command
    if _is_boot_command(message):
        return _activate_novaos(state, kernel, persona)
    
    # Working Memory updates
    direct_answer = wm_answer_reference(state.session_id, message)
    wm_update(state.session_id, message)
    wm_context_string = wm_get_context_string(state.session_id)
    
    # Persona chat (normal conversational fallback)
    response_text = persona.generate_response(
        text=message,
        session_id=state.session_id,
        wm_context_string=wm_context_string,
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
# NOVAOS MODE HANDLER - STRICT (no persona fallback)
# ─────────────────────────────────────────────────────────────────────────────

def _handle_novaos_mode_strict(
    message: str,
    state: NovaState,
    kernel: "NovaKernel",
    persona: "NovaPersona",
) -> Dict[str, Any]:
    """
    Handle input when NovaOS is ON (STRICT mode).
    
    v0.9.1 STRICT MODE BEHAVIOR:
    
    ONLY TWO things are allowed:
    1. Valid syscommands (e.g., #status, #help, #quest)
    2. Natural language inputs successfully mapped to a syscommand via NL router
    
    If neither matches:
    - NO persona fallback
    - NO open conversation
    - Returns fixed error message
    
    This is a COMMAND SHELL, not a chat mode.
    """
    
    # Check for #shutdown
    if _is_shutdown_command(message):
        return _deactivate_novaos(state, kernel, persona)
    
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
