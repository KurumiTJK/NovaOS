# kernel/memory_helpers.py
"""
SHIM: This module has moved to kernel/memory/memory_helpers.py

This file re-exports all symbols for backward compatibility.
New code should import from kernel.memory.memory_helpers directly.
"""

from kernel.memory.memory_helpers import (
    # Pattern constants
    IDENTITY_PATTERNS,
    PREFERENCE_PATTERNS,
    REMEMBER_INTENT_PATTERNS,
    PROCEDURAL_PATTERNS,
    EPISODIC_PATTERNS,
    # Public functions
    maybe_extract_profile_memory,
    handle_remember_intent,
    get_profile_memories,
    get_relevant_semantic_memories,
    format_ltm_context,
    build_ltm_context_for_persona,
    search_by_keywords,
    run_memory_decay,
    store_quest_completion_memory,
    maybe_extract_procedural_memory,
    maybe_extract_episodic_memory,
    run_auto_extraction,
    llm_extract_facts,
    semantic_search_memories,
    get_relevant_semantic_memories_v2,
)

__all__ = [
    # Pattern constants
    "IDENTITY_PATTERNS",
    "PREFERENCE_PATTERNS",
    "REMEMBER_INTENT_PATTERNS",
    "PROCEDURAL_PATTERNS",
    "EPISODIC_PATTERNS",
    # Public functions
    "maybe_extract_profile_memory",
    "handle_remember_intent",
    "get_profile_memories",
    "get_relevant_semantic_memories",
    "format_ltm_context",
    "build_ltm_context_for_persona",
    "search_by_keywords",
    "run_memory_decay",
    "store_quest_completion_memory",
    "maybe_extract_procedural_memory",
    "maybe_extract_episodic_memory",
    "run_auto_extraction",
    "llm_extract_facts",
    "semantic_search_memories",
    "get_relevant_semantic_memories_v2",
]
