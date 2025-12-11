# kernel/identity_section.py
"""
NovaOS Identity Section v1.0.0

The Identity Section is the character sheet and XP ledger for NovaOS Life RPG.

This module provides:
- Full player profile (name, archetype, vibe, goals)
- Global progression (level, XP, current_xp, xp_to_next, total_xp)
- Per-module XP tracking (internally "modules", displayed as "Domains")
- Title management (equipped + history)
- XP event handling (ledger for XP from workflow, timerhythm, presence, etc.)
- XP history (rolling log of recent XP events)
- Archetype evolution based on level and top modules

IMPORTANT:
- Identity does NOT decide XP amounts - it receives XP events from other sections.
- "modules" terminology is used internally; UI displays them as "Domains".
- This module is backwards-compatible with existing player_profile.json data.
"""

from __future__ import annotations

import json
import uuid
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("nova.identity")


# =============================================================================
# CONSTANTS — XP Curves (editable for tuning)
# =============================================================================

# Global level curve: xp_to_next(level) = 100 * level
# E.g., Level 1 needs 100 XP, Level 2 needs 200 XP, etc.
def xp_for_level(level: int) -> int:
    """Calculate total XP required to reach a given level."""
    # Sum of (100 * i) for i in 1..(level-1)
    # = 100 * (1 + 2 + ... + (level-1)) = 100 * (level-1) * level / 2
    if level <= 1:
        return 0
    return 50 * (level - 1) * level


def level_from_total_xp(total_xp: int) -> Tuple[int, int, int]:
    """
    Calculate level, current_xp, and xp_to_next from total_xp.
    
    Returns: (level, current_xp, xp_to_next)
    """
    level = 1
    while True:
        xp_needed = 100 * level  # XP to go from this level to next
        xp_for_this_level = xp_for_level(level)
        xp_for_next_level = xp_for_level(level + 1)
        
        if total_xp < xp_for_next_level:
            current_xp = total_xp - xp_for_this_level
            xp_to_next = xp_needed - current_xp
            return level, current_xp, xp_to_next
        
        level += 1
        if level > 100:  # Safety cap
            current_xp = total_xp - xp_for_level(100)
            return 100, current_xp, 0


# Module level curve: xp_to_next_module_level = 50 * module_level
def module_level_from_xp(xp: int) -> Tuple[int, int, int]:
    """
    Calculate module level, current_xp, and xp_to_next from module XP.
    
    Returns: (level, current_xp, xp_to_next)
    """
    level = 1
    accumulated = 0
    while True:
        xp_for_next = 50 * level
        if accumulated + xp_for_next > xp:
            current_xp = xp - accumulated
            xp_to_next = xp_for_next - current_xp
            return level, current_xp, xp_to_next
        accumulated += xp_for_next
        level += 1
        if level > 50:  # Safety cap
            return 50, xp - accumulated, 0


# Archetype rank thresholds
RANK_THRESHOLDS = [
    (1, "Apprentice"),   # Level 1-4
    (5, "Specialist"),   # Level 5-9
    (10, "Architect"),   # Level 10-14
    (15, "Master"),      # Level 15+
]


def get_rank_for_level(level: int) -> str:
    """Get the archetype rank for a given level."""
    rank = "Apprentice"
    for threshold, name in RANK_THRESHOLDS:
        if level >= threshold:
            rank = name
    return rank


# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class Archetype:
    """
    Dynamic archetype that evolves with level, titles, and top modules.
    
    Attributes:
        current: Full archetype title (e.g., "Azure Recon Specialist")
        base_theme: User-chosen base theme (e.g., "Cloud Rogue", "Red Team")
        rank: Current rank based on level (Apprentice/Specialist/Architect/Master)
        last_updated_level: Level at which archetype last evolved
    """
    current: str = "Apprentice"
    base_theme: str = "Explorer"
    rank: str = "Apprentice"
    last_updated_level: int = 1
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "current": self.current,
            "base_theme": self.base_theme,
            "rank": self.rank,
            "last_updated_level": self.last_updated_level,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Archetype":
        return cls(
            current=data.get("current", "Apprentice"),
            base_theme=data.get("base_theme", "Explorer"),
            rank=data.get("rank", "Apprentice"),
            last_updated_level=data.get("last_updated_level", 1),
        )


