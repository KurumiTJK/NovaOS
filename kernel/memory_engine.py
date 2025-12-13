# kernel/memory_engine.py
"""
SHIM: This module has moved to kernel/memory/memory_engine.py

This file re-exports all symbols for backward compatibility.
New code should import from kernel.memory.memory_engine directly.
"""

from kernel.memory.memory_engine import (
    MemoryEngine,
    MemoryItem,
    MemoryType,
    MemoryStatus,
    DEFAULT_SALIENCE,
    WorkingMemory,
    MemoryIndex,
    LongTermMemory,
)

__all__ = [
    "MemoryEngine",
    "MemoryItem",
    "MemoryType",
    "MemoryStatus",
    "DEFAULT_SALIENCE",
    "WorkingMemory",
    "MemoryIndex",
    "LongTermMemory",
]
