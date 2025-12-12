# kernel/time_rhythm_handlers.py
"""
NovaOS Timerhythm Section v3.0.0

Three-phase daily review (morning + evening + night) with:
- Morning: sleep input → HP/readiness display → goal setting
- Evening: energy input only (no XP)
- Night: reflection + habits + HP finalization

Weekly habits (Mon-Sun): focus_progress, diet_progress
Schedule system: set in weekly review, shown in morning
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Literal

logger = logging.getLogger("nova.timerhythm")

Phase = Literal["morning", "evening", "night"]


# =============================================================================
# DERIVATION FUNCTIONS
# =============================================================================

def derive_mood(energy: int) -> int:
    """mood = (energy - 3) * 2, range: -4 to +4"""
    return (energy - 3) * 2


def derive_stress(energy: int) -> int:
    """stress = 100 - ((energy - 1) * 25), mapping: 1→100, 2→75, 3→50, 4→25, 5→0"""
    return 100 - ((energy - 1) * 25)


def compute_hp(sleep: int, energy: int) -> int:
    """
    HP = 0.45*sleep + 0.35*(100-stress) + 0.20*mood_norm
    where mood_norm = ((mood + 4) / 8) * 100
    """
    mood = derive_mood(energy)
    stress = derive_stress(energy)
    mood_norm = ((mood + 4) / 8) * 100
    hp = 0.45 * sleep + 0.35 * (100 - stress) + 0.20 * mood_norm
    return max(0, min(100, int(round(hp))))


def compute_readiness(hp: int, stress: int, energy: int) -> str:
    """GREEN: HP>=70 AND stress<=40 AND energy>=4; RED: HP<50 OR stress>=70 OR energy<=2; else YELLOW"""
    if hp < 50 or stress >= 70 or energy <= 2:
        return "Red"
    if hp >= 70 and stress <= 40 and energy >= 4:
        return "Green"
    return "Yellow"


# =============================================================================
# WIZARD SESSION STATE
# =============================================================================

@dataclass
class DailyReviewWizardSession:
    session_id: str
    phase: Phase
    step: int = 0
    started_at: str = ""
    
    # Morning
    sleep: Optional[int] = None
    goal: Optional[str] = None
    
    # Evening
    energy: Optional[int] = None
    
    # Night
    what_did_you_do: Optional[str] = None
    goal_progress: Optional[str] = None
    schedule_adjustment: Optional[bool] = None
    schedule_items: Optional[List[str]] = None
    schedule_confirm: Optional[bool] = None
    one_word: Optional[str] = None
    adjustment: Optional[str] = None
    win: Optional[str] = None
    diet_ate: Optional[bool] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DailyReviewWizardSession":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


_wizard_sessions: Dict[str, DailyReviewWizardSession] = {}


def get_daily_review_wizard_session(session_id: str) -> Optional[DailyReviewWizardSession]:
    return _wizard_sessions.get(session_id)


def has_active_daily_review_wizard(session_id: str) -> bool:
    return session_id in _wizard_sessions


def create_daily_review_wizard_session(session_id: str, phase: Phase) -> DailyReviewWizardSession:
    session = DailyReviewWizardSession(
        session_id=session_id, phase=phase, step=0,
        started_at=datetime.now(timezone.utc).isoformat(),
    )
    _wizard_sessions[session_id] = session
    return session


def clear_daily_review_wizard_session(session_id: str) -> None:
    _wizard_sessions.pop(session_id, None)


# =============================================================================
# WIZARD STEPS
# =============================================================================

MORNING_STEPS = [
    {"field": "sleep", "prompt": "Sleep last night (0-100):", "required": True, "type": "int", "show_context_after": True},
    {"field": "goal", "prompt": "What is your goal today?", "required": True, "type": "str"},
]

EVENING_STEPS = [
    {"field": "energy", "prompt": "Energy right now (1-5):", "required": True, "type": "int"},
]

NIGHT_STEPS = [
    {"field": "goal_progress", "prompt": "Did you complete your goal today?\n(Yes / A little / Not today)", "required": True, "type": "str", "show_goal": True},
    {"field": "schedule_adjustment", "prompt": "Any adjustment to tomorrow's schedule? (yes/no)", "required": True, "type": "bool", "show_tomorrow_schedule": True},
    {"field": "schedule_items", "prompt": "What to add? (comma-separated list)", "required": True, "type": "schedule_list", "conditional_on": "schedule_adjustment"},
    {"field": "schedule_confirm", "prompt": "Confirm these additions? (yes/no)", "required": True, "type": "bool", "conditional_on": "schedule_adjustment", "show_schedule_preview": True},
    {"field": "diet_ate", "prompt": "Did you eat dinner today? (yes/no)", "required": True, "type": "bool"},
    {"field": "what_did_you_do", "prompt": "What did you do today?", "required": True, "type": "str"},
    {"field": "one_word", "prompt": "One word to describe your day:", "required": True, "type": "str"},
    {"field": "adjustment", "prompt": "One small adjustment you will make:", "required": False, "type": "str"},
    {"field": "win", "prompt": "One win (small counts):", "required": True, "type": "str"},
]


def get_wizard_steps(phase: Phase) -> List[Dict[str, Any]]:
    if phase == "morning":
        return MORNING_STEPS
    elif phase == "evening":
        return EVENING_STEPS
    return NIGHT_STEPS


# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class DailyState:
    date: str = ""
    sleep: Optional[int] = None
    energy: Optional[int] = None
    goal: Optional[str] = None
    mood: Optional[int] = None
    stress: Optional[int] = None
    hp: Optional[int] = None
    morning_completed: bool = False
    evening_completed: bool = False
    night_completed: bool = False
    morning_completed_at: Optional[str] = None
    evening_completed_at: Optional[str] = None
    night_completed_at: Optional[str] = None
    what_did_you_do: Optional[str] = None
    goal_progress: Optional[str] = None
    one_word: Optional[str] = None
    adjustment: Optional[str] = None
    win: Optional[str] = None
    diet_ate: Optional[bool] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DailyState":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
    
    def is_phase_completed(self, phase: Phase) -> bool:
        return getattr(self, f"{phase}_completed", False)
    
    def phases_completed_count(self) -> int:
        return int(self.morning_completed) + int(self.evening_completed) + int(self.night_completed)
    
    def is_perfect_day(self) -> bool:
        return self.morning_completed and self.evening_completed and self.night_completed
    
    def recompute_derived(self) -> None:
        if self.energy is not None:
            self.mood = derive_mood(self.energy)
            self.stress = derive_stress(self.energy)
            if self.sleep is not None:
                self.hp = compute_hp(self.sleep, self.energy)


@dataclass
class WeeklyHabits:
    week_id: str = ""
    focus_progress: float = 0.0
    focus_target: int = 7
    diet_progress: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WeeklyHabits":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class WeeklySchedule:
    week_id: str = ""
    monday: List[str] = field(default_factory=list)
    tuesday: List[str] = field(default_factory=list)
    wednesday: List[str] = field(default_factory=list)
    thursday: List[str] = field(default_factory=list)
    friday: List[str] = field(default_factory=list)
    saturday: List[str] = field(default_factory=list)
    sunday: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WeeklySchedule":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
    
    def get_day_schedule(self, day_name: str) -> List[str]:
        return getattr(self, day_name.lower(), [])


@dataclass
class TimerhythmState:
    today: DailyState = field(default_factory=DailyState)
    yesterday: DailyState = field(default_factory=DailyState)
    weekly_habits: WeeklyHabits = field(default_factory=WeeklyHabits)
    weekly_schedule: WeeklySchedule = field(default_factory=WeeklySchedule)
    last_daily_review_date: Optional[str] = None
    daily_review_streak_count: int = 0
    daily_review_dates: List[str] = field(default_factory=list)
    last_presence_date: Optional[str] = None
    last_weekly_review_week_id: Optional[str] = None
    perfect_day_count: int = 0
    perfect_day_streak: int = 0
    last_perfect_day_date: Optional[str] = None
    hp_history: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "today": self.today.to_dict(),
            "yesterday": self.yesterday.to_dict(),
            "weekly_habits": self.weekly_habits.to_dict(),
            "weekly_schedule": self.weekly_schedule.to_dict(),
            "last_daily_review_date": self.last_daily_review_date,
            "daily_review_streak_count": self.daily_review_streak_count,
            "daily_review_dates": self.daily_review_dates,
            "last_presence_date": self.last_presence_date,
            "last_weekly_review_week_id": self.last_weekly_review_week_id,
            "perfect_day_count": self.perfect_day_count,
            "perfect_day_streak": self.perfect_day_streak,
            "last_perfect_day_date": self.last_perfect_day_date,
            "hp_history": self.hp_history,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TimerhythmState":
        today = DailyState.from_dict(data.get("today", {})) if data.get("today") else DailyState()
        yesterday = DailyState.from_dict(data.get("yesterday", {})) if data.get("yesterday") else DailyState()
        habits = WeeklyHabits.from_dict(data.get("weekly_habits", {})) if data.get("weekly_habits") else WeeklyHabits()
        schedule = WeeklySchedule.from_dict(data.get("weekly_schedule", {})) if data.get("weekly_schedule") else WeeklySchedule()
        return cls(
            today=today, yesterday=yesterday, weekly_habits=habits, weekly_schedule=schedule,
            last_daily_review_date=data.get("last_daily_review_date"),
            daily_review_streak_count=data.get("daily_review_streak_count", 0),
            daily_review_dates=data.get("daily_review_dates", []),
            last_presence_date=data.get("last_presence_date"),
            last_weekly_review_week_id=data.get("last_weekly_review_week_id"),
            perfect_day_count=data.get("perfect_day_count", 0),
            perfect_day_streak=data.get("perfect_day_streak", 0),
            last_perfect_day_date=data.get("last_perfect_day_date"),
            hp_history=data.get("hp_history", []),
        )


@dataclass 
class TimerhythmLogEntry:
    type: str
    date: str
    timestamp: str
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
    MAX_LOG_ENTRIES = 50
    MAX_DAILY_REVIEW_HISTORY = 14
    MAX_HP_HISTORY = 14
    
    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir or Path("data")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.data_dir / "timerhythm.json"
        self.log_file = self.data_dir / "timerhythm_log.json"
        self._state: Optional[TimerhythmState] = None
        self._log: Optional[List[Dict[str, Any]]] = None
    
    def _load_state(self) -> TimerhythmState:
        if self._state is not None:
            return self._state
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    self._state = TimerhythmState.from_dict(json.load(f))
                self._ensure_today()
            except Exception as e:
                logger.error("Failed to load timerhythm state: %s", e)
                self._state = TimerhythmState()
        else:
            self._state = TimerhythmState()
        return self._state
    
    def _save_state(self) -> None:
        if self._state is None:
            return
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(self._state.to_dict(), f, indent=2)
        except Exception as e:
            logger.error("Failed to save timerhythm state: %s", e)
    
    def _load_log(self) -> List[Dict[str, Any]]:
        if self._log is not None:
            return self._log
        if self.log_file.exists():
            try:
                with open(self.log_file, "r", encoding="utf-8") as f:
                    self._log = json.load(f)
            except:
                self._log = []
        else:
            self._log = []
        return self._log
    
    def _save_log(self) -> None:
        if self._log is None:
            return
        if len(self._log) > self.MAX_LOG_ENTRIES:
            self._log = self._log[-self.MAX_LOG_ENTRIES:]
        try:
            with open(self.log_file, "w", encoding="utf-8") as f:
                json.dump(self._log, f, indent=2)
        except Exception as e:
            logger.error("Failed to save timerhythm log: %s", e)
    
    def _get_or_create_daily_log_entry(self, date: str) -> Dict[str, Any]:
        log = self._load_log()
        for entry in log:
            if entry.get("date") == date and entry.get("type") != "weekly":
                return entry
        new_entry = {"date": date, "morning": None, "evening": None, "night": None,
                     "xp": {"presence_awarded": False, "phase1_awarded": 0, "phase2_awarded": 0, "phase3_awarded": 0}}
        log.append(new_entry)
        return new_entry
    
    def _add_weekly_log_entry(self, entry: TimerhythmLogEntry) -> None:
        log = self._load_log()
        log.append(entry.to_dict())
        self._save_log()
    
    # Date helpers
    def _get_today_str(self) -> str:
        return datetime.now().strftime("%Y-%m-%d")
    
    def _get_yesterday_str(self) -> str:
        return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    
    def _get_week_id(self, dt: Optional[datetime] = None) -> str:
        return (dt or datetime.now()).strftime("%Y-W%W")
    
    def _get_day_name(self, dt: Optional[datetime] = None) -> str:
        return (dt or datetime.now()).strftime("%A").lower()
    
    def _get_date_n_days_ago(self, n: int) -> str:
        return (datetime.now() - timedelta(days=n)).strftime("%Y-%m-%d")
    
    def _get_current_time_str(self) -> str:
        return datetime.now().strftime("%I:%M %p").lstrip("0")
    
    def _ensure_today(self) -> None:
        state = self._state
        if state is None:
            return
        today = self._get_today_str()
        if state.today.date != today:
            if state.today.date:
                state.yesterday = state.today
                if state.today.hp is not None:
                    state.hp_history.append({"date": state.today.date, "hp": state.today.hp})
                    if len(state.hp_history) > self.MAX_HP_HISTORY:
                        state.hp_history = state.hp_history[-self.MAX_HP_HISTORY:]
            state.today = DailyState(date=today)
            current_week = self._get_week_id()
            if state.weekly_habits.week_id != current_week:
                state.weekly_habits = WeeklyHabits(week_id=current_week)
            self._save_state()
    
    def _ensure_weekly_habits(self) -> WeeklyHabits:
        state = self._load_state()
        current_week = self._get_week_id()
        if state.weekly_habits.week_id != current_week:
            state.weekly_habits = WeeklyHabits(week_id=current_week)
            self._save_state()
        return state.weekly_habits
    
    # Readiness
    def compute_morning_readiness(self, sleep: int) -> Dict[str, Any]:
        state = self._load_state()
        yesterday_energy = state.yesterday.energy if state.yesterday.energy else 3
        hp = compute_hp(sleep, yesterday_energy)
        stress = derive_stress(yesterday_energy)
        readiness = compute_readiness(hp, stress, yesterday_energy)
        return {"hp": hp, "stress": stress, "energy": yesterday_energy, "readiness": readiness}
    
    def compute_night_readiness(self) -> Dict[str, Any]:
        state = self._load_state()
        today = state.today
        if today.sleep is None or today.energy is None:
            return {"hp": None, "stress": None, "energy": None, "readiness": "Unknown"}
        hp = compute_hp(today.sleep, today.energy)
        stress = derive_stress(today.energy)
        readiness = compute_readiness(hp, stress, today.energy)
        return {"hp": hp, "stress": stress, "energy": today.energy, "readiness": readiness}
    
    def get_today_schedule(self) -> List[str]:
        state = self._load_state()
        return state.weekly_schedule.get_day_schedule(self._get_day_name())
    
    def get_tomorrow_schedule(self) -> List[str]:
        state = self._load_state()
        tomorrow = datetime.now() + timedelta(days=1)
        return state.weekly_schedule.get_day_schedule(tomorrow.strftime("%A").lower())
    
    def add_to_tomorrow_schedule(self, items: List[str]) -> None:
        state = self._load_state()
        tomorrow = datetime.now() + timedelta(days=1)
        day_name = tomorrow.strftime("%A").lower()
        current = getattr(state.weekly_schedule, day_name, [])
        current.extend(items)
        setattr(state.weekly_schedule, day_name, current)
        self._save_state()
    
    # Presence XP
    def check_and_award_presence_xp(self, kernel: Any) -> Optional[Dict[str, Any]]:
        state = self._load_state()
        today = self._get_today_str()
        if state.last_presence_date == today:
            return None
        state.last_presence_date = today
        self._save_state()
        try:
            from kernel.identity_integration import award_xp
            return award_xp(kernel, amount=10, source="presence", module=None, description="First interaction today")
        except ImportError:
            return {"xp_gained": 10, "source": "presence"}
    
    def was_presence_awarded_today(self) -> bool:
        state = self._load_state()
        return state.last_presence_date == self._get_today_str()
    
    # Phase status
    def get_phase_status(self) -> Dict[str, Any]:
        state = self._load_state()
        self._ensure_today()
        today = state.today
        return {
            "date": today.date, "morning_completed": today.morning_completed,
            "evening_completed": today.evening_completed, "night_completed": today.night_completed,
            "phases_done": today.phases_completed_count(), "is_perfect_day": today.is_perfect_day(),
        }
    
    def is_phase_completed(self, phase: Phase) -> bool:
        state = self._load_state()
        self._ensure_today()
        return state.today.is_phase_completed(phase)
    
    def get_current_streak(self) -> int:
        return self._load_state().daily_review_streak_count
    
    def get_perfect_day_stats(self) -> Dict[str, Any]:
        state = self._load_state()
        return {"perfect_day_count": state.perfect_day_count, "perfect_day_streak": state.perfect_day_streak}
    
    def compute_phase_xp_award(self, phase: Phase) -> Tuple[int, str]:
        """XP: first=15, second=10, third=5. Evening=0."""
        if phase == "evening":
            return 0, "Evening check-in (no XP)"
        state = self._load_state()
        self._ensure_today()
        today = state.today
        if today.is_phase_completed(phase):
            return 0, f"Phase '{phase}' already completed"
        # Count only morning/night completions for XP calculation
        xp_phases = int(today.morning_completed) + int(today.night_completed)
        if xp_phases == 0:
            return 15, f"Daily review (phase 1): {phase}"
        elif xp_phases == 1:
            return 10, f"Daily review (phase 2): {phase}"
        return 5, f"Daily review (phase 3): {phase}"
    
    def _update_streak(self, state: TimerhythmState, today: DailyState) -> None:
        """Update streak on first phase of day."""
        yesterday = self._get_yesterday_str()
        is_first_phase = today.phases_completed_count() == 1
        if is_first_phase:
            if state.last_daily_review_date == yesterday:
                state.daily_review_streak_count += 1
            elif state.last_daily_review_date != today.date:
                state.daily_review_streak_count = 1
            state.last_daily_review_date = today.date
            if today.date not in state.daily_review_dates:
                state.daily_review_dates.append(today.date)
                if len(state.daily_review_dates) > self.MAX_DAILY_REVIEW_HISTORY:
                    state.daily_review_dates = state.daily_review_dates[-self.MAX_DAILY_REVIEW_HISTORY:]
    
    def complete_morning_phase(self, kernel: Any, sleep: int, goal: str) -> Dict[str, Any]:
        state = self._load_state()
        self._ensure_today()
        today = state.today
        now_iso = datetime.now(timezone.utc).isoformat()
        
        if today.morning_completed:
            return {"already_completed": True, "phase": "morning", "xp_awarded": 0}
        
        today.sleep = sleep
        today.goal = goal
        today.morning_completed = True
        today.morning_completed_at = now_iso
        
        xp_amount, description = self.compute_phase_xp_award("morning")
        self._update_streak(state, today)
        self._save_state()
        
        xp_result = None
        if xp_amount > 0:
            try:
                from kernel.identity_integration import award_xp
                xp_result = award_xp(kernel, amount=xp_amount, source="timerhythm_daily", module=None, description=description)
            except ImportError:
                pass
        
        log_entry = self._get_or_create_daily_log_entry(today.date)
        log_entry["morning"] = {"completed_at": now_iso, "sleep": sleep, "goal": goal}
        self._save_log()
        
        return {"already_completed": False, "phase": "morning", "xp_awarded": xp_amount,
                "streak": state.daily_review_streak_count, "readiness": self.compute_morning_readiness(sleep), "xp_result": xp_result}
    
    def complete_evening_phase(self, kernel: Any, energy: int) -> Dict[str, Any]:
        state = self._load_state()
        self._ensure_today()
        today = state.today
        now_iso = datetime.now(timezone.utc).isoformat()
        
        if today.evening_completed:
            return {"already_completed": True, "phase": "evening", "xp_awarded": 0}
        
        today.energy = energy
        today.evening_completed = True
        today.evening_completed_at = now_iso
        today.recompute_derived()
        
        self._update_streak(state, today)
        self._save_state()
        
        log_entry = self._get_or_create_daily_log_entry(today.date)
        log_entry["evening"] = {"completed_at": now_iso, "energy": energy}
        self._save_log()
        
        return {"already_completed": False, "phase": "evening", "xp_awarded": 0,
                "energy": energy, "mood": today.mood, "stress": today.stress}
    
    def complete_night_phase(self, kernel: Any, what_did_you_do: str, goal_progress: str,
                             one_word: str, adjustment: Optional[str], win: str, diet_ate: bool) -> Dict[str, Any]:
        state = self._load_state()
        self._ensure_today()
        today = state.today
        yesterday = self._get_yesterday_str()
        now_iso = datetime.now(timezone.utc).isoformat()
        
        if today.night_completed:
            return {"already_completed": True, "phase": "night", "xp_awarded": 0}
        
        today.what_did_you_do = what_did_you_do
        today.goal_progress = goal_progress
        today.one_word = one_word
        today.adjustment = adjustment
        today.win = win
        today.diet_ate = diet_ate
        today.night_completed = True
        today.night_completed_at = now_iso
        
        if today.energy is not None:
            today.recompute_derived()
        
        # Update weekly habits
        habits = self._ensure_weekly_habits()
        if goal_progress.lower() == "yes":
            habits.focus_progress += 1.0
        elif goal_progress.lower() == "a little":
            habits.focus_progress += 0.5
        if diet_ate:
            habits.diet_progress += 1
        
        xp_amount, description = self.compute_phase_xp_award("night")
        self._update_streak(state, today)
        
        became_perfect_day = False
        if today.is_perfect_day():
            became_perfect_day = True
            state.perfect_day_count += 1
            if state.last_perfect_day_date == yesterday:
                state.perfect_day_streak += 1
            else:
                state.perfect_day_streak = 1
            state.last_perfect_day_date = today.date
        
        self._save_state()
        
        xp_result = None
        if xp_amount > 0:
            try:
                from kernel.identity_integration import award_xp
                xp_result = award_xp(kernel, amount=xp_amount, source="timerhythm_daily", module=None, description=description)
            except ImportError:
                pass
        
        log_entry = self._get_or_create_daily_log_entry(today.date)
        log_entry["night"] = {"completed_at": now_iso, "what_did_you_do": what_did_you_do,
                              "goal_progress": goal_progress, "one_word": one_word, "adjustment": adjustment,
                              "win": win, "diet_ate": diet_ate}
        self._save_log()
        
        return {"already_completed": False, "phase": "night", "xp_awarded": xp_amount,
                "streak": state.daily_review_streak_count, "perfect_day": today.is_perfect_day(),
                "became_perfect_day": became_perfect_day, "perfect_day_count": state.perfect_day_count,
                "readiness": self.compute_night_readiness(),
                "weekly_habits": {"focus_progress": habits.focus_progress, "focus_target": habits.focus_target, "diet_progress": habits.diet_progress},
                "xp_result": xp_result}
    
    # Weekly review methods
    def was_weekly_review_completed_this_week(self) -> bool:
        return self._load_state().last_weekly_review_week_id == self._get_week_id()
    
    def get_weekly_hp_average(self) -> Optional[float]:
        state = self._load_state()
        current_week = self._get_week_id()
        week_hps = []
        for entry in state.hp_history:
            try:
                entry_date = datetime.strptime(entry["date"], "%Y-%m-%d")
                if self._get_week_id(entry_date) == current_week:
                    week_hps.append(entry["hp"])
            except:
                continue
        if state.today.hp is not None:
            week_hps.append(state.today.hp)
        return sum(week_hps) / len(week_hps) if week_hps else None
    
    def get_quest_completions_last_7_days(self, kernel: Any) -> Dict[str, int]:
        completions: Dict[str, int] = {}
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        try:
            if not hasattr(kernel, 'quest_engine'):
                return completions
            engine = kernel.quest_engine
            progress = engine.get_progress()
            for quest_id, quest_progress in progress.quest_runs.items():
                if quest_progress.status != "completed" or not quest_progress.completed_at:
                    continue
                try:
                    completed_dt = datetime.fromisoformat(quest_progress.completed_at.replace('Z', '+00:00'))
                except ValueError:
                    continue
                if completed_dt < cutoff:
                    continue
                quest = engine.get_quest(quest_id)
                if quest:
                    module_id = quest.module_id or quest.category or "general"
                    completions[module_id] = completions.get(module_id, 0) + 1
        except Exception as e:
            logger.error("Error getting quest completions: %s", e)
        return completions
    
    def get_daily_review_count_last_7_days(self) -> int:
        state = self._load_state()
        cutoff_dates = {self._get_date_n_days_ago(i) for i in range(7)}
        return sum(1 for d in state.daily_review_dates if d in cutoff_dates)
    
    def evaluate_weekly_macro_goals(self, kernel: Any, quest_completions: Dict[str, int], daily_review_count: int) -> List[Dict[str, Any]]:
        goals = []
        cyber_count = quest_completions.get("Cybersecurity", 0) + quest_completions.get("cyber", 0)
        goals.append({"goal": "4 Cybersecurity quests", "target": 4, "actual": cyber_count,
                      "met": cyber_count >= 4, "xp": 80 if cyber_count >= 4 else 0, "module": "Cybersecurity"})
        biz_count = quest_completions.get("Business", 0) + quest_completions.get("business", 0)
        goals.append({"goal": "3 Business quests", "target": 3, "actual": biz_count,
                      "met": biz_count >= 3, "xp": 60 if biz_count >= 3 else 0, "module": "Business"})
        goals.append({"goal": "Daily review 6+ days", "target": 6, "actual": daily_review_count,
                      "met": daily_review_count >= 6, "xp": 60 if daily_review_count >= 6 else 0, "module": None})
        return goals
    
    def complete_weekly_review(self, kernel: Any) -> Dict[str, Any]:
        state = self._load_state()
        week_id = self._get_week_id()
        if state.last_weekly_review_week_id == week_id:
            return {"already_completed": True, "week_id": week_id}
        
        quest_completions = self.get_quest_completions_last_7_days(kernel)
        daily_review_count = self.get_daily_review_count_last_7_days()
        goals = self.evaluate_weekly_macro_goals(kernel, quest_completions, daily_review_count)
        
        total_xp = 0
        xp_results = []
        try:
            from kernel.identity_integration import award_xp
            for goal in goals:
                if goal["met"]:
                    result = award_xp(kernel, amount=goal["xp"], source="timerhythm_weekly",
                                      module=goal["module"], description=f"Weekly macro: {goal['goal']}")
                    xp_results.append(result)
                    total_xp += goal["xp"]
        except ImportError:
            for goal in goals:
                if goal["met"]:
                    total_xp += goal["xp"]
        
        state.last_weekly_review_week_id = week_id
        self._save_state()
        
        met_count = sum(1 for g in goals if g["met"])
        self._add_weekly_log_entry(TimerhythmLogEntry(
            type="weekly", date=week_id, timestamp=datetime.now(timezone.utc).isoformat(),
            xp_awarded=total_xp, summary=f"Weekly review: {met_count}/{len(goals)} goals met, +{total_xp} XP"))
        
        habits = self._ensure_weekly_habits()
        return {"already_completed": False, "week_id": week_id, "goals": goals, "total_xp": total_xp,
                "quest_completions": quest_completions, "daily_review_count": daily_review_count,
                "xp_results": xp_results, "weekly_habits": {"focus_progress": habits.focus_progress,
                "focus_target": habits.focus_target, "diet_progress": habits.diet_progress},
                "avg_hp": self.get_weekly_hp_average()}
    
    def get_state_summary(self) -> Dict[str, Any]:
        state = self._load_state()
        self._ensure_today()
        today = state.today
        return {"daily_review_streak": state.daily_review_streak_count,
                "morning_completed": today.morning_completed, "evening_completed": today.evening_completed,
                "night_completed": today.night_completed,
                "weekly_review_completed_this_week": self.was_weekly_review_completed_this_week(),
                "presence_awarded_today": self.was_presence_awarded_today(),
                "daily_reviews_last_7_days": self.get_daily_review_count_last_7_days(),
                "perfect_day_count": state.perfect_day_count, "perfect_day_streak": state.perfect_day_streak}


# =============================================================================
# SINGLETON
# =============================================================================

_manager: Optional[TimerhythmManager] = None


def get_timerhythm_manager(data_dir: Optional[Path] = None) -> TimerhythmManager:
    global _manager
    if _manager is None:
        _manager = TimerhythmManager(data_dir)
    return _manager


def _get_manager(kernel: Any) -> TimerhythmManager:
    if hasattr(kernel, 'timerhythm_manager'):
        return kernel.timerhythm_manager
    data_dir = None
    if hasattr(kernel, 'config') and hasattr(kernel.config, 'data_dir'):
        data_dir = kernel.config.data_dir
    return get_timerhythm_manager(data_dir)


# =============================================================================
# COMMAND RESPONSE
# =============================================================================

try:
    from .command_types import CommandResponse
except ImportError:
    from dataclasses import dataclass as _dc
    @_dc
    class CommandResponse:
        ok: bool = True
        command: str = ""
        summary: str = ""
        data: Dict[str, Any] = None
        type: str = "syscommand"
        error_code: Optional[str] = None
        error_message: Optional[str] = None
        def __post_init__(self):
            if self.data is None:
                self.data = {}


def _base_response(cmd_name: str, summary: str, extra: Optional[Dict[str, Any]] = None) -> CommandResponse:
    return CommandResponse(ok=True, command=cmd_name, summary=summary, data=extra or {}, type="syscommand")


def _readiness_emoji(tier: str) -> str:
    return {"Green": "🟢", "Yellow": "🟡", "Red": "🔴"}.get(tier, "⚪")


# =============================================================================
# WIZARD OUTPUT BUILDERS
# =============================================================================

def _build_morning_initial_prompt() -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    current_time = datetime.now().strftime("%I:%M %p").lstrip("0")
    return f"""╔══ Daily Review — Morning ══╗