@dataclass
class Goal:
    """
    A long-term goal tracked by the identity section.
    
    Attributes:
        id: Unique goal ID
        text: Goal description
        status: "active" | "paused" | "completed"
        category: Optional category (e.g., "career", "business", "finance")
        priority: "low" | "medium" | "high" | None
        created_at: ISO timestamp
        completed_at: ISO timestamp (if completed)
    """
    id: str
    text: str
    status: str = "active"
    category: Optional[str] = None
    priority: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "status": self.status,
            "category": self.category,
            "priority": self.priority,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Goal":
        return cls(
            id=data.get("id", str(uuid.uuid4())[:8]),
            text=data.get("text", ""),
            status=data.get("status", "active"),
            category=data.get("category"),
            priority=data.get("priority"),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            completed_at=data.get("completed_at"),
        )


@dataclass
class ModuleXP:
    """
    XP tracking for a single module (displayed as "Domain" in UI).
    
    Attributes:
        xp: Total XP earned in this module
        level: Current level (derived from xp)
    """
    xp: int = 0
    level: int = 1
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "xp": self.xp,
            "level": self.level,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModuleXP":
        xp = data.get("xp", 0)
        # Also support legacy format with "tier" instead of "level"
        level = data.get("level") or data.get("tier", 1)
        return cls(xp=xp, level=level)
    
    def recalculate_level(self) -> None:
        """Recalculate level from XP."""
        self.level, _, _ = module_level_from_xp(self.xp)


@dataclass
class Title:
    """
    A title earned by the player.
    
    Attributes:
        id: Unique title ID
        text: The title text
        source: "workflow" | "macro_goal" | "milestone" | "debug" | "manual"
        module: Which module/domain this relates to (optional)
        earned_at: ISO timestamp
        meta: Extra metadata (quest_id, difficulty, etc.)
    """
    id: str
    text: str
    source: str = "manual"
    module: Optional[str] = None
    earned_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    meta: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "source": self.source,
            "module": self.module,
            "earned_at": self.earned_at,
            "meta": self.meta,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Title":
        if isinstance(data, str):
            # Handle legacy format (just a string)
            return cls(
                id=str(uuid.uuid4())[:8],
                text=data,
                source="legacy",
            )
        return cls(
            id=data.get("id", str(uuid.uuid4())[:8]),
            text=data.get("text", ""),
            source=data.get("source", "manual"),
            module=data.get("module"),
            earned_at=data.get("earned_at", datetime.now(timezone.utc).isoformat()),
            meta=data.get("meta"),
        )


@dataclass
class XPEvent:
    """
    A single XP event in the history.
    
    Attributes:
        amount: XP amount awarded
        source: "workflow" | "timerhythm_daily" | "timerhythm_weekly" | "presence" | "debug"
        module: Which module received XP (optional)
        description: Human-readable description
        timestamp: ISO timestamp
    """
    amount: int
    source: str
    module: Optional[str] = None
    description: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "amount": self.amount,
            "source": self.source,
            "module": self.module,
            "description": self.description,
            "timestamp": self.timestamp,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "XPEvent":
        return cls(
            amount=data.get("amount", 0),
            source=data.get("source", "unknown"),
            module=data.get("module"),
            description=data.get("description", ""),
            timestamp=data.get("timestamp", datetime.now(timezone.utc).isoformat()),
        )


