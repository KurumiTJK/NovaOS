# kernel/timerhythm_handlers.py
"""
NovaOS Timerhythm Section v2.1.0

Implements the Timerhythm section with:
- daily-review: Two-phase daily review (morning + night)
- weekly-review: Weekly macro goals evaluation

v2.1.0 CHANGES:
- Refactored daily-review to support morning and night phases
- Phase 1 awards +15 XP, Phase 2 awards +10 XP bonus
- Perfect day tracking for completing both phases
- Streak logic: counts day if at least one phase completed

Features:
- Presence XP: Awarded once per day on first meaningful interaction
- Daily Review XP:
  - First phase of day: +15 XP
  - Second phase (bonus): +10 XP
  - Total for perfect day: +25 XP
- Weekly Macro Goals XP: Based on quest completions by module

This module ONLY emits XP events to Identity - it never directly manipulates
Identity internals.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Callable, Literal

logger = logging.getLogger("nova.timerhythm")


# =============================================================================
# TYPE DEFINITIONS
# =============================================================================

Phase = Literal["morning", "night"]


# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class DailyReviewPhaseState:
    """
    Tracks phase completion for a single day's daily review.
    """
    date: str = ""  # YYYY-MM-DD
    morning_completed: bool = False
    night_completed: bool = False
    morning_completed_at: Optional[str] = None  # ISO timestamp
    night_completed_at: Optional[str] = None  # ISO timestamp
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date,
            "morning_completed": self.morning_completed,
            "night_completed": self.night_completed,
            "morning_completed_at": self.morning_completed_at,
            "night_completed_at": self.night_completed_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DailyReviewPhaseState":
        return cls(
            date=data.get("date", ""),
            morning_completed=data.get("morning_completed", False),
            night_completed=data.get("night_completed", False),
            morning_completed_at=data.get("morning_completed_at"),
            night_completed_at=data.get("night_completed_at"),
        )
    
    def is_phase_completed(self, phase: Phase) -> bool:
        if phase == "morning":
            return self.morning_completed
        return self.night_completed
    
    def phases_completed_count(self) -> int:
        return int(self.morning_completed) + int(self.night_completed)
    
    def is_perfect_day(self) -> bool:
        return self.morning_completed and self.night_completed


@dataclass
class TimerhythmState:
    """
    Persistent state for the Timerhythm section.
    Stored in data/timerhythm.json
    
    v2.1.0: Added daily_review phase tracking and perfect_day metrics.
    """
    # Daily review tracking
    last_daily_review_date: Optional[str] = None  # YYYY-MM-DD
    daily_review_streak_count: int = 0
    
    # v2.1.0: Phase-based daily review
    daily_review: DailyReviewPhaseState = field(default_factory=DailyReviewPhaseState)
    
    # Presence tracking
    last_presence_date: Optional[str] = None  # YYYY-MM-DD
    
    # Weekly review tracking
    last_weekly_review_week_id: Optional[str] = None  # YYYY-Www
    
    # Daily review history (last 14 entries - dates only for streak calc)
    daily_review_dates: List[str] = field(default_factory=list)  # List of YYYY-MM-DD
    
    # v2.1.0: Perfect day tracking
    perfect_day_count: int = 0
    perfect_day_streak: int = 0
    last_perfect_day_date: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "last_daily_review_date": self.last_daily_review_date,
            "daily_review_streak_count": self.daily_review_streak_count,
            "daily_review": self.daily_review.to_dict(),
            "last_presence_date": self.last_presence_date,
            "last_weekly_review_week_id": self.last_weekly_review_week_id,
            "daily_review_dates": self.daily_review_dates,
            "perfect_day_count": self.perfect_day_count,
            "perfect_day_streak": self.perfect_day_streak,
            "last_perfect_day_date": self.last_perfect_day_date,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TimerhythmState":
        # Parse daily_review sub-object
        daily_review_data = data.get("daily_review")
        if daily_review_data:
            daily_review = DailyReviewPhaseState.from_dict(daily_review_data)
        else:
            daily_review = DailyReviewPhaseState()
        
        return cls(
            last_daily_review_date=data.get("last_daily_review_date"),
            daily_review_streak_count=data.get("daily_review_streak_count", 0),
            daily_review=daily_review,
            last_presence_date=data.get("last_presence_date"),
            last_weekly_review_week_id=data.get("last_weekly_review_week_id"),
            daily_review_dates=data.get("daily_review_dates", []),
            perfect_day_count=data.get("perfect_day_count", 0),
            perfect_day_streak=data.get("perfect_day_streak", 0),
            last_perfect_day_date=data.get("last_perfect_day_date"),
        )


@dataclass
class DailyReviewLogEntry:
    """
    A single daily review log entry containing both phases.
    One entry per date.
    """
    date: str  # YYYY-MM-DD
    readiness: Optional[Dict[str, Any]] = None
    morning: Optional[Dict[str, Any]] = None  # {completed_at, answers}
    night: Optional[Dict[str, Any]] = None  # {completed_at, answers}
    xp: Optional[Dict[str, Any]] = None  # {presence_awarded, daily_awarded, bonus_awarded}
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date,
            "readiness": self.readiness,
            "morning": self.morning,
            "night": self.night,
            "xp": self.xp,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DailyReviewLogEntry":
        return cls(
            date=data.get("date", ""),
            readiness=data.get("readiness"),
            morning=data.get("morning"),
            night=data.get("night"),
            xp=data.get("xp"),
        )


@dataclass 
class TimerhythmLogEntry:
    """A single log entry for weekly reviews (legacy format kept for weekly)."""
    type: str  # "weekly"
    date: str  # YYYY-Www for weekly
    timestamp: str  # ISO timestamp
    xp_awarded: int
    summary: str
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TimerhythmLogEntry":
        return cls(**data)


# =============================================================================
# TIMERHYTHM MANAGER
# =============================================================================

class TimerhythmManager:
    """
    Manages Timerhythm state, persistence, and XP events.
    
    v2.1.0: Added two-phase daily review support.
    """
    
    MAX_LOG_ENTRIES = 50
    MAX_DAILY_REVIEW_HISTORY = 14  # Track last 14 daily review dates
    
    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir or Path("data")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.state_file = self.data_dir / "timerhythm.json"
        self.log_file = self.data_dir / "timerhythm_log.json"
        
        self._state: Optional[TimerhythmState] = None
        self._log: Optional[List[Dict[str, Any]]] = None  # Mixed format for daily + weekly
    
    # ─────────────────────────────────────────────────────────────────────
    # PERSISTENCE
    # ─────────────────────────────────────────────────────────────────────
    
    def _load_state(self) -> TimerhythmState:
        """Load state from disk."""
        if self._state is not None:
            return self._state
        
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._state = TimerhythmState.from_dict(data)
                # Migrate if needed
                self._migrate_state_if_needed()
            except Exception as e:
                logger.error("Failed to load timerhythm state: %s", e)
                self._state = TimerhythmState()
        else:
            self._state = TimerhythmState()
        
        return self._state
    
    def _migrate_state_if_needed(self) -> None:
        """
        Migrate old state format to new two-phase format.
        
        If last_daily_review_date == today and daily_review is empty,
        assume morning was completed to preserve streak continuity.
        """
        state = self._state
        if state is None:
            return
        
        today = self._get_today_str()
        
        # Check if migration needed: old format had last_daily_review_date but no phase tracking
        if state.last_daily_review_date and not state.daily_review.date:
            if state.last_daily_review_date == today:
                # Today was marked complete in old system - assume morning
                state.daily_review = DailyReviewPhaseState(
                    date=today,
                    morning_completed=True,
                    night_completed=False,
                    morning_completed_at=datetime.now(timezone.utc).isoformat(),
                )
                logger.info("Migrated daily review state: assumed morning completed for today")
            else:
                # Different day - start fresh
                state.daily_review = DailyReviewPhaseState(date=today)
    
    def _save_state(self) -> None:
        """Save state to disk."""
        if self._state is None:
            return
        
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(self._state.to_dict(), f, indent=2)
        except Exception as e:
            logger.error("Failed to save timerhythm state: %s", e)
    
    def _load_log(self) -> List[Dict[str, Any]]:
        """Load log from disk."""
        if self._log is not None:
            return self._log
        
        if self.log_file.exists():
            try:
                with open(self.log_file, "r", encoding="utf-8") as f:
                    self._log = json.load(f)
            except Exception as e:
                logger.error("Failed to load timerhythm log: %s", e)
                self._log = []
        else:
            self._log = []
        
        return self._log
    
    def _save_log(self) -> None:
        """Save log to disk."""
        if self._log is None:
            return
        
        # Trim to max entries
        if len(self._log) > self.MAX_LOG_ENTRIES:
            self._log = self._log[-self.MAX_LOG_ENTRIES:]
        
        try:
            with open(self.log_file, "w", encoding="utf-8") as f:
                json.dump(self._log, f, indent=2)
        except Exception as e:
            logger.error("Failed to save timerhythm log: %s", e)
    
    def _get_or_create_daily_log_entry(self, date: str) -> Dict[str, Any]:
        """
        Get or create a daily review log entry for a specific date.
        Returns the entry dict (mutable reference).
        """
        log = self._load_log()
        
        # Find existing entry for this date
        for entry in log:
            if entry.get("date") == date and entry.get("type") != "weekly":
                return entry
        
        # Create new entry
        new_entry = {
            "date": date,
            "readiness": None,
            "morning": None,
            "night": None,
            "xp": {
                "presence_awarded": False,
                "daily_awarded": 0,
                "bonus_awarded": 0,
            },
        }
        log.append(new_entry)
        return new_entry
    
    def _add_weekly_log_entry(self, entry: TimerhythmLogEntry) -> None:
        """Add a weekly review log entry."""
        log = self._load_log()
        log.append(entry.to_dict())
        self._save_log()
    
    # ─────────────────────────────────────────────────────────────────────
    # DATE HELPERS
    # ─────────────────────────────────────────────────────────────────────
    
    def _get_today_str(self) -> str:
        """Get today's date string in YYYY-MM-DD format (local timezone)."""
        return datetime.now().strftime("%Y-%m-%d")
    
    def _get_yesterday_str(self) -> str:
        """Get yesterday's date string in YYYY-MM-DD format."""
        yesterday = datetime.now() - timedelta(days=1)
        return yesterday.strftime("%Y-%m-%d")
    
    def _get_week_id(self, dt: Optional[datetime] = None) -> str:
        """Get ISO week ID in YYYY-Www format."""
        dt = dt or datetime.now()
        return dt.strftime("%Y-W%W")
    
    def _get_date_n_days_ago(self, n: int) -> str:
        """Get date string for n days ago."""
        past = datetime.now() - timedelta(days=n)
        return past.strftime("%Y-%m-%d")
    
    def _get_current_hour(self) -> int:
        """Get current hour in local timezone (0-23)."""
        return datetime.now().hour
    
    def _suggest_phase(self) -> Phase:
        """
        Suggest a phase based on time of day.
        Before 2pm (14:00) => morning
        After 2pm => night
        """
        hour = self._get_current_hour()
        if hour < 14:
            return "morning"
        return "night"
    
    # ─────────────────────────────────────────────────────────────────────
    # PRESENCE XP (unchanged from v2.0.0)
    # ─────────────────────────────────────────────────────────────────────
    
    def check_and_award_presence_xp(self, kernel: Any) -> Optional[Dict[str, Any]]:
        """
        Check if presence XP should be awarded and award it if needed.
        
        Returns XP result dict if awarded, None if already awarded today.
        """
        state = self._load_state()
        today = self._get_today_str()
        
        if state.last_presence_date == today:
            # Already awarded today
            return None
        
        # Award presence XP
        state.last_presence_date = today
        self._save_state()
        
        # Emit XP event to Identity
        try:
            from kernel.identity_integration import award_xp
            result = award_xp(
                kernel,
                amount=10,
                source="presence",
                module=None,
                description="First interaction today",
            )
            logger.info("Presence XP awarded: 10 XP")
            return result
        except ImportError:
            logger.warning("Could not import identity_integration for presence XP")
            return {"xp_gained": 10, "source": "presence"}
    
    def was_presence_awarded_today(self) -> bool:
        """Check if presence XP was already awarded today."""
        state = self._load_state()
        return state.last_presence_date == self._get_today_str()
    
    # ─────────────────────────────────────────────────────────────────────
    # DAILY REVIEW — TWO-PHASE SYSTEM (v2.1.0)
    # ─────────────────────────────────────────────────────────────────────
    
    def _ensure_today_phase_state(self) -> DailyReviewPhaseState:
        """
        Ensure daily_review state is for today.
        If date changed, reset phase completion for new day.
        """
        state = self._load_state()
        today = self._get_today_str()
        
        if state.daily_review.date != today:
            # Date changed - reset for new day
            state.daily_review = DailyReviewPhaseState(date=today)
            self._save_state()
        
        return state.daily_review
    
    def get_phase_status(self) -> Dict[str, Any]:
        """
        Get current phase completion status for today.
        
        Returns dict with:
        - date: today's date
        - morning_completed: bool
        - night_completed: bool
        - phases_done: 0, 1, or 2
        - is_perfect_day: bool
        """
        phase_state = self._ensure_today_phase_state()
        
        return {
            "date": phase_state.date,
            "morning_completed": phase_state.morning_completed,
            "night_completed": phase_state.night_completed,
            "phases_done": phase_state.phases_completed_count(),
            "is_perfect_day": phase_state.is_perfect_day(),
        }
    
    def is_phase_completed(self, phase: Phase) -> bool:
        """Check if a specific phase is completed today."""
        phase_state = self._ensure_today_phase_state()
        return phase_state.is_phase_completed(phase)
    
    def get_current_streak(self) -> int:
        """Get the current daily review streak."""
        state = self._load_state()
        return state.daily_review_streak_count
    
    def get_perfect_day_stats(self) -> Dict[str, Any]:
        """Get perfect day statistics."""
        state = self._load_state()
        return {
            "perfect_day_count": state.perfect_day_count,
            "perfect_day_streak": state.perfect_day_streak,
        }
    
    def compute_daily_review_xp_award(self, phase: Phase) -> Tuple[int, int, str]:
        """
        Compute XP award for completing a daily review phase.
        
        Returns: (daily_award, bonus_award, description)
        
        Rules:
        - First phase of day: +15 XP
        - Second phase (bonus): +10 XP
        - Re-running completed phase: +0 XP
        """
        phase_state = self._ensure_today_phase_state()
        
        # Check if this phase already completed
        if phase_state.is_phase_completed(phase):
            return 0, 0, f"Phase '{phase}' already completed today"
        
        # Determine if this is first or second phase
        phases_done = phase_state.phases_completed_count()
        
        if phases_done == 0:
            # First phase of the day
            return 15, 0, f"Daily review (phase 1/2): {phase}"
        else:
            # Second phase - bonus
            return 0, 10, f"Daily review bonus (phase 2/2): {phase}"
    
    def complete_daily_review_phase(
        self,
        kernel: Any,
        phase: Phase,
        answers: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Complete a daily review phase and award XP.
        
        Args:
            kernel: NovaKernel instance
            phase: "morning" or "night"
            answers: Optional dict of reflection answers
        
        Returns dict with:
        - already_completed: bool
        - phase: str
        - daily_award: int
        - bonus_award: int
        - total_xp: int
        - streak: int
        - perfect_day: bool
        - perfect_day_count: int
        """
        state = self._load_state()
        today = self._get_today_str()
        yesterday = self._get_yesterday_str()
        now_iso = datetime.now(timezone.utc).isoformat()
        
        # Ensure we have today's phase state
        phase_state = self._ensure_today_phase_state()
        
        # Check if already completed
        if phase_state.is_phase_completed(phase):
            return {
                "already_completed": True,
                "phase": phase,
                "daily_award": 0,
                "bonus_award": 0,
                "total_xp": 0,
                "streak": state.daily_review_streak_count,
                "perfect_day": phase_state.is_perfect_day(),
                "perfect_day_count": state.perfect_day_count,
            }
        
        # Compute XP award
        daily_award, bonus_award, description = self.compute_daily_review_xp_award(phase)
        total_xp = daily_award + bonus_award
        
        # Mark phase as completed
        if phase == "morning":
            phase_state.morning_completed = True
            phase_state.morning_completed_at = now_iso
        else:
            phase_state.night_completed = True
            phase_state.night_completed_at = now_iso
        
        # Update streak logic (only on first phase of day)
        is_first_phase_today = phase_state.phases_completed_count() == 1
        
        if is_first_phase_today:
            # Check if we should increment or reset streak
            if state.last_daily_review_date == yesterday:
                # Continuing streak
                state.daily_review_streak_count += 1
            elif state.last_daily_review_date != today:
                # Missed days or fresh start
                state.daily_review_streak_count = 1
            # else: same day, streak already counted
            
            # Update last daily review date
            state.last_daily_review_date = today
            
            # Update daily review dates history
            if today not in state.daily_review_dates:
                state.daily_review_dates.append(today)
                if len(state.daily_review_dates) > self.MAX_DAILY_REVIEW_HISTORY:
                    state.daily_review_dates = state.daily_review_dates[-self.MAX_DAILY_REVIEW_HISTORY:]
        
        # Check for perfect day (both phases done)
        became_perfect_day = False
        if phase_state.is_perfect_day():
            became_perfect_day = True
            state.perfect_day_count += 1
            
            # Update perfect day streak
            if state.last_perfect_day_date == yesterday:
                state.perfect_day_streak += 1
            else:
                state.perfect_day_streak = 1
            
            state.last_perfect_day_date = today
        
        # Save state
        self._save_state()
        
        # Award XP via Identity
        xp_result = None
        if total_xp > 0:
            try:
                from kernel.identity_integration import award_xp
                xp_result = award_xp(
                    kernel,
                    amount=total_xp,
                    source="timerhythm_daily",
                    module=None,
                    description=description,
                )
                logger.info("Daily review XP awarded: %d XP (%s)", total_xp, description)
            except ImportError:
                logger.warning("Could not import identity_integration for daily review XP")
        
        # Update log
        log_entry = self._get_or_create_daily_log_entry(today)
        
        # Update readiness if not set
        if log_entry.get("readiness") is None:
            try:
                from kernel.human_state_integration import get_timerhythm_context
                ctx = get_timerhythm_context(kernel)
                log_entry["readiness"] = ctx.get("today", {})
            except:
                pass
        
        # Update phase in log
        phase_log = {
            "completed_at": now_iso,
            "answers": answers or {},
        }
        log_entry[phase] = phase_log
        
        # Update XP in log
        if log_entry.get("xp") is None:
            log_entry["xp"] = {"presence_awarded": False, "daily_awarded": 0, "bonus_awarded": 0}
        
        log_entry["xp"]["daily_awarded"] = log_entry["xp"].get("daily_awarded", 0) + daily_award
        log_entry["xp"]["bonus_awarded"] = log_entry["xp"].get("bonus_awarded", 0) + bonus_award
        
        self._save_log()
        
        return {
            "already_completed": False,
            "phase": phase,
            "daily_award": daily_award,
            "bonus_award": bonus_award,
            "total_xp": total_xp,
            "streak": state.daily_review_streak_count,
            "perfect_day": phase_state.is_perfect_day(),
            "became_perfect_day": became_perfect_day,
            "perfect_day_count": state.perfect_day_count,
            "perfect_day_streak": state.perfect_day_streak,
            "xp_result": xp_result,
        }
    
    def get_daily_review_count_last_7_days(self) -> int:
        """Get the count of daily reviews completed in the last 7 days."""
        state = self._load_state()
        
        # Get dates for last 7 days
        cutoff_dates = set()
        for i in range(7):
            cutoff_dates.add(self._get_date_n_days_ago(i))
        
        # Count how many daily review dates fall within
        count = sum(1 for d in state.daily_review_dates if d in cutoff_dates)
        return count
    
    # ─────────────────────────────────────────────────────────────────────
    # WEEKLY REVIEW (unchanged from v2.0.0)
    # ─────────────────────────────────────────────────────────────────────
    
    def was_weekly_review_completed_this_week(self) -> bool:
        """Check if weekly review was already completed this week."""
        state = self._load_state()
        return state.last_weekly_review_week_id == self._get_week_id()
    
    def get_quest_completions_last_7_days(self, kernel: Any) -> Dict[str, int]:
        """
        Get quest completions by module_id for the last 7 days.
        
        Returns dict: {module_id: count}
        """
        completions: Dict[str, int] = {}
        
        # Calculate cutoff date
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        
        try:
            # Access quest engine
            if not hasattr(kernel, 'quest_engine'):
                return completions
            
            engine = kernel.quest_engine
            progress = engine.get_progress()
            
            for quest_id, quest_progress in progress.quest_runs.items():
                if quest_progress.status != "completed":
                    continue
                
                if not quest_progress.completed_at:
                    continue
                
                # Parse completion date
                try:
                    completed_dt = datetime.fromisoformat(quest_progress.completed_at.replace('Z', '+00:00'))
                except ValueError:
                    continue
                
                if completed_dt < cutoff:
                    continue
                
                # Get quest to find module_id
                quest = engine.get_quest(quest_id)
                if quest:
                    module_id = quest.module_id or quest.category or "general"
                    completions[module_id] = completions.get(module_id, 0) + 1
        
        except Exception as e:
            logger.error("Error getting quest completions: %s", e)
        
        return completions
    
    def evaluate_weekly_macro_goals(
        self,
        kernel: Any,
        quest_completions: Dict[str, int],
        daily_review_count: int,
    ) -> List[Dict[str, Any]]:
        """
        Evaluate weekly macro goals and return list of results.
        
        Each result has: {goal, target, actual, met, xp, module}
        """
        goals = []
        
        # Goal 1: 4+ Cybersecurity quests
        cyber_count = quest_completions.get("Cybersecurity", 0) + quest_completions.get("cyber", 0)
        goals.append({
            "goal": "4 Cybersecurity quests",
            "target": 4,
            "actual": cyber_count,
            "met": cyber_count >= 4,
            "xp": 80 if cyber_count >= 4 else 0,
            "module": "Cybersecurity",
        })
        
        # Goal 2: 3+ Business quests
        biz_count = quest_completions.get("Business", 0) + quest_completions.get("business", 0)
        goals.append({
            "goal": "3 Business quests",
            "target": 3,
            "actual": biz_count,
            "met": biz_count >= 3,
            "xp": 60 if biz_count >= 3 else 0,
            "module": "Business",
        })
        
        # Goal 3: Daily review 6+ days
        goals.append({
            "goal": "Daily review 6+ days",
            "target": 6,
            "actual": daily_review_count,
            "met": daily_review_count >= 6,
            "xp": 60 if daily_review_count >= 6 else 0,
            "module": None,  # Meta goal
        })
        
        return goals
    
    def complete_weekly_review(self, kernel: Any) -> Dict[str, Any]:
        """
        Complete the weekly review and award macro goal XP.
        
        Returns dict with macro goal results and XP info.
        """
        state = self._load_state()
        week_id = self._get_week_id()
        
        # Check if already completed this week
        if state.last_weekly_review_week_id == week_id:
            return {
                "already_completed": True,
                "week_id": week_id,
            }
        
        # Get data for evaluation
        quest_completions = self.get_quest_completions_last_7_days(kernel)
        daily_review_count = self.get_daily_review_count_last_7_days()
        
        # Evaluate macro goals
        goals = self.evaluate_weekly_macro_goals(kernel, quest_completions, daily_review_count)
        
        # Award XP for each met goal
        total_xp = 0
        xp_results = []
        
        try:
            from kernel.identity_integration import award_xp
            
            for goal in goals:
                if goal["met"]:
                    result = award_xp(
                        kernel,
                        amount=goal["xp"],
                        source="timerhythm_weekly",
                        module=goal["module"],
                        description=f"Weekly macro: {goal['goal']}",
                    )
                    xp_results.append(result)
                    total_xp += goal["xp"]
                    logger.info("Weekly goal XP awarded: %d XP for %s", goal["xp"], goal["goal"])
        
        except ImportError:
            logger.warning("Could not import identity_integration for weekly XP")
            for goal in goals:
                if goal["met"]:
                    total_xp += goal["xp"]
        
        # Update state
        state.last_weekly_review_week_id = week_id
        self._save_state()
        
        # Add log entry
        met_count = sum(1 for g in goals if g["met"])
        self._add_weekly_log_entry(TimerhythmLogEntry(
            type="weekly",
            date=week_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            xp_awarded=total_xp,
            summary=f"Weekly review: {met_count}/{len(goals)} goals met, +{total_xp} XP",
        ))
        
        return {
            "already_completed": False,
            "week_id": week_id,
            "goals": goals,
            "total_xp": total_xp,
            "quest_completions": quest_completions,
            "daily_review_count": daily_review_count,
            "xp_results": xp_results,
        }
    
    # ─────────────────────────────────────────────────────────────────────
    # GET STATE FOR DISPLAY
    # ─────────────────────────────────────────────────────────────────────
    
    def get_state_summary(self) -> Dict[str, Any]:
        """Get state summary for display."""
        state = self._load_state()
        phase_status = self.get_phase_status()
        
        return {
            "daily_review_streak": state.daily_review_streak_count,
            "morning_completed": phase_status["morning_completed"],
            "night_completed": phase_status["night_completed"],
            "weekly_review_completed_this_week": self.was_weekly_review_completed_this_week(),
            "presence_awarded_today": self.was_presence_awarded_today(),
            "daily_reviews_last_7_days": self.get_daily_review_count_last_7_days(),
            "perfect_day_count": state.perfect_day_count,
            "perfect_day_streak": state.perfect_day_streak,
        }


# =============================================================================
# SINGLETON MANAGER
# =============================================================================

_manager: Optional[TimerhythmManager] = None


def get_timerhythm_manager(data_dir: Optional[Path] = None) -> TimerhythmManager:
    """Get or create the TimerhythmManager singleton."""
    global _manager
    if _manager is None:
        _manager = TimerhythmManager(data_dir)
    return _manager


def _get_manager(kernel: Any) -> TimerhythmManager:
    """Get manager, trying kernel first."""
    if hasattr(kernel, 'timerhythm_manager'):
        return kernel.timerhythm_manager
    
    data_dir = None
    if hasattr(kernel, 'config') and hasattr(kernel.config, 'data_dir'):
        data_dir = kernel.config.data_dir
    
    return get_timerhythm_manager(data_dir)


# =============================================================================
# COMMAND HANDLERS
# =============================================================================

CommandResponse = Dict[str, Any]


def _base_response(
    cmd_name: str,
    summary: str,
    extra: Optional[Dict[str, Any]] = None,
) -> CommandResponse:
    """Build a standard response."""
    return {
        "ok": True,
        "command": cmd_name,
        "summary": summary,
        "data": extra or {},
        "type": "syscommand",
    }


def _parse_phase_arg(args: Any) -> Optional[Phase]:
    """
    Parse phase argument from command args.
    
    Returns "morning", "night", or None if not specified/invalid.
    """
    action = None
    
    if isinstance(args, dict):
        action = args.get("phase") or args.get("action")
        positional = args.get("_", [])
        if not action and positional:
            action = str(positional[0]).lower()
    elif isinstance(args, str) and args.strip():
        action = args.strip().lower()
    
    if action in ("morning", "night"):
        return action
    
    # Check for "done" with phase
    if action and action.startswith("done"):
        # e.g., "done morning" or just "done"
        parts = action.split()
        if len(parts) > 1 and parts[1] in ("morning", "night"):
            return parts[1]
    
    return None


def handle_daily_review(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    Two-phase daily review (morning + night).
    
    Usage:
        #daily-review                  — Show status (auto-suggest phase)
        #daily-review morning          — Complete morning phase
        #daily-review night            — Complete night phase
        #daily-review morning done     — Same as above
    
    XP:
        - First phase of day: +15 XP
        - Second phase (bonus): +10 XP
        - Total for perfect day: +25 XP
    """
    from datetime import datetime, timezone
    
    manager = _get_manager(kernel)
    today = datetime.now().strftime("%Y-%m-%d")
    
    # Parse phase argument
    phase = _parse_phase_arg(args)
    
    # Check for "done" action without phase (legacy support)
    action_str = ""
    if isinstance(args, dict):
        positional = args.get("_", [])
        if positional:
            action_str = str(positional[0]).lower()
    elif isinstance(args, str):
        action_str = args.strip().lower()
    
    # If just "done" with no phase, suggest based on time
    if action_str == "done" and phase is None:
        phase = manager._suggest_phase()
    
    # ─── COMPLETE A PHASE ───
    if phase is not None:
        # Check and award presence XP first (if not already awarded today)
        presence_result = manager.check_and_award_presence_xp(kernel)
        presence_awarded = presence_result is not None
        
        # Complete the phase
        result = manager.complete_daily_review_phase(kernel, phase)
        
        if result.get("already_completed"):
            # Phase already done - show status
            status = manager.get_phase_status()
            lines = [
                f"╔══ Daily Review — {phase.title()} ══╗",
                f"Date: {today}",
                "",
                f"Phase '{phase}' already completed today.",
                "",
                "Status:",
                f"  Morning: {'✓' if status['morning_completed'] else '✗'}",
                f"  Night: {'✓' if status['night_completed'] else '✗'}",
                "",
                "XP Earned: +0 (already done)",
                "",
                f"Streak: {result['streak']} days",
            ]
            if result.get("perfect_day"):
                lines.append(f"Perfect days: {result.get('perfect_day_count', 0)} 🌟")
            
            return _base_response(cmd_name, "\n".join(lines), {
                "status": "already_complete",
                "phase": phase,
            })
        
        # Build completion message
        status = manager.get_phase_status()
        
        lines = [
            f"╔══ Daily Review — {phase.title()} ══╗",
            f"Date: {today}",
        ]
        
        # Add human state summary
        try:
            from kernel.human_state_integration import get_timerhythm_context, get_load_modifier
            ctx = get_timerhythm_context(kernel)
            today_state = ctx.get("today", {})
            tier = today_state.get("readiness_tier", "Unknown")
            mode = today_state.get("recommended_mode", "?")
            load_mod = get_load_modifier(kernel)
            tier_emoji = {"Green": "🟢", "Yellow": "🟡", "Red": "🔴"}.get(tier, "⚪")
            lines.append(f"Readiness: {tier_emoji} {tier} (Load {load_mod:.2f}) — {mode}")
        except:
            pass
        
        lines.extend([
            "",
            "Status:",
            f"  Morning: {'✓' if status['morning_completed'] else '✗'}",
            f"  Night: {'✓' if status['night_completed'] else '✗'}",
            "",
            "XP Earned:",
        ])
        
        if presence_awarded:
            lines.append("  Presence: +10 XP")
        
        if result["daily_award"] > 0:
            lines.append(f"  Daily Review: +{result['daily_award']} XP (phase 1/2)")
        elif result["bonus_award"] > 0:
            lines.append(f"  Daily Review: +{result['bonus_award']} XP (bonus, phase 2/2)")
        else:
            lines.append("  Daily Review: +0 XP")
        
        total_this_run = result["total_xp"] + (10 if presence_awarded else 0)
        if total_this_run > 0:
            lines.append(f"  Total: +{total_this_run} XP")
        
        lines.append("")
        lines.append(f"Streak: {result['streak']} days")
        
        if result.get("became_perfect_day"):
            lines.append(f"🌟 Perfect day! (Total: {result['perfect_day_count']})")
        elif result.get("perfect_day_count", 0) > 0:
            lines.append(f"Perfect days: {result['perfect_day_count']}")
        
        # Suggest next phase if only one done
        if status["phases_done"] == 1:
            other_phase = "night" if phase == "morning" else "morning"
            lines.extend([
                "",
                f"Complete #{other_phase} review later for +10 XP bonus!",
            ])
        
        return _base_response(cmd_name, "\n".join(lines), {
            "status": "complete",
            "phase": phase,
            "daily_award": result["daily_award"],
            "bonus_award": result["bonus_award"],
            "streak": result["streak"],
            "perfect_day": result.get("perfect_day", False),
        })
    
    # ─── SHOW STATUS (no phase specified) ───
    
    status = manager.get_phase_status()
    streak = manager.get_current_streak()
    perfect_stats = manager.get_perfect_day_stats()
    suggested_phase = manager._suggest_phase()
    
    # Get Human State context
    human_state_lines = []
    try:
        from kernel.human_state_integration import get_timerhythm_context, get_load_modifier
        ctx = get_timerhythm_context(kernel)
        today_state = ctx.get("today", {})
        
        tier = today_state.get("readiness_tier", "Unknown")
        mode = today_state.get("recommended_mode", "?")
        load_mod = get_load_modifier(kernel)
        tier_emoji = {"Green": "🟢", "Yellow": "🟡", "Red": "🔴"}.get(tier, "⚪")
        
        human_state_lines = [
            f"Readiness: {tier_emoji} {tier} (Load {load_mod:.2f}) — {mode}",
            f"Human State: Sleep {today_state.get('sleep_quality', '?')} · "
            f"Stamina {today_state.get('stamina', '?')} · "
            f"Stress {today_state.get('stress', '?')} · "
            f"Focus {today_state.get('focus', '?')}",
        ]
    except:
        human_state_lines = ["Human State: (not available)"]
    
    # Get today's workflow progress
    workflow_lines = []
    try:
        if hasattr(kernel, 'quest_engine'):
            engine = kernel.quest_engine
            progress = engine.get_progress()
            
            # Count today's completions
            today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            today_completions = 0
            
            for quest_id, qp in progress.quest_runs.items():
                if qp.status == "completed" and qp.completed_at:
                    try:
                        completed_dt = datetime.fromisoformat(qp.completed_at.replace('Z', '+00:00'))
                        if completed_dt >= today_start:
                            today_completions += 1
                    except:
                        pass
            
            workflow_lines = [f"Quests completed today: {today_completions}"]
    except:
        pass
    
    # Build output
    lines = [
        "╔══ Daily Review ══╗",
        f"Date: {today}",
    ]
    
    for line in human_state_lines:
        lines.append(line)
    
    if workflow_lines:
        lines.append("")
        for line in workflow_lines:
            lines.append(line)
    
    lines.extend([
        "",
        "Status:",
        f"  Morning: {'✓' if status['morning_completed'] else '✗'}",
        f"  Night: {'✓' if status['night_completed'] else '✗'}",
    ])
    
    # XP info
    lines.append("")
    presence_pending = not manager.was_presence_awarded_today()
    
    if status["phases_done"] == 0:
        lines.append("XP Available:")
        if presence_pending:
            lines.append("  Presence: +10 XP")
        lines.append("  Daily Review (phase 1): +15 XP")
        lines.append("  Daily Review (phase 2): +10 XP bonus")
    elif status["phases_done"] == 1:
        lines.append("XP Available:")
        if presence_pending:
            lines.append("  Presence: +10 XP")
        lines.append("  Daily Review (phase 2): +10 XP bonus")
    else:
        lines.append("✓ Both phases completed!")
    
    lines.extend([
        "",
        f"Streak: {streak} days",
    ])
    
    if perfect_stats["perfect_day_count"] > 0:
        lines.append(f"Perfect days: {perfect_stats['perfect_day_count']}")
    
    # Suggest action
    if status["phases_done"] < 2:
        lines.extend([
            "",
            f"Suggested: #daily-review {suggested_phase}",
        ])
    
    return _base_response(cmd_name, "\n".join(lines), {
        "date": today,
        "morning_completed": status["morning_completed"],
        "night_completed": status["night_completed"],
        "suggested_phase": suggested_phase,
        "streak": streak,
    })


def handle_weekly_review(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    Weekly review with macro goals evaluation.
    
    Usage:
        #weekly-review         — Show weekly stats and macro goal progress
        #weekly-review done    — Complete weekly review and earn macro XP
    """
    from datetime import datetime, timezone
    
    manager = _get_manager(kernel)
    week_id = manager._get_week_id()
    
    # Calculate date range
    today = datetime.now()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    date_range = f"{week_start.strftime('%Y-%m-%d')} to {week_end.strftime('%Y-%m-%d')}"
    
    # Parse action
    action = None
    if isinstance(args, dict):
        action = args.get("action")
        positional = args.get("_", [])
        if not action and positional:
            action = str(positional[0]).lower()
    elif isinstance(args, str) and args.strip():
        action = args.strip().lower()
    
    # ─── COMPLETE WEEKLY REVIEW ───
    if action == "done":
        result = manager.complete_weekly_review(kernel)
        
        if result.get("already_completed"):
            return _base_response(cmd_name,
                f"✓ Weekly review already completed for {week_id}.\n\n"
                "Come back next week!",
                {"status": "already_complete", "week_id": week_id})
        
        # Build completion message
        lines = [
            "╔══ Weekly Review Complete ══╗",
            f"Week: {week_id}",
            "",
            "Macro Goals:",
        ]
        
        for goal in result["goals"]:
            status = "✅" if goal["met"] else "❌"
            lines.append(f"  {status} {goal['goal']}: {goal['actual']}/{goal['target']}" + 
                        (f" => +{goal['xp']} XP" if goal["met"] else ""))
        
        lines.extend([
            "",
            f"Total XP Earned: +{result['total_xp']} XP",
            "",
            "Great week! Keep up the momentum.",
        ])
        
        return _base_response(cmd_name, "\n".join(lines), {
            "status": "complete",
            "week_id": week_id,
            "goals": result["goals"],
            "total_xp": result["total_xp"],
        })
    
    # ─── SHOW WEEKLY REVIEW ───
    
    already_done = manager.was_weekly_review_completed_this_week()
    quest_completions = manager.get_quest_completions_last_7_days(kernel)
    daily_review_count = manager.get_daily_review_count_last_7_days()
    
    # Get human state averages
    avg_lines = []
    try:
        from kernel.human_state_integration import get_7_day_averages
        avgs = get_7_day_averages(kernel)
        avg_lines = [
            f"  Sleep {avgs.get('avg_sleep_quality', 0):.0f} · "
            f"Stamina {avgs.get('avg_stamina', 0):.0f} · "
            f"Stress {avgs.get('avg_stress', 0):.0f}"
        ]
    except:
        avg_lines = ["  (not available)"]
    
    # Evaluate goals (preview)
    goals = manager.evaluate_weekly_macro_goals(kernel, quest_completions, daily_review_count)
    
    # Build output
    lines = [
        "╔══ Weekly Review ══╗",
        f"Week: {week_id} ({date_range})",
        "",
        "Human State Averages:",
    ]
    lines.extend(avg_lines)
    
    lines.extend([
        "",
        "Progress (last 7 days):",
        f"  Quests completed: {sum(quest_completions.values())}",
    ])
    
    if quest_completions:
        lines.append("  By module:")
        for mod, count in sorted(quest_completions.items()):
            lines.append(f"    • {mod}: {count}")
    
    lines.extend([
        "",
        "Macro Goals:",
    ])
    
    potential_xp = 0
    for goal in goals:
        status = "✅" if goal["met"] else "❌"
        progress = f"{goal['actual']}/{goal['target']}"
        xp_str = f" => +{goal['xp']} XP" if goal["met"] else ""
        lines.append(f"  {status} {goal['goal']} ({progress}){xp_str}")
        if goal["met"]:
            potential_xp += goal["xp"]
    
    lines.append("")
    
    if already_done:
        lines.extend([
            f"✓ Weekly review already completed for {week_id}.",
            "",
            "Come back next week!",
        ])
    else:
        lines.extend([
            f"Potential XP: +{potential_xp} XP",
            "",
            "When ready, run: #weekly-review done",
        ])
    
    return _base_response(cmd_name, "\n".join(lines), {
        "week_id": week_id,
        "status": "already_complete" if already_done else "pending",
        "goals": goals,
        "quest_completions": quest_completions,
    })


# =============================================================================
# HANDLER REGISTRY
# =============================================================================

def get_time_rhythm_handlers() -> Dict[str, Any]:
    """
    Get timerhythm command handlers for registration.
    
    These override the placeholder handlers in syscommands.py.
    """
    return {
        "handle_daily_review": handle_daily_review,
        "handle_weekly_review": handle_weekly_review,
    }


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Manager
    "TimerhythmManager",
    "get_timerhythm_manager",
    
    # Handlers
    "handle_daily_review",
    "handle_weekly_review",
    "get_time_rhythm_handlers",
    
    # Data models
    "TimerhythmState",
    "DailyReviewPhaseState",
    "DailyReviewLogEntry",
    "TimerhythmLogEntry",
]
