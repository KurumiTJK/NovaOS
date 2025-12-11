# kernel/module_manager.py
"""
NovaOS Module Manager v2.0.0

The Modules Section is the "World Map" of NovaOS - regions/areas of your life.
Each module represents a domain like Cybersecurity, Business, Real Estate, etc.
"""

from __future__ import annotations

import json
import re
import uuid
import logging
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from .command_types import CommandResponse

logger = logging.getLogger("nova.modules")

# =============================================================================
# CONSTANTS
# =============================================================================

VALID_STATUSES = {"active", "paused", "archived"}
VALID_PHASES = {"foundation", "growth", "scaling", "maintenance", "legacy"}
VALID_CATEGORIES = {"career", "business", "health", "finance", "personal", "creative", "social", "education", "other"}

DEFAULT_STATUS = "active"
DEFAULT_PHASE = "foundation"
DEFAULT_CATEGORY = "personal"
DEFAULT_ICON = "📁"
DEFAULT_COLOR = "#95a5a6"


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def slugify(text: str) -> str:
    """Convert text to a URL-friendly slug."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text)
    text = re.sub(r'^-+|-+$', '', text)
    return text


def generate_module_id(name: str) -> str:
    """Generate a unique module ID from name."""
    slug = slugify(name)
    short_uuid = str(uuid.uuid4())[:6]
    return f"mod_{slug}_{short_uuid}"


# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class WorldMeta:
    """Visual/UI metadata for a module."""
    realm_name: str = ""
    icon: str = DEFAULT_ICON
    color: str = DEFAULT_COLOR
    tier_labels: Optional[Dict[str, str]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "realm_name": self.realm_name,
            "icon": self.icon,
            "color": self.color,
            "tier_labels": self.tier_labels,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorldMeta":
        return cls(
            realm_name=data.get("realm_name", ""),
            icon=data.get("icon", DEFAULT_ICON),
            color=data.get("color", DEFAULT_COLOR),
            tier_labels=data.get("tier_labels"),
        )


@dataclass
class Module:
    """A module/region in the NovaOS world map."""
    id: str
    name: str
    slug: str = ""
    category: str = DEFAULT_CATEGORY
    status: str = DEFAULT_STATUS
    phase: str = DEFAULT_PHASE
    description: str = ""
    tags: List[str] = field(default_factory=list)
    color: str = DEFAULT_COLOR
    icon: str = DEFAULT_ICON
    world_meta: Optional[WorldMeta] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    def __post_init__(self):
        if not self.slug:
            self.slug = slugify(self.name)
        if self.world_meta:
            if not self.world_meta.icon or self.world_meta.icon == DEFAULT_ICON:
                self.world_meta.icon = self.icon
            else:
                self.icon = self.world_meta.icon
            if not self.world_meta.color or self.world_meta.color == DEFAULT_COLOR:
                self.world_meta.color = self.color
            else:
                self.color = self.world_meta.color
    
    @property
    def realm_name(self) -> str:
        if self.world_meta and self.world_meta.realm_name:
            return self.world_meta.realm_name
        return f"{self.name} Realm"
    
    def get_tier_label(self, tier: int) -> str:
        if self.world_meta and self.world_meta.tier_labels:
            return self.world_meta.tier_labels.get(str(tier), f"Tier {tier}")
        defaults = {1: "Novice", 2: "Apprentice", 3: "Journeyman", 4: "Expert", 5: "Master"}
        return defaults.get(tier, f"Tier {tier}")
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "slug": self.slug,
            "category": self.category,
            "status": self.status,
            "phase": self.phase,
            "description": self.description,
            "tags": self.tags,
            "color": self.color,
            "icon": self.icon,
            "world_meta": self.world_meta.to_dict() if self.world_meta else None,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Module":
        world_meta = None
        if data.get("world_meta"):
            world_meta = WorldMeta.from_dict(data["world_meta"])
        
        icon = data.get("icon", DEFAULT_ICON)
        color = data.get("color", DEFAULT_COLOR)
        if world_meta:
            if icon == DEFAULT_ICON and world_meta.icon:
                icon = world_meta.icon
            if color == DEFAULT_COLOR and world_meta.color:
                color = world_meta.color
        
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            slug=data.get("slug", ""),
            category=data.get("category", DEFAULT_CATEGORY),
            status=data.get("status", DEFAULT_STATUS),
            phase=data.get("phase", DEFAULT_PHASE),
            description=data.get("description", ""),
            tags=data.get("tags", []),
            color=color,
            icon=icon,
            world_meta=world_meta,
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            updated_at=data.get("updated_at", datetime.now(timezone.utc).isoformat()),
        )


# =============================================================================
# MODULE STORE
# =============================================================================

class ModuleStore:
    """Manages modules for the NovaOS world map."""
    
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.modules_file = self.data_dir / "modules.json"
        self._modules: Dict[str, Module] = {}
        self._load()
    
    def _load(self) -> None:
        if not self.modules_file.exists():
            self._modules = {}
            self._save()
            return
        
        try:
            with open(self.modules_file, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (json.JSONDecodeError, IOError):
            self._modules = {}
            self._save()
            return
        
        if isinstance(raw, dict):
            if "modules" in raw and isinstance(raw["modules"], list):
                for item in raw["modules"]:
                    if isinstance(item, dict) and "id" in item:
                        module = Module.from_dict(item)
                        self._modules[module.id] = module
            else:
                for key, val in raw.items():
                    if isinstance(val, dict):
                        val["id"] = key
                        module = Module.from_dict(val)
                        self._modules[module.id] = module
    
    def _save(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        data = {"modules": [m.to_dict() for m in self._modules.values()]}
        with open(self.modules_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def get(self, module_id: str) -> Optional[Module]:
        return self._modules.get(module_id)
    
    def get_by_name(self, name: str) -> Optional[Module]:
        name_lower = name.lower()
        for module in self._modules.values():
            if module.name.lower() == name_lower:
                return module
        return None
    
    def get_by_slug(self, slug: str) -> Optional[Module]:
        for module in self._modules.values():
            if module.slug == slug:
                return module
        return None
    
    def find(self, identifier: str) -> Optional[Module]:
        module = self.get(identifier)
        if module:
            return module
        module = self.get_by_name(identifier)
        if module:
            return module
        module = self.get_by_slug(identifier)
        return module
    
    def list_all(self, include_archived: bool = True) -> List[Module]:
        modules = list(self._modules.values())
        if not include_archived:
            modules = [m for m in modules if m.status != "archived"]
        return modules
    
    def exists(self, module_id: str) -> bool:
        return module_id in self._modules
    
    def create(self, name: str, category: str = DEFAULT_CATEGORY, status: str = DEFAULT_STATUS,
               phase: str = DEFAULT_PHASE, description: str = "", tags: Optional[List[str]] = None,
               icon: str = DEFAULT_ICON, color: str = DEFAULT_COLOR, module_id: Optional[str] = None) -> Module:
        if not module_id:
            module_id = generate_module_id(name)
        if module_id in self._modules:
            raise ValueError(f"Module '{module_id}' already exists")
        if self.get_by_name(name):
            raise ValueError(f"Module with name '{name}' already exists")
        
        module = Module(
            id=module_id, name=name, slug=slugify(name), category=category, status=status,
            phase=phase, description=description, tags=tags or [], color=color, icon=icon,
            world_meta=WorldMeta(realm_name=f"{name} Realm", icon=icon, color=color),
        )
        self._modules[module_id] = module
        self._save()
        return module
    
    def update(self, module_id: str, **kwargs) -> Optional[Module]:
        module = self._modules.get(module_id)
        if not module:
            return None
        
        allowed_fields = {"name", "category", "status", "phase", "description", "tags", "color", "icon"}
        for key, value in kwargs.items():
            if key in allowed_fields and value is not None:
                setattr(module, key, value)
                if key == "icon" and module.world_meta:
                    module.world_meta.icon = value
                if key == "color" and module.world_meta:
                    module.world_meta.color = value
        
        if "name" in kwargs:
            module.slug = slugify(kwargs["name"])
            if module.world_meta:
                module.world_meta.realm_name = f"{kwargs['name']} Realm"
        
        module.updated_at = datetime.now(timezone.utc).isoformat()
        self._save()
        return module
    
    def archive(self, module_id: str) -> Optional[Module]:
        return self.update(module_id, status="archived")
    
    def delete(self, module_id: str) -> bool:
        if module_id not in self._modules:
            return False
        del self._modules[module_id]
        self._save()
        return True
    
    def count(self) -> int:
        return len(self._modules)


# =============================================================================
# HELPER: Get Identity XP for a module
# =============================================================================

def get_module_xp_from_identity(kernel: Any, module_name: str) -> Tuple[int, int]:
    """Get XP and level for a module from Identity section."""
    identity_manager = getattr(kernel, 'identity_section_manager', None)
    if identity_manager:
        try:
            state = identity_manager.get_state()
            mod_data = state.modules.get(module_name)
            if mod_data:
                return (mod_data.xp, mod_data.level)
        except Exception:
            pass
    
    profile_manager = getattr(kernel, 'player_profile_manager', None)
    if profile_manager:
        try:
            profile = profile_manager.get_profile()
            domain_data = profile.domains.get(module_name)
            if domain_data:
                return (domain_data.xp, domain_data.tier)
        except Exception:
            pass
    
    return (0, 0)


def get_quests_for_module(kernel: Any, module_id: str) -> List[Any]:
    """Get quests that belong to a module."""
    quest_engine = getattr(kernel, 'quest_engine', None)
    if not quest_engine:
        return []
    try:
        quests = quest_engine.list_quests()
        return [q for q in quests if q.module_id == module_id]
    except Exception:
        return []


def check_module_has_xp(kernel: Any, module_name: str) -> bool:
    xp, _ = get_module_xp_from_identity(kernel, module_name)
    return xp > 0


def remove_module_from_identity(kernel: Any, module_name: str) -> bool:
    identity_manager = getattr(kernel, 'identity_section_manager', None)
    if identity_manager:
        try:
            state = identity_manager.get_state()
            if module_name in state.modules:
                del state.modules[module_name]
                identity_manager._save()
                return True
        except Exception:
            pass
    
    profile_manager = getattr(kernel, 'player_profile_manager', None)
    if profile_manager:
        try:
            profile = profile_manager.get_profile()
            if module_name in profile.domains:
                del profile.domains[module_name]
                profile_manager.save_profile()
                return True
        except Exception:
            pass
    return False


def detach_quests_from_module(kernel: Any, module_id: str) -> int:
    quest_engine = getattr(kernel, 'quest_engine', None)
    if not quest_engine:
        return 0
    try:
        count = 0
        quests = quest_engine._quests
        for quest_key, quest in quests.items():
            if quest.module_id == module_id:
                quest.module_id = None
                count += 1
        if count > 0:
            quest_engine._save_quests()
        return count
    except Exception:
        return 0


# =============================================================================
# RESPONSE HELPERS
# =============================================================================

def _get_command_response():
    from .command_types import CommandResponse
    return CommandResponse


def _base_response(cmd_name: str, summary: str, data: Optional[Dict] = None) -> "CommandResponse":
    CommandResponse = _get_command_response()
    return CommandResponse(ok=True, command=cmd_name, summary=summary, data=data or {})


def _error_response(cmd_name: str, message: str, error_code: str = "ERROR") -> "CommandResponse":
    CommandResponse = _get_command_response()
    return CommandResponse(ok=False, command=cmd_name, summary=message, error_code=error_code)


# =============================================================================
# COMMAND HANDLERS
# =============================================================================

def handle_section_modules(cmd_name, args, session_id, context, kernel, meta) -> "CommandResponse":
    """Show the Modules section menu."""
    print(f"[ModuleManager] handle_section_modules called", flush=True)
    try:
        store = getattr(kernel, 'module_store', None)
        module_count = store.count() if store else 0
        
        lines = [
            "╔══ Modules ══╗",
            "World map: regions of your life.",
            "",
            f"You have {module_count} module(s).",
            "",
            "1) modules-list",
            "   List all modules with status, phase, and Domain Level",
            "   Example: `#modules-list`",
            "",
            "2) modules-add",
            "   Create a new module",
            '   Example: `#modules-add name="Cybersecurity" category=career`',
            "",
            "3) modules-show",
            "   Show details for one module",
            '   Example: `#modules-show name="Cybersecurity"`',
            "",
            "4) modules-update",
            "   Update module metadata (status, phase, description, tags)",
            '   Example: `#modules-update name="Cybersecurity" phase=growth`',
            "",
            "5) modules-archive",
            "   Archive a module (keep history, remove from active focus)",
            '   Example: `#modules-archive name="Cybersecurity"`',
            "",
            "6) modules-delete",
            "   Delete a module (hard removal, with safety checks)",
            '   Example: `#modules-delete name="Cybersecurity"`',
            "",
        ]
        
        return _base_response(cmd_name, "\n".join(lines), {
            "section": "modules",
            "commands": ["modules-list", "modules-add", "modules-show", "modules-update", "modules-archive", "modules-delete"],
            "menu_active": True,
        })
    except Exception as e:
        print(f"[ModuleManager] ERROR: {e}", flush=True)
        traceback.print_exc()
        return _error_response(cmd_name, f"Error: {e}", "INTERNAL_ERROR")


def handle_modules_list(cmd_name, args, session_id, context, kernel, meta) -> "CommandResponse":
    """List all modules as a world map overview."""
    print(f"[ModuleManager] handle_modules_list called", flush=True)
    try:
        store = getattr(kernel, 'module_store', None)
        if not store:
            return _error_response(cmd_name, "Module system not available.", "NO_MODULE_STORE")
        
        status_filter = None
        category_filter = None
        if isinstance(args, dict):
            status_filter = args.get("status")
            category_filter = args.get("category")
        
        modules = store.list_all()
        
        if not modules:
            lines = [
                "╔══ Modules (World Map) ══╗",
                "",
                "Your world map is empty.",
                "Create your first module with `#modules-add`.",
            ]
            return _base_response(cmd_name, "\n".join(lines), {"modules": [], "count": 0})
        
        if status_filter:
            modules = [m for m in modules if m.status == status_filter]
        if category_filter:
            modules = [m for m in modules if m.category == category_filter]
        
        status_order = {"active": 0, "paused": 1, "archived": 2}
        modules.sort(key=lambda m: (status_order.get(m.status, 3), m.name.lower()))
        
        lines = ["╔══ Modules (World Map) ══╗", ""]
        
        for i, module in enumerate(modules, 1):
            xp, level = get_module_xp_from_identity(kernel, module.name)
            status_icon = {"active": "🟢", "paused": "⏸️", "archived": "📦"}.get(module.status, "")
            lines.append(f"{i}. {module.icon} **{module.name}** — Phase: {module.phase.title()} ({module.status.title()}) {status_icon}")
            lines.append(f"   Domain Level: {level} · XP: {xp}")
            if module.tags:
                lines.append(f"   Tags: {', '.join(module.tags)}")
            lines.append("")
        
        lines.append("─────────────────────────────────────────")
        lines.append("Commands: `#modules-show name=<n>` | `#modules-add` | `#modules-update`")
        
        return _base_response(cmd_name, "\n".join(lines), {
            "modules": [m.to_dict() for m in modules],
            "count": len(modules),
        })
    except Exception as e:
        print(f"[ModuleManager] ERROR: {e}", flush=True)
        traceback.print_exc()
        return _error_response(cmd_name, f"Error: {e}", "INTERNAL_ERROR")


def handle_modules_show(cmd_name, args, session_id, context, kernel, meta) -> "CommandResponse":
    """Show details for a specific module."""
    print(f"[ModuleManager] handle_modules_show called", flush=True)
    try:
        store = getattr(kernel, 'module_store', None)
        if not store:
            return _error_response(cmd_name, "Module system not available.", "NO_MODULE_STORE")
        
        identifier = None
        if isinstance(args, dict):
            identifier = args.get("name") or args.get("id") or args.get("slug")
            positional = args.get("_", [])
            if not identifier and positional:
                # Check if positional is a number (selection from wizard)
                first_arg = str(positional[0])
                if first_arg.isdigit():
                    modules = store.list_all()
                    idx = int(first_arg) - 1
                    if 0 <= idx < len(modules):
                        identifier = modules[idx].name
                else:
                    identifier = " ".join(str(p) for p in positional)
        elif isinstance(args, str):
            identifier = args
        
        # No identifier - show wizard selection
        if not identifier:
            modules = store.list_all()
            if not modules:
                return _base_response(cmd_name, "No modules exist yet.\n\nCreate one with:\n  `#modules-add name=\"Cybersecurity\" category=career`", {"wizard": True, "awaiting_selection": False})
            
            lines = [
                "**Select a Module to View**",
                "",
            ]
            for i, m in enumerate(modules, 1):
                status_icon = {"active": "🟢", "paused": "⏸️", "archived": "📦"}.get(m.status, "")
                lines.append(f"  {i}) {m.icon} {m.name} {status_icon}")
            
            lines.extend([
                "",
                "Reply with a number or name:",
                "  `#modules-show 1` or `#modules-show name=\"Cybersecurity\"`",
            ])
            return _base_response(cmd_name, "\n".join(lines), {"wizard": True, "awaiting_selection": True, "modules": [m.name for m in modules]})
        
        module = store.find(identifier)
        if not module:
            return _error_response(cmd_name, f"Module `{identifier}` not found.", "NOT_FOUND")
        
        xp, level = get_module_xp_from_identity(kernel, module.name)
        
        lines = [
            f"╔══ Module: {module.name} ══╗",
            "",
            f"**ID:** {module.id}",
            f"**Status:** {module.status.title()}",
            f"**Phase:** {module.phase.title()}",
            f"**Category:** {module.category.title()}",
        ]
        
        if module.tags:
            lines.append(f"**Tags:** {', '.join(module.tags)}")
        
        lines.append("")
        lines.append(f"**Domain Level:** {level} ({xp} XP)")
        lines.append("")
        
        if module.description:
            lines.append("**Description:**")
            lines.append(module.description)
            lines.append("")
        
        quests = get_quests_for_module(kernel, module.id)
        if quests:
            lines.append("**Sample Quests:**")
            for q in quests[:5]:
                status_icon = {"completed": "✅", "in_progress": "🔄", "not_started": "⬜"}.get(getattr(q, 'status', ''), "")
                lines.append(f"  {status_icon} {q.title}")
        else:
            lines.append("**Quests:** None yet")
        
        lines.append("")
        lines.append("─────────────────────────────────────────")
        lines.append(f"Commands: `#modules-update name={module.name}` | `#modules-archive` | `#modules-delete`")
        
        return _base_response(cmd_name, "\n".join(lines), module.to_dict())
    except Exception as e:
        print(f"[ModuleManager] ERROR: {e}", flush=True)
        traceback.print_exc()
        return _error_response(cmd_name, f"Error: {e}", "INTERNAL_ERROR")


def handle_modules_add(cmd_name, args, session_id, context, kernel, meta) -> "CommandResponse":
    """Create a new module."""
    print(f"[ModuleManager] handle_modules_add called", flush=True)
    try:
        store = getattr(kernel, 'module_store', None)
        if not store:
            return _error_response(cmd_name, "Module system not available.", "NO_MODULE_STORE")
        
        name = None
        category = DEFAULT_CATEGORY
        phase = DEFAULT_PHASE
        status = DEFAULT_STATUS
        description = ""
        tags = []
        icon = DEFAULT_ICON
        color = DEFAULT_COLOR
        
        if isinstance(args, dict):
            name = args.get("name")
            category = args.get("category", DEFAULT_CATEGORY)
            phase = args.get("phase", DEFAULT_PHASE)
            status = args.get("status", DEFAULT_STATUS)
            description = args.get("description", "")
            icon = args.get("icon", DEFAULT_ICON)
            color = args.get("color", DEFAULT_COLOR)
            
            tags_raw = args.get("tags", "")
            if isinstance(tags_raw, str) and tags_raw:
                tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
            elif isinstance(tags_raw, list):
                tags = tags_raw
            
            positional = args.get("_", [])
            if not name and positional:
                name = " ".join(str(p) for p in positional)
        
        if not name:
            lines = [
                "**Create a New Module**",
                "",
                "Usage:",
                '  `#modules-add name="Module Name" category=career`',
                "",
                "Examples:",
                '  `#modules-add name="Cybersecurity" category=career`',
                '  `#modules-add name="Real Estate" category=finance phase=foundation`',
                '  `#modules-add name="Health" category=health tags="gym,nutrition"`',
                "",
                f"Categories: {', '.join(sorted(VALID_CATEGORIES))}",
                f"Phases: {', '.join(VALID_PHASES)}",
            ]
            return _base_response(cmd_name, "\n".join(lines), {"usage": True})
        
        if category not in VALID_CATEGORIES:
            return _error_response(cmd_name, f"Invalid category. Valid: {', '.join(VALID_CATEGORIES)}", "INVALID_CATEGORY")
        if phase not in VALID_PHASES:
            return _error_response(cmd_name, f"Invalid phase. Valid: {', '.join(VALID_PHASES)}", "INVALID_PHASE")
        if status not in VALID_STATUSES:
            return _error_response(cmd_name, f"Invalid status. Valid: {', '.join(VALID_STATUSES)}", "INVALID_STATUS")
        
        if store.get_by_name(name):
            return _error_response(cmd_name, f"A module named `{name}` already exists.", "DUPLICATE_NAME")
        
        module = store.create(name=name, category=category, phase=phase, status=status,
                              description=description, tags=tags, icon=icon, color=color)
        
        lines = [
            f"✅ Created module: **{module.name}**",
            "",
            f"ID: {module.id}",
            f"Category: {module.category.title()}",
            f"Phase: {module.phase.title()}",
            f"Status: {module.status.title()}",
            "",
            "Next steps:",
            f"  • View details: `#modules-show name={module.name}`",
            "  • Create a quest: `#quest-compose`",
            "  • See all modules: `#modules-list`",
        ]
        
        return _base_response(cmd_name, "\n".join(lines), module.to_dict())
    except Exception as e:
        print(f"[ModuleManager] ERROR: {e}", flush=True)
        traceback.print_exc()
        return _error_response(cmd_name, f"Error: {e}", "INTERNAL_ERROR")


def handle_modules_update(cmd_name, args, session_id, context, kernel, meta) -> "CommandResponse":
    """Update module metadata."""
    print(f"[ModuleManager] handle_modules_update called", flush=True)
    try:
        store = getattr(kernel, 'module_store', None)
        if not store:
            return _error_response(cmd_name, "Module system not available.", "NO_MODULE_STORE")
        
        identifier = None
        if isinstance(args, dict):
            identifier = args.get("name") or args.get("id")
            positional = args.get("_", [])
            if not identifier and positional:
                first_arg = str(positional[0])
                if first_arg.isdigit():
                    modules = store.list_all()
                    idx = int(first_arg) - 1
                    if 0 <= idx < len(modules):
                        identifier = modules[idx].name
                else:
                    identifier = first_arg
        
        # No identifier - show wizard selection
        if not identifier:
            modules = store.list_all()
            if not modules:
                return _base_response(cmd_name, "No modules exist yet.\n\nCreate one with:\n  `#modules-add name=\"Cybersecurity\" category=career`", {"wizard": True})
            
            lines = [
                "**Select a Module to Update**",
                "",
            ]
            for i, m in enumerate(modules, 1):
                status_icon = {"active": "🟢", "paused": "⏸️", "archived": "📦"}.get(m.status, "")
                lines.append(f"  {i}) {m.icon} {m.name} — {m.phase} {status_icon}")
            
            lines.extend([
                "",
                "**Usage:** `#modules-update <number or name> <field>=<value>`",
                "",
                "**Fields & Examples:**",
                "",
                "  status     → active, paused, archived",
                "              `#modules-update 1 status=paused`",
                "",
                "  phase      → foundation, growth, scaling, maintenance, legacy",
                "              `#modules-update 1 phase=growth`",
                "",
                "  category   → career, business, health, finance, personal, creative, social, education, other",
                "              `#modules-update 1 category=career`",
                "",
                "  description → Free text description",
                '              `#modules-update 1 description="My security skills"`',
                "",
                "  tags       → Comma-separated keywords",
                '              `#modules-update 1 tags="cloud,pentest,redteam"`',
                "",
                "  icon       → Emoji icon",
                "              `#modules-update 1 icon=🛡️`",
                "",
                "  color      → Hex color code",
                "              `#modules-update 1 color=#3498db`",
                "",
                "**Multiple fields at once:**",
                '  `#modules-update 1 phase=growth status=active tags="cloud,aws"`',
            ])
            return _base_response(cmd_name, "\n".join(lines), {"wizard": True, "modules": [m.name for m in modules]})
        
        module = store.find(identifier)
        if not module:
            return _error_response(cmd_name, f"Module `{identifier}` not found.", "NOT_FOUND")
        
        updates = {}
        changes = []
        
        if "category" in args and args["category"]:
            if args["category"] not in VALID_CATEGORIES:
                return _error_response(cmd_name, f"Invalid category. Valid: {', '.join(VALID_CATEGORIES)}", "INVALID_CATEGORY")
            updates["category"] = args["category"]
            changes.append(f"Category → {args['category']}")
        
        if "status" in args and args["status"]:
            if args["status"] not in VALID_STATUSES:
                return _error_response(cmd_name, f"Invalid status. Valid: {', '.join(VALID_STATUSES)}", "INVALID_STATUS")
            updates["status"] = args["status"]
            changes.append(f"Status → {args['status']}")
        
        if "phase" in args and args["phase"]:
            if args["phase"] not in VALID_PHASES:
                return _error_response(cmd_name, f"Invalid phase. Valid: {', '.join(VALID_PHASES)}", "INVALID_PHASE")
            updates["phase"] = args["phase"]
            changes.append(f"Phase → {args['phase']}")
        
        if "description" in args:
            updates["description"] = args["description"]
            changes.append("Description updated")
        
        if "tags" in args:
            tags_raw = args["tags"]
            if isinstance(tags_raw, str):
                tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
            else:
                tags = tags_raw or []
            updates["tags"] = tags
            changes.append(f"Tags → {', '.join(tags)}")
        
        if "icon" in args and args["icon"]:
            updates["icon"] = args["icon"]
            changes.append(f"Icon → {args['icon']}")
        
        if "color" in args and args["color"]:
            updates["color"] = args["color"]
            changes.append(f"Color → {args['color']}")
        
        if not updates:
            return _error_response(cmd_name, "No updates specified. Use: category, status, phase, description, tags, icon, color", "NO_UPDATES")
        
        updated_module = store.update(module.id, **updates)
        
        lines = [f"✅ Updated module: **{module.name}**", "", "Changes:"]
        for change in changes:
            lines.append(f"  • {change}")
        
        return _base_response(cmd_name, "\n".join(lines), updated_module.to_dict())
    except Exception as e:
        print(f"[ModuleManager] ERROR: {e}", flush=True)
        traceback.print_exc()
        return _error_response(cmd_name, f"Error: {e}", "INTERNAL_ERROR")


def handle_modules_archive(cmd_name, args, session_id, context, kernel, meta) -> "CommandResponse":
    """Archive a module (retire from active focus)."""
    print(f"[ModuleManager] handle_modules_archive called", flush=True)
    try:
        store = getattr(kernel, 'module_store', None)
        if not store:
            return _error_response(cmd_name, "Module system not available.", "NO_MODULE_STORE")
        
        identifier = None
        if isinstance(args, dict):
            identifier = args.get("name") or args.get("id")
            positional = args.get("_", [])
            if not identifier and positional:
                first_arg = str(positional[0])
                if first_arg.isdigit():
                    modules = [m for m in store.list_all() if m.status != "archived"]
                    idx = int(first_arg) - 1
                    if 0 <= idx < len(modules):
                        identifier = modules[idx].name
                else:
                    identifier = " ".join(str(p) for p in positional)
        elif isinstance(args, str):
            identifier = args
        
        # No identifier - show wizard selection
        if not identifier:
            modules = store.list_all()
            active_modules = [m for m in modules if m.status != "archived"]
            
            if not modules:
                return _base_response(cmd_name, "No modules exist yet.\n\nCreate one with:\n  `#modules-add name=\"Cybersecurity\" category=career`", {"wizard": True})
            
            if not active_modules:
                return _base_response(cmd_name, "All modules are already archived.\n\nRestore with: `#modules-update name=\"...\" status=active`", {"wizard": True})
            
            lines = [
                "**Select a Module to Archive**",
                "",
                "Archiving preserves XP and quest history.",
                "",
            ]
            for i, m in enumerate(active_modules, 1):
                status_icon = {"active": "🟢", "paused": "⏸️"}.get(m.status, "")
                lines.append(f"  {i}) {m.icon} {m.name} {status_icon}")
            
            lines.extend([
                "",
                "Reply with a number or name:",
                '  `#modules-archive 1`',
                '  `#modules-archive name="Cybersecurity"`',
            ])
            return _base_response(cmd_name, "\n".join(lines), {"wizard": True, "modules": [m.name for m in active_modules]})
        
        module = store.find(identifier)
        if not module:
            return _error_response(cmd_name, f"Module `{identifier}` not found.", "NOT_FOUND")
        
        if module.status == "archived":
            return _error_response(cmd_name, f"Module `{module.name}` is already archived.", "ALREADY_ARCHIVED")
        
        store.archive(module.id)
        
        lines = [
            f"📦 Module **{module.name}** has been archived.",
            "",
            "• XP and history have been preserved",
            "• Quests remain linked",
            "• The module is now retired from active focus",
            "",
            f"To restore: `#modules-update name={module.name} status=active`",
        ]
        
        return _base_response(cmd_name, "\n".join(lines), {"archived": module.id})
    except Exception as e:
        print(f"[ModuleManager] ERROR: {e}", flush=True)
        traceback.print_exc()
        return _error_response(cmd_name, f"Error: {e}", "INTERNAL_ERROR")


def handle_modules_delete(cmd_name, args, session_id, context, kernel, meta) -> "CommandResponse":
    """Delete a module (hard removal) with safety checks."""
    print(f"[ModuleManager] handle_modules_delete called", flush=True)
    try:
        store = getattr(kernel, 'module_store', None)
        if not store:
            return _error_response(cmd_name, "Module system not available.", "NO_MODULE_STORE")
        
        identifier = None
        force = False
        
        if isinstance(args, dict):
            identifier = args.get("name") or args.get("id")
            positional = args.get("_", [])
            if not identifier and positional:
                first_arg = str(positional[0])
                if first_arg.isdigit():
                    modules = store.list_all()
                    idx = int(first_arg) - 1
                    if 0 <= idx < len(modules):
                        identifier = modules[idx].name
                else:
                    identifier = first_arg
            force_raw = args.get("force", "")
            force = str(force_raw).lower() in ("true", "yes", "1")
        elif isinstance(args, str):
            identifier = args
        
        # No identifier - show wizard selection
        if not identifier:
            modules = store.list_all()
            if not modules:
                return _base_response(cmd_name, "No modules exist to delete.", {"wizard": True})
            
            lines = [
                "**Select a Module to Delete**",
                "",
                "⚠️  This permanently removes the module.",
                "    Use `#modules-archive` to retire while keeping history.",
                "",
            ]
            for i, m in enumerate(modules, 1):
                status_icon = {"active": "🟢", "paused": "⏸️", "archived": "📦"}.get(m.status, "")
                lines.append(f"  {i}) {m.icon} {m.name} {status_icon}")
            
            lines.extend([
                "",
                "Reply with a number or name:",
                '  `#modules-delete 1`',
                '  `#modules-delete name="Cybersecurity"`',
                '  `#modules-delete 1 force=true`  (skip safety checks)',
            ])
            return _base_response(cmd_name, "\n".join(lines), {"wizard": True, "modules": [m.name for m in modules]})
        
        module = store.find(identifier)
        if not module:
            return _error_response(cmd_name, f"Module `{identifier}` not found.", "NOT_FOUND")
        
        has_xp = check_module_has_xp(kernel, module.name)
        xp, level = get_module_xp_from_identity(kernel, module.name) if has_xp else (0, 0)
        linked_quests = get_quests_for_module(kernel, module.id)
        quest_count = len(linked_quests)
        
        if not force and (has_xp or quest_count > 0):
            lines = [
                f"⚠️ Cannot delete module **{module.name}**",
                "",
                "This module still has XP or linked quests:",
            ]
            if has_xp:
                lines.append(f"  • XP: {xp} in Identity (Level {level})")
            if quest_count > 0:
                lines.append(f"  • Linked quests: {quest_count}")
            lines.extend([
                "",
                "Options:",
                f"  • Use `#modules-archive name={module.name}` to retire it safely",
                f"  • Use `#modules-delete name={module.name} force=true` to delete and detach",
            ])
            return _error_response(cmd_name, "\n".join(lines), "HAS_DEPENDENCIES")
        
        if not force:
            store.delete(module.id)
            if not has_xp:
                remove_module_from_identity(kernel, module.name)
            return _base_response(cmd_name, f"✅ Deleted module **{module.name}**.", {"deleted": module.id})
        
        # Forced delete
        store.delete(module.id)
        xp_removed = remove_module_from_identity(kernel, module.name) if has_xp else False
        detached_count = detach_quests_from_module(kernel, module.id) if quest_count > 0 else 0
        
        lines = [
            f"🗑️ Module **{module.name}** has been deleted (forced).",
            "",
            "Summary:",
            "  • Removed from world map",
        ]
        if detached_count > 0:
            lines.append(f"  • Detached {detached_count} quest(s) (set to Unassigned)")
        if xp_removed:
            lines.append(f"  • Removed Domain XP bucket from Identity ({xp} XP)")
            lines.append("  • Note: Global XP remains unchanged")
        
        return _base_response(cmd_name, "\n".join(lines), {
            "deleted": module.id,
            "quests_detached": detached_count,
            "xp_removed": xp_removed,
        })
    except Exception as e:
        print(f"[ModuleManager] ERROR: {e}", flush=True)
        traceback.print_exc()
        return _error_response(cmd_name, f"Error: {e}", "INTERNAL_ERROR")


# =============================================================================
# HANDLER REGISTRY
# =============================================================================

MODULE_HANDLERS = {
    "handle_section_modules": handle_section_modules,
    "handle_modules_list": handle_modules_list,
    "handle_modules_show": handle_modules_show,
    "handle_modules_add": handle_modules_add,
    "handle_modules_update": handle_modules_update,
    "handle_modules_archive": handle_modules_archive,
    "handle_modules_delete": handle_modules_delete,
}


def get_module_handlers():
    """Get all module handlers for registration."""
    return MODULE_HANDLERS
