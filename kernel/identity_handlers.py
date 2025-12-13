# kernel/identity_handlers.py
"""
SHIM: This module has moved to kernel/identity/identity_handlers.py

This file re-exports all symbols for backward compatibility.
New code should import from kernel.identity.identity_handlers directly.
"""

from kernel.identity.identity_handlers import (
    handle_identity_show,
    handle_identity_set,
    handle_identity_clear,
    get_identity_handlers,
)

__all__ = [
    "handle_identity_show",
    "handle_identity_set",
    "handle_identity_clear",
    "get_identity_handlers",
]
