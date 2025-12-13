# kernel/player_profile.py
"""
v0.8.0 — Player Profile for NovaOS Life RPG

The Player Profile is your character sheet in the Life RPG.
It tracks:
- Level and total XP
- Domain-specific XP and tiers (Cyber, Finance, etc.)
- Titles earned from quest completions
- Visual unlocks and shortcuts

This module provides:
- PlayerProfile dataclass
- PlayerProfileManager for persistence
- XP award functions
- Level/tier calculations
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


# =============================================================================
# CONSTANTS
# =============================================================================

# Level thresholds (total_xp required for each level)
# Level = floor(total_xp / 100) for simplicity
LEVEL_DIVISOR = 100

# Domain tier thresholds
TIER_THRESHOLDS = {
    1: 0,      # 0-199 XP
    2: 200,    # 200-499 XP
    3: 500,    # 500-999 XP
    4: 1000,   # 1000-1999 XP
    5: 2000,   # 2000+ XP
}

# NOTE: No default domains. Domains are created dynamically when XP is awarded.
# The domain ID should match a module ID (if modules are used).


# =============================================================================
# DOMAIN XP MODEL
# =============================================================================

@dataclass
class DomainXP:
    """XP tracking for a single domain/region."""
    xp: int = 0
    tier: int = 1
    quests_completed: int = 0
    last_quest_at: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "xp": self.xp,
            "tier": self.tier,
            "quests_completed": self.quests_completed,
            "last_quest_at": self.last_quest_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DomainXP":
        return cls(
            xp=data.get("xp", 0),
            tier=data.get("tier", 1),
            quests_completed=data.get("quests_completed", 0),
            last_quest_at=data.get("last_quest_at"),
        )


# =============================================================================
# PLAYER PROFILE MODEL
# =============================================================================

@dataclass
class PlayerProfile:
    """
    The player's character sheet.
    
    Attributes:
        level: Current player level (derived from total_xp)
        total_xp: Total XP earned across all domains
        titles: List of earned titles (e.g., "Cyber Initiate")
        domains: Per-domain XP tracking
        visual_unlocks: Visual customizations earned
        unlocked_shortcuts: Command shortcuts earned from quests
        created_at: When profile was created
        updated_at: Last update timestamp
    """
    level: int = 1
    total_xp: int = 0
    titles: List[str] = field(default_factory=list)
    domains: Dict[str, DomainXP] = field(default_factory=dict)
    visual_unlocks: List[str] = field(default_factory=list)
    unlocked_shortcuts: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level,
            "total_xp": self.total_xp,
            "titles": self.titles,
            "domains": {k: v.to_dict() for k, v in self.domains.items()},
            "visual_unlocks": self.visual_unlocks,
            "unlocked_shortcuts": self.unlocked_shortcuts,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PlayerProfile":
        domains = {}
        for k, v in data.get("domains", {}).items():
            domains[k] = DomainXP.from_dict(v) if isinstance(v, dict) else DomainXP(xp=v)
        
        return cls(
            level=data.get("level", 1),
            total_xp=data.get("total_xp", 0),
            titles=data.get("titles", []),
            domains=domains,
            visual_unlocks=data.get("visual_unlocks", []),
            unlocked_shortcuts=data.get("unlocked_shortcuts", []),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            updated_at=data.get("updated_at", datetime.now(timezone.utc).isoformat()),
        )
    
    def get_domain_xp(self, domain: str) -> int:
        """Get XP for a specific domain."""
        if domain in self.domains:
            return self.domains[domain].xp
        return 0
    
    def get_domain_tier(self, domain: str) -> int:
        """Get tier for a specific domain."""
        if domain in self.domains:
            return self.domains[domain].tier
        return 1
    
    def get_xp_to_next_level(self) -> int:
        """Calculate XP needed for next level."""
        next_level_xp = (self.level + 1) * LEVEL_DIVISOR
        return max(0, next_level_xp - self.total_xp)
    
    def get_level_progress_pct(self) -> float:
        """Get progress percentage toward next level."""
        current_level_xp = self.level * LEVEL_DIVISOR
        next_level_xp = (self.level + 1) * LEVEL_DIVISOR
        progress = self.total_xp - current_level_xp
        needed = next_level_xp - current_level_xp
        return min(100.0, (progress / needed) * 100) if needed > 0 else 100.0


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def compute_level(total_xp: int) -> int:
    """Compute level from total XP."""
    return max(1, total_xp // LEVEL_DIVISOR + 1)


def compute_tier(domain_xp: int) -> int:
    """Compute tier from domain XP."""
    tier = 1
    for t, threshold in sorted(TIER_THRESHOLDS.items()):
        if domain_xp >= threshold:
            tier = t
    return tier


def get_tier_name(tier: int) -> str:
    """Get display name for a tier."""
    return {
        1: "Novice",
        2: "Apprentice", 
        3: "Journeyman",
        4: "Expert",
        5: "Master",
    }.get(tier, f"Tier {tier}")


def get_xp_to_next_tier(current_xp: int, current_tier: int) -> int:
    """Calculate XP needed for next tier."""
    next_tier = current_tier + 1
    if next_tier not in TIER_THRESHOLDS:
        return 0  # Max tier
    return max(0, TIER_THRESHOLDS[next_tier] - current_xp)


# =============================================================================
# PLAYER PROFILE MANAGER
# =============================================================================

class PlayerProfileManager:
    """
    Manages player profile persistence and XP operations.
    
    Profile is stored in data/player_profile.json
    """
    
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.profile_path = self.data_dir / "player_profile.json"
        self._profile: Optional[PlayerProfile] = None
    
    def get_profile(self) -> PlayerProfile:
        """Get the current player profile, loading from disk if needed."""
        if self._profile is None:
            self._profile = self._load_profile()
        return self._profile
    
    def save_profile(self, profile: Optional[PlayerProfile] = None) -> None:
        """Save profile to disk."""
        if profile is not None:
            self._profile = profile
        if self._profile is None:
            return
        
        self._profile.updated_at = datetime.now(timezone.utc).isoformat()
        
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with open(self.profile_path, "w") as f:
            json.dump(self._profile.to_dict(), f, indent=2)
    
    def _load_profile(self) -> PlayerProfile:
        """Load profile from disk or create new one."""
        if self.profile_path.exists():
            try:
                with open(self.profile_path) as f:
                    data = json.load(f)
                return PlayerProfile.from_dict(data)
            except (json.JSONDecodeError, KeyError):
                pass
        
        # Create new empty profile (no default domains)
        profile = PlayerProfile()
        # Domains are created dynamically when XP is awarded
        return profile
    
    def award_xp(
        self,
        amount: int,
        domain: Optional[str] = None,
        quest_id: Optional[str] = None,
        source: str = "quest",
    ) -> Dict[str, Any]:
        """
        Award XP to the player.
        
        Args:
            amount: XP amount to award
            domain: Domain/module to attribute XP to (optional)
            quest_id: Quest that awarded this XP (for tracking)
            source: Source of XP ("quest", "bonus", etc.)
        
        Returns:
            Dict with award details and any level-ups/tier-ups
        """
        profile = self.get_profile()
        result = {
            "xp_awarded": amount,
            "domain": domain,
            "quest_id": quest_id,
            "source": source,
            "level_up": False,
            "tier_up": False,
            "new_level": profile.level,
            "new_tier": None,
        }
        
        old_level = profile.level
        old_tier = None
        
        # Award total XP
        profile.total_xp += amount
        profile.level = compute_level(profile.total_xp)
        result["new_level"] = profile.level
        
        if profile.level > old_level:
            result["level_up"] = True
            result["levels_gained"] = profile.level - old_level
        
        # Award domain XP if specified
        if domain:
            if domain not in profile.domains:
                profile.domains[domain] = DomainXP()
            
            domain_data = profile.domains[domain]
            old_tier = domain_data.tier
            
            domain_data.xp += amount
            domain_data.tier = compute_tier(domain_data.xp)
            domain_data.last_quest_at = datetime.now(timezone.utc).isoformat()
            
            if quest_id:
                domain_data.quests_completed += 1
            
            result["new_tier"] = domain_data.tier
            result["domain_xp"] = domain_data.xp
            
            if domain_data.tier > old_tier:
                result["tier_up"] = True
                result["old_tier"] = old_tier
        
        self.save_profile()
        return result
    
    def add_title(self, title: str) -> bool:
        """Add a title to the player profile."""
        profile = self.get_profile()
        if title not in profile.titles:
            profile.titles.append(title)
            self.save_profile()
            return True
        return False
    
    def add_visual_unlock(self, unlock: str) -> bool:
        """Add a visual unlock to the player profile."""
        profile = self.get_profile()
        if unlock not in profile.visual_unlocks:
            profile.visual_unlocks.append(unlock)
            self.save_profile()
            return True
        return False
    
    def add_shortcut(self, shortcut: str) -> bool:
        """Add an unlocked shortcut to the player profile."""
        profile = self.get_profile()
        if shortcut not in profile.unlocked_shortcuts:
            profile.unlocked_shortcuts.append(shortcut)
            self.save_profile()
            return True
        return False
    
    def apply_quest_rewards(
        self,
        xp: int,
        domain: str,
        quest_id: str,
        titles: Optional[List[str]] = None,
        shortcuts: Optional[List[str]] = None,
        visual_unlock: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Apply all rewards from quest completion.
        
        Returns summary of all rewards applied.
        """
        result = {
            "xp_result": None,
            "titles_added": [],
            "shortcuts_added": [],
            "visual_added": None,
        }
        
        # Award XP
        result["xp_result"] = self.award_xp(xp, domain=domain, quest_id=quest_id)
        
        # Add titles
        if titles:
            for title in titles:
                if self.add_title(title):
                    result["titles_added"].append(title)
        
        # Add shortcuts
        if shortcuts:
            for shortcut in shortcuts:
                if self.add_shortcut(shortcut):
                    result["shortcuts_added"].append(shortcut)
        
        # Add visual unlock
        if visual_unlock:
            if self.add_visual_unlock(visual_unlock):
                result["visual_added"] = visual_unlock
        
        return result
    
    def get_domain_summary(self) -> List[Dict[str, Any]]:
        """Get summary of all domains with XP and tier info."""
        profile = self.get_profile()
        summary = []
        
        for domain_id, domain_data in profile.domains.items():
            summary.append({
                "domain": domain_id,
                "xp": domain_data.xp,
                "tier": domain_data.tier,
                "tier_name": get_tier_name(domain_data.tier),
                "quests_completed": domain_data.quests_completed,
                "xp_to_next_tier": get_xp_to_next_tier(domain_data.xp, domain_data.tier),
            })
        
        # Sort by XP descending
        summary.sort(key=lambda x: -x["xp"])
        return summary
    
    def reset_profile(self) -> None:
        """Reset player profile to empty state (no default domains)."""
        self._profile = PlayerProfile()
        # Domains are created dynamically when XP is awarded
        self.save_profile()


