# kernel/identity_integration.py
"""
SHIM: This module has moved to kernel/identity/identity_integration.py

This file re-exports all symbols for backward compatibility.
New code should import from kernel.identity.identity_integration directly.
"""

from kernel.identity.identity_integration import (
    get_identity_manager,
    award_xp,
    award_quest_xp,
    award_presence_xp,
    award_daily_review_xp,
    award_weekly_review_xp,
    award_debug_xp,
)

__all__ = [
    "get_identity_manager",
    "award_xp",
    "award_quest_xp",
    "award_presence_xp",
    "award_daily_review_xp",
    "award_weekly_review_xp",
    "award_debug_xp",
]
