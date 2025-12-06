# kernel/module_manager.py
"""
v0.8.1 — Dynamic Module System for NovaOS Life RPG

Modules are "regions" on the world map. Each module/region has:
- id: unique identifier
- name: display name
- description: what this module is about
- world_meta: realm_name, icon, color, tier_labels

IMPORTANT: NO DEFAULT MODULES.
The world map starts EMPTY. All modules are user-created.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


# =============================================================================
# WORLD META MODEL
# =============================================================================

@dataclass
class WorldMeta:
    """
    World/RPG metadata for a module/region.
    
    Attributes:
        realm_name: Display name for the region (e.g., "Cyber Realm")
        icon: Emoji icon for the region
        color: Hex color for UI
        tier_labels: Custom tier names for this region (dict: tier_num -> label)
        description: Flavor text for the region
    """
    realm_name: str
    icon: str = "📁"
    color: str = "#95a5a6"
    tier_labels: Dict[str, str] = field(default_factory=lambda: {
        "1": "Novice",
        "2": "Apprentice", 
        "3": "Journeyman",
        "4": "Expert",
        "5": "Master",
    })
    description: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "realm_name": self.realm_name,
            "icon": self.icon,
            "color": self.color,
            "tier_labels": self.tier_labels,
            "description": self.description,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorldMeta":
        return cls(
            realm_name=data.get("realm_name", "Unknown Realm"),
            icon=data.get("icon", "📁"),
            color=data.get("color", "#95a5a6"),
            tier_labels=data.get("tier_labels", {
                "1": "Novice",
                "2": "Apprentice",
                "3": "Journeyman",
                "4": "Expert",
                "5": "Master",
            }),
            description=data.get("description", ""),
        )


# =============================================================================
# MODULE MODEL
# =============================================================================

@dataclass
class Module:
    """
    A module/region in the NovaOS world.
    
    Attributes:
        id: Unique identifier (e.g., "cyber")
        name: Display name (e.g., "Cybersecurity")
        description: What this module is about
        world_meta: RPG world metadata (realm_name, icon, color, tier_labels)
        created_at: When module was created
        updated_at: Last update timestamp
    """
    id: str
    name: str
    description: str = ""
    world_meta: Optional[WorldMeta] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    def __post_init__(self):
        # Auto-create world_meta if not provided
        if self.world_meta is None:
            self.world_meta = WorldMeta(
                realm_name=f"{self.name} Realm",
                icon="📁",
                color="#95a5a6",
            )
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "world_meta": self.world_meta.to_dict() if self.world_meta else None,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Module":
        world_meta = None
        if data.get("world_meta"):
            world_meta = WorldMeta.from_dict(data["world_meta"])
        
        return cls(
            id=data.get("id", "unknown"),
            name=data.get("name", data.get("id", "Unknown")),
            description=data.get("description", ""),
            world_meta=world_meta,
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            updated_at=data.get("updated_at", datetime.now(timezone.utc).isoformat()),
        )
    
    @property
    def icon(self) -> str:
        """Get module icon."""
        return self.world_meta.icon if self.world_meta else "📁"
    
    @property
    def color(self) -> str:
        """Get module color."""
        return self.world_meta.color if self.world_meta else "#95a5a6"
    
    @property
    def realm_name(self) -> str:
        """Get realm display name."""
        return self.world_meta.realm_name if self.world_meta else self.name
    
    def get_tier_label(self, tier: int) -> str:
        """Get the label for a specific tier."""
        if self.world_meta and self.world_meta.tier_labels:
            return self.world_meta.tier_labels.get(str(tier), f"Tier {tier}")
        return f"Tier {tier}"


# =============================================================================
# MODULE STORE (NO DEFAULTS)
# =============================================================================

class ModuleStore:
    """
    Manages modules for the NovaOS world map.
    
    IMPORTANT: No default modules. The world starts empty.
    All modules are user-created.
    
    Data is stored in data/modules.json:
    {
        "modules": [
            {
                "id": "cyber",
                "name": "Cybersecurity",
                "description": "...",
                "world_meta": {...}
            }
        ]
    }
    """
    
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.modules_file = self.data_dir / "modules.json"
        self._modules: Dict[str, Module] = {}
        self._load()
    
    def _load(self) -> None:
        """Load modules from disk. NO DEFAULTS ARE CREATED."""
        if not self.modules_file.exists():
            # Create empty modules file
            self._modules = {}
            self._save()
            return
        
        try:
            with open(self.modules_file) as f:
                raw = json.load(f)
        except (json.JSONDecodeError, IOError):
            self._modules = {}
            self._save()
            return
        
        # Handle both formats: {"modules": [...]} or {id: {...}, ...}
        if isinstance(raw, dict):
            if "modules" in raw and isinstance(raw["modules"], list):
                # New format: {"modules": [...]}
                for item in raw["modules"]:
                    if isinstance(item, dict) and "id" in item:
                        module = Module.from_dict(item)
                        self._modules[module.id] = module
            else:
                # Legacy format: {id: {...}, ...}
                for key, val in raw.items():
                    if isinstance(val, dict):
                        val["id"] = key  # Ensure id is set
                        module = Module.from_dict(val)
                        self._modules[module.id] = module
    
    def _save(self) -> None:
        """Save modules to disk."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # Save in new format: {"modules": [...]}
        data = {
            "modules": [m.to_dict() for m in self._modules.values()]
        }
        
        with open(self.modules_file, "w") as f:
            json.dump(data, f, indent=2)
    
    # -------------------------------------------------------------------------
    # CRUD Operations
    # -------------------------------------------------------------------------
    
    def get(self, module_id: str) -> Optional[Module]:
        """Get a module by ID."""
        return self._modules.get(module_id)
    
    def list_all(self) -> List[Module]:
        """Get all modules."""
        return list(self._modules.values())
    
    def exists(self, module_id: str) -> bool:
        """Check if a module exists."""
        return module_id in self._modules
    
    def create(
        self,
        module_id: str,
        name: str,
        description: str = "",
        realm_name: Optional[str] = None,
        icon: str = "📁",
        color: str = "#95a5a6",
        tier_labels: Optional[Dict[str, str]] = None,
    ) -> Module:
        """Create a new module."""
        if module_id in self._modules:
            raise ValueError(f"Module '{module_id}' already exists")
        
        world_meta = WorldMeta(
            realm_name=realm_name or f"{name} Realm",
            icon=icon,
            color=color,
            tier_labels=tier_labels or {
                "1": "Novice",
                "2": "Apprentice",
                "3": "Journeyman",
                "4": "Expert",
                "5": "Master",
            },
        )
        
        module = Module(
            id=module_id,
            name=name,
            description=description,
            world_meta=world_meta,
        )
        
        self._modules[module_id] = module
        self._save()
        return module
    
    def update(self, module_id: str, **kwargs) -> Optional[Module]:
        """Update a module's properties."""
        module = self._modules.get(module_id)
        if not module:
            return None
        
        # Update basic fields
        if "name" in kwargs:
            module.name = kwargs["name"]
        if "description" in kwargs:
            module.description = kwargs["description"]
        
        # Update world_meta fields
        if module.world_meta:
            if "realm_name" in kwargs:
                module.world_meta.realm_name = kwargs["realm_name"]
            if "icon" in kwargs:
                module.world_meta.icon = kwargs["icon"]
            if "color" in kwargs:
                module.world_meta.color = kwargs["color"]
            if "tier_labels" in kwargs:
                module.world_meta.tier_labels = kwargs["tier_labels"]
        
        module.updated_at = datetime.now(timezone.utc).isoformat()
        self._save()
        return module
    
    def delete(self, module_id: str) -> bool:
        """Delete a module. Returns True if deleted, False if not found."""
        if module_id not in self._modules:
            return False
        
        del self._modules[module_id]
        self._save()
        return True
    
    def count(self) -> int:
        """Get number of modules."""
        return len(self._modules)