# =============================================================================
# COMMAND HANDLERS
# =============================================================================

def handle_identity_show(cmd_name, args, session_id, context, kernel, meta):
    """
    Show player profile (level, XP, titles, domains).
    
    Usage:
        #identity-show
    """
    from .command_types import CommandResponse
    
    manager = getattr(kernel, 'player_profile_manager', None)
    if not manager:
        return CommandResponse(
            ok=False,
            command=cmd_name,
            summary="Player profile not available.",
            error_code="NO_PROFILE_MANAGER",
        )
    
    profile = manager.get_profile()
    domain_summary = manager.get_domain_summary()
    
    # Build display
    lines = [
        "╔══ Player Profile ══╗",
        "",
        f"⭐ **Level {profile.level}**",
        f"   Total XP: {profile.total_xp}",
        f"   Next level: {profile.get_xp_to_next_level()} XP needed",
        f"   Progress: {profile.get_level_progress_pct():.0f}%",
        "",
    ]
    
    # Titles
    if profile.titles:
        lines.append(f"🏆 **Titles:** {', '.join(profile.titles)}")
    else:
        lines.append("🏆 **Titles:** None yet")
    lines.append("")
    
    # Domains
    lines.append("🗺️ **Domains:**")
    for d in domain_summary:
        if d["xp"] > 0:
            tier_icon = "⭐" * d["tier"]
            lines.append(f"   {d['domain'].title()}: {d['xp']} XP • {d['tier_name']} {tier_icon}")
            if d["xp_to_next_tier"] > 0:
                lines.append(f"      └─ {d['xp_to_next_tier']} XP to next tier")
    
    # Check if no domains have XP
    if not any(d["xp"] > 0 for d in domain_summary):
        lines.append("   No domain progress yet. Complete quests to earn XP!")
    
    lines.append("")
    
    # Unlocks
    if profile.unlocked_shortcuts:
        lines.append(f"⚡ **Shortcuts:** {', '.join(profile.unlocked_shortcuts)}")
    if profile.visual_unlocks:
        lines.append(f"✨ **Visuals:** {', '.join(profile.visual_unlocks)}")
    
    return CommandResponse(
        ok=True,
        command=cmd_name,
        summary="\n".join(lines),
        data=profile.to_dict(),
    )


