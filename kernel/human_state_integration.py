# kernel/human_state_integration.py
"""
NovaOS Human State Integration — v2.0.0

Provides helper APIs for other sections to read Human State:
- Workflow: load_modifier, readiness_tier for difficulty scaling
- Timerhythm: readiness context, 7-day averages for reviews
- Reminders: tone hints based on readiness tier

These functions are import-safe and won't cause circular imports.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .human_state import (
        HumanStateManagerV2,
        HumanStateSnapshot,
        ReadinessTier,
        RecommendedMode,
        ToneHint,
    )


# =============================================================================
# LAZY IMPORT HELPERS
# =============================================================================

def _get_manager(kernel: Optional[Any] = None, data_dir: Optional[Path] = None) -> "HumanStateManagerV2":
    """
    Get HumanStateManager instance, checking kernel first.
    
    Import is done lazily to avoid circular imports.
    """
    from .human_state import get_human_state_manager, HumanStateManagerV2
    
    # Try to get from kernel
    if kernel is not None and hasattr(kernel, "human_state_manager"):
        return kernel.human_state_manager
    
    # Determine data_dir
    if data_dir is None:
        if kernel is not None and hasattr(kernel, "config") and hasattr(kernel.config, "data_dir"):
            data_dir = kernel.config.data_dir
        else:
            data_dir = Path("data")
    
    return get_human_state_manager(data_dir)


# =============================================================================
# GENERAL GETTERS
# =============================================================================

def get_today_human_state(kernel: Optional[Any] = None) -> "HumanStateSnapshot":
    """
    Get today's human state snapshot.
    
    Safe to call from any section.
    
    Returns:
        HumanStateSnapshot with all current metrics and derived values
    """
    manager = _get_manager(kernel)
    return manager.get_today_human_state()


def get_readiness_tier(kernel: Optional[Any] = None) -> "ReadinessTier":
    """
    Get current readiness tier (Green/Yellow/Red).
    
    Returns:
        "Green", "Yellow", or "Red"
    """
    manager = _get_manager(kernel)
    return manager.get_readiness_tier()


def get_load_modifier(kernel: Optional[Any] = None) -> float:
    """
    Get current load modifier.
    
    Returns:
        1.15 (Green), 1.00 (Yellow), or 0.75 (Red)
    """
    manager = _get_manager(kernel)
    return manager.get_load_modifier()


def get_recommended_mode(kernel: Optional[Any] = None) -> "RecommendedMode":
    """
    Get current recommended mode.
    
    Returns:
        "Push" (Green), "Maintain" (Yellow), or "Recover" (Red)
    """
    manager = _get_manager(kernel)
    return manager.get_recommended_mode()


def get_hp(kernel: Optional[Any] = None) -> int:
    """
    Get current HP (0-100).
    """
    manager = _get_manager(kernel)
    return manager.get_hp()


# =============================================================================
# WORKFLOW INTEGRATION
# =============================================================================

def get_workflow_context(kernel: Optional[Any] = None) -> Dict[str, Any]:
    """
    Get human state context for Workflow section.
    
    Use this when starting a quest or generating today's plan.
    
    Returns:
        Dict with:
        - readiness_tier: "Green" / "Yellow" / "Red"
        - load_modifier: 0.75 / 1.00 / 1.15
        - recommended_mode: "Push" / "Maintain" / "Recover"
        - hp: 0-100
        - suggestion: text suggestion for difficulty
    """
    manager = _get_manager(kernel)
    snapshot = manager.get_today_human_state()
    
    # Generate suggestion based on tier
    suggestions = {
        "Green": "Full capacity — take on challenging content",
        "Yellow": "Moderate capacity — maintain steady progress",
        "Red": "Limited capacity — focus on review or lighter tasks",
    }
    
    return {
        "readiness_tier": snapshot.readiness_tier,
        "load_modifier": snapshot.load_modifier,
        "recommended_mode": snapshot.recommended_mode,
        "hp": snapshot.hp,
        "suggestion": suggestions.get(snapshot.readiness_tier, ""),
        "stamina": snapshot.stamina,
        "stress": snapshot.stress,
    }


def format_readiness_for_workflow(kernel: Optional[Any] = None) -> str:
    """
    Get a formatted one-liner for workflow display.
    
    Example: "Today's readiness: 🟢 Green (Load: 1.15x)"
    """
    ctx = get_workflow_context(kernel)
    
    emoji = {
        "Green": "🟢",
        "Yellow": "🟡", 
        "Red": "🔴",
    }.get(ctx["readiness_tier"], "⚪")
    
    return f"Today's readiness: {emoji} {ctx['readiness_tier']} (Load: {ctx['load_modifier']:.2f}x)"


# =============================================================================
# TIMERHYTHM INTEGRATION
# =============================================================================

def get_timerhythm_context(kernel: Optional[Any] = None) -> Dict[str, Any]:
    """
    Get human state context for Timerhythm reviews.
    
    Use this in daily-review and weekly-review.
    
    Returns:
        Dict with:
        - today: current snapshot summary
        - averages_7d: 7-day rolling averages
        - trend: "improving" / "stable" / "declining" based on HP trend
    """
    manager = _get_manager(kernel)
    snapshot = manager.get_today_human_state()
    averages = manager.get_7_day_averages()
    
    # Calculate trend based on HP vs 7-day average
    trend = "stable"
    if snapshot.hp > averages["avg_hp"] + 10:
        trend = "improving"
    elif snapshot.hp < averages["avg_hp"] - 10:
        trend = "declining"
    
    return {
        "today": {
            "hp": snapshot.hp,
            "readiness_tier": snapshot.readiness_tier,
            "recommended_mode": snapshot.recommended_mode,
            "stamina": snapshot.stamina,
            "stress": snapshot.stress,
            "mood": snapshot.mood,
            "focus": snapshot.focus,
            "sleep_quality": snapshot.sleep_quality,
        },
        "averages_7d": {
            "hp": round(averages["avg_hp"], 1),
            "stamina": round(averages["avg_stamina"], 1),
            "stress": round(averages["avg_stress"], 1),
            "sleep_quality": round(averages["avg_sleep_quality"], 1),
        },
        "trend": trend,
    }


def get_7_day_averages(kernel: Optional[Any] = None) -> Dict[str, float]:
    """
    Get 7-day rolling averages for key metrics.
    
    Returns:
        Dict with avg_stamina, avg_stress, avg_sleep_quality, avg_hp
    """
    manager = _get_manager(kernel)
    return manager.get_7_day_averages()


def format_state_for_daily_review(kernel: Optional[Any] = None) -> str:
    """
    Get formatted human state section for daily review output.
    """
    ctx = get_timerhythm_context(kernel)
    today = ctx["today"]
    avgs = ctx["averages_7d"]
    
    emoji = {
        "Green": "🟢",
        "Yellow": "🟡",
        "Red": "🔴",
    }.get(today["readiness_tier"], "⚪")
    
    trend_emoji = {
        "improving": "📈",
        "stable": "➡️",
        "declining": "📉",
    }.get(ctx["trend"], "")
    
    lines = [
        "─── HUMAN STATE ─────────────────────────────",
        "",
        f"  Today: HP {today['hp']}/100  {emoji} {today['readiness_tier']}",
        f"  7-Day Avg HP: {avgs['hp']:.0f}  {trend_emoji} {ctx['trend']}",
        "",
        f"  Stamina: {today['stamina']} (avg: {avgs['stamina']:.0f})",
        f"  Stress:  {today['stress']} (avg: {avgs['stress']:.0f})",
        f"  Sleep:   {today['sleep_quality']} (avg: {avgs['sleep_quality']:.0f})",
    ]
    
    return "\n".join(lines)


def format_state_for_weekly_review(kernel: Optional[Any] = None) -> str:
    """
    Get formatted human state section for weekly review output.
    """
    manager = _get_manager(kernel)
    history = manager.get_history(limit=7)
    
    if not history:
        return "─── HUMAN STATE (WEEK) ─────────────────────\n\n  No data logged this week.\n"
    
    # Calculate weekly stats
    hp_values = [e.hp for e in history]
    stress_values = [e.stress for e in history]
    
    green_days = sum(1 for e in history if e.readiness_tier == "Green")
    yellow_days = sum(1 for e in history if e.readiness_tier == "Yellow")
    red_days = sum(1 for e in history if e.readiness_tier == "Red")
    
    avg_hp = sum(hp_values) / len(hp_values)
    avg_stress = sum(stress_values) / len(stress_values)
    
    best_day = max(history, key=lambda e: e.hp)
    worst_day = min(history, key=lambda e: e.hp)
    
    lines = [
        "─── HUMAN STATE (WEEK) ─────────────────────",
        "",
        f"  Days tracked: {len(history)}",
        f"  Distribution: 🟢 {green_days}  🟡 {yellow_days}  🔴 {red_days}",
        "",
        f"  Average HP:     {avg_hp:.0f}/100",
        f"  Average Stress: {avg_stress:.0f}/100",
        "",
        f"  Best day:  {best_day.date} (HP: {best_day.hp})",
        f"  Toughest:  {worst_day.date} (HP: {worst_day.hp})",
    ]
    
    return "\n".join(lines)


# =============================================================================
# REMINDERS INTEGRATION
# =============================================================================

def get_tone_hint(kernel: Optional[Any] = None) -> "ToneHint":
    """
    Get tone hint for reminders based on readiness tier.
    
    Returns:
        "ambitious" (Green), "normal" (Yellow), or "gentle" (Red)
    """
    manager = _get_manager(kernel)
    return manager.get_tone_hint()


def get_reminders_context(kernel: Optional[Any] = None) -> Dict[str, Any]:
    """
    Get human state context for Reminders section.
    
    Returns:
        Dict with:
        - tone_hint: "ambitious" / "normal" / "gentle"
        - readiness_tier: for reference
        - should_reduce_intensity: bool
    """
    manager = _get_manager(kernel)
    snapshot = manager.get_today_human_state()
    
    return {
        "tone_hint": manager.get_tone_hint(),
        "readiness_tier": snapshot.readiness_tier,
        "should_reduce_intensity": snapshot.readiness_tier == "Red",
        "hp": snapshot.hp,
    }


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # General getters
    "get_today_human_state",
    "get_readiness_tier",
    "get_load_modifier",
    "get_recommended_mode",
    "get_hp",
    # Workflow
    "get_workflow_context",
    "format_readiness_for_workflow",
    # Timerhythm
    "get_timerhythm_context",
    "get_7_day_averages",
    "format_state_for_daily_review",
    "format_state_for_weekly_review",
    # Reminders
    "get_tone_hint",
    "get_reminders_context",
]
