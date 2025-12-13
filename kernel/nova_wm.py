# kernel/nova_wm.py
"""
SHIM: This module has moved to kernel/memory/nova_wm.py

This file re-exports all symbols for backward compatibility.
New code should import from kernel.memory.nova_wm directly.
"""

from kernel.memory.nova_wm import (
    # Classes
    NovaWorkingMemory,
    WMEntity,
    WMTopic,
    WMGoal,
    ReferentCandidate,
    # Enums
    EntityType,
    TopicStatus,
    GoalStatus,
    EmotionalTone,
    GenderHint,
    # Pronoun constants
    MASCULINE_PRONOUNS,
    FEMININE_PRONOUNS,
    NEUTRAL_PRONOUNS,
    OBJECT_PRONOUNS,
    PRONOUN_TO_GENDER,
    PRONOUN_ENTITY_MAP,
    # Public API functions
    get_wm,
    wm_update,
    wm_record_response,
    wm_get_context,
    wm_get_context_string,
    wm_answer_reference,
    wm_clear,
    wm_set_module,
    wm_check_meta_question,
    wm_answer_meta_question,
    wm_get_group_info,
    wm_create_snapshot,
    wm_rehydrate_from_snapshot,
    wm_get_snapshots_info,
    wm_get_all_groups,
    wm_get_group_context,
    wm_record_entity_event,
    wm_answer_event_recall,
    wm_merge_topic,
    wm_bridge_load_relevant,
)

__all__ = [
    # Classes
    "NovaWorkingMemory",
    "WMEntity",
    "WMTopic",
    "WMGoal",
    "ReferentCandidate",
    # Enums
    "EntityType",
    "TopicStatus",
    "GoalStatus",
    "EmotionalTone",
    "GenderHint",
    # Pronoun constants
    "MASCULINE_PRONOUNS",
    "FEMININE_PRONOUNS",
    "NEUTRAL_PRONOUNS",
    "OBJECT_PRONOUNS",
    "PRONOUN_TO_GENDER",
    "PRONOUN_ENTITY_MAP",
    # Public API functions
    "get_wm",
    "wm_update",
    "wm_record_response",
    "wm_get_context",
    "wm_get_context_string",
    "wm_answer_reference",
    "wm_clear",
    "wm_set_module",
    "wm_check_meta_question",
    "wm_answer_meta_question",
    "wm_get_group_info",
    "wm_create_snapshot",
    "wm_rehydrate_from_snapshot",
    "wm_get_snapshots_info",
    "wm_get_all_groups",
    "wm_get_group_context",
    "wm_record_entity_event",
    "wm_answer_event_recall",
    "wm_merge_topic",
    "wm_bridge_load_relevant",
]