def handle_identity_set(cmd_name, args, session_id, context, kernel, meta):
    """
    Set an identity trait.
    
    Usage:
        #identity-set title="New Title"
    """
    from .command_types import CommandResponse
    
    manager = getattr(kernel, 'player_profile_manager', None)
    if not manager:
        return CommandResponse(
            ok=False,
            command=cmd_name,
            summary="Player profile not available.",
            error_code="NO_PROFILE_MANAGER",
        )
    
    if not isinstance(args, dict):
        return CommandResponse(
            ok=False,
            command=cmd_name,
            summary="Usage: `#identity-set title=\"New Title\"`",
            error_code="INVALID_ARGS",
        )
    
    title = args.get("title")
    if title:
        if manager.add_title(title):
            return CommandResponse(
                ok=True,
                command=cmd_name,
                summary=f"✓ Added title: **{title}**",
            )
        else:
            return CommandResponse(
                ok=True,
                command=cmd_name,
                summary=f"Title **{title}** already exists.",
            )
    
    return CommandResponse(
        ok=False,
        command=cmd_name,
        summary="No valid trait provided. Usage: `#identity-set title=\"...\"`",
        error_code="INVALID_ARGS",
    )


def handle_identity_clear(cmd_name, args, session_id, context, kernel, meta):
    """
    Clear/reset player profile.
    
    Usage:
        #identity-clear confirm=yes
    """
    from .command_types import CommandResponse
    
    manager = getattr(kernel, 'player_profile_manager', None)
    if not manager:
        return CommandResponse(
            ok=False,
            command=cmd_name,
            summary="Player profile not available.",
            error_code="NO_PROFILE_MANAGER",
        )
    
    confirm = args.get("confirm", "") if isinstance(args, dict) else ""
    
    if confirm.lower() != "yes":
        return CommandResponse(
            ok=True,
            command=cmd_name,
            summary="⚠️ This will reset your entire player profile (level, XP, titles, etc.).\n\n"
                    "Run `#identity-clear confirm=yes` to confirm.",
            data={"needs_confirmation": True},
        )
    
    manager.reset_profile()
    
    return CommandResponse(
        ok=True,
        command=cmd_name,
        summary="✓ Player profile has been reset.",
    )


# =============================================================================
# HANDLER REGISTRY
# =============================================================================

PLAYER_PROFILE_HANDLERS = {
    "handle_identity_show": handle_identity_show,
    "handle_identity_set": handle_identity_set,
    "handle_identity_clear": handle_identity_clear,
}


def get_player_profile_handlers():
    """Get all player profile handlers for registration."""
    return PLAYER_PROFILE_HANDLERS
