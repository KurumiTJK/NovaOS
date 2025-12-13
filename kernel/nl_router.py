# kernel/nl_router.py
"""
SHIM: This module has moved to kernel/routing/nl_router.py

This file re-exports all symbols for backward compatibility.
New code should import from kernel.routing.nl_router directly.
"""

from kernel.routing.nl_router import (
    IntentMatch,
    IntentPatterns,
    NaturalLanguageRouter,
    EXTRACTORS,
    QUEST_SUGGESTION_PATTERNS,
    route_natural_language,
    check_quest_suggestion,
    debug_nl_intent,
)

__all__ = [
    "IntentMatch",
    "IntentPatterns",
    "NaturalLanguageRouter",
    "EXTRACTORS",
    "QUEST_SUGGESTION_PATTERNS",
    "route_natural_language",
    "check_quest_suggestion",
    "debug_nl_intent",
]
