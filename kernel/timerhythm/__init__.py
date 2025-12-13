# kernel/timerhythm/__init__.py
"""
NovaOS Timerhythm Subpackage

Contains:
- time_rhythm_handlers: Three-phase daily review system (morning/evening/night)
  with HP computation, readiness tiers, weekly habits, and schedule management

All symbols are re-exported for backward compatibility.
"""

from .time_rhythm_handlers import (
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
    # Type
    Phase,
)
