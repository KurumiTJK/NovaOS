# kernel/section_defs.py
"""
SHIM: This module has moved to kernel/routing/section_defs.py

This file re-exports all symbols for backward compatibility.
New code should import from kernel.routing.section_defs directly.
"""

from kernel.routing.section_defs import (
    CommandInfo,
    Section,
    SECTION_DEFS,
    get_section_keys,
    get_section,
    get_section_commands,
    get_section_title,
    get_section_description,
    find_section_for_command,
    get_all_command_names,
)

__all__ = [
    "CommandInfo",
    "Section",
    "SECTION_DEFS",
    "get_section_keys",
    "get_section",
    "get_section_commands",
    "get_section_title",
    "get_section_description",
    "find_section_for_command",
    "get_all_command_names",
]
