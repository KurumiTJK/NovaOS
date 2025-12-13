# kernel/identity_manager.py
"""
v0.5.5 — Identity Profile & Versioned Self

Manages user identity with:
- Current profile (active identity snapshot)
- Version history (past snapshots for evolution tracking)
- Explicit-only mutations (no automatic changes)
- Re-confirmation hooks for identity-tagged memories

Core Principle: Identity Safety
- User identity is fluid and evolving
- Past versions inform but don't constrain
- All changes require explicit user action
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import threading
import uuid


# -----------------------------------------------------------------------------
# Identity Profile Data Model
# -----------------------------------------------------------------------------

@dataclass
class IdentityTraits:
    """
    Core identity traits.
    
    All fields are optional — identity is what the user defines.
    """
    name: Optional[str] = None
    goals: List[str] = field(default_factory=list)
    values: List[str] = field(default_factory=list)
    context: Optional[str] = None  # Current life context
    roles: List[str] = field(default_factory=list)  # e.g., "developer", "founder"
    strengths: List[str] = field(default_factory=list)
    growth_areas: List[str] = field(default_factory=list)
    custom: Dict[str, Any] = field(default_factory=dict)  # User-defined fields

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IdentityTraits":
        return cls(
            name=data.get("name"),
            goals=list(data.get("goals", [])),
            values=list(data.get("values", [])),
            context=data.get("context"),
            roles=list(data.get("roles", [])),
            strengths=list(data.get("strengths", [])),
            growth_areas=list(data.get("growth_areas", [])),
            custom=dict(data.get("custom", {})),
        )

    def merge(self, other: "IdentityTraits") -> "IdentityTraits":
        """
        Merge another traits object into this one.
        Non-empty values from other override this.
        """
        return IdentityTraits(
            name=other.name or self.name,
            goals=other.goals if other.goals else self.goals,
            values=other.values if other.values else self.values,
            context=other.context or self.context,
            roles=other.roles if other.roles else self.roles,
            strengths=other.strengths if other.strengths else self.strengths,
            growth_areas=other.growth_areas if other.growth_areas else self.growth_areas,
            custom={**self.custom, **other.custom},
        )


@dataclass
class IdentityProfile:
    """
    A versioned identity profile.
    """
    id: str
    created_at: str  # ISO format
    updated_at: str  # ISO format
    traits: IdentityTraits
    notes: str = ""
    version: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "traits": self.traits.to_dict(),
            "notes": self.notes,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IdentityProfile":
        return cls(
            id=data.get("id", _generate_profile_id()),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            updated_at=data.get("updated_at", datetime.now(timezone.utc).isoformat()),
            traits=IdentityTraits.from_dict(data.get("traits", {})),
            notes=data.get("notes", ""),
            version=int(data.get("version", 1)),
        )

    def snapshot(self) -> Dict[str, Any]:
        """Create a snapshot dict for history."""
        return {
            "id": self.id,
            "snapshot_at": datetime.now(timezone.utc).isoformat(),
            "traits": self.traits.to_dict(),
            "notes": self.notes,
            "version": self.version,
        }


@dataclass
class IdentityHistoryEntry:
    """
    A historical snapshot of identity.
    """
    id: str
    snapshot_at: str
    traits: IdentityTraits
    notes: str = ""
    version: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "snapshot_at": self.snapshot_at,
            "traits": self.traits.to_dict(),
            "notes": self.notes,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IdentityHistoryEntry":
        return cls(
            id=data.get("id", "unknown"),
            snapshot_at=data.get("snapshot_at", ""),
            traits=IdentityTraits.from_dict(data.get("traits", {})),
            notes=data.get("notes", ""),
            version=int(data.get("version", 1)),
        )


# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------

def _generate_profile_id() -> str:
    """Generate a unique profile ID."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    short_uuid = uuid.uuid4().hex[:6]
    return f"profile-{ts}-{short_uuid}"


def _now_iso() -> str:
    """Get current time in ISO format."""
    return datetime.now(timezone.utc).isoformat()


# -----------------------------------------------------------------------------
# Identity Manager
# -----------------------------------------------------------------------------

