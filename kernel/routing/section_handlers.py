# kernel/routing/section_handlers.py
"""
v0.6 — Section Handlers

Implements:
- New sectioned #help handler
- Section menu commands (#core, #memory, etc.)
- Section router logic

These are NEW handlers that wrap existing syscommand functionality.
DO NOT modify existing syscommand handlers.
"""

from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass

from .section_defs import (
    SECTION_DEFS,
    SECTION_ROUTES,
    get_section,
    get_section_keys,
    resolve_section_route,
    SectionDef,
    CommandDef,
)
from ..command_types import CommandRequest
from ..formatting import OutputFormatter as F


# Type alias for kernel response
KernelResponse = Dict[str, Any]


def _base_response(cmd_name: str, summary: str, extra: Dict[str, Any] = None) -> KernelResponse:
    """Build a standard response dict."""
    return {
        "ok": True,
        "command": cmd_name,
        "summary": summary,
        "extra": extra or {},
    }


# -----------------------------------------------------------------------------
# PHASE 2 — New Sectioned #help Handler
# -----------------------------------------------------------------------------

def handle_help_sectioned(cmd_name: str, args: Any, session_id: str, context: Any, kernel: Any, meta: Any) -> KernelResponse:
    """
    Display commands organized by section.
    
    Usage:
        #help              (show all sections)
        #help section=memory  (show specific section)
    """
    # Check if specific section requested
    target_section = None
    if isinstance(args, dict):
        target_section = args.get("section") or args.get("_", [None])[0] if "_" in args else None
    
    lines = []
    
    if target_section:
        # Show specific section
        section = get_section(target_section)
        if not section:
            return _base_response(
                cmd_name,
                f"Unknown section '{target_section}'. Use #help to see all sections.",
                {"ok": False}
            )
        
        lines.append(f"[{section.title}]")
        lines.append(f"{section.description}")
        lines.append("")
        
        for i, cmd in enumerate(section.commands, 1):
            lines.append(f"{i}) {cmd.name}")
            lines.append(f"   Description: {cmd.description}")
            lines.append(f"   Example: {cmd.example}")
            lines.append("")
        
        lines.append(f"Tip: Type #{target_section} to enter this section's menu.")
    else:
        # Show all sections
        lines.append("NovaOS Commands")
        lines.append("=" * 40)
        lines.append("")
        
        for section in SECTION_DEFS:
            lines.append(f"[{section.title}]")
            lines.append(f"{section.description}")
            lines.append("")
            
            for i, cmd in enumerate(section.commands, 1):
                lines.append(f"{i}) {cmd.name}")
                lines.append(f"   Description: {cmd.description}")
                lines.append(f"   Example: {cmd.example}")
                lines.append("")
            
            lines.append("-" * 40)
            lines.append("")
        
        # Section menu tip
        lines.append("Section Menus:")
        section_list = ", ".join(f"#{s.key}" for s in SECTION_DEFS)
        lines.append(f"  {section_list}")
        lines.append("")
        lines.append("Type a section command (e.g., #memory) to see its menu.")
    
    summary = "\n".join(lines)
    return _base_response(cmd_name, summary, {"sections": [s.key for s in SECTION_DEFS]})


# -----------------------------------------------------------------------------
# PHASE 3 — Section Menu Handlers
# -----------------------------------------------------------------------------

class SectionMenuState:
    """
    Tracks which section menu the user is currently in.
    
    This allows follow-up inputs to be interpreted as command selections.
    """
    def __init__(self):
        self._active_section: Dict[str, Optional[str]] = {}  # session_id -> section_key
    
    def set_active(self, session_id: str, section_key: str) -> None:
        self._active_section[session_id] = section_key
    
    def get_active(self, session_id: str) -> Optional[str]:
        return self._active_section.get(session_id)
    
    def clear(self, session_id: str) -> None:
        self._active_section.pop(session_id, None)


# Global section menu state
_section_menu_state = SectionMenuState()


def handle_section_menu(
    section_key: str,
    cmd_name: str,
    args: Any,
    session_id: str,
    context: Any,
    kernel: Any,
    meta: Any,
) -> KernelResponse:
    """
    Display a section's command menu.
    
    When user types #<section>, show the menu and set active section.
    """
    section = get_section(section_key)
    if not section:
        return _base_response(
            cmd_name,
            f"Unknown section '{section_key}'.",
            {"ok": False}
        )
    
    # Set active section for follow-up
    _section_menu_state.set_active(session_id, section_key)
    
    lines = [
        f"You're in the {section.title} section. Which command would you like to run?",
        "",
    ]
    
    for i, cmd in enumerate(section.commands, 1):
        lines.append(f"{i}) {cmd.name}")
        lines.append(f"   Description: {cmd.description}")
        lines.append(f"   Example: {cmd.example}")
        lines.append("")
    
    lines.append('Please type the command name exactly (e.g., "{}"). Numbers will not work.'.format(
        section.commands[0].name if section.commands else "command"
    ))
    
    summary = "\n".join(lines)
    return _base_response(cmd_name, summary, {
        "section": section_key,
        "commands": [cmd.name for cmd in section.commands],
        "menu_active": True,
    })


