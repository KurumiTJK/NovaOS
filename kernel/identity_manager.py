# kernel/identity_manager.py
"""
SHIM: This module has moved to kernel/identity/identity_manager.py

This file re-exports all symbols for backward compatibility.
New code should import from kernel.identity.identity_manager directly.
"""

from kernel.identity.identity_manager import (
    IdentityTraits,
    IdentityProfile,
    IdentityHistoryEntry,
    IdentityManager,
)

__all__ = [
    "IdentityTraits",
    "IdentityProfile",
    "IdentityHistoryEntry",
    "IdentityManager",
]
