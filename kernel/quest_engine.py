# kernel/quest_engine.py
"""
Shim for backward compatibility.
Real implementation is in kernel/quests/quest_engine.py
"""

from kernel.quests.quest_engine import QuestEngine, Quest

__all__ = ["QuestEngine", "Quest"]
