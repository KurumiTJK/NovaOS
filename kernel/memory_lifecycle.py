# kernel/memory_lifecycle.py
"""
SHIM: This module has moved to kernel/memory/memory_lifecycle.py

This file re-exports all symbols for backward compatibility.
New code should import from kernel.memory.memory_lifecycle directly.
"""

from kernel.memory.memory_lifecycle import (
    DecayConfig,
    DriftReport,
    ReconfirmationItem,
    MemoryLifecycle,
)

# Aliases for backward compatibility with __init__.py exports
MemoryDecayEngine = MemoryLifecycle
compute_decay = lambda *args, **kwargs: MemoryLifecycle(*args, **kwargs).compute_decay_scores()
detect_drift = lambda *args, **kwargs: MemoryLifecycle(*args, **kwargs).detect_drift()

__all__ = [
    "DecayConfig",
    "DriftReport",
    "ReconfirmationItem",
    "MemoryLifecycle",
    "MemoryDecayEngine",
    "compute_decay",
    "detect_drift",
]
