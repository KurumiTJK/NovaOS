# FILE: kernel/reminders_manager.py

from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

# -------------------------------------------------------------
# Data model
# -------------------------------------------------------------

@dataclass
class Reminder:
    id: str
    title: str
    when: str                     # ISO timestamp string
    timezone: str = "UTC"
    repeat: Optional[str] = None  # None | daily | weekly | monthly
    status: str = "pending"       # pending | triggered | snoozed | done
    created_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Reminder":
        return cls(
            id=data["id"],
            title=data["title"],
            when=data["when"],
            timezone=data.get("timezone", "UTC"),
            repeat=data.get("repeat"),
            status=data.get("status", "pending"),
            created_at=data.get("created_at", ""),
        )


# -------------------------------------------------------------
# Reminder Manager
# -------------------------------------------------------------

class RemindersManager:
    """
    v0.4.1: Basic JSON reminder store.
    No background threads — kernel triggers reminder checks on each user input.
    """

    def __init__(self, data_dir: Path):
        self.file = data_dir / "reminders.json"
        self.reminders: Dict[str, Reminder] = self._load()

    # ---------- JSON load/save ----------

    def _load(self) -> Dict[str, Reminder]:
        if not self.file.exists():
            return {}
        try:
            raw = json.loads(self.file.read_text(encoding="utf-8"))
            result: Dict[str, Reminder] = {}
            for rid, rdata in raw.items():
                try:
                    r = Reminder.from_dict(rdata)
                    # Option B: normalize legacy/messy 'when' values on load
                    r.when = self._normalize_when(r.when)
                    result[rid] = r
                except Exception:
                    continue
            return result
        except Exception:
            return {}

    def _save(self) -> None:
        raw = {rid: r.to_dict() for rid, r in self.reminders.items()}
        self.file.write_text(json.dumps(raw, indent=2), encoding="utf-8")

    # ---------- Helpers ----------

    def _generate_id(self) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        return f"rem-{ts}"

    # ---------- CRUD ops ----------

    def add(self, title: str, when: str, repeat: Optional[str] = None, tz: str = "UTC") -> Reminder:
        rid = self._generate_id()
        normalized_when = self._normalize_when(when)
        r = Reminder(
            id=rid,
            title=title,
            when=normalized_when,
            timezone=tz,
            repeat=repeat,
            status="pending",
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self.reminders[rid] = r
        self._save()
        return r

    def update(self, rid: str, fields: Dict[str, Any]) -> Optional[Reminder]:
        r = self.reminders.get(rid)
        if not r:
            return None
        for k, v in fields.items():
            if hasattr(r, k):
                setattr(r, k, v)
        self._save()
        return r

    def delete(self, rid: str) -> bool:
        if rid in self.reminders:
            del self.reminders[rid]
            self._save()
            return True
        return False

    def list(self) -> List[Reminder]:
        return list(self.reminders.values())

    # ---------- Reminder checking ----------

    def check_due(self, now: Optional[datetime] = None) -> List[Reminder]:
        now = now or datetime.now(timezone.utc)
        due: List[Reminder] = []
        for r in self.reminders.values():
            if r.status != "pending":
                continue
            raw_when = r.when
            if not raw_when:
                continue
            try:
                s = raw_when
                # Allow trailing 'Z' (UTC) by converting to +00:00
                if s.endswith("Z"):
                    s = s[:-1] + "+00:00"
                when_dt = datetime.fromisoformat(s)
            except Exception:
                continue
            if when_dt <= now:
                r.status = "triggered"
                due.append(r)
        if due:
            self._save()
        return due

    # ---------- Time parsing helpers ----------

    def _normalize_when(self, value: str) -> str:
        """
        Best-effort parsing for human-friendly times.

        Handles:
        - Full ISO strings (with or without 'Z')
        - 'in 10 minutes', 'in 2 hours'
        - 'tomorrow', 'tomorrow 9am'
        - '9am', '9:30pm', '21:15'
        Falls back to now+5 minutes if parsing fails.
        """
        now = datetime.now(timezone.utc)
        s = (value or "").strip().lower()

        if not s:
            return (now + timedelta(minutes=5)).isoformat()

        # 1) ISO-ish (with optional Z)
        try:
            iso_candidate = s
            if iso_candidate.endswith("z"):
                iso_candidate = iso_candidate[:-1] + "+00:00"
            dt = datetime.fromisoformat(iso_candidate)
            return dt.astimezone(timezone.utc).isoformat()
        except Exception:
            pass

        # 2) "in N minutes/hours"
        m = re.match(r"in\s+(\d+)\s+minute", s)
        if m:
            minutes = int(m.group(1))
            return (now + timedelta(minutes=minutes)).isoformat()
        m = re.match(r"in\s+(\d+)\s+hour", s)
        if m:
            hours = int(m.group(1))
            return (now + timedelta(hours=hours)).isoformat()

        # 3) "tomorrow" / "tomorrow 9am"
        if s.startswith("tomorrow"):
            base = now + timedelta(days=1)
            time_part = s[len("tomorrow"):].strip()
            dt = self._apply_clock_time(base, time_part or "9am")
            return dt.astimezone(timezone.utc).isoformat()

        # 4) Plain clock time ("9am", "9:30pm", "21:15")
        dt = self._apply_clock_time(now, s)
        if dt:
            return dt.astimezone(timezone.utc).isoformat()

        # 5) Fallback: 5 minutes from now
        return (now + timedelta(minutes=5)).isoformat()

    def _apply_clock_time(self, base: datetime, time_str: Optional[str]) -> Optional[datetime]:
        """
        Apply a time-of-day string to a base date.
        Examples:
            '9am', '9:30 pm', '21:15'
        """
        if not time_str:
            return None
        t = time_str.strip().lower()

        # 21:15
        m_24 = re.match(r"^(\d{1,2}):(\d{2})$", t)
        if m_24:
            hour = int(m_24.group(1))
            minute = int(m_24.group(2))
            return base.replace(hour=hour, minute=minute, second=0, microsecond=0)

        # 9am, 9 pm, 9:30am etc.
        m_12 = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)$", t)
        if m_12:
            hour = int(m_12.group(1))
            minute = int(m_12.group(2) or "0")
            suffix = m_12.group(3)
            if suffix == "pm" and hour != 12:
                hour += 12
            if suffix == "am" and hour == 12:
                hour = 0
            return base.replace(hour=hour, minute=minute, second=0, microsecond=0)

        # Bare hour: "9" -> 9:00 today
        if t.isdigit():
            hour = int(t)
            return base.replace(hour=hour, minute=0, second=0, microsecond=0)

        return None