# =============================================================================
# COMMAND HANDLERS
# =============================================================================

def handle_modules(cmd_name, args, session_id, context, kernel, meta) -> "CommandResponse":
    """
    List all modules/regions.
    
    Usage:
        #modules
    """
    from .command_types import CommandResponse
    
    store = getattr(kernel, 'module_store', None)
    if not store:
        return CommandResponse(
            ok=False,
            command=cmd_name,
            summary="Module system not available.",
            error_code="NO_MODULE_STORE",
        )
    
    modules = store.list_all()
    
    if not modules:
        return CommandResponse(
            ok=True,
            command=cmd_name,
            summary="No modules defined yet.\n\n"
                    "Create your first region with:\n"
                    '`#module-create id="cyber" name="Cybersecurity" description="..."`',
            data={"modules": []},
        )
    
    lines = ["╔══ World Map ══╗", ""]
    
    # Get player profile for XP display
    profile_manager = getattr(kernel, 'player_profile_manager', None)
    profile = profile_manager.get_profile() if profile_manager else None
    
    for module in modules:
        icon = module.icon
        realm = module.realm_name
        
        # Get player XP for this module
        xp = 0
        tier = 1
        tier_label = "Novice"
        if profile and module.id in profile.domains:
            domain_data = profile.domains[module.id]
            xp = domain_data.xp
            tier = domain_data.tier
            tier_label = module.get_tier_label(tier)
        
        lines.append(f"{icon} **{realm}**")
        if xp > 0:
            tier_stars = "⭐" * tier
            lines.append(f"   {tier_label} {tier_stars} • {xp} XP")
        else:
            lines.append(f"   No progress yet")
        lines.append("")
    
    lines.append("**Commands:**")
    lines.append("• `#module-inspect <id>` — View module details")
    lines.append("• `#module-create` — Create a new module")
    lines.append("• `#quest` — View available quests")
    
    return CommandResponse(
        ok=True,
        command=cmd_name,
        summary="\n".join(lines),
        data={"modules": [m.to_dict() for m in modules]},
    )