Date: {today} · {current_time}

Sleep last night (0-100):
> _"""


def _build_morning_context_display(manager: TimerhythmManager, kernel: Any, sleep: int) -> str:
    today = manager._get_today_str()
    current_time = manager._get_current_time_str()
    readiness_info = manager.compute_morning_readiness(sleep)
    hp = readiness_info["hp"]
    tier = readiness_info["readiness"]
    emoji = _readiness_emoji(tier)
    schedule = manager.get_today_schedule()
    
    lines = [f"╔══ Daily Review — Morning ══╗", f"Date: {today} · {current_time}", "",
             f"Health: {hp}", f"Readiness: {emoji} {tier}", "Honor where you are. Steady progress counts.", ""]
    if schedule:
        lines.append("Schedule today:")
        for item in schedule:
            lines.append(f"• {item}")
        lines.append("")
    lines.extend(["What is your goal today?", "> _"])
    return "\n".join(lines)


def _build_morning_completion(manager: TimerhythmManager, kernel: Any, result: Dict[str, Any],
                              sleep: int, goal: str, presence_awarded: bool) -> str:
    today = manager._get_today_str()
    current_time = manager._get_current_time_str()
    readiness_info = result["readiness"]
    hp, tier = readiness_info["hp"], readiness_info["readiness"]
    emoji = _readiness_emoji(tier)
    schedule = manager.get_today_schedule()
    
    lines = [f"╔══ Daily Review — Morning ══╗", f"Date: {today} · {current_time}", "",
             f"Health: {hp}", f"Readiness: {emoji} {tier}", "Honor where you are. Steady progress counts.", ""]
    if schedule:
        lines.append("Schedule today:")
        for item in schedule:
            lines.append(f"• {item}")
        lines.append("")
    lines.extend([f"Goal: {goal}", "", "Status:", "  Morning: ✓", "  Evening: ✗", "  Night: ✗", "", "XP Earned:"])
    if presence_awarded:
        lines.append("  Presence: +10 XP")
    if result["xp_awarded"] > 0:
        lines.append(f"  Daily Review: +{result['xp_awarded']} XP")
    total = result["xp_awarded"] + (10 if presence_awarded else 0)
    if total > 0:
        lines.append(f"  Total: +{total} XP")
    lines.extend(["", f"Streak: {result['streak']} days", "", "Complete Evening check-in later to log your energy."])
    return "\n".join(lines)


def _build_evening_prompt() -> str:
    return """╔══ Evening Check-in ══╗

