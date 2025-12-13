# kernel/syscommand_router.py
"""
SHIM: This module has moved to kernel/routing/syscommand_router.py

This file re-exports all symbols for backward compatibility.
New code should import from kernel.routing.syscommand_router directly.
"""

from kernel.routing.syscommand_router import (
    SyscommandRouter,
    SKIP_LLM_POSTPROCESS,
)

__all__ = [
    "SyscommandRouter",
    "SKIP_LLM_POSTPROCESS",
]
