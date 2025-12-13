# kernel/player_profile.py
"""
SHIM: This module has moved to kernel/identity/player_profile.py

This file re-exports all symbols for backward compatibility.
New code should import from kernel.identity.player_profile directly.
"""

from kernel.identity.player_profile import (
    # Constants
    LEVEL_DIVISOR,
    TIER_THRESHOLDS,
    # Classes
    DomainXP,
    PlayerProfile,
    PlayerProfileManager,
)

__all__ = [
    "LEVEL_DIVISOR",
    "TIER_THRESHOLDS",
    "DomainXP",
    "PlayerProfile",
    "PlayerProfileManager",
]
