# kernel/memory_policy.py
"""
SHIM: This module has moved to kernel/memory/memory_policy.py

This file re-exports all symbols for backward compatibility.
New code should import from kernel.memory.memory_policy directly.
"""

from kernel.memory.memory_policy import (
    MemoryPolicyConfig,
    PreStoreResult,
    RecallAnnotation,
    MemoryPolicy,
)

__all__ = [
    "MemoryPolicyConfig",
    "PreStoreResult",
    "RecallAnnotation",
    "MemoryPolicy",
]
