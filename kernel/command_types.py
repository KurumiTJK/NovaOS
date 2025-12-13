# kernel/command_types.py
"""
SHIM: This module has moved to kernel/utils/command_types.py

This file re-exports all symbols for backward compatibility.
New code should import from kernel.utils.command_types directly.
"""

from kernel.utils.command_types import (
    CommandRequest,
    CommandResponse,
)

__all__ = [
    "CommandRequest",
    "CommandResponse",
]
