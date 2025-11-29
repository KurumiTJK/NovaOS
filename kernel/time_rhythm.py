# FILE: kernel/time_rhythm.py

# --- BEFORE (snippet) ---
# (file was empty)

# --- AFTER (updated snippet) ---
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, date, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence


@dataclass
class RhythmCycle:
    """
    A named time cycle (e.g., 30-day plan, 8-week MVP) tracked by the TimeRhythmEngine.
    """
    id: str
    label: str
    start_date: date
    length_days: int
    kind: str  # e.g., "30day", "8week", "custom"
    meta: Dict[str, Any] = field(default_factory=dict)

    def phase_for(self, today: date) -> Dict[str, Any]:
        """Return the phase information for this cycle on a given date."""
        delta_days = (today - self.start_date).days

        if delta_days < 0:
            status = "upcoming"
            day_index: Optional[int] = None
        elif delta_days >= self.length_days:
            status = "completed"
            day_index = self.length_days
        else:
            status = "active"
            day_index = delta_days + 1  # 1-based day index

        week_index: Optional[int] = None
        if day_index is not None and self.length_days >= 7:
            # 1-based week index
            week_index = (day_index - 1) // 7 + 1

        return {
            "cycle_id": self.id,
            "label": self.label,
            "kind": self.kind,
            "status": status,
            "day_index": day_index,
            "week_index": week_index,
            "start_date": self.start_date.isoformat(),
            "length_days": self.length_days,
            "meta": self.meta,
        }


@dataclass
class TimeRhythmState:
    """
    Serializable state for the TimeRhythmEngine.
    Compatible with snapshot/export mechanisms.
    """
    cycles: Dict[str, RhythmCycle] = field(default_factory=dict)
    last_updated: Optional[datetime] = None


class TimeRhythmEngine:
    """
    Tracks global time rhythm:
    - Calendar information (day of week, week of year).
    - Named cycles (30-day plans, 8-week MVP plans, etc.).
    Provides presence() and pulse() hooks for syscommands.
    """

    def __init__(self, state: Optional[TimeRhythmState] = None) -> None:
        self.state = state or TimeRhythmState()

    # ---------- Core helpers ----------

    @staticmethod
    def _now_utc() -> datetime:
        return datetime.now(timezone.utc)

    # ---------- Serialization ----------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cycles": {cid: asdict(cycle) for cid, cycle in self.state.cycles.items()},
            "last_updated": self.state.last_updated.isoformat()
            if self.state.last_updated
            else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TimeRhythmEngine":
        raw_cycles = data.get("cycles") or {}
        cycles: Dict[str, RhythmCycle] = {}

        for cid, raw in raw_cycles.items():
            try:
                start_date = date.fromisoformat(raw["start_date"])
            except Exception:
                # If invalid/missing, skip this cycle gracefully
                continue

            cycles[cid] = RhythmCycle(
                id=raw.get("id", cid),
                label=raw.get("label", cid),
                start_date=start_date,
                length_days=int(raw.get("length_days", 0)),
                kind=raw.get("kind", "custom"),
                meta=raw.get("meta") or {},
            )

        last_updated_raw = data.get("last_updated")
        last_updated: Optional[datetime] = None
        if last_updated_raw:
            try:
                last_updated = datetime.fromisoformat(last_updated_raw)
            except Exception:
                last_updated = None

        state = TimeRhythmState(cycles=cycles, last_updated=last_updated)
        return cls(state)

    # ---------- Cycle management ----------

    def register_cycle(
        self,
        cycle_id: str,
        label: str,
        start: date,
        length_days: int,
        kind: str = "custom",
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Create or update a named cycle."""
        self.state.cycles[cycle_id] = RhythmCycle(
            id=cycle_id,
            label=label,
            start_date=start,
            length_days=length_days,
            kind=kind,
            meta=meta or {},
        )
        self.state.last_updated = self._now_utc()

    def remove_cycle(self, cycle_id: str) -> None:
        """Remove a named cycle if it exists."""
        if cycle_id in self.state.cycles:
            del self.state.cycles[cycle_id]
            self.state.last_updated = self._now_utc()

    # ---------- Presence & Pulse ----------

    def presence(self, today: Optional[date] = None) -> Dict[str, Any]:
        """
        High-level awareness of the current position in time:
        - Calendar (date, weekday, ISO week).
        - Phase information for all registered cycles.
        """
        now = self._now_utc()
        today = today or now.date()

        iso_year, iso_week, iso_weekday = today.isocalendar()

        cycles_info: List[Dict[str, Any]] = [
            cycle.phase_for(today) for cycle in self.state.cycles.values()
        ]

        return {
            "timestamp": now.isoformat(),
            "today": today.isoformat(),
            "day_of_week": iso_weekday,  # 1 = Monday, 7 = Sunday
            "iso_week": iso_week,
            "iso_year": iso_year,
            "cycles": cycles_info,
        }

    def pulse(
        self,
        workflows: Sequence[Mapping[str, Any]],
        now: Optional[datetime] = None,
        stall_threshold_days: int = 2,
    ) -> Dict[str, Any]:
        """
        Diagnostics on active workflows:
        - Counts by status.
        - Detects "stalled" workflows if they expose a 'last_updated' field (ISO string).
        This is deliberately loose so it can work with any WorkflowEngine that returns
        dict-like workflow summaries.
        """
        now = now or self._now_utc()

        by_status: Dict[str, int] = {}
        stalled: List[Dict[str, Any]] = []

        for wf in workflows:
            status = str(wf.get("status", "unknown"))
            by_status[status] = by_status.get(status, 0) + 1

            last_updated_raw = wf.get("last_updated")
            if not last_updated_raw:
                continue

            try:
                last_updated = datetime.fromisoformat(last_updated_raw)
            except Exception:
                continue

            age_days = (now - last_updated).total_seconds() / 86400.0
            if status in ("active", "pending") and age_days >= stall_threshold_days:
                stalled.append(
                    {
                        "id": wf.get("id"),
                        "name": wf.get("name"),
                        "status": status,
                        "age_days": round(age_days, 2),
                    }
                )

        return {
            "timestamp": now.isoformat(),
            "total_workflows": len(workflows),
            "by_status": by_status,
            "stalled": stalled,
        }

