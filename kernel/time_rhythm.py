# kernel/time_rhythm.py
"""
v0.8.0 — Time Rhythm Module for NovaOS Life RPG

Manages time-based features:
- Time of day awareness (morning, afternoon, evening, night)
- Day of week tracking
- Weekly review scheduling
- Daily/weekly rhythm patterns

This module provides the foundation for:
- Context-aware suggestions
- Weekly review quests
- Time-based productivity patterns
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from .command_types import CommandResponse


# =============================================================================
# TIME ENUMS
# =============================================================================

class TimeOfDay(Enum):
    """Time of day periods."""
    MORNING = "morning"      # 5am - 12pm
    AFTERNOON = "afternoon"  # 12pm - 5pm
    EVENING = "evening"      # 5pm - 9pm
    NIGHT = "night"          # 9pm - 5am
    
    @classmethod
    def from_hour(cls, hour: int) -> "TimeOfDay":
        """Get time of day from hour (0-23)."""
        if 5 <= hour < 12:
            return cls.MORNING
        elif 12 <= hour < 17:
            return cls.AFTERNOON
        elif 17 <= hour < 21:
            return cls.EVENING
        else:
            return cls.NIGHT
    
    @property
    def icon(self) -> str:
        icons = {
            TimeOfDay.MORNING: "🌅",
            TimeOfDay.AFTERNOON: "☀️",
            TimeOfDay.EVENING: "🌆",
            TimeOfDay.NIGHT: "🌙",
        }
        return icons.get(self, "⏰")
    
    @property
    def greeting(self) -> str:
        greetings = {
            TimeOfDay.MORNING: "Good morning",
            TimeOfDay.AFTERNOON: "Good afternoon",
            TimeOfDay.EVENING: "Good evening",
            TimeOfDay.NIGHT: "Working late",
        }
        return greetings.get(self, "Hello")


class DayType(Enum):
    """Type of day."""
    WEEKDAY = "weekday"
    WEEKEND = "weekend"
    
    @classmethod
    def from_weekday(cls, weekday: int) -> "DayType":
        """Get day type from weekday (0=Monday, 6=Sunday)."""
        if weekday >= 5:  # Saturday or Sunday
            return cls.WEEKEND
        return cls.WEEKDAY


# =============================================================================
# RHYTHM STATE
# =============================================================================

@dataclass
class RhythmState:
    """
    Tracks time rhythm state and history.
    
    Attributes:
        last_weekly_review: ISO timestamp of last weekly review
        weekly_review_day: Preferred day for weekly review (0=Mon, 6=Sun)
        daily_focus_hours: Preferred focus hours (start, end)
        streak_days: Current streak of active days
        last_active_date: Last date user was active
    """
    last_weekly_review: Optional[str] = None
    weekly_review_day: int = 6  # Sunday by default
    daily_focus_start: int = 9   # 9am
    daily_focus_end: int = 17    # 5pm
    streak_days: int = 0
    last_active_date: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "last_weekly_review": self.last_weekly_review,
            "weekly_review_day": self.weekly_review_day,
            "daily_focus_start": self.daily_focus_start,
            "daily_focus_end": self.daily_focus_end,
            "streak_days": self.streak_days,
            "last_active_date": self.last_active_date,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RhythmState":
        return cls(
            last_weekly_review=data.get("last_weekly_review"),
            weekly_review_day=data.get("weekly_review_day", 6),
            daily_focus_start=data.get("daily_focus_start", 9),
            daily_focus_end=data.get("daily_focus_end", 17),
            streak_days=data.get("streak_days", 0),
            last_active_date=data.get("last_active_date"),
        )


# =============================================================================
# TIME RHYTHM MANAGER
# =============================================================================

class TimeRhythmManager:
    """
    Manages time rhythm state and provides time-aware features.
    
    Data stored in data/rhythm.json
    """
    
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.rhythm_file = self.data_dir / "rhythm.json"
        self._state: RhythmState = self._load()
    
    def _load(self) -> RhythmState:
        """Load rhythm state from disk."""
        if not self.rhythm_file.exists():
            state = RhythmState()
            self._save(state)
            return state
        
        try:
            with open(self.rhythm_file) as f:
                data = json.load(f)
            return RhythmState.from_dict(data)
        except (json.JSONDecodeError, IOError):
            return RhythmState()
    
    def _save(self, state: Optional[RhythmState] = None) -> None:
        """Save rhythm state to disk."""
        state = state or self._state
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        with open(self.rhythm_file, "w") as f:
            json.dump(state.to_dict(), f, indent=2)
    
    @property
    def state(self) -> RhythmState:
        """Get current rhythm state."""
        return self._state
    
    # -------------------------------------------------------------------------
    # Time Queries
    # -------------------------------------------------------------------------
    
    def get_current_time_info(self) -> Dict[str, Any]:
        """Get current time information."""
        now = datetime.now()
        time_of_day = TimeOfDay.from_hour(now.hour)
        day_type = DayType.from_weekday(now.weekday())
        
        return {
            "datetime": now.isoformat(),
            "hour": now.hour,
            "weekday": now.weekday(),
            "weekday_name": now.strftime("%A"),
            "time_of_day": time_of_day.value,
            "time_of_day_icon": time_of_day.icon,
            "greeting": time_of_day.greeting,
            "day_type": day_type.value,
            "is_weekend": day_type == DayType.WEEKEND,
            "is_focus_hours": self._state.daily_focus_start <= now.hour < self._state.daily_focus_end,
        }
    
    def is_weekly_review_due(self) -> bool:
        """Check if weekly review is due."""
        now = datetime.now()
        
        # Check if it's the review day
        if now.weekday() != self._state.weekly_review_day:
            return False
        
        # Check if we've done a review this week
        if self._state.last_weekly_review:
            try:
                last_review = datetime.fromisoformat(
                    self._state.last_weekly_review.replace("Z", "+00:00")
                )
                # If last review was less than 6 days ago, not due
                if (now - last_review.replace(tzinfo=None)).days < 6:
                    return False
            except:
                pass
        
        return True
    
    def days_since_weekly_review(self) -> Optional[int]:
        """Get days since last weekly review."""
        if not self._state.last_weekly_review:
            return None
        
        try:
            last_review = datetime.fromisoformat(
                self._state.last_weekly_review.replace("Z", "+00:00")
            )
            now = datetime.now(timezone.utc)
            return (now - last_review).days
        except:
            return None
    
    # -------------------------------------------------------------------------
    # State Updates
    # -------------------------------------------------------------------------
    
    def record_activity(self) -> Dict[str, Any]:
        """Record user activity and update streak."""
        now = datetime.now()
        today = now.date().isoformat()
        
        result = {"streak_updated": False, "new_streak": self._state.streak_days}
        
        if self._state.last_active_date:
            last_date = datetime.fromisoformat(self._state.last_active_date).date()
            days_diff = (now.date() - last_date).days
            
            if days_diff == 0:
                # Same day, no change
                pass
            elif days_diff == 1:
                # Consecutive day, increment streak
                self._state.streak_days += 1
                result["streak_updated"] = True
                result["new_streak"] = self._state.streak_days
            else:
                # Streak broken
                self._state.streak_days = 1
                result["streak_updated"] = True
                result["streak_broken"] = True
                result["new_streak"] = 1
        else:
            # First activity
            self._state.streak_days = 1
            result["streak_updated"] = True
            result["new_streak"] = 1
        
        self._state.last_active_date = today
        self._save()
        
        return result
    
    def complete_weekly_review(self) -> None:
        """Mark weekly review as complete."""
        self._state.last_weekly_review = datetime.now(timezone.utc).isoformat()
        self._save()
    
    def set_review_day(self, weekday: int) -> None:
        """Set preferred weekly review day (0=Mon, 6=Sun)."""
        if 0 <= weekday <= 6:
            self._state.weekly_review_day = weekday
            self._save()
    
    def set_focus_hours(self, start: int, end: int) -> None:
        """Set preferred focus hours."""
        if 0 <= start < 24 and 0 <= end <= 24:
            self._state.daily_focus_start = start
            self._state.daily_focus_end = end
            self._save()


# =============================================================================
# COMMAND HANDLERS
# =============================================================================

def _base_response(cmd: str, summary: str, data: Dict[str, Any] = None) -> CommandResponse:
    return CommandResponse(
        ok=True,
        command=cmd,
        summary=summary,
        data=data or {},
    )


def _error_response(cmd: str, message: str, code: str) -> CommandResponse:
    return CommandResponse(
        ok=False,
        command=cmd,
        summary=message,
        error_code=code,
    )


def handle_presence(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    Show time rhythm presence snapshot.
    
    Displays current time context, streak, and rhythm state.
    
    Usage:
        #presence
    """
    rhythm = getattr(kernel, 'time_rhythm_manager', None)
    if not rhythm:
        return _error_response(cmd_name, "Time rhythm not available.", "NO_RHYTHM")
    
    # Get assistant mode
    mode_mgr = getattr(kernel, 'assistant_mode_manager', None)
    show_fancy = mode_mgr and mode_mgr.is_story_mode()
    
    # Get current time info
    time_info = rhythm.get_current_time_info()
    state = rhythm.state
    
    # Record activity (updates streak)
    activity = rhythm.record_activity()
    
    if show_fancy:
        lines = [
            f"{time_info['time_of_day_icon']} **{time_info['greeting']}!**",
            "",
            f"**{time_info['weekday_name']}** • {time_info['time_of_day'].title()}",
        ]
        
        if time_info['is_focus_hours']:
            lines.append("🎯 *Focus hours active*")
        
        lines.append("")
        
        # Streak
        streak = state.streak_days
        if streak > 0:
            streak_icon = "🔥" if streak >= 7 else "⚡"
            lines.append(f"{streak_icon} **{streak} day streak**")
        
        # Weekly review status
        if rhythm.is_weekly_review_due():
            lines.append("")
            lines.append("📋 **Weekly review due!**")
            lines.append("   Run `#weekly-review` to reflect on your progress")
        else:
            days = rhythm.days_since_weekly_review()
            if days is not None:
                lines.append(f"📋 Last review: {days} day(s) ago")
        
        lines.append("")
        lines.append("**Commands:**")
        lines.append("• `#pulse` — Quest pulse diagnostics")
        lines.append("• `#align` — Time-based suggestions")
        
    else:
        lines = [
            f"{time_info['weekday_name']} {time_info['time_of_day']}",
            f"Streak: {state.streak_days} days",
        ]
        if rhythm.is_weekly_review_due():
            lines.append("Weekly review due")
    
    return _base_response(cmd_name, "\n".join(lines), {
        "time": time_info,
        "streak": state.streak_days,
        "weekly_review_due": rhythm.is_weekly_review_due(),
    })