@dataclass
class IdentityState:
    """
    The complete identity state for the player.
    
    This is the canonical data model for the Identity Section.
    """
    # Core profile
    display_name: str = "Player"
    vibe_tags: List[str] = field(default_factory=list)
    
    # Archetype
    archetype: Archetype = field(default_factory=Archetype)
    
    # Goals
    goals: List[Goal] = field(default_factory=list)
    
    # Global progression
    level: int = 1
    current_xp: int = 0
    xp_to_next: int = 100
    total_xp: int = 0
    xp_by_source: Dict[str, int] = field(default_factory=dict)
    
    # Modules (displayed as "Domains" in UI)
    modules: Dict[str, ModuleXP] = field(default_factory=dict)
    
    # Titles
    equipped_title: Optional[str] = None
    titles: List[Title] = field(default_factory=list)
    
    # XP History
    xp_history: List[XPEvent] = field(default_factory=list)
    
    # Metadata
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    version: str = "1.0.0"
    
    # Legacy compatibility fields (from old PlayerProfile)
    visual_unlocks: List[str] = field(default_factory=list)
    unlocked_shortcuts: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "display_name": self.display_name,
            "vibe_tags": self.vibe_tags,
            "archetype": self.archetype.to_dict(),
            "goals": [g.to_dict() for g in self.goals],
            "level": self.level,
            "current_xp": self.current_xp,
            "xp_to_next": self.xp_to_next,
            "total_xp": self.total_xp,
            "xp_by_source": self.xp_by_source,
            "modules": {k: v.to_dict() for k, v in self.modules.items()},
            "equipped_title": self.equipped_title,
            "titles": [t.to_dict() for t in self.titles],
            "xp_history": [e.to_dict() for e in self.xp_history],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "version": self.version,
            # Legacy
            "visual_unlocks": self.visual_unlocks,
            "unlocked_shortcuts": self.unlocked_shortcuts,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IdentityState":
        """Create IdentityState from dict, with migration from legacy formats."""
        
        # Parse archetype
        archetype_data = data.get("archetype")
        if isinstance(archetype_data, dict):
            archetype = Archetype.from_dict(archetype_data)
        else:
            archetype = Archetype()
        
        # Parse goals
        goals = []
        for g in data.get("goals", []):
            if isinstance(g, dict):
                goals.append(Goal.from_dict(g))
            elif isinstance(g, str):
                # Legacy: just a string
                goals.append(Goal(id=str(uuid.uuid4())[:8], text=g))
        
        # Parse modules (with migration from DomainXP format)
        modules = {}
        modules_data = data.get("modules") or data.get("domains", {})
        for k, v in modules_data.items():
            if isinstance(v, dict):
                modules[k] = ModuleXP.from_dict(v)
            elif isinstance(v, int):
                modules[k] = ModuleXP(xp=v, level=1)
                modules[k].recalculate_level()
        
        # Parse titles (with migration from legacy string list)
        titles = []
        for t in data.get("titles", []):
            titles.append(Title.from_dict(t))
        
        # Parse XP history
        xp_history = []
        for e in data.get("xp_history", []):
            if isinstance(e, dict):
                xp_history.append(XPEvent.from_dict(e))
        
        # Get progression values
        total_xp = data.get("total_xp", 0)
        
        # Recalculate level/current_xp/xp_to_next from total_xp if not provided
        if "level" in data and "current_xp" in data:
            level = data.get("level", 1)
            current_xp = data.get("current_xp", 0)
            xp_to_next = data.get("xp_to_next", 100)
        else:
            level, current_xp, xp_to_next = level_from_total_xp(total_xp)
        
        return cls(
            display_name=data.get("display_name") or data.get("name", "Player"),
            vibe_tags=data.get("vibe_tags", []),
            archetype=archetype,
            goals=goals,
            level=level,
            current_xp=current_xp,
            xp_to_next=xp_to_next,
            total_xp=total_xp,
            xp_by_source=data.get("xp_by_source", {}),
            modules=modules,
            equipped_title=data.get("equipped_title"),
            titles=titles,
            xp_history=xp_history,
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            updated_at=data.get("updated_at", datetime.now(timezone.utc).isoformat()),
            version=data.get("version", "1.0.0"),
            visual_unlocks=data.get("visual_unlocks", []),
            unlocked_shortcuts=data.get("unlocked_shortcuts", []),
        )


# =============================================================================
# XP EVENT CONTRACT
# =============================================================================

@dataclass
class XPEventInput:
    """
    Input structure for XP events sent from other sections.
    
    This is the contract other sections must follow when sending XP to Identity.
    """
    source: str  # "workflow" | "timerhythm_daily" | "timerhythm_weekly" | "presence" | "debug"
    amount: int
    module: Optional[str] = None
    description: str = ""
    metadata: Optional[Dict[str, Any]] = None
    timestamp: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "amount": self.amount,
            "module": self.module,
            "description": self.description,
            "metadata": self.metadata,
            "timestamp": self.timestamp or datetime.now(timezone.utc).isoformat(),
        }