Energy right now (1-5):
> _"""


def _build_evening_completion(energy: int) -> str:
    return f"""╔══ Evening Check-in ══╗

Energy: {energy}

✓ Logged.

Complete Night Review later to close your day."""


def _build_night_form(manager: TimerhythmManager, kernel: Any, wizard: DailyReviewWizardSession,
                      current_prompt: Optional[str] = None, show_goal: bool = False, 
                      show_tomorrow_schedule: bool = False, show_schedule_preview: bool = False) -> str:
    today = manager._get_today_str()
    current_time = manager._get_current_time_str()
    state = manager._load_state()
    morning_goal = state.today.goal
    
    lines = [f"╔══ Daily Review — Night ══╗", f"Date: {today} · {current_time}"]
    if show_goal and morning_goal:
        lines.append("")
        lines.append(f"Today's goal: {morning_goal}")
    
    if show_tomorrow_schedule:
        tomorrow_schedule = manager.get_tomorrow_schedule()
        lines.append("")
        if tomorrow_schedule:
            lines.append("Tomorrow's schedule:")
            for item in tomorrow_schedule:
                lines.append(f"  • {item}")
        else:
            lines.append("Tomorrow's schedule: (none set)")
    
    if show_schedule_preview and wizard.schedule_items:
        lines.append("")
        lines.append("Adding to tomorrow's schedule:")
        for item in wizard.schedule_items:
            lines.append(f"  • {item}")
    
    lines.append("")
    
    if current_prompt:
        lines.append(current_prompt)
        lines.append("> _")
    
    return "\n".join(lines)


def _build_night_completion(manager: TimerhythmManager, kernel: Any, result: Dict[str, Any],
                            wizard: DailyReviewWizardSession, presence_awarded: bool) -> str:
    today = manager._get_today_str()
    current_time = manager._get_current_time_str()
    readiness_info = result.get("readiness", {})
    hp = readiness_info.get("hp")
    tier = readiness_info.get("readiness", "Unknown")
    emoji = _readiness_emoji(tier)
    state = manager._load_state()
    morning_goal = state.today.goal
    
    lines = [f"╔══ Daily Review — Night ══╗", f"Date: {today} · {current_time}"]
    if hp is not None:
        lines.extend(["", f"Health: {hp}", f"Readiness: {emoji} {tier}"])
    if morning_goal:
        lines.append(f"Today's goal was: {morning_goal}")
    lines.extend(["", "Reflection (short answers are enough):", "",
                  "What did you do today?", f"> {wizard.what_did_you_do or '(not set)'}", "",
                  "Did you complete your goal today?", f"> {wizard.goal_progress or '(not set)'}", "",
                  "One word to describe your day:", f"> {wizard.one_word or '(not set)'}", "",
                  "One small adjustment you will make:", f"> {wizard.adjustment or '(skipped)'}", "",
                  "One win (small counts):", f"> {wizard.win or '(not set)'}", "",
                  "Did you eat today?", f"> {'yes' if wizard.diet_ate else 'no'}", "",
                  "Status:",
                  f"  Morning: {'✓' if state.today.morning_completed else '✗'}",
                  f"  Evening: {'✓' if state.today.evening_completed else '✗'}",
                  "  Night: ✓", "", "XP Earned:"])
    if presence_awarded:
        lines.append("  Presence: +10 XP")
    if result["xp_awarded"] > 0:
        lines.append(f"  Daily Review: +{result['xp_awarded']} XP")
    total = result["xp_awarded"] + (10 if presence_awarded else 0)
    if total > 0:
        lines.append(f"  Total: +{total} XP")
    lines.extend(["", f"Streak: {result['streak']} days"])
    if result.get("became_perfect_day"):
        lines.append(f"🌟 Perfect day! (Total: {result['perfect_day_count']})")
    habits = result.get("weekly_habits", {})
    if habits:
        focus = habits.get('focus_progress', 0)
        focus_str = str(int(focus)) if focus == int(focus) else f"{focus:.1f}"
        lines.extend(["", "Weekly Progress:",
                      f"  Focus: {focus_str}/{habits.get('focus_target', 7)}",
                      f"  Diet: {habits.get('diet_progress', 0)}/7"])
    lines.extend(["", "Day closed. Rest well."])
    return "\n".join(lines)


# =============================================================================
# WIZARD INPUT PROCESSOR
# =============================================================================

def process_daily_review_wizard_input(session_id: str, user_input: str, kernel: Any) -> Optional[CommandResponse]:
    wizard = get_daily_review_wizard_session(session_id)
    if not wizard:
        return None
    
    manager = _get_manager(kernel)
    steps = get_wizard_steps(wizard.phase)
    user_input = user_input.strip()
    
    current_step = steps[wizard.step] if wizard.step < len(steps) else None
    if not current_step:
        clear_daily_review_wizard_session(session_id)
        return None
    
    # Handle skip for optional fields
    if not current_step["required"] and user_input.lower() in ("skip", "s", "-", ""):
        user_input = None
    
    # Parse input
    field_name = current_step["field"]
    field_type = current_step.get("type", "str")
    parsed_value = None
    
    if user_input is not None:
        if field_type == "int":
            try:
                parsed_value = int(user_input)
            except ValueError:
                return _base_response("daily-review", f"Please enter a number.\n\n{current_step['prompt']}",
                                      {"status": "wizard_active", "phase": wizard.phase, "step": wizard.step, "error": "invalid_int"})
        elif field_type == "bool":
            if user_input.lower() in ("yes", "y", "true", "1"):
                parsed_value = True
            elif user_input.lower() in ("no", "n", "false", "0"):
                parsed_value = False
            else:
                return _base_response("daily-review", f"Please enter yes or no.\n\n{current_step['prompt']}",
                                      {"status": "wizard_active", "phase": wizard.phase, "step": wizard.step, "error": "invalid_bool"})
        elif field_type == "schedule_list":
            # Parse comma-separated list
            parsed_value = [item.strip() for item in user_input.split(",") if item.strip()]
            if not parsed_value:
                return _base_response("daily-review", f"Please enter at least one item.\n\n{current_step['prompt']}",
                                      {"status": "wizard_active", "phase": wizard.phase, "step": wizard.step, "error": "empty_list"})
        else:
            parsed_value = user_input
    
    setattr(wizard, field_name, parsed_value)
    
    # Handle schedule confirmation - save to tomorrow's schedule
    if field_name == "schedule_confirm" and parsed_value == True and wizard.schedule_items:
        manager.add_to_tomorrow_schedule(wizard.schedule_items)
    
    # Special: show context after sleep in morning
    if wizard.phase == "morning" and field_name == "sleep" and current_step.get("show_context_after"):
        wizard.step += 1
        return _base_response("daily-review", _build_morning_context_display(manager, kernel, parsed_value),
                              {"status": "wizard_active", "phase": wizard.phase, "step": wizard.step, "field": "goal"})
    
    wizard.step += 1
    
    # Skip conditional steps if condition not met
    while wizard.step < len(steps):
        next_step = steps[wizard.step]
        conditional_on = next_step.get("conditional_on")
        if conditional_on:
            condition_value = getattr(wizard, conditional_on, None)
            if not condition_value:
                wizard.step += 1
                continue
        break
    
    # Check if complete
    if wizard.step >= len(steps):
        return _finalize_wizard(session_id, wizard, manager, kernel)
    
    # Show next prompt
    next_step = steps[wizard.step]
    if wizard.phase == "night":
        show_goal = next_step.get("show_goal", False)
        show_tomorrow_schedule = next_step.get("show_tomorrow_schedule", False)
        show_schedule_preview = next_step.get("show_schedule_preview", False)
        output = _build_night_form(manager, kernel, wizard, next_step["prompt"], 
                                   show_goal=show_goal, show_tomorrow_schedule=show_tomorrow_schedule,
                                   show_schedule_preview=show_schedule_preview)
    else:
        output = next_step["prompt"]
    return _base_response("daily-review", output,
                          {"status": "wizard_active", "phase": wizard.phase, "step": wizard.step, "field": next_step["field"]})


def _finalize_wizard(session_id: str, wizard: DailyReviewWizardSession,
                     manager: TimerhythmManager, kernel: Any) -> CommandResponse:
    presence_result = manager.check_and_award_presence_xp(kernel)
    presence_awarded = presence_result is not None
    
    if wizard.phase == "morning":
        result = manager.complete_morning_phase(kernel, wizard.sleep, wizard.goal)
        output = _build_morning_completion(manager, kernel, result, wizard.sleep, wizard.goal, presence_awarded)
    elif wizard.phase == "evening":
        result = manager.complete_evening_phase(kernel, wizard.energy)
        output = _build_evening_completion(wizard.energy)
    else:
        result = manager.complete_night_phase(kernel, wizard.what_did_you_do, wizard.goal_progress,
                                              wizard.one_word, wizard.adjustment, wizard.win, wizard.diet_ate)
        output = _build_night_completion(manager, kernel, result, wizard, presence_awarded)
    
    clear_daily_review_wizard_session(session_id)
    return _base_response("daily-review", output, {"status": "complete", "phase": wizard.phase, "result": result})


# =============================================================================
# COMMAND HANDLERS
# =============================================================================

def _parse_phase_arg(args: Any) -> Optional[Phase]:
    action = None
    if isinstance(args, dict):
        action = args.get("phase") or args.get("action")
        positional = args.get("_", [])
        if not action and positional:
            action = str(positional[0]).lower()
    elif isinstance(args, str) and args.strip():
        action = args.strip().lower()
    if action in ("morning", "evening", "night"):
        return action
    return None


def handle_daily_review(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """Three-phase daily review: morning (sleep→context→goal), evening (energy), night (reflection+habits)."""
    manager = _get_manager(kernel)
    today = manager._get_today_str()
    current_time = manager._get_current_time_str()
    phase = _parse_phase_arg(args)
    
    if phase is None and has_active_daily_review_wizard(session_id):
        clear_daily_review_wizard_session(session_id)
    
    if phase is not None:
        if manager.is_phase_completed(phase):
            status = manager.get_phase_status()
            lines = [f"╔══ Daily Review — {phase.title()} ══╗", f"Date: {today} · {current_time}", "",
                     f"✓ {phase.title()} already completed today.", "", "Status:",
                     f"  Morning: {'✓' if status['morning_completed'] else '✗'}",
                     f"  Evening: {'✓' if status['evening_completed'] else '✗'}",
                     f"  Night: {'✓' if status['night_completed'] else '✗'}",
                     "", f"Streak: {manager.get_current_streak()} days"]
            if not status["morning_completed"]:
                lines.append("\nRun #daily-review morning")
            elif not status["evening_completed"]:
                lines.append("\nRun #daily-review evening")
            elif not status["night_completed"]:
                lines.append("\nRun #daily-review night")
            return _base_response(cmd_name, "\n".join(lines), {"status": "already_complete", "phase": phase})
        
        clear_daily_review_wizard_session(session_id)
        wizard = create_daily_review_wizard_session(session_id, phase)
        steps = get_wizard_steps(phase)
        first_step = steps[0]
        
        if phase == "morning":
            output = _build_morning_initial_prompt()
        elif phase == "evening":
            output = _build_evening_prompt()
        else:
            show_goal = first_step.get("show_goal", False)
            show_tomorrow_schedule = first_step.get("show_tomorrow_schedule", False)
            output = _build_night_form(manager, kernel, wizard, first_step["prompt"], 
                                       show_goal=show_goal, show_tomorrow_schedule=show_tomorrow_schedule)
        
        return _base_response(cmd_name, output, {"status": "wizard_active", "phase": phase, "step": 0, "field": first_step["field"]})
    
    # Show status
    status = manager.get_phase_status()
    streak = manager.get_current_streak()
    perfect_stats = manager.get_perfect_day_stats()
    
    lines = [f"╔══ Daily Review ══╗", f"Date: {today} · {current_time}", "", "Status:",
             f"  Morning: {'✓' if status['morning_completed'] else '✗'}",
             f"  Evening: {'✓' if status['evening_completed'] else '✗'}",
             f"  Night: {'✓' if status['night_completed'] else '✗'}", ""]
    
    presence_pending = not manager.was_presence_awarded_today()
    if status["phases_done"] == 0:
        lines.extend(["XP Available:"])
        if presence_pending:
            lines.append("  Presence: +10 XP")
        lines.extend(["  Morning: +15 XP", "  Evening: +0 XP", "  Night: +10 XP"])
    elif status["phases_done"] < 3:
        lines.append("XP Available:")
        if presence_pending:
            lines.append("  Presence: +10 XP")
        lines.append("  Next phase: +10 XP" if status["phases_done"] == 1 else "  Final phase: +5 XP")
    else:
        lines.append("✓ All phases completed!")
    
    lines.extend(["", f"Streak: {streak} days"])
    if perfect_stats["perfect_day_count"] > 0:
        lines.append(f"Perfect days: {perfect_stats['perfect_day_count']}")
    
    if not status["morning_completed"]:
        lines.extend(["", "Run: #daily-review morning"])
    elif not status["evening_completed"]:
        lines.extend(["", "Run: #daily-review evening"])
    elif not status["night_completed"]:
        lines.extend(["", "Run: #daily-review night"])
    
    return _base_response(cmd_name, "\n".join(lines), {"date": today, **status, "streak": streak})


def handle_weekly_review(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """Weekly review with macro goals and habit tracking."""
    manager = _get_manager(kernel)
    week_id = manager._get_week_id()
    today = datetime.now()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    date_range = f"{week_start.strftime('%Y-%m-%d')} to {week_end.strftime('%Y-%m-%d')}"
    
    action = None
    if isinstance(args, dict):
        action = args.get("action")
        positional = args.get("_", [])
        if not action and positional:
            action = str(positional[0]).lower()
    elif isinstance(args, str) and args.strip():
        action = args.strip().lower()
    
    if action == "done":
        result = manager.complete_weekly_review(kernel)
        if result.get("already_completed"):
            return _base_response(cmd_name, f"✓ Weekly review already completed for {week_id}.\n\nCome back next week!",
                                  {"status": "already_complete", "week_id": week_id})
        
        lines = [f"╔══ Weekly Review Complete ══╗", f"Week: {week_id}", ""]
        habits = result.get("weekly_habits", {})
        if habits:
            lines.extend(["Habit Progress:",
                          f"  Focus: {habits.get('focus_progress', 0):.1f}/{habits.get('focus_target', 7)}",
                          f"  Diet: {habits.get('diet_progress', 0)}/7", ""])
        avg_hp = result.get("avg_hp")
        if avg_hp is not None:
            lines.extend([f"Average HP: {avg_hp:.0f}", ""])
        lines.append("Macro Goals:")
        for goal in result["goals"]:
            mark = "✅" if goal["met"] else "❌"
            xp_str = f" => +{goal['xp']} XP" if goal["met"] else ""
            lines.append(f"  {mark} {goal['goal']}: {goal['actual']}/{goal['target']}{xp_str}")
        lines.extend(["", f"Total XP Earned: +{result['total_xp']} XP", "", "Great week! Keep up the momentum."])
        return _base_response(cmd_name, "\n".join(lines), {"status": "complete", "week_id": week_id, "goals": result["goals"], "total_xp": result["total_xp"]})
    
    # Show status
    already_done = manager.was_weekly_review_completed_this_week()
    quest_completions = manager.get_quest_completions_last_7_days(kernel)
    daily_review_count = manager.get_daily_review_count_last_7_days()
    goals = manager.evaluate_weekly_macro_goals(kernel, quest_completions, daily_review_count)
    habits = manager._ensure_weekly_habits()
    avg_hp = manager.get_weekly_hp_average()
    
    lines = [f"╔══ Weekly Review ══╗", f"Week: {week_id} ({date_range})", ""]
    if avg_hp is not None:
        lines.extend([f"Average HP: {avg_hp:.0f}", ""])
    lines.extend(["Habit Progress:",
                  f"  Focus: {habits.focus_progress:.1f}/{habits.focus_target}",
                  f"  Diet: {habits.diet_progress}/7", "",
                  "Quest Progress (last 7 days):",
                  f"  Quests completed: {sum(quest_completions.values())}"])
    if quest_completions:
        for mod, count in sorted(quest_completions.items()):
            lines.append(f"    • {mod}: {count}")
    lines.extend(["", "Macro Goals:"])
    potential_xp = 0
    for goal in goals:
        mark = "✅" if goal["met"] else "❌"
        xp_str = f" => +{goal['xp']} XP" if goal["met"] else ""
        lines.append(f"  {mark} {goal['goal']} ({goal['actual']}/{goal['target']}){xp_str}")
        if goal["met"]:
            potential_xp += goal["xp"]
    lines.append("")
    if already_done:
        lines.extend([f"✓ Weekly review already completed for {week_id}.", "", "Come back next week!"])
    else:
        lines.extend([f"Potential XP: +{potential_xp} XP", "", "When ready, run: #weekly-review done"])
    return _base_response(cmd_name, "\n".join(lines), {"week_id": week_id, "status": "already_complete" if already_done else "pending", "goals": goals})


def handle_time_clear(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """DEV: Clear all timerhythm data."""
    manager = _get_manager(kernel)
    confirm = False
    if isinstance(args, dict):
        positional = args.get("_", [])
        if positional and str(positional[0]).lower() == "confirm":
            confirm = True
    elif isinstance(args, str) and args.strip().lower() == "confirm":
        confirm = True
    
    if not confirm:
        state = manager._load_state()
        log = manager._load_log()
        lines = ["╔══ Time Clear (Preview) ══╗", "", "This will clear ALL timerhythm data:", "",
                 f"  • Daily review streak: {state.daily_review_streak_count} days → 0",
                 f"  • Perfect day count: {state.perfect_day_count} → 0",
                 f"  • Last daily review: {state.last_daily_review_date or 'none'} → none",
                 f"  • Last weekly review: {state.last_weekly_review_week_id or 'none'} → none",
                 f"  • Weekly habits: focus={state.weekly_habits.focus_progress:.1f}, diet={state.weekly_habits.diet_progress} → 0",
                 f"  • Log entries: {len(log)} → 0", "", "⚠️  This cannot be undone!", "", "To confirm, run: #time-clear confirm"]
        return _base_response(cmd_name, "\n".join(lines), {"status": "preview", "streak": state.daily_review_streak_count, "log_count": len(log)})
    
    manager._state = TimerhythmState()
    manager._save_state()
    manager._log = []
    manager._save_log()
    clear_daily_review_wizard_session(session_id)
    
    lines = ["╔══ Time Clear ══╗", "", "✓ All timerhythm data cleared.", "", "Reset:",
             "  • Daily review streak: 0", "  • Perfect day count: 0", "  • Weekly habits: cleared",
             "  • Weekly review: cleared", "  • Log entries: 0", "", "Ready for fresh start!"]
    return _base_response(cmd_name, "\n".join(lines), {"status": "cleared"})


# =============================================================================
# HANDLER REGISTRY & EXPORTS
# =============================================================================

def get_time_rhythm_handlers() -> Dict[str, Any]:
    return {"handle_daily_review": handle_daily_review, "handle_weekly_review": handle_weekly_review, "handle_time_clear": handle_time_clear}


__all__ = [
    "TimerhythmManager", "get_timerhythm_manager",
    "handle_daily_review", "handle_weekly_review", "handle_time_clear", "get_time_rhythm_handlers",
    "has_active_daily_review_wizard", "get_daily_review_wizard_session", "process_daily_review_wizard_input", "clear_daily_review_wizard_session",
    "derive_mood", "derive_stress", "compute_hp", "compute_readiness",
    "TimerhythmState", "DailyState", "WeeklyHabits", "WeeklySchedule", "DailyReviewWizardSession",
]