def handle_module_create(cmd_name, args, session_id, context, kernel, meta) -> "CommandResponse":
    """
    Create a new module/region.
    
    Usage:
        #module-create id="cyber" name="Cybersecurity"
        #module-create id="cyber" name="Cybersecurity" description="Red team and cloud security"
        #module-create id="cyber" name="Cybersecurity" icon="🛡️" color="#4fd1c5"
    """
    from .command_types import CommandResponse
    
    store = getattr(kernel, 'module_store', None)
    if not store:
        return CommandResponse(
            ok=False,
            command=cmd_name,
            summary="Module system not available.",
            error_code="NO_MODULE_STORE",
        )
    
    if not isinstance(args, dict):
        return CommandResponse(
            ok=False,
            command=cmd_name,
            summary='Usage: `#module-create id="module_id" name="Module Name"`\n\n'
                    'Optional: `description="..." icon="🎯" color="#hex"`',
            error_code="INVALID_ARGS",
        )
    
    module_id = args.get("id")
    name = args.get("name")
    
    if not module_id:
        return CommandResponse(
            ok=False,
            command=cmd_name,
            summary='Missing required `id` parameter.\n\n'
                    'Usage: `#module-create id="cyber" name="Cybersecurity"`',
            error_code="MISSING_ID",
        )
    
    if not name:
        return CommandResponse(
            ok=False,
            command=cmd_name,
            summary='Missing required `name` parameter.\n\n'
                    'Usage: `#module-create id="cyber" name="Cybersecurity"`',
            error_code="MISSING_NAME",
        )
    
    # Check if exists
    if store.exists(module_id):
        return CommandResponse(
            ok=False,
            command=cmd_name,
            summary=f"Module `{module_id}` already exists.",
            error_code="ALREADY_EXISTS",
        )
    
    try:
        module = store.create(
            module_id=module_id,
            name=name,
            description=args.get("description", ""),
            realm_name=args.get("realm_name"),
            icon=args.get("icon", "📁"),
            color=args.get("color", "#95a5a6"),
        )
    except Exception as e:
        return CommandResponse(
            ok=False,
            command=cmd_name,
            summary=f"Failed to create module: {e}",
            error_code="CREATE_FAILED",
        )
    
    return CommandResponse(
        ok=True,
        command=cmd_name,
        summary=f"✓ Created module: {module.icon} **{module.realm_name}**\n\n"
                f"View it with `#module-inspect {module_id}`",
        data=module.to_dict(),
    )


def handle_module_delete(cmd_name, args, session_id, context, kernel, meta) -> "CommandResponse":
    """
    Delete a module/region.
    
    Usage:
        #module-delete id="cyber"
        #module-delete cyber
    """
    from .command_types import CommandResponse
    
    store = getattr(kernel, 'module_store', None)
    if not store:
        return CommandResponse(
            ok=False,
            command=cmd_name,
            summary="Module system not available.",
            error_code="NO_MODULE_STORE",
        )
    
    # Get module ID
    module_id = None
    if isinstance(args, dict):
        module_id = args.get("id")
        positional = args.get("_", [])
        if not module_id and positional:
            module_id = positional[0]
    elif isinstance(args, str):
        module_id = args
    
    if not module_id:
        return CommandResponse(
            ok=False,
            command=cmd_name,
            summary='Usage: `#module-delete id="cyber"` or `#module-delete cyber`',
            error_code="MISSING_ID",
        )
    
    # Check if exists
    module = store.get(module_id)
    if not module:
        return CommandResponse(
            ok=False,
            command=cmd_name,
            summary=f"Module `{module_id}` not found.",
            error_code="NOT_FOUND",
        )
    
    # Check for quests using this module (warning only)
    quest_engine = getattr(kernel, 'quest_engine', None)
    orphan_warning = ""
    if quest_engine:
        quests = quest_engine.list_quests()
        orphan_quests = [q for q in quests if q.module_id == module_id]
        if orphan_quests:
            orphan_warning = f"\n\n⚠️ Warning: {len(orphan_quests)} quest(s) referenced this module and are now unassigned."
    
    # Delete
    store.delete(module_id)
    
    return CommandResponse(
        ok=True,
        command=cmd_name,
        summary=f"✓ Deleted module: **{module.name}**{orphan_warning}",
        data={"deleted_id": module_id},
    )


