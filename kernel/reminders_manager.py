# kernel/reminders_manager.py
"""
NovaOS Reminders Manager — v2.0.0

Complete reminders system with:
- One-time and recurring reminders (daily/weekly/monthly)
- Windowed reminders (e.g., Sundays 5pm-11:59pm catch window)
- Pin/unpin, snooze, done/complete
- List/due/today views

Data model stored in data/reminders.json
Default timezone: America/Los_Angeles
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Literal
from zoneinfo import ZoneInfo

# -------------------------------------------------------------
# Constants
# -------------------------------------------------------------

DEFAULT_TIMEZONE = "America/Los_Angeles"
REMINDER_STATUS = Literal["active", "done", "archived"]
PRIORITY_LEVELS = Literal["low", "normal", "high"]
REPEAT_TYPES = Literal["daily", "weekly", "monthly"]

WEEKDAY_MAP = {
    "MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6,
    "MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6,
    "MONDAY": 0, "TUESDAY": 1, "WEDNESDAY": 2, "THURSDAY": 3,
    "FRIDAY": 4, "SATURDAY": 5, "SUNDAY": 6,
}

WEEKDAY_ABBREV = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]


# -------------------------------------------------------------
# Data Models
# -------------------------------------------------------------

@dataclass
class RepeatWindow:
    """Time window for windowed reminders."""
    start: str  # HH:MM format
    end: str    # HH:MM format
    
    def to_dict(self) -> Dict[str, str]:
        return {"start": self.start, "end": self.end}
    
    @classmethod
    def from_dict(cls, data: Dict[str, str]) -> "RepeatWindow":
        return cls(start=data.get("start", "00:00"), end=data.get("end", "23:59"))


@dataclass
class RepeatConfig:
    """Recurrence configuration."""
    type: REPEAT_TYPES  # daily, weekly, monthly
    interval: int = 1
    by_day: List[str] = field(default_factory=list)  # ["MO", "TU", ...] for weekly
    by_month_day: List[int] = field(default_factory=list)  # [1, 15] for monthly
    window: Optional[RepeatWindow] = None  # Optional catch window
    
    def to_dict(self) -> Dict[str, Any]:
        result = {
            "type": self.type,
            "interval": self.interval,
            "by_day": self.by_day,
            "by_month_day": self.by_month_day,
        }
        if self.window:
            result["window"] = self.window.to_dict()
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RepeatConfig":
        window = None
        if data.get("window"):
            window = RepeatWindow.from_dict(data["window"])
        return cls(
            type=data.get("type", "daily"),
            interval=int(data.get("interval", 1)),
            by_day=data.get("by_day", []),
            by_month_day=data.get("by_month_day", []),
            window=window,
        )


@dataclass
class Reminder:
    """Reminder data model."""
    id: str
    title: str
    notes: Optional[str] = None
    status: REMINDER_STATUS = "active"
    priority: PRIORITY_LEVELS = "normal"
    pinned: bool = False
    
    due_at: str = ""  # ISO datetime with tz offset
    timezone: str = DEFAULT_TIMEZONE
    
    repeat: Optional[RepeatConfig] = None
    
    snoozed_until: Optional[str] = None  # ISO datetime or null
    created_at: str = ""
    updated_at: str = ""
    last_fired_at: Optional[str] = None
    missed_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        result = {
            "id": self.id,
            "title": self.title,
            "notes": self.notes,
            "status": self.status,
            "priority": self.priority,
            "pinned": self.pinned,
            "due_at": self.due_at,
            "timezone": self.timezone,
            "repeat": self.repeat.to_dict() if self.repeat else None,
            "snoozed_until": self.snoozed_until,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_fired_at": self.last_fired_at,
            "missed_count": self.missed_count,
        }
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Reminder":
        repeat = None
        if data.get("repeat"):
            repeat = RepeatConfig.from_dict(data["repeat"])
        return cls(
            id=data.get("id", ""),
            title=data.get("title", ""),
            notes=data.get("notes"),
            status=data.get("status", "active"),
            priority=data.get("priority", "normal"),
            pinned=data.get("pinned", False),
            due_at=data.get("due_at", ""),
            timezone=data.get("timezone", DEFAULT_TIMEZONE),
            repeat=repeat,
            snoozed_until=data.get("snoozed_until"),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            last_fired_at=data.get("last_fired_at"),
            missed_count=data.get("missed_count", 0),
        )
    
    @property
    def is_recurring(self) -> bool:
        return self.repeat is not None
    
    @property
    def has_window(self) -> bool:
        return self.repeat is not None and self.repeat.window is not None


# -------------------------------------------------------------
# Reminders Manager
# -------------------------------------------------------------

class RemindersManager:
    """
    v2.0.0: Complete reminders system with windowed reminders,
    recurrence, snooze, pin, and proper timezone handling.
    """
    
    DATA_VERSION = 1
    
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.file = self.data_dir / "reminders.json"
        self._items: Dict[str, Reminder] = {}
        self._next_id: int = 1
        self._loaded = False
    
    # =========================================================================
    # PERSISTENCE
    # =========================================================================
    
    def _load(self) -> None:
        """Load reminders from disk."""
        if self._loaded:
            return
        
        if not self.file.exists():
            self._items = {}
            self._next_id = 1
            self._loaded = True
            # Create default weekly review reminder
            self._ensure_default_reminder()
            return
        
        try:
            with open(self.file, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            version = data.get("version", 0)
            
            if version < self.DATA_VERSION:
                # Migrate from legacy format
                self._migrate_legacy(data)
            else:
                # v2 format
                items_data = data.get("items", [])
                for item_data in items_data:
                    try:
                        reminder = Reminder.from_dict(item_data)
                        self._items[reminder.id] = reminder
                        # Track max ID
                        if reminder.id.startswith("rem_"):
                            try:
                                num = int(reminder.id.split("_")[1])
                                if num >= self._next_id:
                                    self._next_id = num + 1
                            except (IndexError, ValueError):
                                pass
                    except Exception as e:
                        print(f"[RemindersManager] Skip invalid item: {e}", flush=True)
            
            self._loaded = True
            self._ensure_default_reminder()
            
        except Exception as e:
            print(f"[RemindersManager] Load error: {e}", flush=True)
            self._items = {}
            self._next_id = 1
            self._loaded = True
            self._ensure_default_reminder()
    
    def _migrate_legacy(self, data: Dict[str, Any]) -> None:
        """Migrate from legacy format (dict keyed by ID or list)."""
        self._items = {}
        self._next_id = 1
        
        # Handle dict format (old RemindersManager)
        if isinstance(data, dict) and "items" not in data and "version" not in data:
            for rid, rdata in data.items():
                if isinstance(rdata, dict):
                    # Convert legacy fields
                    reminder = Reminder(
                        id=rid if rid.startswith("rem_") else f"rem_{self._next_id:03d}",
                        title=rdata.get("title", rdata.get("msg", "")),
                        status="active" if rdata.get("status", "pending") == "pending" else "done",
                        due_at=rdata.get("when", rdata.get("due_at", "")),
                        timezone=rdata.get("timezone", DEFAULT_TIMEZONE),
                        created_at=rdata.get("created_at", ""),
                        updated_at=datetime.now(ZoneInfo(DEFAULT_TIMEZONE)).isoformat(),
                    )
                    # Handle legacy repeat field
                    legacy_repeat = rdata.get("repeat")
                    if legacy_repeat and legacy_repeat in ("daily", "weekly", "monthly"):
                        reminder.repeat = RepeatConfig(type=legacy_repeat)
                    
                    self._items[reminder.id] = reminder
                    if reminder.id.startswith("rem_"):
                        try:
                            num = int(reminder.id.split("_")[1])
                            if num >= self._next_id:
                                self._next_id = num + 1
                        except (IndexError, ValueError):
                            pass
        
        self._save()
    
    def _save(self) -> None:
        """Save reminders to disk."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        data = {
            "version": self.DATA_VERSION,
            "items": [r.to_dict() for r in self._items.values()]
        }
        
        with open(self.file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def _ensure_default_reminder(self) -> None:
        """Create the default Weekly Review reminder if not present."""
        # Check if weekly review already exists
        for r in self._items.values():
            if "weekly review" in r.title.lower():
                return
        
        # Create default weekly review reminder
        now = datetime.now(ZoneInfo(DEFAULT_TIMEZONE))
        next_sunday = self._next_weekday(now, 6)  # Sunday = 6
        due_at = next_sunday.replace(hour=17, minute=0, second=0, microsecond=0)
        
        reminder = Reminder(
            id=self._generate_id(),
            title="Weekly Review",
            notes="Run #weekly-review",
            status="active",
            priority="normal",
            pinned=True,
            due_at=due_at.isoformat(),
            timezone=DEFAULT_TIMEZONE,
            repeat=RepeatConfig(
                type="weekly",
                interval=1,
                by_day=["SU"],
                window=RepeatWindow(start="17:00", end="23:59"),
            ),
            created_at=now.isoformat(),
            updated_at=now.isoformat(),
        )
        
        self._items[reminder.id] = reminder
        self._save()
        print(f"[RemindersManager] Created default Weekly Review reminder: {reminder.id}", flush=True)
    
    # =========================================================================
    # ID GENERATION
    # =========================================================================
    
    def _generate_id(self) -> str:
        """Generate a stable, collision-free ID."""
        rid = f"rem_{self._next_id:03d}"
        self._next_id += 1
        return rid
    
    # =========================================================================
    # TIME HELPERS
    # =========================================================================
    
    def _get_tz(self, tz_name: str = DEFAULT_TIMEZONE) -> ZoneInfo:
        """Get timezone object, fallback to default."""
        try:
            return ZoneInfo(tz_name)
        except Exception:
            return ZoneInfo(DEFAULT_TIMEZONE)
    
    def _now(self, tz_name: str = DEFAULT_TIMEZONE) -> datetime:
        """Get current time in specified timezone."""
        return datetime.now(self._get_tz(tz_name))
    
    def _parse_datetime(self, dt_str: str, tz_name: str = DEFAULT_TIMEZONE) -> Optional[datetime]:
        """Parse ISO datetime string to datetime object."""
        if not dt_str:
            return None
        try:
            # Handle trailing Z
            if dt_str.endswith("Z"):
                dt_str = dt_str[:-1] + "+00:00"
            dt = datetime.fromisoformat(dt_str)
            # If naive, assume specified timezone
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=self._get_tz(tz_name))
            return dt
        except Exception:
            return None
    
    def _next_weekday(self, dt: datetime, weekday: int) -> datetime:
        """Get next occurrence of weekday (0=Monday, 6=Sunday)."""
        days_ahead = weekday - dt.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        return dt + timedelta(days=days_ahead)
    
    def _parse_due_input(self, due_str: str, tz_name: str = DEFAULT_TIMEZONE) -> str:
        """
        Parse flexible due time input to ISO string.
        
        Supports:
        - ISO format: 2025-12-15T17:00:00
        - Date + time: 2025-12-15 17:00
        - Relative: tomorrow, sunday, etc.
        - Time only: 17:00, 5pm
        """
        due_str = due_str.strip()
        tz = self._get_tz(tz_name)
        now = datetime.now(tz)
        
        # Try ISO format first
        dt = self._parse_datetime(due_str, tz_name)
        if dt:
            return dt.isoformat()
        
        # Try date + time format: YYYY-MM-DD HH:MM
        match = re.match(r"(\d{4}-\d{2}-\d{2})\s+(\d{1,2}):(\d{2})", due_str)
        if match:
            try:
                date_part = match.group(1)
                hour = int(match.group(2))
                minute = int(match.group(3))
                dt = datetime.fromisoformat(date_part).replace(
                    hour=hour, minute=minute, second=0, microsecond=0, tzinfo=tz
                )
                return dt.isoformat()
            except Exception:
                pass
        
        # Relative dates
        lower = due_str.lower()
        
        if lower == "today":
            dt = now.replace(hour=23, minute=59, second=0, microsecond=0)
            return dt.isoformat()
        
        if lower == "tomorrow":
            dt = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
            return dt.isoformat()
        
        # Weekday names
        for name, weekday in WEEKDAY_MAP.items():
            if lower == name.lower():
                dt = self._next_weekday(now, weekday).replace(
                    hour=9, minute=0, second=0, microsecond=0
                )
                return dt.isoformat()
        
        # Time only (assume today or tomorrow if past)
        time_match = re.match(r"(\d{1,2}):(\d{2})\s*(am|pm)?", lower)
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2))
            ampm = time_match.group(3)
            
            if ampm == "pm" and hour < 12:
                hour += 12
            elif ampm == "am" and hour == 12:
                hour = 0
            
            dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if dt <= now:
                dt += timedelta(days=1)
            return dt.isoformat()
        
        # 12-hour format without colon: 5pm, 9am
        time_match = re.match(r"(\d{1,2})(am|pm)", lower)
        if time_match:
            hour = int(time_match.group(1))
            ampm = time_match.group(2)
            
            if ampm == "pm" and hour < 12:
                hour += 12
            elif ampm == "am" and hour == 12:
                hour = 0
            
            dt = now.replace(hour=hour, minute=0, second=0, microsecond=0)
            if dt <= now:
                dt += timedelta(days=1)
            return dt.isoformat()
        
        # Fallback: try to parse as-is
        try:
            dt = datetime.fromisoformat(due_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=tz)
            return dt.isoformat()
        except Exception:
            # Last resort: 1 hour from now
            return (now + timedelta(hours=1)).isoformat()
    
    # =========================================================================
    # SCHEDULING LOGIC
    # =========================================================================
    
    def compute_effective_due(self, reminder: Reminder) -> Optional[datetime]:
        """
        Get effective due time considering snooze.
        Returns snoozed_until if set, else due_at.
        """
        if reminder.snoozed_until:
            return self._parse_datetime(reminder.snoozed_until, reminder.timezone)
        return self._parse_datetime(reminder.due_at, reminder.timezone)
    
    def is_due_now(self, reminder: Reminder, now: Optional[datetime] = None) -> bool:
        """
        Check if reminder is due now.
        
        For windowed reminders: due if current time is within window.
        For regular reminders: due if current time >= effective_due.
        """
        if reminder.status != "active":
            return False
        
        tz = self._get_tz(reminder.timezone)
        if now is None:
            now = datetime.now(tz)
        else:
            # Ensure now is in correct timezone
            now = now.astimezone(tz)
        
        effective_due = self.compute_effective_due(reminder)
        if not effective_due:
            return False
        
        effective_due = effective_due.astimezone(tz)
        
        # Handle windowed reminders
        if reminder.has_window:
            return self._is_in_window(reminder, now)
        
        # Regular reminder: due if now >= effective_due
        return now >= effective_due
    
    def _is_in_window(self, reminder: Reminder, now: datetime) -> bool:
        """Check if current time is within the reminder's window."""
        if not reminder.repeat or not reminder.repeat.window:
            return False
        
        tz = self._get_tz(reminder.timezone)
        now = now.astimezone(tz)
        
        # Get due_at date
        due_dt = self._parse_datetime(reminder.due_at, reminder.timezone)
        if not due_dt:
            return False
        due_dt = due_dt.astimezone(tz)
        
        # Only check window if we're on or after the due date
        if now.date() < due_dt.date():
            return False
        
        # Check if we're on the right day for weekly reminders
        if reminder.repeat.type == "weekly" and reminder.repeat.by_day:
            current_day = WEEKDAY_ABBREV[now.weekday()]
            if current_day not in reminder.repeat.by_day:
                return False
        
        # Parse window times
        window = reminder.repeat.window
        try:
            start_parts = window.start.split(":")
            end_parts = window.end.split(":")
            window_start = now.replace(
                hour=int(start_parts[0]), minute=int(start_parts[1]),
                second=0, microsecond=0
            )
            window_end = now.replace(
                hour=int(end_parts[0]), minute=int(end_parts[1]),
                second=59, microsecond=999999
            )
        except (ValueError, IndexError):
            return False
        
        # Snoozed? Check if snooze has passed
        if reminder.snoozed_until:
            snoozed = self._parse_datetime(reminder.snoozed_until, reminder.timezone)
            if snoozed and now < snoozed.astimezone(tz):
                return False
        
        return window_start <= now <= window_end
    
    def is_due_today(self, reminder: Reminder, now: Optional[datetime] = None) -> bool:
        """Check if reminder is due today (for list view)."""
        if reminder.status != "active":
            return False
        
        tz = self._get_tz(reminder.timezone)
        if now is None:
            now = datetime.now(tz)
        else:
            now = now.astimezone(tz)
        
        effective_due = self.compute_effective_due(reminder)
        if not effective_due:
            return False
        
        effective_due = effective_due.astimezone(tz)
        return effective_due.date() == now.date()
    
    def is_overdue(self, reminder: Reminder, now: Optional[datetime] = None) -> bool:
        """Check if reminder is overdue (past due and not completed)."""
        if reminder.status != "active":
            return False
        
        tz = self._get_tz(reminder.timezone)
        if now is None:
            now = datetime.now(tz)
        else:
            now = now.astimezone(tz)
        
        effective_due = self.compute_effective_due(reminder)
        if not effective_due:
            return False
        
        effective_due = effective_due.astimezone(tz)
        
        # For windowed reminders, check if window has passed
        if reminder.has_window:
            window = reminder.repeat.window
            try:
                end_parts = window.end.split(":")
                window_end = effective_due.replace(
                    hour=int(end_parts[0]), minute=int(end_parts[1]),
                    second=59, microsecond=999999
                )
                return now > window_end
            except (ValueError, IndexError):
                pass
        
        return now > effective_due
    
    def advance_recurrence(self, reminder: Reminder, now: Optional[datetime] = None) -> None:
        """
        Advance a recurring reminder to its next occurrence.
        Called when completing a recurring reminder.
        """
        if not reminder.repeat:
            return
        
        tz = self._get_tz(reminder.timezone)
        if now is None:
            now = datetime.now(tz)
        else:
            now = now.astimezone(tz)
        
        current_due = self._parse_datetime(reminder.due_at, reminder.timezone)
        if not current_due:
            current_due = now
        current_due = current_due.astimezone(tz)
        
        repeat = reminder.repeat
        interval = repeat.interval
        
        if repeat.type == "daily":
            next_due = current_due + timedelta(days=interval)
        
        elif repeat.type == "weekly":
            if repeat.by_day:
                # Find next occurrence of any specified weekday
                next_due = self._find_next_weekly(current_due, repeat.by_day, interval)
            else:
                next_due = current_due + timedelta(weeks=interval)
        
        elif repeat.type == "monthly":
            if repeat.by_month_day:
                next_due = self._find_next_monthly(current_due, repeat.by_month_day, interval)
            else:
                # Same day next month
                month = current_due.month + interval
                year = current_due.year + (month - 1) // 12
                month = ((month - 1) % 12) + 1
                day = min(current_due.day, 28)  # Safe day for all months
                next_due = current_due.replace(year=year, month=month, day=day)
        else:
            next_due = current_due + timedelta(days=1)
        
        # Apply window start time if windowed
        if repeat.window:
            try:
                start_parts = repeat.window.start.split(":")
                next_due = next_due.replace(
                    hour=int(start_parts[0]), minute=int(start_parts[1]),
                    second=0, microsecond=0
                )
            except (ValueError, IndexError):
                pass
        
        reminder.due_at = next_due.isoformat()
        reminder.snoozed_until = None
        reminder.last_fired_at = now.isoformat()
        reminder.updated_at = now.isoformat()
    
    def _find_next_weekly(self, current: datetime, by_day: List[str], interval: int) -> datetime:
        """Find next occurrence for weekly reminder with specified days."""
        target_weekdays = [WEEKDAY_MAP.get(d.upper(), 0) for d in by_day]
        if not target_weekdays:
            return current + timedelta(weeks=interval)
        
        # Try days in current week first
        current_weekday = current.weekday()
        for wd in sorted(target_weekdays):
            if wd > current_weekday:
                return current + timedelta(days=wd - current_weekday)
        
        # Otherwise, go to next interval week, first target day
        days_to_monday = 7 - current_weekday
        days_to_add = days_to_monday + (interval - 1) * 7 + min(target_weekdays)
        return current + timedelta(days=days_to_add)
    
    def _find_next_monthly(self, current: datetime, by_month_day: List[int], interval: int) -> datetime:
        """Find next occurrence for monthly reminder with specified days."""
        target_days = sorted([d for d in by_month_day if 1 <= d <= 31])
        if not target_days:
            return current.replace(month=current.month + interval)
        
        # Try days in current month first
        for day in target_days:
            if day > current.day:
                try:
                    return current.replace(day=day)
                except ValueError:
                    continue
        
        # Next month
        month = current.month + interval
        year = current.year + (month - 1) // 12
        month = ((month - 1) % 12) + 1
        
        for day in target_days:
            try:
                return current.replace(year=year, month=month, day=day)
            except ValueError:
                continue
        
        return current.replace(year=year, month=month, day=1)
    
    def apply_window_rollover(self, reminder: Reminder, now: Optional[datetime] = None) -> bool:
        """
        Handle missed windows for windowed reminders.
        If window has passed and not completed, increment missed_count
        and advance to next occurrence.
        
        Returns True if rollover occurred.
        """
        if not reminder.has_window or reminder.status != "active":
            return False
        
        tz = self._get_tz(reminder.timezone)
        if now is None:
            now = datetime.now(tz)
        else:
            now = now.astimezone(tz)
        
        due_dt = self._parse_datetime(reminder.due_at, reminder.timezone)
        if not due_dt:
            return False
        due_dt = due_dt.astimezone(tz)
        
        window = reminder.repeat.window
        try:
            end_parts = window.end.split(":")
            window_end = due_dt.replace(
                hour=int(end_parts[0]), minute=int(end_parts[1]),
                second=59, microsecond=999999
            )
        except (ValueError, IndexError):
            return False
        
        if now > window_end:
            # Window has passed
            reminder.missed_count += 1
            self.advance_recurrence(reminder, now)
            return True
        
        return False
    
    # =========================================================================
    # CRUD OPERATIONS
    # =========================================================================
    
    def add(
        self,
        title: str,
        due: str,
        notes: Optional[str] = None,
        priority: PRIORITY_LEVELS = "normal",
        repeat: Optional[Dict[str, Any]] = None,
        window: Optional[Dict[str, str]] = None,
        pinned: bool = False,
        timezone: str = DEFAULT_TIMEZONE,
    ) -> Reminder:
        """Add a new reminder."""
        self._load()
        
        now = self._now(timezone)
        due_at = self._parse_due_input(due, timezone)
        
        # Build repeat config if provided
        repeat_config = None
        if repeat:
            repeat_window = None
            if window:
                repeat_window = RepeatWindow(
                    start=window.get("start", "00:00"),
                    end=window.get("end", "23:59"),
                )
            repeat_config = RepeatConfig(
                type=repeat.get("type", "daily"),
                interval=int(repeat.get("interval", 1)),
                by_day=repeat.get("by_day", []),
                by_month_day=repeat.get("by_month_day", []),
                window=repeat_window,
            )
        
        reminder = Reminder(
            id=self._generate_id(),
            title=title,
            notes=notes,
            status="active",
            priority=priority,
            pinned=pinned,
            due_at=due_at,
            timezone=timezone,
            repeat=repeat_config,
            created_at=now.isoformat(),
            updated_at=now.isoformat(),
        )
        
        self._items[reminder.id] = reminder
        self._save()
        
        return reminder
    
    def get(self, rid: str) -> Optional[Reminder]:
        """Get a reminder by ID."""
        self._load()
        return self._items.get(rid)
    
    def update(self, rid: str, fields: Dict[str, Any]) -> Optional[Reminder]:
        """Update reminder fields."""
        self._load()
        
        reminder = self._items.get(rid)
        if not reminder:
            return None
        
        now = self._now(reminder.timezone)
        
        for key, value in fields.items():
            if key == "repeat" and value is not None:
                if isinstance(value, dict):
                    reminder.repeat = RepeatConfig.from_dict(value)
                elif isinstance(value, RepeatConfig):
                    reminder.repeat = value
            elif key == "due" or key == "due_at":
                reminder.due_at = self._parse_due_input(str(value), reminder.timezone)
            elif hasattr(reminder, key):
                setattr(reminder, key, value)
        
        reminder.updated_at = now.isoformat()
        self._save()
        
        return reminder
    
    def delete(self, rid: str) -> bool:
        """Delete a reminder."""
        self._load()
        
        if rid not in self._items:
            return False
        
        del self._items[rid]
        self._save()
        return True
    
    def list_all(self) -> List[Reminder]:
        """Get all reminders."""
        self._load()
        return list(self._items.values())
    
    # =========================================================================
    # ACTION OPERATIONS
    # =========================================================================
    
    def complete(self, rid: str) -> Optional[Reminder]:
        """
        Mark reminder as done.
        - Non-recurring: set status=done
        - Recurring: keep active, advance to next occurrence
        """
        self._load()
        
        reminder = self._items.get(rid)
        if not reminder:
            return None
        
        now = self._now(reminder.timezone)
        
        if reminder.is_recurring:
            # Advance recurrence
            self.advance_recurrence(reminder, now)
            reminder.status = "active"
        else:
            reminder.status = "done"
            reminder.last_fired_at = now.isoformat()
        
        reminder.updated_at = now.isoformat()
        self._save()
        
        return reminder
    
    def snooze(self, rid: str, duration: str) -> Optional[Reminder]:
        """
        Snooze a reminder for specified duration.
        Duration: 10m, 1h, 3h, 1d
        """
        self._load()
        
        reminder = self._items.get(rid)
        if not reminder:
            return None
        
        now = self._now(reminder.timezone)
        
        # Parse duration
        match = re.match(r"(\d+)(m|h|d)", duration.lower())
        if not match:
            return None
        
        amount = int(match.group(1))
        unit = match.group(2)
        
        if unit == "m":
            delta = timedelta(minutes=amount)
        elif unit == "h":
            delta = timedelta(hours=amount)
        elif unit == "d":
            delta = timedelta(days=amount)
        else:
            return None
        
        reminder.snoozed_until = (now + delta).isoformat()
        reminder.updated_at = now.isoformat()
        self._save()
        
        return reminder
    
    def pin(self, rid: str) -> Optional[Reminder]:
        """Pin a reminder."""
        self._load()
        
        reminder = self._items.get(rid)
        if not reminder:
            return None
        
        reminder.pinned = True
        reminder.updated_at = self._now(reminder.timezone).isoformat()
        self._save()
        
        return reminder
    
    def unpin(self, rid: str) -> Optional[Reminder]:
        """Unpin a reminder."""
        self._load()
        
        reminder = self._items.get(rid)
        if not reminder:
            return None
        
        reminder.pinned = False
        reminder.updated_at = self._now(reminder.timezone).isoformat()
        self._save()
        
        return reminder
    
    # =========================================================================
    # QUERY OPERATIONS
    # =========================================================================
    
    def get_due_now(self, now: Optional[datetime] = None) -> List[Reminder]:
        """Get all reminders currently due."""
        self._load()
        
        # First, apply window rollovers
        for reminder in self._items.values():
            if reminder.has_window:
                self.apply_window_rollover(reminder, now)
        
        return [r for r in self._items.values() if self.is_due_now(r, now)]
    
    def get_due_today(self, now: Optional[datetime] = None) -> List[Reminder]:
        """Get all reminders due today."""
        self._load()
        return [r for r in self._items.values() if self.is_due_today(r, now)]
    
    def get_overdue(self, now: Optional[datetime] = None) -> List[Reminder]:
        """Get all overdue reminders."""
        self._load()
        return [r for r in self._items.values() if self.is_overdue(r, now)]
    
    def get_pinned(self) -> List[Reminder]:
        """Get all pinned reminders."""
        self._load()
        return [r for r in self._items.values() if r.pinned and r.status == "active"]
    
    def get_upcoming(self, days: int = 7, now: Optional[datetime] = None) -> List[Reminder]:
        """Get reminders due in the next N days."""
        self._load()
        
        tz = self._get_tz(DEFAULT_TIMEZONE)
        if now is None:
            now = datetime.now(tz)
        else:
            now = now.astimezone(tz)
        
        cutoff = now + timedelta(days=days)
        result = []
        
        for reminder in self._items.values():
            if reminder.status != "active":
                continue
            
            due = self.compute_effective_due(reminder)
            if due and now < due <= cutoff:
                result.append(reminder)
        
        return sorted(result, key=lambda r: r.due_at)
    
    def get_done(self, limit: int = 10) -> List[Reminder]:
        """Get recently completed reminders."""
        self._load()
        done = [r for r in self._items.values() if r.status == "done"]
        return sorted(done, key=lambda r: r.updated_at or "", reverse=True)[:limit]


# -------------------------------------------------------------
# Module Export
# -------------------------------------------------------------

__all__ = [
    "RemindersManager",
    "Reminder",
    "RepeatConfig",
    "RepeatWindow",
    "DEFAULT_TIMEZONE",
    "WEEKDAY_MAP",
    "WEEKDAY_ABBREV",
]