@dataclass
class XPEventResult:
    """
    Result of applying an XP event.
    """
    xp_gained: int
    new_level: int
    level_up: bool
    levels_gained: int = 0
    affected_module: Optional[str] = None
    module_level_up: bool = False
    new_module_level: int = 0
    archetype_evolved: bool = False
    new_archetype: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# =============================================================================
# ARCHETYPE EVOLUTION
# =============================================================================

# Module flavor mapping for archetype generation
MODULE_FLAVORS = {
    "cybersecurity": ["Cyber", "Shadow", "Recon", "Cloud", "Red Team"],
    "cyber": ["Cyber", "Shadow", "Recon", "Cloud", "Red Team"],
    "business": ["Strategist", "Venture", "Architect", "Growth"],
    "real_estate": ["Estate", "Property", "Land", "Asset"],
    "finance": ["Capital", "Wealth", "Investment", "Asset"],
    "health": ["Vitality", "Wellness", "Life", "Energy"],
    "meta": ["Meta", "Reflection", "Insight", "Mind"],
}


def evolve_archetype(
    state: IdentityState,
    force_update: bool = False,
) -> Tuple[bool, Optional[str]]:
    """
    Evolve the archetype based on level, modules, and base_theme.
    
    Returns: (evolved, new_archetype_string_or_None)
    """
    # Get new rank based on level
    new_rank = get_rank_for_level(state.level)
    
    # Only evolve if rank changed or force_update
    if not force_update and new_rank == state.archetype.rank:
        return False, None
    
    # Find top module by XP
    top_module = None
    top_xp = 0
    for mod_id, mod_data in state.modules.items():
        if mod_data.xp > top_xp:
            top_xp = mod_data.xp
            top_module = mod_id
    
    # Build archetype string
    base = state.archetype.base_theme or "Explorer"
    
    # Get module flavor
    flavor = ""
    if top_module:
        mod_lower = top_module.lower().replace(" ", "_")
        flavors = MODULE_FLAVORS.get(mod_lower, [])
        if flavors:
            flavor = flavors[0] + " "
    
    # Combine: "<flavor> <base_theme> <rank>" or "<base_theme> <rank>"
    if flavor:
        new_archetype = f"{flavor}{base} {new_rank}"
    else:
        new_archetype = f"{base} {new_rank}"
    
    # Update state
    state.archetype.rank = new_rank
    state.archetype.current = new_archetype
    state.archetype.last_updated_level = state.level
    
    return True, new_archetype


# =============================================================================
# IDENTITY SECTION MANAGER
# =============================================================================

