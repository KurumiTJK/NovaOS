# FILE: kernel/reminders_manager.py

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
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
            result = {}
            for rid, rdata in raw.items():
                try:
                    result[rid] = Reminder.from_dict(rdata)
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
        r = Reminder(
            id=rid,
            title=title,
            when=when,
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
        due = []
        for r in self.reminders.values():
            if r.status != "pending":
                continue
            try:
                when_dt = datetime.fromisoformat(r.when)
            except Exception:
                continue
            if when_dt <= now:
                r.status = "triggered"
                due.append(r)
        if due:
            self._save()
        return due