def handle_pulse(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    Quest pulse diagnostics - show quest activity patterns.
    
    Usage:
        #pulse
    """
    rhythm = getattr(kernel, 'time_rhythm_manager', None)
    quest_engine = getattr(kernel, 'quest_engine', None)
    
    # Get assistant mode
    mode_mgr = getattr(kernel, 'assistant_mode_manager', None)
    show_fancy = mode_mgr and mode_mgr.is_story_mode()
    
    # Gather stats
    stats = {
        "active_quest": None,
        "quests_available": 0,
        "quests_completed": 0,
        "total_xp": 0,
    }
    
    if quest_engine:
        active_run = quest_engine.get_active_run()
        if active_run:
            quest = quest_engine.get_quest(active_run.quest_id)
            if quest:
                stats["active_quest"] = {
                    "title": quest.title,
                    "step": active_run.current_step_index + 1,
                    "total_steps": len(quest.steps),
                }
        
        quests = quest_engine.list_quests()
        stats["quests_available"] = len([q for q in quests if q.status in ("available", "not_started")])
        
        progress = quest_engine.get_progress()
        stats["quests_completed"] = sum(
            1 for q in progress.quest_runs.values()
            if q.status == "completed" or q.completed_at
        )
        stats["total_xp"] = sum(q.xp_earned for q in progress.quest_runs.values())
    
    # Get player level
    profile_mgr = getattr(kernel, 'player_profile_manager', None)
    if profile_mgr:
        profile = profile_mgr.get_profile()
        stats["player_level"] = profile.level
        stats["player_xp"] = profile.total_xp
    
    if show_fancy:
        lines = ["💓 **Quest Pulse**", ""]
        
        if stats.get("active_quest"):
            aq = stats["active_quest"]
            lines.append(f"🎯 **Active:** {aq['title']}")
            lines.append(f"   Step {aq['step']}/{aq['total_steps']}")
            lines.append("")
        
        lines.append(f"📜 Available quests: {stats['quests_available']}")
        lines.append(f"✅ Completed quests: {stats['quests_completed']}")
        lines.append(f"⚡ Total XP earned: {stats['total_xp']}")
        
        if stats.get("player_level"):
            lines.append("")
            lines.append(f"🏆 Player Level: {stats['player_level']}")
        
        if rhythm:
            streak = rhythm.state.streak_days
            if streak > 0:
                lines.append(f"🔥 Streak: {streak} days")
    else:
        lines = [
            f"Active: {stats['active_quest']['title'] if stats.get('active_quest') else 'None'}",
            f"Available: {stats['quests_available']} | Completed: {stats['quests_completed']}",
            f"XP: {stats['total_xp']}",
        ]
    
    return _base_response(cmd_name, "\n".join(lines), stats)


def handle_align(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    Alignment suggestions based on time and current state.
    
    Usage:
        #align
    """
    rhythm = getattr(kernel, 'time_rhythm_manager', None)
    if not rhythm:
        return _error_response(cmd_name, "Time rhythm not available.", "NO_RHYTHM")
    
    # Get assistant mode
    mode_mgr = getattr(kernel, 'assistant_mode_manager', None)
    show_fancy = mode_mgr and mode_mgr.is_story_mode()
    
    time_info = rhythm.get_current_time_info()
    suggestions = []
    
    # Time-based suggestions
    time_of_day = TimeOfDay(time_info["time_of_day"])
    
    if time_of_day == TimeOfDay.MORNING:
        suggestions.append({
            "text": "Morning is great for focused learning",
            "action": "Start a challenging quest",
            "command": "#quest",
        })
        suggestions.append({
            "text": "Process yesterday's inbox",
            "action": "Clear the backlog",
            "command": "#inbox",
        })
    
    elif time_of_day == TimeOfDay.AFTERNOON:
        suggestions.append({
            "text": "Afternoon energy dip — try lighter tasks",
            "action": "Continue an active quest",
            "command": "#next",
        })
    
    elif time_of_day == TimeOfDay.EVENING:
        suggestions.append({
            "text": "Evening review time",
            "action": "Check your progress",
            "command": "#insight",
        })
        suggestions.append({
            "text": "Capture tomorrow's ideas",
            "action": "Add to inbox",
            "command": "#capture",
        })
    
    else:  # Night
        suggestions.append({
            "text": "Late night — consider wrapping up",
            "action": "Quick capture and rest",
            "command": "#capture",
        })
    
    # Weekly review suggestion
    if rhythm.is_weekly_review_due():
        suggestions.insert(0, {
            "text": "Weekly review is due!",
            "action": "Reflect on your week",
            "command": "#weekly-review",
            "priority": "high",
        })
    
    # Weekend suggestion
    if time_info["is_weekend"]:
        suggestions.append({
            "text": "Weekend mode — balance rest and growth",
            "action": "Explore new modules",
            "command": "#modules",
        })
    
    if show_fancy:
        lines = [
            f"🧭 **Alignment Suggestions**",
            "",
            f"*{time_info['weekday_name']} {time_info['time_of_day'].title()}*",
            "",
        ]
        
        for i, sug in enumerate(suggestions[:4], 1):
            priority_mark = "❗ " if sug.get("priority") == "high" else ""
            lines.append(f"{priority_mark}**{sug['text']}**")
            lines.append(f"   {sug['action']} → `{sug['command']}`")
            lines.append("")
    else:
        lines = [f"Suggestions for {time_info['time_of_day']}:"]
        for sug in suggestions[:4]:
            lines.append(f"- {sug['text']} ({sug['command']})")
    
    return _base_response(cmd_name, "\n".join(lines), {
        "time": time_info,
        "suggestions": suggestions,
    })


def handle_weekly_review(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    Start or complete weekly review.
    
    Usage:
        #weekly-review          — Show weekly review status
        #weekly-review start    — Begin weekly review process
        #weekly-review complete — Mark review as done
    """
    rhythm = getattr(kernel, 'time_rhythm_manager', None)
    if not rhythm:
        return _error_response(cmd_name, "Time rhythm not available.", "NO_RHYTHM")
    
    # Parse action
    action = None
    if isinstance(args, dict):
        action = args.get("action")
        positional = args.get("_", [])
        if not action and positional:
            action = positional[0]
    elif isinstance(args, str):
        action = args
    
    # Get assistant mode
    mode_mgr = getattr(kernel, 'assistant_mode_manager', None)
    show_fancy = mode_mgr and mode_mgr.is_story_mode()
    
    if action == "complete":
        rhythm.complete_weekly_review()
        if show_fancy:
            return _base_response(
                cmd_name,
                "✅ **Weekly review complete!**\n\n"
                "Great job reflecting on your progress. See you next week!",
                {"completed": True},
            )
        else:
            return _base_response(cmd_name, "Weekly review marked complete.", {"completed": True})
    
    if action == "start":
        # Gather review data
        review_data = _gather_weekly_review_data(kernel)
        
        if show_fancy:
            lines = [
                "📋 **Weekly Review**",
                "",
                "Let's reflect on your week!",
                "",
            ]
            
            if review_data.get("quests_completed", 0) > 0:
                lines.append(f"**Quests Completed:** {review_data['quests_completed']}")
            if review_data.get("xp_earned", 0) > 0:
                lines.append(f"**XP Earned:** {review_data['xp_earned']}")
            if review_data.get("streak", 0) > 0:
                lines.append(f"**Current Streak:** {review_data['streak']} days")
            
            lines.append("")
            lines.append("**Reflection Questions:**")
            lines.append("1. What went well this week?")
            lines.append("2. What could be improved?")
            lines.append("3. What's your focus for next week?")
            lines.append("")
            lines.append("When done, run `#weekly-review complete`")
        else:
            lines = [
                "Weekly Review",
                f"Quests: {review_data.get('quests_completed', 0)} | XP: {review_data.get('xp_earned', 0)}",
                "Run #weekly-review complete when done",
            ]
        
        return _base_response(cmd_name, "\n".join(lines), review_data)
    
    # Default: show status
    days_since = rhythm.days_since_weekly_review()
    is_due = rhythm.is_weekly_review_due()
    
    if show_fancy:
        lines = ["📋 **Weekly Review Status**", ""]
        
        if days_since is not None:
            lines.append(f"Last review: {days_since} day(s) ago")
        else:
            lines.append("No reviews completed yet")
        
        if is_due:
            lines.append("")
            lines.append("⚡ **Review is due!**")
            lines.append("Run `#weekly-review start` to begin")
        else:
            lines.append("")
            lines.append("Next review: " + _get_next_review_day(rhythm))
        
        lines.append("")
        lines.append("**Commands:**")
        lines.append("• `#weekly-review start` — Begin review")
        lines.append("• `#weekly-review complete` — Mark done")
    else:
        status = "due" if is_due else f"in {7 - (days_since or 0)} days"
        lines = [f"Weekly review: {status}"]
    
    return _base_response(cmd_name, "\n".join(lines), {
        "days_since": days_since,
        "is_due": is_due,
    })


def _gather_weekly_review_data(kernel) -> Dict[str, Any]:
    """Gather data for weekly review."""
    data = {
        "quests_completed": 0,
        "xp_earned": 0,
        "streak": 0,
        "inbox_processed": 0,
    }
    
    # Quest stats
    quest_engine = getattr(kernel, 'quest_engine', None)
    if quest_engine:
        progress = quest_engine.get_progress()
        data["quests_completed"] = sum(
            1 for q in progress.quest_runs.values()
            if q.status == "completed" or q.completed_at
        )
        data["xp_earned"] = sum(q.xp_earned for q in progress.quest_runs.values())
    
    # Player profile
    profile_mgr = getattr(kernel, 'player_profile_manager', None)
    if profile_mgr:
        profile = profile_mgr.get_profile()
        data["player_level"] = profile.level
        data["total_xp"] = profile.total_xp
    
    # Rhythm
    rhythm = getattr(kernel, 'time_rhythm_manager', None)
    if rhythm:
        data["streak"] = rhythm.state.streak_days
    
    return data


def _get_next_review_day(rhythm: TimeRhythmManager) -> str:
    """Get human-readable next review day."""
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    return days[rhythm.state.weekly_review_day]


# =============================================================================
# HANDLER REGISTRY
# =============================================================================

TIME_RHYTHM_HANDLERS = {
    "handle_presence": handle_presence,
    "handle_pulse": handle_pulse,
    "handle_align": handle_align,
    "handle_weekly_review": handle_weekly_review,
}


def get_time_rhythm_handlers():
    """Get all time rhythm handlers for registration."""
    return TIME_RHYTHM_HANDLERS