class IdentitySectionManager:
    """
    Manages the Identity Section state and operations.
    
    This is the main API for interacting with the Identity Section.
    """
    
    MAX_XP_HISTORY = 50  # Rolling window for XP events
    
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.identity_file = self.data_dir / "identity.json"
        self._state: Optional[IdentityState] = None
        self._loaded = False
    
    # =========================================================================
    # PERSISTENCE
    # =========================================================================
    
    def _load(self) -> None:
        """Load identity state from disk with migration support."""
        if self._loaded:
            return
        
        # Try to load identity.json first
        if self.identity_file.exists():
            try:
                with open(self.identity_file) as f:
                    data = json.load(f)
                self._state = IdentityState.from_dict(data)
                self._loaded = True
                logger.info("Loaded identity from identity.json")
                return
            except Exception as e:
                logger.warning("Failed to load identity.json: %s", e)
        
        # Try to migrate from legacy player_profile.json
        legacy_file = self.data_dir / "player_profile.json"
        if legacy_file.exists():
            try:
                with open(legacy_file) as f:
                    legacy_data = json.load(f)
                self._state = self._migrate_from_legacy(legacy_data)
                self._loaded = True
                self._save()  # Save migrated data
                logger.info("Migrated identity from player_profile.json")
                return
            except Exception as e:
                logger.warning("Failed to migrate player_profile.json: %s", e)
        
        # Create new default state
        self._state = IdentityState()
        self._loaded = True
        self._save()
        logger.info("Created new identity state")
    
    def _migrate_from_legacy(self, legacy_data: Dict[str, Any]) -> IdentityState:
        """Migrate from legacy player_profile.json format."""
        # Map legacy fields to new format
        new_data = {
            "display_name": "Player",  # Legacy didn't have this
            "vibe_tags": [],
            "total_xp": legacy_data.get("total_xp", 0),
            "xp_by_source": {},
            "equipped_title": None,
            "visual_unlocks": legacy_data.get("visual_unlocks", []),
            "unlocked_shortcuts": legacy_data.get("unlocked_shortcuts", []),
            "created_at": legacy_data.get("created_at"),
            "updated_at": legacy_data.get("updated_at"),
        }
        
        # Migrate titles (legacy was just strings)
        titles = []
        for t in legacy_data.get("titles", []):
            if isinstance(t, str):
                titles.append({"text": t, "source": "legacy"})
            elif isinstance(t, dict):
                titles.append(t)
        new_data["titles"] = titles
        
        # Migrate domains/modules
        modules = {}
        domains = legacy_data.get("domains", {})
        for k, v in domains.items():
            if isinstance(v, dict):
                modules[k] = {
                    "xp": v.get("xp", 0),
                    "level": v.get("tier", 1),  # Legacy used "tier"
                }
            elif isinstance(v, int):
                modules[k] = {"xp": v, "level": 1}
        new_data["modules"] = modules
        
        return IdentityState.from_dict(new_data)
    
    def _save(self) -> None:
        """Save identity state to disk."""
        if not self._state:
            return
        
        self._state.updated_at = datetime.now(timezone.utc).isoformat()
        
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with open(self.identity_file, "w") as f:
            json.dump(self._state.to_dict(), f, indent=2)
    
    def reload(self) -> None:
        """Force reload from disk."""
        self._loaded = False
        self._state = None
        self._load()
    
    # =========================================================================
    # STATE ACCESS
    # =========================================================================
    
    def get_state(self) -> IdentityState:
        """Get the current identity state."""
        self._load()
        return self._state
    
    def get_profile_summary(self) -> Dict[str, Any]:
        """Get a summary of the profile for display."""
        self._load()
        s = self._state
        
        # Get top 3 modules by XP
        sorted_modules = sorted(
            [(k, v) for k, v in s.modules.items()],
            key=lambda x: -x[1].xp
        )[:3]
        
        # Get active goals
        active_goals = [g for g in s.goals if g.status == "active"][:3]
        
        # Get recent XP events
        recent_xp = s.xp_history[-3:] if s.xp_history else []
        
        return {
            "display_name": s.display_name,
            "archetype": s.archetype.to_dict(),
            "vibe_tags": s.vibe_tags,
            "level": s.level,
            "current_xp": s.current_xp,
            "xp_to_next": s.xp_to_next,
            "total_xp": s.total_xp,
            "equipped_title": s.equipped_title,
            "top_modules": [
                {"name": k, "xp": v.xp, "level": v.level}
                for k, v in sorted_modules
            ],
            "active_goals": [g.to_dict() for g in active_goals],
            "recent_xp": [e.to_dict() for e in reversed(recent_xp)],
            "title_count": len(s.titles),
        }
    
    # =========================================================================
    # XP ENGINE — Core XP Event Handler
    # =========================================================================
    
    def apply_xp_event(self, event: XPEventInput) -> XPEventResult:
        """
        Apply an XP event to the identity state.
        
        This is the central XP handler that other sections call.
        
        Args:
            event: XP event from workflow, timerhythm, presence, etc.
        
        Returns:
            XPEventResult with details of what changed
        """
        self._load()
        s = self._state
        
        # Validate
        if event.amount <= 0:
            logger.warning("Ignoring XP event with amount <= 0: %s", event.amount)
            return XPEventResult(
                xp_gained=0,
                new_level=s.level,
                level_up=False,
            )
        
        old_level = s.level
        result = XPEventResult(
            xp_gained=event.amount,
            new_level=s.level,
            level_up=False,
        )
        
        # Update total XP
        s.total_xp += event.amount
        
        # Update XP by source
        source_key = event.source
        s.xp_by_source[source_key] = s.xp_by_source.get(source_key, 0) + event.amount
        
        # Recalculate level
        new_level, new_current_xp, new_xp_to_next = level_from_total_xp(s.total_xp)
        s.level = new_level
        s.current_xp = new_current_xp
        s.xp_to_next = new_xp_to_next
        
        result.new_level = new_level
        if new_level > old_level:
            result.level_up = True
            result.levels_gained = new_level - old_level
        
        # Update module XP if provided
        if event.module:
            mod_id = event.module
            if mod_id not in s.modules:
                s.modules[mod_id] = ModuleXP()
            
            old_mod_level = s.modules[mod_id].level
            s.modules[mod_id].xp += event.amount
            s.modules[mod_id].recalculate_level()
            
            result.affected_module = mod_id
            result.new_module_level = s.modules[mod_id].level
            if s.modules[mod_id].level > old_mod_level:
                result.module_level_up = True
        
        # Check for archetype evolution on level up
        if result.level_up:
            evolved, new_arch = evolve_archetype(s)
            if evolved:
                result.archetype_evolved = True
                result.new_archetype = new_arch
        
        # Add to XP history
        xp_event = XPEvent(
            amount=event.amount,
            source=event.source,
            module=event.module,
            description=event.description,
            timestamp=event.timestamp or datetime.now(timezone.utc).isoformat(),
        )
        s.xp_history.append(xp_event)
        
        # Trim history
        if len(s.xp_history) > self.MAX_XP_HISTORY:
            s.xp_history = s.xp_history[-self.MAX_XP_HISTORY:]
        
        # Save
        self._save()
        
        logger.info(
            "Applied XP event: +%d from %s (module=%s) -> level %d",
            event.amount, event.source, event.module, s.level
        )
        
        return result
    
    # =========================================================================
    # PROFILE MANAGEMENT
    # =========================================================================
    
    def set_display_name(self, name: str) -> None:
        """Set the display name."""
        self._load()
        self._state.display_name = name
        self._save()
    
    def set_vibe_tags(self, tags: List[str]) -> None:
        """Set vibe tags."""
        self._load()
        self._state.vibe_tags = tags
        self._save()
    
    def set_base_theme(self, theme: str) -> None:
        """Set the archetype base theme and re-evolve."""
        self._load()
        self._state.archetype.base_theme = theme
        evolve_archetype(self._state, force_update=True)
        self._save()
    
    # =========================================================================
    # GOAL MANAGEMENT
    # =========================================================================
    
    def add_goal(
        self,
        text: str,
        category: Optional[str] = None,
        priority: Optional[str] = None,
    ) -> Goal:
        """Add a new goal."""
        self._load()
        goal = Goal(
            id=str(uuid.uuid4())[:8],
            text=text,
            status="active",
            category=category,
            priority=priority,
        )
        self._state.goals.append(goal)
        self._save()
        return goal
    
    def update_goal(
        self,
        goal_id: str,
        text: Optional[str] = None,
        status: Optional[str] = None,
        category: Optional[str] = None,
        priority: Optional[str] = None,
    ) -> Optional[Goal]:
        """Update an existing goal."""
        self._load()
        for g in self._state.goals:
            if g.id == goal_id:
                if text is not None:
                    g.text = text
                if status is not None:
                    g.status = status
                    if status == "completed":
                        g.completed_at = datetime.now(timezone.utc).isoformat()
                if category is not None:
                    g.category = category
                if priority is not None:
                    g.priority = priority
                self._save()
                return g
        return None
    
    def remove_goal(self, goal_id: str) -> bool:
        """Remove a goal."""
        self._load()
        for i, g in enumerate(self._state.goals):
            if g.id == goal_id:
                self._state.goals.pop(i)
                self._save()
                return True
        return False
    
    def get_active_goals(self) -> List[Goal]:
        """Get active goals."""
        self._load()
        return [g for g in self._state.goals if g.status == "active"]
    
    # =========================================================================
    # TITLE MANAGEMENT
    # =========================================================================
    
    def add_title(
        self,
        text: str,
        source: str = "manual",
        module: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
        auto_equip: bool = False,
    ) -> Title:
        """Add a new title."""
        self._load()
        
        # Check for duplicates
        for t in self._state.titles:
            if t.text == text:
                return t  # Already exists
        
        title = Title(
            id=str(uuid.uuid4())[:8],
            text=text,
            source=source,
            module=module,
            meta=meta,
        )
        self._state.titles.append(title)
        
        if auto_equip or self._state.equipped_title is None:
            self._state.equipped_title = text
        
        self._save()
        return title
    
    def equip_title(self, title_text: str) -> bool:
        """Equip a title."""
        self._load()
        for t in self._state.titles:
            if t.text == title_text:
                self._state.equipped_title = title_text
                self._save()
                return True
        return False
    
    def unequip_title(self) -> None:
        """Unequip the current title."""
        self._load()
        self._state.equipped_title = None
        self._save()
    
    def get_titles(self) -> List[Title]:
        """Get all titles."""
        self._load()
        return self._state.titles
    
    # =========================================================================
    # RESET / CLEAR
    # =========================================================================
    
    def soft_reset(self) -> None:
        """
        Soft reset: Reset progression but keep profile.
        
        Resets:
        - level, current_xp, xp_to_next, total_xp
        - modules xp/level
        - titles and equipped_title
        - xp_history
        - archetype rank/current
        
        Keeps:
        - display_name
        - archetype.base_theme
        - vibe_tags
        - goals
        """
        self._load()
        s = self._state
        
        # Reset progression
        s.level = 1
        s.current_xp = 0
        s.xp_to_next = 100
        s.total_xp = 0
        s.xp_by_source = {}
        
        # Reset modules
        s.modules = {}
        
        # Reset titles
        s.titles = []
        s.equipped_title = None
        
        # Reset XP history
        s.xp_history = []
        
        # Reset archetype to base
        s.archetype.rank = "Apprentice"
        s.archetype.current = f"{s.archetype.base_theme} Apprentice"
        s.archetype.last_updated_level = 1
        
        # Reset legacy fields
        s.visual_unlocks = []
        s.unlocked_shortcuts = []
        
        self._save()
        logger.info("Performed soft reset")
    
    def hard_reset(self) -> None:
        """
        Hard reset: Reset everything including profile.
        """
        self._state = IdentityState()
        self._save()
        logger.info("Performed hard reset")
    
    # =========================================================================
    # LEGACY COMPATIBILITY
    # =========================================================================
    
    def get_legacy_profile(self) -> Dict[str, Any]:
        """
        Get profile in legacy PlayerProfile format for backwards compatibility.
        """
        self._load()
        s = self._state
        
        # Convert modules to legacy domains format
        domains = {}
        for k, v in s.modules.items():
            domains[k] = {
                "xp": v.xp,
                "tier": v.level,  # Legacy used "tier"
                "quests_completed": 0,
                "last_quest_at": None,
            }
        
        return {
            "level": s.level,
            "total_xp": s.total_xp,
            "titles": [t.text for t in s.titles],
            "domains": domains,
            "visual_unlocks": s.visual_unlocks,
            "unlocked_shortcuts": s.unlocked_shortcuts,
            "created_at": s.created_at,
            "updated_at": s.updated_at,
        }
    
    # =========================================================================
    # EXPORTS
    # =========================================================================
    
    def export_state(self) -> Dict[str, Any]:
        """Export full state for system snapshots."""
        self._load()
        return self._state.to_dict()
    
    def import_state(self, data: Dict[str, Any]) -> None:
        """Import state from system snapshot."""
        self._state = IdentityState.from_dict(data)
        self._save()
        logger.info("Imported identity state")


# =============================================================================
# MODULE EXPORTS
# =============================================================================

__all__ = [
    # Data models
    "Archetype",
    "Goal",
    "ModuleXP",
    "Title",
    "XPEvent",
    "IdentityState",
    
    # XP Event Contract
    "XPEventInput",
    "XPEventResult",
    
    # Manager
    "IdentitySectionManager",
    
    # Helper functions
    "level_from_total_xp",
    "module_level_from_xp",
    "get_rank_for_level",
    "evolve_archetype",
]
