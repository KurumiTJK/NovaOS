# kernel/section_handlers.py
"""
SHIM: This module has moved to kernel/routing/section_handlers.py

This file re-exports all symbols for backward compatibility.
New code should import from kernel.routing.section_handlers directly.
"""

from kernel.routing.section_handlers import (
    SectionMenuState,
    handle_help_sectioned,
    handle_section_menu,
    handle_section_menu_selection,
    clear_section_menu,
    get_active_section_menu,
    route_section_command,
    parse_section_input,
    create_section_menu_handler,
    SECTION_MENU_HANDLERS,
)

__all__ = [
    "SectionMenuState",
    "handle_help_sectioned",
    "handle_section_menu",
    "handle_section_menu_selection",
    "clear_section_menu",
    "get_active_section_menu",
    "route_section_command",
    "parse_section_input",
    "create_section_menu_handler",
    "SECTION_MENU_HANDLERS",
]