class IdentityManager:
    """
    v0.5.5 Identity Manager
    
    Manages versioned identity profiles with:
    - Current active profile
    - Historical snapshots
    - Explicit-only mutations
    - Export/import for snapshots
    
    Core principle: Identity Safety
    - No automatic mutations
    - Past versions are informational, not binding
    - User controls all changes
    """

    MAX_HISTORY_SIZE = 50  # Keep last N snapshots

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.identity_file = data_dir / "identity_profile.json"
        
        self._current: Optional[IdentityProfile] = None
        self._history: List[IdentityHistoryEntry] = []
        self._loaded: bool = False
        self._lock = threading.Lock()

    # ---------- File Operations ----------

    def _load(self) -> None:
        """Load identity profile from disk."""
        if self._loaded:
            return

        with self._lock:
            if self._loaded:
                return

            if not self.identity_file.exists():
                # Initialize with empty profile
                self._current = IdentityProfile(
                    id=_generate_profile_id(),
                    created_at=_now_iso(),
                    updated_at=_now_iso(),
                    traits=IdentityTraits(),
                    notes="Initial empty profile",
                )
                self._history = []
                self._loaded = True
                self._save_unlocked()
                return

            try:
                raw = json.loads(self.identity_file.read_text(encoding="utf-8"))
                
                # Load current profile
                current_data = raw.get("current_profile")
                if current_data:
                    self._current = IdentityProfile.from_dict(current_data)
                else:
                    self._current = IdentityProfile(
                        id=_generate_profile_id(),
                        created_at=_now_iso(),
                        updated_at=_now_iso(),
                        traits=IdentityTraits(),
                    )

                # Load history
                self._history = []
                for entry_data in raw.get("history", []):
                    try:
                        entry = IdentityHistoryEntry.from_dict(entry_data)
                        self._history.append(entry)
                    except Exception:
                        continue

            except Exception:
                # Initialize with empty on error
                self._current = IdentityProfile(
                    id=_generate_profile_id(),
                    created_at=_now_iso(),
                    updated_at=_now_iso(),
                    traits=IdentityTraits(),
                )
                self._history = []

            self._loaded = True

    def _save(self) -> None:
        """Save identity profile to disk."""
        with self._lock:
            self._save_unlocked()

    def _save_unlocked(self) -> None:
        """Save without lock (for internal use)."""
        data = {
            "version": "0.5.5",
            "current_profile": self._current.to_dict() if self._current else None,
            "history": [entry.to_dict() for entry in self._history],
        }
        
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.identity_file.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

    # ---------- Public API ----------

    def get_current(self) -> Optional[IdentityProfile]:
        """Get the current identity profile."""
        self._load()
        return self._current

    def get_traits(self) -> IdentityTraits:
        """Get current identity traits (convenience method)."""
        self._load()
        if self._current:
            return self._current.traits
        return IdentityTraits()

    def get_history(self, limit: int = 10) -> List[IdentityHistoryEntry]:
        """Get identity history (most recent first)."""
        self._load()
        # Return in reverse chronological order
        sorted_history = sorted(
            self._history,
            key=lambda x: x.snapshot_at,
            reverse=True
        )
        return sorted_history[:limit]

    def update_traits(
        self,
        traits: Optional[IdentityTraits] = None,
        notes: str = "",
        snapshot_before: bool = True,
        **kwargs
    ) -> IdentityProfile:
        """
        Update identity traits.
        
        Args:
            traits: New traits to merge (or use kwargs for individual fields)
            notes: Notes for this update
            snapshot_before: If True, save current state to history first
            **kwargs: Individual trait fields (name, goals, values, etc.)
            
        Returns:
            Updated IdentityProfile
        """
        self._load()

        with self._lock:
            # Snapshot current state before update
            if snapshot_before and self._current:
                self._add_to_history_unlocked(self._current)

            # Build new traits
            if traits:
                new_traits = traits
            else:
                # Build from kwargs
                new_traits = IdentityTraits(
                    name=kwargs.get("name"),
                    goals=kwargs.get("goals", []),
                    values=kwargs.get("values", []),
                    context=kwargs.get("context"),
                    roles=kwargs.get("roles", []),
                    strengths=kwargs.get("strengths", []),
                    growth_areas=kwargs.get("growth_areas", []),
                    custom=kwargs.get("custom", {}),
                )

            # Merge with current
            if self._current:
                merged_traits = self._current.traits.merge(new_traits)
                self._current.traits = merged_traits
                self._current.updated_at = _now_iso()
                self._current.notes = notes or self._current.notes
                self._current.version += 1
            else:
                self._current = IdentityProfile(
                    id=_generate_profile_id(),
                    created_at=_now_iso(),
                    updated_at=_now_iso(),
                    traits=new_traits,
                    notes=notes,
                )

            self._save_unlocked()
            return self._current

    def set_trait(self, key: str, value: Any, notes: str = "") -> IdentityProfile:
        """
        Set a single trait value.
        
        Convenience method for updating one field at a time.
        """
        self._load()

        with self._lock:
            # Snapshot first
            if self._current:
                self._add_to_history_unlocked(self._current)

            if not self._current:
                self._current = IdentityProfile(
                    id=_generate_profile_id(),
                    created_at=_now_iso(),
                    updated_at=_now_iso(),
                    traits=IdentityTraits(),
                )

            # Update the specific trait
            traits = self._current.traits
            if key == "name":
                traits.name = str(value) if value else None
            elif key == "goals":
                traits.goals = list(value) if isinstance(value, list) else [str(value)]
            elif key == "values":
                traits.values = list(value) if isinstance(value, list) else [str(value)]
            elif key == "context":
                traits.context = str(value) if value else None
            elif key == "roles":
                traits.roles = list(value) if isinstance(value, list) else [str(value)]
            elif key == "strengths":
                traits.strengths = list(value) if isinstance(value, list) else [str(value)]
            elif key == "growth_areas":
                traits.growth_areas = list(value) if isinstance(value, list) else [str(value)]
            else:
                # Custom field
                traits.custom[key] = value

            self._current.updated_at = _now_iso()
            self._current.version += 1
            if notes:
                self._current.notes = notes

            self._save_unlocked()
            return self._current

    def snapshot(self, notes: str = "") -> IdentityHistoryEntry:
        """
        Create a snapshot of current identity without changing it.
        
        Useful for marking milestones or before major life changes.
        """
        self._load()

        with self._lock:
            if not self._current:
                raise ValueError("No current profile to snapshot")

            entry = IdentityHistoryEntry(
                id=self._current.id,
                snapshot_at=_now_iso(),
                traits=IdentityTraits.from_dict(self._current.traits.to_dict()),
                notes=notes or f"Manual snapshot",
                version=self._current.version,
            )
            
            self._history.append(entry)
            self._trim_history_unlocked()
            self._save_unlocked()
            
            return entry

    def restore_from_history(self, snapshot_id: str) -> Optional[IdentityProfile]:
        """
        Restore identity from a historical snapshot.
        
        Creates a new profile based on the historical traits.
        Current state is saved to history first.
        """
        self._load()

        with self._lock:
            # Find the snapshot
            target = None
            for entry in self._history:
                if entry.id == snapshot_id or entry.snapshot_at == snapshot_id:
                    target = entry
                    break

            if not target:
                return None

            # Save current to history
            if self._current:
                self._add_to_history_unlocked(self._current)

            # Create new profile from historical traits
            self._current = IdentityProfile(
                id=_generate_profile_id(),
                created_at=_now_iso(),
                updated_at=_now_iso(),
                traits=IdentityTraits.from_dict(target.traits.to_dict()),
                notes=f"Restored from snapshot {target.snapshot_at}",
                version=1,
            )

            self._save_unlocked()
            return self._current

    def clear_history(self) -> int:
        """Clear all history. Returns count cleared."""
        self._load()
        with self._lock:
            count = len(self._history)
            self._history = []
            self._save_unlocked()
            return count

    def _add_to_history_unlocked(self, profile: IdentityProfile) -> None:
        """Add profile to history (no lock)."""
        entry = IdentityHistoryEntry(
            id=profile.id,
            snapshot_at=_now_iso(),
            traits=IdentityTraits.from_dict(profile.traits.to_dict()),
            notes=profile.notes,
            version=profile.version,
        )
        self._history.append(entry)
        self._trim_history_unlocked()

    def _trim_history_unlocked(self) -> None:
        """Trim history to max size."""
        if len(self._history) > self.MAX_HISTORY_SIZE:
            # Keep most recent
            self._history = sorted(
                self._history,
                key=lambda x: x.snapshot_at,
                reverse=True
            )[:self.MAX_HISTORY_SIZE]

    # ---------- Export/Import ----------

    def export_state(self) -> Dict[str, Any]:
        """Export identity state for system snapshots."""
        self._load()
        return {
            "version": "0.5.5",
            "current_profile": self._current.to_dict() if self._current else None,
            "history": [entry.to_dict() for entry in self._history],
        }

    def import_state(self, state: Dict[str, Any]) -> None:
        """Import identity state from system snapshot."""
        with self._lock:
            current_data = state.get("current_profile")
            if current_data:
                self._current = IdentityProfile.from_dict(current_data)
            else:
                self._current = None

            self._history = []
            for entry_data in state.get("history", []):
                try:
                    entry = IdentityHistoryEntry.from_dict(entry_data)
                    self._history.append(entry)
                except Exception:
                    continue

            self._loaded = True
            self._save_unlocked()

    # ---------- Introspection ----------

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of identity state."""
        self._load()
        
        current_summary = None
        if self._current:
            traits = self._current.traits
            current_summary = {
                "id": self._current.id,
                "name": traits.name,
                "goals_count": len(traits.goals),
                "values_count": len(traits.values),
                "roles": traits.roles,
                "version": self._current.version,
                "updated_at": self._current.updated_at,
            }

        return {
            "has_profile": self._current is not None,
            "current": current_summary,
            "history_count": len(self._history),
        }
