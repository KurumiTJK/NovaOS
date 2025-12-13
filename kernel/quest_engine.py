# kernel/quest_engine.py
"""
SHIM: This module has moved to kernel/quests/quest_engine.py

This file re-exports all symbols for backward compatibility.
New code should import from kernel.quests.quest_engine directly.
"""

from kernel.quests.quest_engine import (
    # Type definitions
    StepType,
    ValidationMode,
    QuestStatus,
    StepStatus,
    # Classes
    ValidationConfig,
    Step,
    Quest,
    RunState,
    QuestProgress,
    QuestEngine,
)

__all__ = [
    "StepType",
    "ValidationMode",
    "QuestStatus",
    "StepStatus",
    "ValidationConfig",
    "Step",
    "Quest",
    "RunState",
    "QuestProgress",
    "QuestEngine",
]
