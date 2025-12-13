# kernel/memory_manager.py
"""
SHIM: This module has moved to kernel/memory/memory_manager.py

This file re-exports all symbols for backward compatibility.
New code should import from kernel.memory.memory_manager directly.
"""

from kernel.memory.memory_manager import (
    MemoryManager,
    MemoryItem,
)

__all__ = [
    "MemoryManager",
    "MemoryItem",
]
