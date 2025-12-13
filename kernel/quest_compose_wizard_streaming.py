# kernel/quest_compose_wizard_streaming.py
"""
SHIM: This module has moved to kernel/quests/quest_compose_wizard_streaming.py

This file re-exports all symbols for backward compatibility.
New code should import from kernel.quests.quest_compose_wizard_streaming directly.
"""

from kernel.quests.quest_compose_wizard_streaming import (
    _generate_steps_with_llm_streaming,
)

__all__ = [
    "_generate_steps_with_llm_streaming",
]
