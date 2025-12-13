# kernel/identity/__init__.py
"""
NovaOS Identity Subpackage

Contains:
- identity_section: v1.0.0 Character sheet and XP ledger
- identity_manager: v0.5.5 Identity Profile & Versioned Self
- identity_handlers: Identity section command handlers
- identity_integration: Integration hooks for XP events
- player_profile: v0.8.0 Legacy Player Profile

All symbols are re-exported for backward compatibility.
"""

# Core identity section - always available
from .identity_section import (
    IdentityState,
    IdentitySectionManager,
    XPEventInput,
    XPEventResult,
    Title,
    xp_for_level,
    level_from_total_xp,
    module_level_from_xp,
)

# Identity manager
from .identity_manager import (
    IdentityTraits,
    IdentityProfile,
    IdentityManager,
)

# Player profile (legacy)
from .player_profile import (
    PlayerProfile,
    PlayerProfileManager,
    DomainXP,
)

# Safe imports for handlers and integration
try:
    from .identity_handlers import (
        handle_identity_show,
        handle_identity_set,
        handle_identity_clear,
        get_identity_handlers,
    )
except ImportError:
    pass

try:
    from .identity_integration import (
        get_identity_manager,
        award_xp,
        award_quest_xp,
        award_presence_xp,
        award_daily_review_xp,
        award_weekly_review_xp,
        award_debug_xp,
    )
except ImportError:
    pass
