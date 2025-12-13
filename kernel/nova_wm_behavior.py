# kernel/nova_wm_behavior.py
"""
SHIM: This module has moved to kernel/memory/nova_wm_behavior.py

This file re-exports all symbols for backward compatibility.
New code should import from kernel.memory.nova_wm_behavior directly.
"""

from kernel.memory.nova_wm_behavior import (
    # Enums
    ConversationGoalType,
    GoalStatus,
    UserStateSignal,
    # Data classes
    OpenQuestion,
    ConversationGoal,
    UserState,
    TopicTransition,
    ThreadSummary,
    # Pattern constants
    IMPLICIT_AFFIRMATIVE,
    IMPLICIT_NEGATIVE,
    IMPLICIT_UNCERTAIN,
    IMPLICIT_CONTINUE,
    IMPLICIT_DEFER,
    TOPIC_SWITCH_PATTERNS,
    TOPIC_RETURN_PATTERNS,
    BEHAVIOR_META_PATTERNS,
    GOAL_PATTERNS,
    USER_STATE_PATTERNS,
    NOVA_QUESTION_PATTERNS,
    # Classes
    WMBehaviorEngine,
    BehaviorEngineManager,
    # Public API functions
    get_behavior_engine,
    behavior_update,
    behavior_after_response,
    behavior_get_context,
    behavior_get_context_string,
    behavior_answer_reference,
    behavior_resolve_goal,
    behavior_clear,
    behavior_delete,
    behavior_get_mode,
    behavior_set_mode,
    behavior_summarize_thread,
    behavior_summarize_entity,
    behavior_check_meta_question,
    behavior_handle_meta_question,
    behavior_check_topic_return,
)

# Aliases for backward compatibility
BehaviorEngine = WMBehaviorEngine
get_behavior = get_behavior_engine

__all__ = [
    # Enums
    "ConversationGoalType",
    "GoalStatus",
    "UserStateSignal",
    # Data classes
    "OpenQuestion",
    "ConversationGoal",
    "UserState",
    "TopicTransition",
    "ThreadSummary",
    # Pattern constants
    "IMPLICIT_AFFIRMATIVE",
    "IMPLICIT_NEGATIVE",
    "IMPLICIT_UNCERTAIN",
    "IMPLICIT_CONTINUE",
    "IMPLICIT_DEFER",
    "TOPIC_SWITCH_PATTERNS",
    "TOPIC_RETURN_PATTERNS",
    "BEHAVIOR_META_PATTERNS",
    "GOAL_PATTERNS",
    "USER_STATE_PATTERNS",
    "NOVA_QUESTION_PATTERNS",
    # Classes
    "WMBehaviorEngine",
    "BehaviorEngineManager",
    "BehaviorEngine",  # Alias
    # Public API functions
    "get_behavior_engine",
    "get_behavior",  # Alias
    "behavior_update",
    "behavior_after_response",
    "behavior_get_context",
    "behavior_get_context_string",
    "behavior_answer_reference",
    "behavior_resolve_goal",
    "behavior_clear",
    "behavior_delete",
    "behavior_get_mode",
    "behavior_set_mode",
    "behavior_summarize_thread",
    "behavior_summarize_entity",
    "behavior_check_meta_question",
    "behavior_handle_meta_question",
    "behavior_check_topic_return",
]
