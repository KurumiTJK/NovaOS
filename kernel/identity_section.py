# kernel/identity_section.py
"""
SHIM: This module has moved to kernel/identity/identity_section.py

This file re-exports all symbols for backward compatibility.
New code should import from kernel.identity.identity_section directly.
"""

from kernel.identity.identity_section import (
    # XP calculation functions
    xp_for_level,
    level_from_total_xp,
    module_level_from_xp,
    # Data classes
    Archetype,
    Goal,
    ModuleXP,
    Title,
    XPEvent,
    IdentityState,
    XPEventInput,
    XPEventResult,
    # Manager
    IdentitySectionManager,
)

# Alias for backwards compatibility
IdentitySectionState = IdentityState

__all__ = [
    "xp_for_level",
    "level_from_total_xp",
    "module_level_from_xp",
    "Archetype",
    "Goal",
    "ModuleXP",
    "Title",
    "XPEvent",
    "IdentityState",
    "IdentitySectionState",
    "XPEventInput",
    "XPEventResult",
    "IdentitySectionManager",
]
