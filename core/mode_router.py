# core/mode_router.py
"""
NovaOS v0.9.0 — Mode Router

The single entrypoint for all user messages.
Routes based on NovaState.novaos_enabled:

- novaos_enabled=False (Persona Mode):
    → Pure conversational Nova
    → Only #boot is recognized to switch modes
    → Everything else goes directly to persona.chat()

- novaos_enabled=True (NovaOS Mode):
    → Full kernel routing (syscommands, modules, NL router)
    → Kernel returns KernelResponse
    → Persona renders the response naturally
    → #shutdown returns to Persona mode

This file is the ONLY place that decides which mode handles input.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Dict, Any
import re

from .nova_state import NovaState

if TYPE_CHECKING:
    from kernel.nova_kernel import NovaKernel
    from persona.nova_persona import NovaPersona


# ─────────────────────────────────────────────────────────────────────────────
# BOOT / SHUTDOWN DETECTION
# ─────────────────────────────────────────────────────────────────────────────

# Commands that activate NovaOS (only recognized in Persona mode)
BOOT_PATTERNS = re.compile(
    r"^#boot\b",
    re.IGNORECASE
)

# Commands that deactivate NovaOS (only recognized in NovaOS mode)
SHUTDOWN_PATTERNS = re.compile(
    r"^#shutdown\b",
    re.IGNORECASE
)


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
    - True: NovaOS mode (kernel routing with persona rendering)
    
    Args:
        message: Raw user input
        state: NovaState object (tracks mode and session)
        kernel: NovaKernel instance (for OS operations)
        persona: NovaPersona instance (for chat and rendering)
    
    Returns:
        Dict with at minimum:
        - "text": The response text
        - "mode": Current mode name
        - Additional fields from kernel/persona as needed
    """
    message = message.strip()
    
    if not message:
        return {
            "text": "",
            "mode": state.mode_name,
            "error": "EMPTY_INPUT",
        }
    
    # ─────────────────────────────────────────────────────────────────────
    # PERSONA MODE (NovaOS OFF)
    # ─────────────────────────────────────────────────────────────────────
    
    if not state.novaos_enabled:
        return _handle_persona_mode(message, state, kernel, persona)
    
    # ─────────────────────────────────────────────────────────────────────
    # NOVAOS MODE (NovaOS ON)
    # ─────────────────────────────────────────────────────────────────────
    
    return _handle_novaos_mode(message, state, kernel, persona)


# ─────────────────────────────────────────────────────────────────────────────
# PERSONA MODE HANDLER
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
    """
    
    # Check for #boot command
    if _is_boot_command(message):
        return _activate_novaos(state, kernel, persona)
    
    # Pure persona chat — no kernel involvement
    response_text = persona.generate_response(
        text=message,
        session_id=state.session_id,
    )
    
    return {
        "text": response_text,
        "mode": state.mode_name,
        "handled_by": "persona",
    }


# ─────────────────────────────────────────────────────────────────────────────
# NOVAOS MODE HANDLER
# ─────────────────────────────────────────────────────────────────────────────

def _handle_novaos_mode(
    message: str,
    state: NovaState,
    kernel: "NovaKernel",
    persona: "NovaPersona",
) -> Dict[str, Any]:
    """
    Handle input when NovaOS is ON.
    
    Routes through kernel first. If kernel doesn't handle it,
    falls back to persona chat.
    """
    
    # Check for #shutdown
    if _is_shutdown_command(message):
        return _deactivate_novaos(state, persona)
    
    # Route through kernel
    # Note: We use the existing handle_input for now
    kernel_result = kernel.handle_input(message, state.session_id)
    
    # Check if kernel handled it
    # Current kernel returns dict with "type" field
    # "fallback" or "persona" means kernel didn't handle it
    kernel_type = kernel_result.get("type", "")
    
    if kernel_type in ("fallback", "persona", "error_fallback"):
        # Kernel didn't handle — already fell back to persona
        # Just return the result as-is
        return {
            **kernel_result,
            "mode": state.mode_name,
            "handled_by": "persona",
        }
    
    # Kernel handled it
    return {
        **kernel_result,
        "mode": state.mode_name,
        "handled_by": "kernel",
    }


# ─────────────────────────────────────────────────────────────────────────────
# MODE TRANSITIONS
# ─────────────────────────────────────────────────────────────────────────────

def _activate_novaos(
    state: NovaState,
    kernel: "NovaKernel",
    persona: "NovaPersona",
) -> Dict[str, Any]:
    """
    Activate NovaOS mode.
    
    Called when #boot is detected in Persona mode.
    """
    # Enable NovaOS
    state.enable_novaos()
    
    # Run kernel boot sequence (marks session as booted, loads modules, etc.)
    boot_result = kernel.handle_input("#boot", state.session_id)
    
    # Generate persona-phrased acknowledgment
    boot_message = (
        "NovaOS is now running. "
        "Your commands and modules are ready. "
        "Type #help to see what's available, or just talk to me normally."
    )
    
    # Let persona phrase it naturally
    response_text = persona.generate_response(
        text="[SYSTEM: Acknowledge that NovaOS has booted successfully]",
        session_id=state.session_id,
        direct_answer=boot_message,
    )
    
    return {
        "text": response_text,
        "mode": state.mode_name,
        "handled_by": "mode_router",
        "event": "boot",
        "boot_result": boot_result,
    }


def _deactivate_novaos(
    state: NovaState,
    persona: "NovaPersona",
) -> Dict[str, Any]:
    """
    Deactivate NovaOS mode.
    
    Called when #shutdown is detected in NovaOS mode.
    """
    # Disable NovaOS
    state.disable_novaos()
    
    # Generate persona-phrased acknowledgment
    shutdown_message = (
        "NovaOS is now offline. "
        "We're back to just us talking. "
        "Say #boot whenever you want to bring up the OS again."
    )
    
    # Let persona phrase it naturally
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
    }


# ─────────────────────────────────────────────────────────────────────────────
# STATE MANAGEMENT HELPERS
# ─────────────────────────────────────────────────────────────────────────────

# Session state storage (in-memory for now)
# In production, you might want to persist this
_session_states: Dict[str, NovaState] = {}


def get_or_create_state(session_id: str) -> NovaState:
    """
    Get existing state for session or create a new one.
    
    This is a convenience function for the API layer.
    """
    if session_id not in _session_states:
        _session_states[session_id] = NovaState(session_id=session_id)
    return _session_states[session_id]


def get_state(session_id: str) -> Optional[NovaState]:
    """Get state for session if it exists."""
    return _session_states.get(session_id)


def clear_state(session_id: str) -> None:
    """Clear state for a session."""
    _session_states.pop(session_id, None)
