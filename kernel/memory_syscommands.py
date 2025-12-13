# kernel/memory_syscommands.py
"""
SHIM: This module has moved to kernel/memory/memory_syscommands.py

This file re-exports all symbols for backward compatibility.
New code should import from kernel.memory.memory_syscommands directly.
"""

from kernel.memory.memory_syscommands import (
    # Handlers
    handle_profile,
    handle_memories,
    handle_search_mem,
    handle_memory_maintain,
    handle_session_end,
    # Registry
    get_memory_syscommand_handlers,
    MEMORY_SYSCOMMAND_HANDLERS,
)

__all__ = [
    "handle_profile",
    "handle_memories",
    "handle_search_mem",
    "handle_memory_maintain",
    "handle_session_end",
    "get_memory_syscommand_handlers",
    "MEMORY_SYSCOMMAND_HANDLERS",
]
