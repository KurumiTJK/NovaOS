# kernel/time_rhythm_handlers.py
"""
SHIM: This module has moved to kernel/timerhythm/time_rhythm_handlers.py

This file re-exports all symbols for backward compatibility.
New code should import from kernel.timerhythm.time_rhythm_handlers directly.
"""

from kernel.timerhythm.time_rhythm_handlers import (
    # Type
    Phase,
    # Derivation functions
    derive_mood,
    derive_stress,
    compute_hp,
    compute_readiness,
    # Wizard session
    DailyReviewWizardSession,
    get_daily_review_wizard_session,
    has_active_daily_review_wizard,
    create_daily_review_wizard_session,
    clear_daily_review_wizard_session,
    get_wizard_steps,
    process_daily_review_wizard_input,
    # State classes
    DailyState,
    WeeklyHabits,
    WeeklySchedule,
    TimerhythmState,
    TimerhythmLogEntry,
    # Manager
    TimerhythmManager,
    get_timerhythm_manager,
    # Command handlers
    handle_daily_review,
    handle_weekly_review,
    handle_time_clear,
    get_time_rhythm_handlers,
)

__all__ = [
    "Phase",
    "derive_mood",
    "derive_stress",
    "compute_hp",
    "compute_readiness",
    "DailyReviewWizardSession",
    "get_daily_review_wizard_session",
    "has_active_daily_review_wizard",
    "create_daily_review_wizard_session",
    "clear_daily_review_wizard_session",
    "get_wizard_steps",
    "process_daily_review_wizard_input",
    "DailyState",
    "WeeklyHabits",
    "WeeklySchedule",
    "TimerhythmState",
    "TimerhythmLogEntry",
    "TimerhythmManager",
    "get_timerhythm_manager",
    "handle_daily_review",
    "handle_weekly_review",
    "handle_time_clear",
    "get_time_rhythm_handlers",
]