def handle_section_menu_selection(
    selection: str,
    session_id: str,
    kernel: Any,
) -> Optional[KernelResponse]:
    """
    Handle a follow-up selection from a section menu.
    
    Returns:
        KernelResponse if selection was processed
        None if no active menu or invalid selection
    """
    active_section = _section_menu_state.get_active(session_id)
    if not active_section:
        return None
    
    section = get_section(active_section)
    if not section:
        _section_menu_state.clear(session_id)
        return None
    
    # Clean selection
    selection = selection.strip().lower()
    
    # Check if it's a number (invalid)
    if selection.isdigit():
        return _base_response(
            "section_menu",
            "I didn't recognize that selection.\n"
            'Please type the exact command name shown in the menu (e.g., "{}").'.format(
                section.commands[0].name if section.commands else "command"
            ),
            {"ok": False, "section": active_section}
        )
    
    # Check if it's a valid command name in this section
    valid_commands = [cmd.name for cmd in section.commands]
    if selection not in valid_commands:
        return _base_response(
            "section_menu",
            "I didn't recognize that selection.\n"
            'Please type the exact command name shown in the menu (e.g., "{}").'.format(
                section.commands[0].name if section.commands else "command"
            ),
            {"ok": False, "section": active_section}
        )
    
    # Clear active menu
    _section_menu_state.clear(session_id)
    
    # Build and execute the command
    # This will be handled by the kernel after we return the command name
    return {
        "ok": True,
        "command": "section_menu_redirect",
        "redirect_to": selection,
        "summary": f"Executing: #{selection}",
        "extra": {"section": active_section, "command": selection},
    }


def clear_section_menu(session_id: str) -> None:
    """Clear the active section menu for a session."""
    _section_menu_state.clear(session_id)


def get_active_section_menu(session_id: str) -> Optional[str]:
    """Get the active section menu for a session."""
    return _section_menu_state.get_active(session_id)


# -----------------------------------------------------------------------------
# PHASE 4 — Section Router
# -----------------------------------------------------------------------------

def route_section_command(
    section: str,
    subcommand: str,
    args_str: str,
) -> Optional[Dict[str, Any]]:
    """
    Route a section command to the underlying syscommand.
    
    Example: route_section_command("memory", "store", 'type=semantic "Hello"')
    Returns: {"command": "store", "args_str": 'type=semantic "Hello"'}
    
    Returns None if no mapping exists.
    """
    target_command = resolve_section_route(section, subcommand)
    if not target_command:
        return None
    
    return {
        "command": target_command,
        "args_str": args_str,
    }


def parse_section_input(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse input that might be a section command.
    
    Examples:
        "#memory store type=semantic" → {"section": "memory", "subcommand": "store", "args": "type=semantic"}
        "#workflow start" → {"section": "workflow", "subcommand": "start", "args": ""}
        "#help" → None (not a section command)
    
    Returns None if not a valid section command pattern.
    """
    if not text.startswith("#"):
        return None
    
    text = text[1:].strip()
    parts = text.split(None, 2)  # Split into at most 3 parts
    
    if len(parts) < 2:
        return None  # Just "#section" with no subcommand
    
    section = parts[0].lower()
    subcommand = parts[1].lower()
    args_str = parts[2] if len(parts) > 2 else ""
    
    # Check if this is a valid section
    if section not in get_section_keys():
        return None
    
    return {
        "section": section,
        "subcommand": subcommand,
        "args_str": args_str,
    }


# -----------------------------------------------------------------------------
# Section Handler Factory
# -----------------------------------------------------------------------------

def create_section_menu_handler(section_key: str) -> Callable:
    """
    Create a handler function for a specific section menu.
    
    This is used to register #core, #memory, etc. as commands.
    """
    def handler(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
        return handle_section_menu(section_key, cmd_name, args, session_id, context, kernel, meta)
    
    return handler


# Pre-create handlers for all sections
SECTION_MENU_HANDLERS: Dict[str, Callable] = {
    section.key: create_section_menu_handler(section.key)
    for section in SECTION_DEFS
}
