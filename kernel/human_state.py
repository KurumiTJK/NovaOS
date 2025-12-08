# kernel/human_state.py
"""
v0.5.9 — HumanStateModel + Evolution Status

Tracks the human's state across three dimensions:
1. Biology State (bio_state): sleep, energy, stress, physical
2. Load State (load_state): cognitive load, task count, overwhelm
3. Aspiration State (aspiration_state): current focus, growth areas, momentum

Core Principles:
- All state updates are user-initiated or confirm-gated
- State informs suggestions, never mandates behavior
- "Small version" recommendations under strain
- Evolution status shows progress without judgment
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Literal
import threading


# -----------------------------------------------------------------------------
# State Enums and Types
# -----------------------------------------------------------------------------

EnergyLevel = Literal["depleted", "low", "moderate", "good", "high"]
StressLevel = Literal["overwhelmed", "high", "moderate", "low", "calm"]
LoadLevel = Literal["overloaded", "heavy", "moderate", "light", "clear"]
MomentumLevel = Literal["stalled", "slow", "steady", "building", "flowing"]

# Numeric mappings for calculations
ENERGY_VALUES = {"depleted": 1, "low": 2, "moderate": 3, "good": 4, "high": 5}
STRESS_VALUES = {"overwhelmed": 5, "high": 4, "moderate": 3, "low": 2, "calm": 1}
LOAD_VALUES = {"overloaded": 5, "heavy": 4, "moderate": 3, "light": 2, "clear": 1}
MOMENTUM_VALUES = {"stalled": 1, "slow": 2, "steady": 3, "building": 4, "flowing": 5}


# -----------------------------------------------------------------------------
# State Data Models
# -----------------------------------------------------------------------------

@dataclass
class BiologyState:
    """
    Physical and biological state.
    """
    energy: EnergyLevel = "moderate"
    sleep_quality: Optional[str] = None  # "poor", "fair", "good", "great"
    sleep_hours: Optional[float] = None
    stress: StressLevel = "moderate"
    physical_notes: Optional[str] = None  # Exercise, illness, etc.
    last_updated: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BiologyState":
        return cls(
            energy=data.get("energy", "moderate"),
            sleep_quality=data.get("sleep_quality"),
            sleep_hours=data.get("sleep_hours"),
            stress=data.get("stress", "moderate"),
            physical_notes=data.get("physical_notes"),
            last_updated=data.get("last_updated"),
        )
    
    def get_strain_score(self) -> float:
        """
        Calculate strain score (0-1, higher = more strain).
        """
        energy_inv = 6 - ENERGY_VALUES.get(self.energy, 3)  # Invert: low energy = high strain
        stress_val = STRESS_VALUES.get(self.stress, 3)
        
        # Average and normalize to 0-1
        return (energy_inv + stress_val) / 10.0


@dataclass
class LoadState:
    """
    Cognitive and task load state.
    """
    cognitive_load: LoadLevel = "moderate"
    active_tasks: int = 0
    pending_decisions: int = 0
    overwhelm_feeling: Optional[str] = None  # User's subjective feeling
    focus_quality: Optional[str] = None  # "scattered", "okay", "focused", "deep"
    last_updated: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LoadState":
        return cls(
            cognitive_load=data.get("cognitive_load", "moderate"),
            active_tasks=int(data.get("active_tasks", 0)),
            pending_decisions=int(data.get("pending_decisions", 0)),
            overwhelm_feeling=data.get("overwhelm_feeling"),
            focus_quality=data.get("focus_quality"),
            last_updated=data.get("last_updated"),
        )
    
    def get_strain_score(self) -> float:
        """
        Calculate load strain score (0-1, higher = more strain).
        """
        load_val = LOAD_VALUES.get(self.cognitive_load, 3)
        
        # Task count contribution (cap at 10)
        task_factor = min(self.active_tasks, 10) / 10.0
        
        return (load_val / 5.0 + task_factor) / 2.0


@dataclass
class AspirationState:
    """
    Goals, growth, and momentum state.
    """
    current_focus: Optional[str] = None  # What they're working toward
    growth_areas: List[str] = field(default_factory=list)
    momentum: MomentumLevel = "steady"
    recent_wins: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    last_updated: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AspirationState":
        return cls(
            current_focus=data.get("current_focus"),
            growth_areas=list(data.get("growth_areas", [])),
            momentum=data.get("momentum", "steady"),
            recent_wins=list(data.get("recent_wins", [])),
            blockers=list(data.get("blockers", [])),
            last_updated=data.get("last_updated"),
        )
    
    def get_momentum_score(self) -> float:
        """
        Calculate momentum score (0-1, higher = more momentum).
        """
        base = MOMENTUM_VALUES.get(self.momentum, 3) / 5.0
        
        # Boost for recent wins
        win_boost = min(len(self.recent_wins), 3) * 0.05
        
        # Penalty for blockers
        blocker_penalty = min(len(self.blockers), 3) * 0.05
        
        return max(0, min(1, base + win_boost - blocker_penalty))


@dataclass
class HumanState:
    """
    Complete human state model.
    """
    bio: BiologyState = field(default_factory=BiologyState)
    load: LoadState = field(default_factory=LoadState)
    aspiration: AspirationState = field(default_factory=AspirationState)
    
    # Meta
    version: str = "0.5.9"
    created_at: Optional[str] = None
    last_checkin: Optional[str] = None
    checkin_streak: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "created_at": self.created_at,
            "last_checkin": self.last_checkin,
            "checkin_streak": self.checkin_streak,
            "bio": self.bio.to_dict(),
            "load": self.load.to_dict(),
            "aspiration": self.aspiration.to_dict(),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HumanState":
        return cls(
            version=data.get("version", "0.5.9"),
            created_at=data.get("created_at"),
            last_checkin=data.get("last_checkin"),
            checkin_streak=int(data.get("checkin_streak", 0)),
            bio=BiologyState.from_dict(data.get("bio", {})),
            load=LoadState.from_dict(data.get("load", {})),
            aspiration=AspirationState.from_dict(data.get("aspiration", {})),
        )
    
    def get_overall_strain(self) -> float:
        """
        Calculate overall strain score (0-1).
        """
        bio_strain = self.bio.get_strain_score()
        load_strain = self.load.get_strain_score()
        
        # Weight biology slightly more
        return bio_strain * 0.6 + load_strain * 0.4
    
    def get_capacity_level(self) -> str:
        """
        Get human-readable capacity level.
        """
        strain = self.get_overall_strain()
        
        if strain >= 0.8:
            return "very_limited"
        elif strain >= 0.6:
            return "limited"
        elif strain >= 0.4:
            return "moderate"
        elif strain >= 0.2:
            return "good"
        else:
            return "excellent"
    
    def needs_small_version(self) -> bool:
        """
        Check if recommendations should be "small version".
        """
        return self.get_overall_strain() >= 0.6


# -----------------------------------------------------------------------------
# State History Entry
# -----------------------------------------------------------------------------

@dataclass
class StateHistoryEntry:
    """
    A historical snapshot of state.
    """
    timestamp: str
    bio_energy: str
    bio_stress: str
    load_cognitive: str
    aspiration_momentum: str
    overall_strain: float
    notes: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StateHistoryEntry":
        return cls(
            timestamp=data.get("timestamp", ""),
            bio_energy=data.get("bio_energy", "moderate"),
            bio_stress=data.get("bio_stress", "moderate"),
            load_cognitive=data.get("load_cognitive", "moderate"),
            aspiration_momentum=data.get("aspiration_momentum", "steady"),
            overall_strain=float(data.get("overall_strain", 0.5)),
            notes=data.get("notes"),
        )


# -----------------------------------------------------------------------------
# Human State Manager
# -----------------------------------------------------------------------------

class HumanStateManager:
    """
    v0.5.9 Human State Manager
    
    Manages:
    - Current state (bio, load, aspiration)
    - State history for evolution tracking
    - Check-in streaks and patterns
    - Integration hooks for policy/interpretation
    
    All updates are user-initiated or confirm-gated.
    """

    MAX_HISTORY_SIZE = 100

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.state_file = data_dir / "human_state.json"
        
        self._state: Optional[HumanState] = None
        self._history: List[StateHistoryEntry] = []
        self._loaded: bool = False
        self._lock = threading.Lock()

    # ---------- File Operations ----------

    def _load(self) -> None:
        """Load state from disk."""
        if self._loaded:
            return

        with self._lock:
            if self._loaded:
                return

            if not self.state_file.exists():
                self._state = HumanState(
                    created_at=datetime.now(timezone.utc).isoformat(),
                )
                self._history = []
                self._loaded = True
                self._save_unlocked()
                return

            try:
                raw = json.loads(self.state_file.read_text(encoding="utf-8"))
                self._state = HumanState.from_dict(raw.get("current", {}))
                
                self._history = []
                for entry_data in raw.get("history", []):
                    try:
                        entry = StateHistoryEntry.from_dict(entry_data)
                        self._history.append(entry)
                    except Exception:
                        continue
            except Exception:
                self._state = HumanState(
                    created_at=datetime.now(timezone.utc).isoformat(),
                )
                self._history = []

            self._loaded = True

    def _save(self) -> None:
        """Save state to disk."""
        with self._lock:
            self._save_unlocked()

    def _save_unlocked(self) -> None:
        """Save without lock."""
        data = {
            "version": "0.5.9",
            "current": self._state.to_dict() if self._state else {},
            "history": [e.to_dict() for e in self._history[-self.MAX_HISTORY_SIZE:]],
        }
        
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

    # ---------- State Access ----------

    def get_state(self) -> HumanState:
        """Get current human state."""
        self._load()
        return self._state or HumanState()

    def get_bio_state(self) -> BiologyState:
        """Get biology state."""
        return self.get_state().bio

    def get_load_state(self) -> LoadState:
        """Get load state."""
        return self.get_state().load

    def get_aspiration_state(self) -> AspirationState:
        """Get aspiration state."""
        return self.get_state().aspiration

    # ---------- State Updates ----------

    def update_bio(
        self,
        energy: Optional[EnergyLevel] = None,
        sleep_quality: Optional[str] = None,
        sleep_hours: Optional[float] = None,
        stress: Optional[StressLevel] = None,
        physical_notes: Optional[str] = None,
    ) -> BiologyState:
        """
        Update biology state.
        """
        self._load()

        with self._lock:
            bio = self._state.bio
            
            if energy:
                bio.energy = energy
            if sleep_quality is not None:
                bio.sleep_quality = sleep_quality
            if sleep_hours is not None:
                bio.sleep_hours = sleep_hours
            if stress:
                bio.stress = stress
            if physical_notes is not None:
                bio.physical_notes = physical_notes
            
            bio.last_updated = datetime.now(timezone.utc).isoformat()
            self._save_unlocked()
            
            return bio

    def update_load(
        self,
        cognitive_load: Optional[LoadLevel] = None,
        active_tasks: Optional[int] = None,
        pending_decisions: Optional[int] = None,
        overwhelm_feeling: Optional[str] = None,
        focus_quality: Optional[str] = None,
    ) -> LoadState:
        """
        Update load state.
        """
        self._load()

        with self._lock:
            load = self._state.load
            
            if cognitive_load:
                load.cognitive_load = cognitive_load
            if active_tasks is not None:
                load.active_tasks = active_tasks
            if pending_decisions is not None:
                load.pending_decisions = pending_decisions
            if overwhelm_feeling is not None:
                load.overwhelm_feeling = overwhelm_feeling
            if focus_quality is not None:
                load.focus_quality = focus_quality
            
            load.last_updated = datetime.now(timezone.utc).isoformat()
            self._save_unlocked()
            
            return load

    def update_aspiration(
        self,
        current_focus: Optional[str] = None,
        growth_areas: Optional[List[str]] = None,
        momentum: Optional[MomentumLevel] = None,
        add_win: Optional[str] = None,
        add_blocker: Optional[str] = None,
        remove_blocker: Optional[str] = None,
    ) -> AspirationState:
        """
        Update aspiration state.
        """
        self._load()

        with self._lock:
            asp = self._state.aspiration
            
            if current_focus is not None:
                asp.current_focus = current_focus
            if growth_areas is not None:
                asp.growth_areas = growth_areas
            if momentum:
                asp.momentum = momentum
            
            if add_win:
                asp.recent_wins = [add_win] + asp.recent_wins[:4]  # Keep last 5
            if add_blocker:
                if add_blocker not in asp.blockers:
                    asp.blockers.append(add_blocker)
            if remove_blocker and remove_blocker in asp.blockers:
                asp.blockers.remove(remove_blocker)
            
            asp.last_updated = datetime.now(timezone.utc).isoformat()
            self._save_unlocked()
            
            return asp

    # ---------- Check-in ----------

    def do_checkin(self, notes: Optional[str] = None) -> StateHistoryEntry:
        """
        Record a check-in and add to history.
        """
        self._load()

        with self._lock:
            now = datetime.now(timezone.utc)
            
            # Create history entry
            entry = StateHistoryEntry(
                timestamp=now.isoformat(),
                bio_energy=self._state.bio.energy,
                bio_stress=self._state.bio.stress,
                load_cognitive=self._state.load.cognitive_load,
                aspiration_momentum=self._state.aspiration.momentum,
                overall_strain=self._state.get_overall_strain(),
                notes=notes,
            )
            
            self._history.append(entry)
            
            # Update streak
            last = self._state.last_checkin
            if last:
                try:
                    last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                    days_since = (now - last_dt).days
                    if days_since <= 1:
                        self._state.checkin_streak += 1
                    else:
                        self._state.checkin_streak = 1
                except ValueError:
                    self._state.checkin_streak = 1
            else:
                self._state.checkin_streak = 1
            
            self._state.last_checkin = now.isoformat()
            
            self._save_unlocked()
            
            return entry

    # ---------- History & Evolution ----------

    def get_history(self, limit: int = 10) -> List[StateHistoryEntry]:
        """Get recent state history."""
        self._load()
        return list(reversed(self._history[-limit:]))

    def get_evolution_summary(self) -> Dict[str, Any]:
        """
        Get evolution summary for status display.
        """
        self._load()

        state = self._state
        history = self._history
        
        # Calculate trends (if enough history)
        energy_trend = "stable"
        stress_trend = "stable"
        momentum_trend = "stable"
        
        if len(history) >= 3:
            recent = history[-3:]
            
            # Energy trend
            energy_vals = [ENERGY_VALUES.get(h.bio_energy, 3) for h in recent]
            if energy_vals[-1] > energy_vals[0]:
                energy_trend = "improving"
            elif energy_vals[-1] < energy_vals[0]:
                energy_trend = "declining"
            
            # Stress trend (inverted - lower is better)
            stress_vals = [STRESS_VALUES.get(h.bio_stress, 3) for h in recent]
            if stress_vals[-1] < stress_vals[0]:
                stress_trend = "improving"
            elif stress_vals[-1] > stress_vals[0]:
                stress_trend = "increasing"
            
            # Momentum trend
            momentum_vals = [MOMENTUM_VALUES.get(h.aspiration_momentum, 3) for h in recent]
            if momentum_vals[-1] > momentum_vals[0]:
                momentum_trend = "building"
            elif momentum_vals[-1] < momentum_vals[0]:
                momentum_trend = "slowing"
        
        return {
            "current": {
                "energy": state.bio.energy,
                "stress": state.bio.stress,
                "cognitive_load": state.load.cognitive_load,
                "momentum": state.aspiration.momentum,
                "capacity": state.get_capacity_level(),
                "strain": round(state.get_overall_strain(), 2),
            },
            "trends": {
                "energy": energy_trend,
                "stress": stress_trend,
                "momentum": momentum_trend,
            },
            "meta": {
                "checkin_streak": state.checkin_streak,
                "last_checkin": state.last_checkin,
                "history_entries": len(history),
            },
            "recommendations": self._get_recommendations(),
        }

    def _get_recommendations(self) -> List[str]:
        """
        Generate recommendations based on current state.
        """
        recs = []
        state = self._state
        
        # Energy recommendations
        if state.bio.energy in ("depleted", "low"):
            recs.append("Consider rest or a shorter work session")
        
        # Stress recommendations
        if state.bio.stress in ("overwhelmed", "high"):
            recs.append("Focus on one small task to build momentum")
        
        # Load recommendations
        if state.load.cognitive_load in ("overloaded", "heavy"):
            recs.append("Defer non-essential decisions")
        
        if state.load.active_tasks > 5:
            recs.append(f"You have {state.load.active_tasks} active tasks — consider trimming")
        
        # Momentum recommendations
        if state.aspiration.momentum in ("stalled", "slow"):
            recs.append("Celebrate a small win to rebuild momentum")
        
        # Blocker recommendations
        if state.aspiration.blockers:
            recs.append(f"Active blockers: {', '.join(state.aspiration.blockers[:2])}")
        
        # Small version recommendation
        if state.needs_small_version():
            recs.insert(0, "⚡ Consider 'small version' tasks today")
        
        return recs[:5]

    # ---------- Integration Hooks ----------

    def get_policy_context(self) -> Dict[str, Any]:
        """
        Get context for policy engine integration.
        """
        self._load()
        state = self._state
        
        return {
            "needs_small_version": state.needs_small_version(),
            "capacity": state.get_capacity_level(),
            "strain": state.get_overall_strain(),
            "energy": state.bio.energy,
            "stress": state.bio.stress,
            "cognitive_load": state.load.cognitive_load,
            "momentum": state.aspiration.momentum,
        }

    # ---------- Export/Import ----------

    def export_state(self) -> Dict[str, Any]:
        """Export state for snapshots."""
        self._load()
        return {
            "current": self._state.to_dict() if self._state else {},
            "history": [e.to_dict() for e in self._history],
        }

    def import_state(self, data: Dict[str, Any]) -> None:
        """Import state from snapshot."""
        with self._lock:
            self._state = HumanState.from_dict(data.get("current", {}))
            self._history = []
            for entry_data in data.get("history", []):
                try:
                    entry = StateHistoryEntry.from_dict(entry_data)
                    self._history.append(entry)
                except Exception:
                    continue
            self._loaded = True
            self._save_unlocked()
