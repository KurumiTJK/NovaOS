# kernel/human_state_v2.py
"""
NovaOS Human State Engine — v2.0.0

Real-time operating condition and biological context engine.
Tracks today's condition and provides:
- Readiness tier (Green/Yellow/Red)
- Load modifier (0.75 / 1.00 / 1.15)
- Recommended mode (Push/Maintain/Recover)

Powers:
- Timerhythm daily/weekly review context
- Workflow difficulty scaling suggestions (via load_modifier)
- Reminders tone/intensity hints

Data Model:
- Today snapshot: data/human_state.json
- History log: data/human_state_log.json
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
from typing import Any, Dict, List, Optional, Literal, Tuple


# =============================================================================
# TYPES
# =============================================================================

ReadinessTier = Literal["Green", "Yellow", "Red"]
RecommendedMode = Literal["Push", "Maintain", "Recover"]
ToneHint = Literal["ambitious", "normal", "gentle"]


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class HumanStateSnapshot:
    """
    Today's human state snapshot.
    
    Core metrics (manually set via check-in):
    - stamina: 0-100 (physical/mental energy reserve)
    - stress: 0-100 (pressure level)
    - mood: -5 to +5 (emotional state)
    - focus: 0-100 (concentration ability)
    - sleep_quality: 0-100 (last night's rest)
    - soreness: 0-100 (physical discomfort)
    
    Derived fields (computed):
    - hp: 0-100 (synthesis score)
    - readiness_tier: Green/Yellow/Red
    - load_modifier: 0.75/1.00/1.15
    - recommended_mode: Push/Maintain/Recover
    """
    # Date tracking
    today_date: str = ""  # YYYY-MM-DD
    last_check_in_at: Optional[str] = None  # ISO timestamp
    
    # Core metrics
    stamina: int = 50
    stress: int = 50
    mood: int = 0
    focus: int = 50
    sleep_quality: int = 50
    soreness: int = 0
    
    # Notes and tags
    notes: str = ""
    tags: List[str] = field(default_factory=list)
    
    # Derived fields (computed, not manually set)
    hp: int = 50
    readiness_tier: ReadinessTier = "Yellow"
    load_modifier: float = 1.0
    recommended_mode: RecommendedMode = "Maintain"
    
    # Events logged today
    events: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "today_date": self.today_date,
            "last_check_in_at": self.last_check_in_at,
            "stamina": self.stamina,
            "stress": self.stress,
            "mood": self.mood,
            "focus": self.focus,
            "sleep_quality": self.sleep_quality,
            "soreness": self.soreness,
            "notes": self.notes,
            "tags": self.tags,
            "hp": self.hp,
            "readiness_tier": self.readiness_tier,
            "load_modifier": self.load_modifier,
            "recommended_mode": self.recommended_mode,
            "events": self.events,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HumanStateSnapshot":
        return cls(
            today_date=data.get("today_date", ""),
            last_check_in_at=data.get("last_check_in_at"),
            stamina=int(data.get("stamina", 50)),
            stress=int(data.get("stress", 50)),
            mood=int(data.get("mood", 0)),
            focus=int(data.get("focus", 50)),
            sleep_quality=int(data.get("sleep_quality", 50)),
            soreness=int(data.get("soreness", 0)),
            notes=data.get("notes", ""),
            tags=list(data.get("tags", [])),
            hp=int(data.get("hp", 50)),
            readiness_tier=data.get("readiness_tier", "Yellow"),
            load_modifier=float(data.get("load_modifier", 1.0)),
            recommended_mode=data.get("recommended_mode", "Maintain"),
            events=list(data.get("events", [])),
        )
    
    @classmethod
    def default(cls, today: str) -> "HumanStateSnapshot":
        """Create a default snapshot for today."""
        snapshot = cls(today_date=today)
        snapshot.recompute_derived()
        return snapshot


@dataclass
class HistoryEntry:
    """
    A historical record of a day's state.
    """
    date: str  # YYYY-MM-DD
    timestamp: str  # ISO timestamp of check-in
    
    # Core metrics snapshot
    stamina: int = 50
    stress: int = 50
    mood: int = 0
    focus: int = 50
    sleep_quality: int = 50
    soreness: int = 0
    
    # Derived
    hp: int = 50
    readiness_tier: str = "Yellow"
    load_modifier: float = 1.0
    recommended_mode: str = "Maintain"
    
    # Notes and events
    notes: str = ""
    tags: List[str] = field(default_factory=list)
    events: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date,
            "timestamp": self.timestamp,
            "stamina": self.stamina,
            "stress": self.stress,
            "mood": self.mood,
            "focus": self.focus,
            "sleep_quality": self.sleep_quality,
            "soreness": self.soreness,
            "hp": self.hp,
            "readiness_tier": self.readiness_tier,
            "load_modifier": self.load_modifier,
            "recommended_mode": self.recommended_mode,
            "notes": self.notes,
            "tags": self.tags,
            "events": self.events,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HistoryEntry":
        return cls(
            date=data.get("date", ""),
            timestamp=data.get("timestamp", ""),
            stamina=int(data.get("stamina", 50)),
            stress=int(data.get("stress", 50)),
            mood=int(data.get("mood", 0)),
            focus=int(data.get("focus", 50)),
            sleep_quality=int(data.get("sleep_quality", 50)),
            soreness=int(data.get("soreness", 0)),
            hp=int(data.get("hp", 50)),
            readiness_tier=data.get("readiness_tier", "Yellow"),
            load_modifier=float(data.get("load_modifier", 1.0)),
            recommended_mode=data.get("recommended_mode", "Maintain"),
            notes=data.get("notes", ""),
            tags=list(data.get("tags", [])),
            events=list(data.get("events", [])),
        )
    
    @classmethod
    def from_snapshot(cls, snapshot: HumanStateSnapshot) -> "HistoryEntry":
        """Create a history entry from a snapshot."""
        return cls(
            date=snapshot.today_date,
            timestamp=snapshot.last_check_in_at or datetime.now(timezone.utc).isoformat(),
            stamina=snapshot.stamina,
            stress=snapshot.stress,
            mood=snapshot.mood,
            focus=snapshot.focus,
            sleep_quality=snapshot.sleep_quality,
            soreness=snapshot.soreness,
            hp=snapshot.hp,
            readiness_tier=snapshot.readiness_tier,
            load_modifier=snapshot.load_modifier,
            recommended_mode=snapshot.recommended_mode,
            notes=snapshot.notes,
            tags=snapshot.tags.copy(),
            events=snapshot.events.copy(),
        )


# =============================================================================
# SCORING / DERIVED METRICS ENGINE
# =============================================================================

def compute_hp(
    stamina: int,
    stress: int,
    focus: int,
    sleep_quality: int,
) -> int:
    """
    Compute HP (synthesis score).
    
    Formula:
    hp = 0.35*stamina + 0.25*sleep_quality + 0.20*focus + 0.20*(100-stress)
    Clamped 0-100.
    """
    raw = (
        0.35 * stamina +
        0.25 * sleep_quality +
        0.20 * focus +
        0.20 * (100 - stress)
    )
    return max(0, min(100, int(round(raw))))


def compute_readiness_tier(
    stamina: int,
    stress: int,
    sleep_quality: int,
) -> ReadinessTier:
    """
    Compute readiness tier.
    
    Rules:
    - Green if stamina >= 65 AND stress <= 45
    - Red if stamina < 40 OR stress > 70 OR sleep_quality < 35
    - Yellow otherwise
    """
    # Check Red conditions first (any triggers Red)
    if stamina < 40 or stress > 70 or sleep_quality < 35:
        return "Red"
    
    # Check Green conditions (all must be true)
    if stamina >= 65 and stress <= 45:
        return "Green"
    
    # Default to Yellow
    return "Yellow"


def compute_load_modifier(tier: ReadinessTier) -> float:
    """
    Compute load modifier based on readiness tier.
    
    - Green: 1.15
    - Yellow: 1.00
    - Red: 0.75
    """
    return {
        "Green": 1.15,
        "Yellow": 1.00,
        "Red": 0.75,
    }.get(tier, 1.00)


def compute_recommended_mode(tier: ReadinessTier) -> RecommendedMode:
    """
    Compute recommended mode based on readiness tier.
    
    - Green: Push
    - Yellow: Maintain
    - Red: Recover
    """
    return {
        "Green": "Push",
        "Yellow": "Maintain",
        "Red": "Recover",
    }.get(tier, "Maintain")


def get_tone_hint(tier: ReadinessTier) -> ToneHint:
    """
    Get tone hint for reminders based on tier.
    
    - Green: ambitious
    - Yellow: normal
    - Red: gentle
    """
    return {
        "Green": "ambitious",
        "Yellow": "normal",
        "Red": "gentle",
    }.get(tier, "normal")


# =============================================================================
# DAILY DRIFT (DAY ROLLOVER)
# =============================================================================

def apply_daily_drift(snapshot: HumanStateSnapshot) -> HumanStateSnapshot:
    """
    Apply daily drift when rolling over to a new day.
    
    Rules:
    - stamina: -5 (min 0)
    - stress: -3 (min 0)
    - mood: move 1 point toward 0
    - soreness: -5 (min 0)
    - sleep_quality/focus: -2 (min 0)
    """
    new_snapshot = HumanStateSnapshot(
        today_date=snapshot.today_date,  # Will be updated by caller
        last_check_in_at=None,  # Reset until new check-in
        stamina=max(0, snapshot.stamina - 5),
        stress=max(0, snapshot.stress - 3),
        mood=_drift_toward_zero(snapshot.mood),
        focus=max(0, snapshot.focus - 2),
        sleep_quality=max(0, snapshot.sleep_quality - 2),
        soreness=max(0, snapshot.soreness - 5),
        notes="",  # Reset notes
        tags=[],  # Reset tags
        events=[],  # Reset events
    )
    return new_snapshot


def _drift_toward_zero(value: int) -> int:
    """Move value 1 point toward zero."""
    if value > 0:
        return value - 1
    elif value < 0:
        return value + 1
    return 0


# =============================================================================
# EVENT DELTAS
# =============================================================================

EVENT_DELTAS: Dict[str, Dict[str, Any]] = {
    "workout": {
        "low": {"soreness": 5, "stress": -2, "stamina": -2},
        "medium": {"soreness": 10, "stress": -5, "stamina": -5},
        "high": {"soreness": 15, "stress": -8, "stamina": -8},
    },
    "walk": {
        # Minutes-based scaling (per 10 min)
        "per_10min": {"stress": -3, "focus": 2, "mood": 1},
        "max_effect": {"stress": -10, "focus": 6, "mood": 3},
    },
    "caffeine": {
        # Per serving
        "per_serving": {"stamina": 3, "stress": 1},
        "max_servings": 3,  # Cap at 3 servings worth
    },
    "nap": {
        # Minutes-based scaling
        "per_10min": {"stamina": 3, "focus": 2},
        "max_effect": {"stamina": 15, "focus": 8},
    },
    "meditation": {
        # Minutes-based scaling
        "per_5min": {"stress": -3, "focus": 2},
        "max_effect": {"stress": -15, "focus": 8},
    },
    "bad_sleep": {
        "effect": {"sleep_quality": -20, "stamina": -10, "stress": 8},
    },
}


def apply_event_deltas(
    snapshot: HumanStateSnapshot,
    event_type: str,
    intensity: Optional[str] = None,
    minutes: Optional[int] = None,
    servings: Optional[int] = None,
) -> Tuple[HumanStateSnapshot, List[str]]:
    """
    Apply event deltas to a snapshot.
    
    Returns: (updated_snapshot, list of tags to add)
    """
    tags = [event_type]
    
    if event_type == "workout":
        intensity = intensity or "medium"
        deltas = EVENT_DELTAS["workout"].get(intensity, EVENT_DELTAS["workout"]["medium"])
        snapshot.soreness = _clamp(snapshot.soreness + deltas["soreness"], 0, 100)
        snapshot.stress = _clamp(snapshot.stress + deltas["stress"], 0, 100)
        snapshot.stamina = _clamp(snapshot.stamina + deltas["stamina"], 0, 100)
        tags.append(f"workout_{intensity}")
    
    elif event_type == "walk":
        mins = minutes or 15
        scale = min(mins / 10, 3)  # Cap at 30 mins worth
        per_10 = EVENT_DELTAS["walk"]["per_10min"]
        max_fx = EVENT_DELTAS["walk"]["max_effect"]
        snapshot.stress = _clamp(snapshot.stress + max(per_10["stress"] * scale, max_fx["stress"]), 0, 100)
        snapshot.focus = _clamp(snapshot.focus + min(per_10["focus"] * scale, max_fx["focus"]), 0, 100)
        snapshot.mood = _clamp(snapshot.mood + min(int(per_10["mood"] * scale), max_fx["mood"]), -5, 5)
        tags.append(f"walk_{mins}min")
    
    elif event_type == "caffeine":
        srvs = min(servings or 1, EVENT_DELTAS["caffeine"]["max_servings"])
        per_srv = EVENT_DELTAS["caffeine"]["per_serving"]
        snapshot.stamina = _clamp(snapshot.stamina + per_srv["stamina"] * srvs, 0, 100)
        snapshot.stress = _clamp(snapshot.stress + per_srv["stress"] * srvs, 0, 100)
        tags.append("caffeine")
    
    elif event_type == "nap":
        mins = minutes or 20
        scale = min(mins / 10, 4)  # Cap at 40 mins worth
        per_10 = EVENT_DELTAS["nap"]["per_10min"]
        max_fx = EVENT_DELTAS["nap"]["max_effect"]
        snapshot.stamina = _clamp(snapshot.stamina + min(per_10["stamina"] * scale, max_fx["stamina"]), 0, 100)
        snapshot.focus = _clamp(snapshot.focus + min(per_10["focus"] * scale, max_fx["focus"]), 0, 100)
        tags.append(f"nap_{mins}min")
    
    elif event_type == "meditation":
        mins = minutes or 10
        scale = min(mins / 5, 4)  # Cap at 20 mins worth
        per_5 = EVENT_DELTAS["meditation"]["per_5min"]
        max_fx = EVENT_DELTAS["meditation"]["max_effect"]
        snapshot.stress = _clamp(snapshot.stress + max(per_5["stress"] * scale, max_fx["stress"]), 0, 100)
        snapshot.focus = _clamp(snapshot.focus + min(per_5["focus"] * scale, max_fx["focus"]), 0, 100)
        tags.append(f"meditation_{mins}min")
    
    elif event_type == "bad_sleep":
        fx = EVENT_DELTAS["bad_sleep"]["effect"]
        snapshot.sleep_quality = _clamp(snapshot.sleep_quality + fx["sleep_quality"], 0, 100)
        snapshot.stamina = _clamp(snapshot.stamina + fx["stamina"], 0, 100)
        snapshot.stress = _clamp(snapshot.stress + fx["stress"], 0, 100)
        tags.append("bad_sleep")
    
    return snapshot, tags


def _clamp(value: float, min_val: int, max_val: int) -> int:
    """Clamp value to range and convert to int."""
    return max(min_val, min(max_val, int(round(value))))


# =============================================================================
# HUMAN STATE MANAGER (v2)
# =============================================================================

class HumanStateManagerV2:
    """
    Human State Manager v2.0.0
    
    Manages:
    - Today's snapshot (data/human_state.json)
    - History log (data/human_state_log.json)
    - Daily drift on day rollover
    - Check-ins and events
    - Integration APIs for other sections
    """
    
    MAX_HISTORY_SIZE = 365  # Keep 1 year of history
    
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.snapshot_file = self.data_dir / "human_state.json"
        self.history_file = self.data_dir / "human_state_log.json"
        
        self._snapshot: Optional[HumanStateSnapshot] = None
        self._history: List[HistoryEntry] = []
        self._loaded: bool = False
        self._lock = threading.Lock()
    
    # =========================================================================
    # PERSISTENCE
    # =========================================================================
    
    def _load(self) -> None:
        """Load state from disk."""
        if self._loaded:
            return
        
        with self._lock:
            if self._loaded:
                return
            
            # Load snapshot
            if self.snapshot_file.exists():
                try:
                    data = json.loads(self.snapshot_file.read_text())
                    self._snapshot = HumanStateSnapshot.from_dict(data)
                except Exception as e:
                    print(f"[HumanState] Error loading snapshot: {e}")
                    self._snapshot = None
            
            # Load history
            if self.history_file.exists():
                try:
                    data = json.loads(self.history_file.read_text())
                    self._history = [HistoryEntry.from_dict(e) for e in data]
                except Exception as e:
                    print(f"[HumanState] Error loading history: {e}")
                    self._history = []
            
            self._loaded = True
    
    def _save_snapshot(self) -> None:
        """Save snapshot to disk (must hold lock)."""
        if self._snapshot:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self.snapshot_file.write_text(
                json.dumps(self._snapshot.to_dict(), indent=2)
            )
    
    def _save_history(self) -> None:
        """Save history to disk (must hold lock)."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        # Trim to max size
        if len(self._history) > self.MAX_HISTORY_SIZE:
            self._history = self._history[-self.MAX_HISTORY_SIZE:]
        self.history_file.write_text(
            json.dumps([e.to_dict() for e in self._history], indent=2)
        )
    
    # =========================================================================
    # DATE HANDLING / DRIFT
    # =========================================================================
    
    def _get_today_str(self) -> str:
        """Get today's date string in YYYY-MM-DD format."""
        return datetime.now().strftime("%Y-%m-%d")
    
    def _ensure_today(self) -> HumanStateSnapshot:
        """
        Ensure we have a snapshot for today.
        If date changed, apply drift and create new day's snapshot.
        """
        self._load()
        
        today = self._get_today_str()
        
        with self._lock:
            if self._snapshot is None:
                # Fresh install - create default snapshot
                self._snapshot = HumanStateSnapshot.default(today)
                self._snapshot.recompute_derived()
                self._save_snapshot()
                return self._snapshot
            
            if self._snapshot.today_date != today:
                # Day changed - apply drift
                old_date = self._snapshot.today_date
                
                # Apply drift to create new day's base
                self._snapshot = apply_daily_drift(self._snapshot)
                self._snapshot.today_date = today
                self._snapshot.recompute_derived()
                self._save_snapshot()
                
                print(f"[HumanState] Day rollover: {old_date} -> {today}, drift applied")
            
            return self._snapshot
    
    # =========================================================================
    # PUBLIC API - GETTERS
    # =========================================================================
    
    def get_today_human_state(self) -> HumanStateSnapshot:
        """Get today's snapshot (ensuring day rollover is handled)."""
        return self._ensure_today()
    
    def get_readiness_tier(self) -> ReadinessTier:
        """Get current readiness tier."""
        snapshot = self._ensure_today()
        return snapshot.readiness_tier
    
    def get_load_modifier(self) -> float:
        """Get current load modifier."""
        snapshot = self._ensure_today()
        return snapshot.load_modifier
    
    def get_recommended_mode(self) -> RecommendedMode:
        """Get current recommended mode."""
        snapshot = self._ensure_today()
        return snapshot.recommended_mode
    
    def get_tone_hint(self) -> ToneHint:
        """Get tone hint for reminders."""
        return get_tone_hint(self.get_readiness_tier())
    
    def get_hp(self) -> int:
        """Get current HP."""
        snapshot = self._ensure_today()
        return snapshot.hp
    
    # =========================================================================
    # PUBLIC API - CHECK-IN
    # =========================================================================
    
    def do_checkin(
        self,
        stamina: Optional[int] = None,
        stress: Optional[int] = None,
        mood: Optional[int] = None,
        focus: Optional[int] = None,
        sleep_quality: Optional[int] = None,
        soreness: Optional[int] = None,
        notes: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> HumanStateSnapshot:
        """
        Perform a check-in, updating provided metrics.
        
        - Only provided values are updated
        - Derived fields are recomputed
        - History is updated (one entry per day)
        """
        snapshot = self._ensure_today()
        
        with self._lock:
            # Update provided values
            if stamina is not None:
                snapshot.stamina = _clamp(stamina, 0, 100)
            if stress is not None:
                snapshot.stress = _clamp(stress, 0, 100)
            if mood is not None:
                snapshot.mood = _clamp(mood, -5, 5)
            if focus is not None:
                snapshot.focus = _clamp(focus, 0, 100)
            if sleep_quality is not None:
                snapshot.sleep_quality = _clamp(sleep_quality, 0, 100)
            if soreness is not None:
                snapshot.soreness = _clamp(soreness, 0, 100)
            if notes is not None:
                snapshot.notes = notes
            if tags is not None:
                # Merge tags
                existing = set(snapshot.tags)
                for t in tags:
                    existing.add(t)
                snapshot.tags = list(existing)
            
            # Update timestamp
            snapshot.last_check_in_at = datetime.now(timezone.utc).isoformat()
            
            # Recompute derived
            snapshot.recompute_derived()
            
            # Save snapshot
            self._save_snapshot()
            
            # Update history (one entry per day)
            self._update_history_for_today(snapshot)
            
            return snapshot
    
    def _update_history_for_today(self, snapshot: HumanStateSnapshot) -> None:
        """Update or create history entry for today (must hold lock)."""
        today = snapshot.today_date
        
        # Find existing entry for today
        for i, entry in enumerate(self._history):
            if entry.date == today:
                # Update existing
                self._history[i] = HistoryEntry.from_snapshot(snapshot)
                self._save_history()
                return
        
        # Add new entry
        self._history.append(HistoryEntry.from_snapshot(snapshot))
        self._save_history()
    
    # =========================================================================
    # PUBLIC API - EVENTS
    # =========================================================================
    
    def log_event(
        self,
        event_type: str,
        intensity: Optional[str] = None,
        minutes: Optional[int] = None,
        servings: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Log a quick event that modifies today's state.
        
        Supported event types:
        - workout (intensity: low/medium/high)
        - walk (minutes)
        - caffeine (servings)
        - nap (minutes)
        - meditation (minutes)
        - bad_sleep
        
        Returns: dict with event details and new state summary
        """
        snapshot = self._ensure_today()
        
        with self._lock:
            # Apply deltas
            snapshot, new_tags = apply_event_deltas(
                snapshot, event_type, intensity, minutes, servings
            )
            
            # Merge tags
            existing = set(snapshot.tags)
            for t in new_tags:
                existing.add(t)
            snapshot.tags = list(existing)
            
            # Log event
            event_record = {
                "type": event_type,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "intensity": intensity,
                "minutes": minutes,
                "servings": servings,
            }
            snapshot.events.append(event_record)
            
            # Recompute derived
            snapshot.recompute_derived()
            
            # Save
            self._save_snapshot()
            self._update_history_for_today(snapshot)
            
            return {
                "event": event_record,
                "hp": snapshot.hp,
                "readiness_tier": snapshot.readiness_tier,
                "recommended_mode": snapshot.recommended_mode,
            }
    
    # =========================================================================
    # PUBLIC API - CLEAR / RESET
    # =========================================================================
    
    def clear_today(self, hard: bool = False) -> Dict[str, Any]:
        """
        Clear today's snapshot.
        
        - soft (default): Reset metrics to neutral defaults, keep history
        - hard=True: Also clear history log
        """
        today = self._get_today_str()
        
        with self._lock:
            # Reset snapshot
            self._snapshot = HumanStateSnapshot.default(today)
            self._snapshot.recompute_derived()
            self._save_snapshot()
            
            result = {"today_cleared": True, "history_cleared": False}
            
            if hard:
                self._history = []
                self._save_history()
                result["history_cleared"] = True
            
            return result
    
    # =========================================================================
    # PUBLIC API - HISTORY / ANALYTICS
    # =========================================================================
    
    def get_history(self, limit: int = 7) -> List[HistoryEntry]:
        """Get recent history entries (most recent first)."""
        self._load()
        return list(reversed(self._history[-limit:]))
    
    def get_7_day_averages(self) -> Dict[str, float]:
        """
        Get 7-day rolling averages for key metrics.
        
        Returns: dict with average stamina, stress, sleep_quality, hp
        """
        self._load()
        
        entries = self._history[-7:]
        if not entries:
            return {
                "avg_stamina": 50.0,
                "avg_stress": 50.0,
                "avg_sleep_quality": 50.0,
                "avg_hp": 50.0,
            }
        
        n = len(entries)
        return {
            "avg_stamina": sum(e.stamina for e in entries) / n,
            "avg_stress": sum(e.stress for e in entries) / n,
            "avg_sleep_quality": sum(e.sleep_quality for e in entries) / n,
            "avg_hp": sum(e.hp for e in entries) / n,
        }
    
    # =========================================================================
    # MIGRATION FROM LEGACY
    # =========================================================================
    
    def migrate_from_legacy(self, legacy_data: Dict[str, Any]) -> bool:
        """
        Migrate from legacy human_state format.
        
        Legacy format had: bio (energy, stress), load, aspiration
        New format has: stamina, stress, mood, focus, sleep_quality, soreness
        """
        try:
            today = self._get_today_str()
            
            # Map legacy fields
            bio = legacy_data.get("current", {}).get("bio", {})
            
            # Energy mapping: depleted=20, low=35, moderate=50, good=65, high=80
            energy_map = {
                "depleted": 20, "low": 35, "moderate": 50, "good": 65, "high": 80
            }
            stamina = energy_map.get(bio.get("energy", "moderate"), 50)
            
            # Stress mapping: calm=10, low=25, moderate=50, high=70, overwhelmed=90
            stress_map = {
                "calm": 10, "low": 25, "moderate": 50, "high": 70, "overwhelmed": 90
            }
            stress = stress_map.get(bio.get("stress", "moderate"), 50)
            
            # Sleep quality
            sleep_map = {"poor": 25, "fair": 45, "good": 70, "great": 90}
            sleep_quality = sleep_map.get(bio.get("sleep_quality"), 50)
            
            with self._lock:
                self._snapshot = HumanStateSnapshot(
                    today_date=today,
                    stamina=stamina,
                    stress=stress,
                    mood=0,
                    focus=50,
                    sleep_quality=sleep_quality,
                    soreness=0,
                )
                self._snapshot.recompute_derived()
                self._save_snapshot()
            
            print(f"[HumanState] Migrated from legacy format")
            return True
            
        except Exception as e:
            print(f"[HumanState] Migration error: {e}")
            return False


# =============================================================================
# EXTEND SNAPSHOT WITH RECOMPUTE METHOD
# =============================================================================

def _recompute_derived(self: HumanStateSnapshot) -> None:
    """Recompute all derived fields."""
    self.hp = compute_hp(self.stamina, self.stress, self.focus, self.sleep_quality)
    self.readiness_tier = compute_readiness_tier(self.stamina, self.stress, self.sleep_quality)
    self.load_modifier = compute_load_modifier(self.readiness_tier)
    self.recommended_mode = compute_recommended_mode(self.readiness_tier)


# Monkey-patch the method onto the dataclass
HumanStateSnapshot.recompute_derived = _recompute_derived


# =============================================================================
# MODULE-LEVEL HELPER FOR EASY IMPORT
# =============================================================================

_manager_instance: Optional[HumanStateManagerV2] = None


def get_human_state_manager(data_dir: Optional[Path] = None) -> HumanStateManagerV2:
    """Get or create the global HumanStateManager instance."""
    global _manager_instance
    
    if _manager_instance is None:
        if data_dir is None:
            data_dir = Path("data")
        _manager_instance = HumanStateManagerV2(data_dir)
    
    return _manager_instance


def reset_human_state_manager() -> None:
    """Reset the global manager instance (for testing)."""
    global _manager_instance
    _manager_instance = None


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Types
    "ReadinessTier",
    "RecommendedMode",
    "ToneHint",
    # Data classes
    "HumanStateSnapshot",
    "HistoryEntry",
    # Scoring functions
    "compute_hp",
    "compute_readiness_tier",
    "compute_load_modifier",
    "compute_recommended_mode",
    "get_tone_hint",
    # Manager
    "HumanStateManagerV2",
    "get_human_state_manager",
    "reset_human_state_manager",
]