def handle_module_inspect(cmd_name, args, session_id, context, kernel, meta) -> "CommandResponse":
    """
    Inspect a specific module/region.
    
    Usage:
        #module-inspect cyber
        #module-inspect id="cyber"
    """
    from .command_types import CommandResponse
    
    store = getattr(kernel, 'module_store', None)
    if not store:
        return CommandResponse(
            ok=False,
            command=cmd_name,
            summary="Module system not available.",
            error_code="NO_MODULE_STORE",
        )
    
    # Get module ID
    module_id = None
    if isinstance(args, dict):
        module_id = args.get("id") or args.get("key")
        positional = args.get("_", [])
        if not module_id and positional:
            module_id = positional[0]
    elif isinstance(args, str):
        module_id = args
    
    if not module_id:
        modules = store.list_all()
        if not modules:
            return CommandResponse(
                ok=False,
                command=cmd_name,
                summary="No modules exist yet. Create one with `#module-create`.",
                error_code="NO_MODULES",
            )
        
        module_list = ", ".join([f"`{m.id}`" for m in modules])
        return CommandResponse(
            ok=False,
            command=cmd_name,
            summary=f"Usage: `#module-inspect <module_id>`\n\nAvailable modules: {module_list}",
            error_code="MISSING_ID",
        )
    
    module = store.get(module_id)
    if not module:
        return CommandResponse(
            ok=False,
            command=cmd_name,
            summary=f"Module `{module_id}` not found.\n\nRun `#modules` to see available modules.",
            error_code="NOT_FOUND",
        )
    
    lines = [
        f"╔══ {module.icon} {module.realm_name} ══╗",
        "",
        f"**ID:** {module.id}",
        f"**Name:** {module.name}",
    ]
    
    if module.description:
        lines.append(f"**Description:** {module.description}")
    
    lines.append("")
    
    # World meta details
    if module.world_meta:
        lines.append(f"**Icon:** {module.world_meta.icon}")
        lines.append(f"**Color:** {module.world_meta.color}")
        if module.world_meta.tier_labels:
            tier_str = " → ".join([
                f"{module.world_meta.tier_labels.get(str(i), f'Tier {i}')}"
                for i in range(1, 6)
            ])
            lines.append(f"**Tiers:** {tier_str}")
        lines.append("")
    
    # Player progress
    profile_manager = getattr(kernel, 'player_profile_manager', None)
    if profile_manager:
        profile = profile_manager.get_profile()
        domain_data = profile.domains.get(module.id)
        if domain_data and domain_data.xp > 0:
            tier_label = module.get_tier_label(domain_data.tier)
            lines.append(f"**Your Progress:** {domain_data.xp} XP • {tier_label}")
            lines.append(f"**Quests Completed:** {domain_data.quests_completed}")
            lines.append("")
    
    # Quest count
    quest_engine = getattr(kernel, 'quest_engine', None)
    if quest_engine:
        quests = quest_engine.list_quests()
        module_quests = [q for q in quests if q.module_id == module.id]
        if module_quests:
            lines.append(f"**Quests in Module:** {len(module_quests)}")
            lines.append(f"Run `#quest {module.id}` to see quests in this module.")
    
    return CommandResponse(
        ok=True,
        command=cmd_name,
        summary="\n".join(lines),
        data=module.to_dict(),
    )


# =============================================================================
# HANDLER REGISTRY
# =============================================================================

MODULE_HANDLERS = {
    "handle_modules": handle_modules,
    "handle_module_create": handle_module_create,
    "handle_module_delete": handle_module_delete,
    "handle_module_inspect": handle_module_inspect,
}


def get_module_handlers():
    """Get all module handlers for registration."""
    return MODULE_HANDLERS
