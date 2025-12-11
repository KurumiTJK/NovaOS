# kernel/identity_handlers.py
"""
NovaOS Identity Section Command Handlers v1.0.0

Handlers for the Identity Section syscommands:
- identity-show: Show character sheet
- identity-set: Update profile and goals (NOT XP)
- identity-clear: Reset progression (soft/hard)

Note: Modules are displayed as "Domains" in user-facing output,
but internally we use "modules" terminology.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .command_types import CommandResponse


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _base_response(
    cmd_name: str,
    summary: str,
    extra: Dict[str, Any] | None = None,
) -> CommandResponse:
    return CommandResponse(
        ok=True,
        command=cmd_name,
        summary=summary,
        data=extra or {},
        type=cmd_name,
    )


def _error_response(
    cmd_name: str,
    message: str,
    error_code: str = "ERROR",
) -> CommandResponse:
    return CommandResponse(
        ok=False,
        command=cmd_name,
        summary=message,
        error_code=error_code,
        error_message=message,
        type=cmd_name,
    )


def _priority_icon(priority: Optional[str]) -> str:
    """Get icon for priority level."""
    return {
        "high": "🔴",
        "medium": "🟡",
        "low": "🟢",
    }.get(priority or "", "⚪")


def _module_level_display(level: int) -> str:
    """Get display string for module level."""
    # Use level names similar to archetype ranks
    names = {
        1: "Novice",
        2: "Apprentice",
        3: "Journeyman",
        4: "Expert",
        5: "Master",
    }
    if level in names:
        return f"{names[level]} {'⭐' * level}"
    return f"Level {level} {'⭐' * min(level, 5)}"


# =============================================================================
# #identity-show HANDLER
# =============================================================================

def handle_identity_show(
    cmd_name: str,
    args: Dict[str, Any],
    session_id: str,
    context: Dict[str, Any],
    kernel: Any,
    meta: Any,
) -> CommandResponse:
    """
    Show the player's character sheet.
    
    Usage:
        #identity-show
    
    Displays:
    - Name, Archetype, Vibe tags
    - Active Goals
    - Level, XP progress
    - Equipped Title
    - Top Domains (modules displayed as "Domains")
    - Recent XP events
    """
    # Get identity manager
    manager = getattr(kernel, 'identity_section_manager', None)
    if not manager:
        # Fallback to legacy player_profile_manager
        legacy_manager = getattr(kernel, 'player_profile_manager', None)
        if legacy_manager:
            return _handle_legacy_identity_show(cmd_name, legacy_manager)
        return _error_response(cmd_name, "Identity system not available.", "NO_MANAGER")
    
    state = manager.get_state()
    summary = manager.get_profile_summary()
    
    # Build character sheet display
    lines = []
    
    # Header
    lines.append("╔══ Identity Overview ══╗")
    lines.append("")
    
    # Core profile
    lines.append(f"**Name:** {state.display_name}")
    lines.append(f"**Archetype:** {state.archetype.current} (Rank: {state.archetype.rank})")
    
    if state.vibe_tags:
        lines.append(f"**Vibe:** {', '.join(state.vibe_tags)}")
    
    lines.append("")
    
    # Active Goals
    active_goals = [g for g in state.goals if g.status == "active"]
    if active_goals:
        lines.append("**Active Goals:**")
        for g in active_goals[:3]:  # Top 3
            icon = _priority_icon(g.priority)
            cat = f" [{g.category}]" if g.category else ""
            lines.append(f"  {icon} {g.text}{cat}")
        if len(active_goals) > 3:
            lines.append(f"  ... and {len(active_goals) - 3} more")
        lines.append("")
    
    # Progression
    lines.append(f"**Level:** {state.level}")
    lines.append(f"**XP:** {state.current_xp} / {state.xp_to_next} to next level (total: {state.total_xp})")
    
    # Equipped title
    if state.equipped_title:
        lines.append(f"**Equipped Title:** {state.equipped_title}")
    else:
        lines.append("**Equipped Title:** None")
    
    lines.append("")
    
    # Top Domains (internally "modules")
    lines.append("**Top Domains:**")
    sorted_modules = sorted(
        [(k, v) for k, v in state.modules.items() if v.xp > 0],
        key=lambda x: -x[1].xp
    )
    
    if sorted_modules:
        for mod_id, mod_data in sorted_modules[:3]:
            level_str = _module_level_display(mod_data.level)
            # Use title case for display
            display_name = mod_id.replace("_", " ").title()
            lines.append(f"  • {display_name} — Level {mod_data.level} ({mod_data.xp} XP)")
    else:
        lines.append("  No domain progress yet. Complete quests to earn XP!")
    
    lines.append("")
    
    # Recent XP events
    if state.xp_history:
        lines.append("**Recent XP:**")
        for evt in reversed(state.xp_history[-2:]):
            mod_str = f" ({evt.module})" if evt.module else ""
            lines.append(f"  • +{evt.amount} XP from {evt.source.replace('_', ' ').title()}{mod_str}")
            if evt.description:
                lines.append(f"    └─ {evt.description[:60]}{'...' if len(evt.description) > 60 else ''}")
    
    # Footer with hints
    lines.append("")
    lines.append("**Commands:** `#identity-set name=\"...\"` | `#quest` | `#quest-log`")
    
    return _base_response(cmd_name, "\n".join(lines), state.to_dict())


def _handle_legacy_identity_show(cmd_name: str, manager: Any) -> CommandResponse:
    """Fallback handler for legacy PlayerProfileManager."""
    profile = manager.get_profile()
    domain_summary = manager.get_domain_summary()
    
    lines = [
        "╔══ Player Profile ══╗",
        "",
        f"⭐ **Level {profile.level}**",
        f"   Total XP: {profile.total_xp}",
        f"   Next level: {profile.get_xp_to_next_level()} XP needed",
        f"   Progress: {profile.get_level_progress_pct():.0f}%",
        "",
    ]
    
    if profile.titles:
        lines.append(f"🏆 **Titles:** {', '.join(profile.titles)}")
    else:
        lines.append("🏆 **Titles:** None yet")
    lines.append("")
    
    lines.append("🗺️ **Domains:**")
    for d in domain_summary:
        if d["xp"] > 0:
            tier_icon = "⭐" * d["tier"]
            lines.append(f"   {d['domain'].title()}: {d['xp']} XP • {d['tier_name']} {tier_icon}")
    
    if not any(d["xp"] > 0 for d in domain_summary):
        lines.append("   No domain progress yet. Complete quests to earn XP!")
    
    return _base_response(cmd_name, "\n".join(lines), profile.to_dict())


# =============================================================================
# #identity-set HANDLER
# =============================================================================

def handle_identity_set(
    cmd_name: str,
    args: Dict[str, Any],
    session_id: str,
    context: Dict[str, Any],
    kernel: Any,
    meta: Any,
) -> CommandResponse:
    """
    Set identity profile values and goals.
    
    IMPORTANT: This command does NOT modify XP, level, or modules.
    Those are updated only via XP events from other sections.
    
    Usage:
        #identity-set name="Vant"
        #identity-set theme="Cloud Rogue"
        #identity-set vibe="cyber-ethereal, analytical, calm"
        #identity-set goal="Launch pentest SaaS MVP" category=business priority=high
        #identity-set title="Cyber Sentinel"
    """
    manager = getattr(kernel, 'identity_section_manager', None)
    if not manager:
        # Fallback to legacy
        legacy_manager = getattr(kernel, 'player_profile_manager', None)
        if legacy_manager:
            return _handle_legacy_identity_set(cmd_name, args, legacy_manager)
        return _error_response(cmd_name, "Identity system not available.", "NO_MANAGER")
    
    if not isinstance(args, dict):
        return _error_response(
            cmd_name,
            "Usage: `#identity-set name=\"...\"` or `#identity-set goal=\"...\" category=... priority=...`\n\n"
            "**Available options:**\n"
            "• `name` — Set display name\n"
            "• `theme` — Set archetype base theme\n"
            "• `vibe` — Set vibe tags (comma-separated)\n"
            "• `goal` — Add a new goal\n"
            "• `title` — Add a title manually",
            "INVALID_ARGS"
        )
    
    changes = []
    
    # ─────────────────────────────────────────────────────────────────────
    # Display Name
    # ─────────────────────────────────────────────────────────────────────
    name = args.get("name") or args.get("display_name")
    if name:
        manager.set_display_name(str(name))
        changes.append(f"✓ Name set to **{name}**")
    
    # ─────────────────────────────────────────────────────────────────────
    # Archetype Base Theme
    # ─────────────────────────────────────────────────────────────────────
    theme = args.get("theme") or args.get("base_theme") or args.get("archetype")
    if theme:
        manager.set_base_theme(str(theme))
        state = manager.get_state()
        changes.append(f"✓ Archetype base theme set to **{theme}**")
        changes.append(f"  Current archetype: **{state.archetype.current}**")
    
    # ─────────────────────────────────────────────────────────────────────
    # Vibe Tags
    # ─────────────────────────────────────────────────────────────────────
    vibe = args.get("vibe") or args.get("vibe_tags")
    if vibe:
        if isinstance(vibe, str):
            tags = [t.strip() for t in vibe.split(",") if t.strip()]
        else:
            tags = list(vibe)
        manager.set_vibe_tags(tags)
        changes.append(f"✓ Vibe tags set to: {', '.join(tags)}")
    
    # ─────────────────────────────────────────────────────────────────────
    # Goal
    # ─────────────────────────────────────────────────────────────────────
    goal_text = args.get("goal")
    if goal_text:
        category = args.get("category")
        priority = args.get("priority")
        if priority and priority not in ("low", "medium", "high"):
            changes.append(f"⚠️ Invalid priority '{priority}'. Use: low, medium, high")
            priority = None
        
        goal = manager.add_goal(str(goal_text), category=category, priority=priority)
        icon = _priority_icon(priority)
        cat_str = f" [{category}]" if category else ""
        changes.append(f"✓ Goal added: {icon} **{goal_text}**{cat_str}")
    
    # ─────────────────────────────────────────────────────────────────────
    # Title
    # ─────────────────────────────────────────────────────────────────────
    title = args.get("title")
    if title:
        t = manager.add_title(str(title), source="manual", auto_equip=False)
        changes.append(f"✓ Title added: **{title}**")
    
    # ─────────────────────────────────────────────────────────────────────
    # Equip Title
    # ─────────────────────────────────────────────────────────────────────
    equip_title = args.get("equip")
    if equip_title:
        if manager.equip_title(str(equip_title)):
            changes.append(f"✓ Equipped title: **{equip_title}**")
        else:
            changes.append(f"⚠️ Title '{equip_title}' not found in your titles")
    
    # ─────────────────────────────────────────────────────────────────────
    # Rejection: XP / Level / Module modifications
    # ─────────────────────────────────────────────────────────────────────
    rejected_keys = []
    for key in ["xp", "level", "total_xp", "current_xp", "module", "domain"]:
        if key in args:
            rejected_keys.append(key)
    
    if rejected_keys:
        changes.append(
            f"\n⚠️ Cannot modify: {', '.join(rejected_keys)}\n"
            "   XP and levels come from completing quests and reviews."
        )
    
    if not changes:
        return _error_response(
            cmd_name,
            "No valid changes provided.\n\n"
            "**Available options:**\n"
            "• `name=\"...\"` — Set display name\n"
            "• `theme=\"...\"` — Set archetype base theme\n"
            "• `vibe=\"..., ...\"` — Set vibe tags\n"
            "• `goal=\"...\"` — Add a goal (with `category=` and `priority=`)\n"
            "• `title=\"...\"` — Add a title\n"
            "• `equip=\"...\"` — Equip an existing title",
            "NO_CHANGES"
        )
    
    return _base_response(cmd_name, "\n".join(changes))


def _handle_legacy_identity_set(cmd_name: str, args: Dict[str, Any], manager: Any) -> CommandResponse:
    """Fallback handler for legacy PlayerProfileManager."""
    if not isinstance(args, dict):
        return _error_response(cmd_name, "Usage: `#identity-set title=\"...\"`", "INVALID_ARGS")
    
    title = args.get("title")
    if title:
        if manager.add_title(title):
            return _base_response(cmd_name, f"✓ Added title: **{title}**")
        else:
            return _base_response(cmd_name, f"Title **{title}** already exists.")
    
    return _error_response(
        cmd_name,
        "No valid trait provided. Usage: `#identity-set title=\"...\"`",
        "INVALID_ARGS"
    )


# =============================================================================
# #identity-clear HANDLER
# =============================================================================

def handle_identity_clear(
    cmd_name: str,
    args: Dict[str, Any],
    session_id: str,
    context: Dict[str, Any],
    kernel: Any,
    meta: Any,
) -> CommandResponse:
    """
    Clear/reset identity progression.
    
    Usage:
        #identity-clear confirm=yes          — Soft reset (keeps profile, resets XP/levels)
        #identity-clear confirm=yes hard=yes — Hard reset (clears everything)
    
    Soft Reset (default):
    - Resets: level, XP, module XP, titles, XP history, archetype rank
    - Keeps: name, base_theme, vibe_tags, goals
    
    Hard Reset:
    - Clears everything including profile
    """
    manager = getattr(kernel, 'identity_section_manager', None)
    if not manager:
        # Fallback to legacy
        legacy_manager = getattr(kernel, 'player_profile_manager', None)
        if legacy_manager:
            return _handle_legacy_identity_clear(cmd_name, args, legacy_manager)
        return _error_response(cmd_name, "Identity system not available.", "NO_MANAGER")
    
    confirm = args.get("confirm", "") if isinstance(args, dict) else ""
    is_hard = args.get("hard", "").lower() == "yes" if isinstance(args, dict) else False
    
    if confirm.lower() != "yes":
        reset_type = "hard" if is_hard else "soft"
        
        if is_hard:
            warning = (
                "⚠️ **HARD RESET** will clear EVERYTHING:\n"
                "• Level, XP, all progression\n"
                "• All titles and equipped title\n"
                "• All domain/module progress\n"
                "• Name, archetype, vibe tags\n"
                "• All goals\n\n"
                "Run `#identity-clear confirm=yes hard=yes` to confirm."
            )
        else:
            warning = (
                "⚠️ **SOFT RESET** will clear progression:\n"
                "• Level, XP, all progression\n"
                "• All titles and equipped title\n"
                "• All domain/module progress\n"
                "• XP history\n\n"
                "**Keeps:** Name, archetype theme, vibe tags, goals\n\n"
                "Run `#identity-clear confirm=yes` to confirm.\n"
                "Or `#identity-clear confirm=yes hard=yes` for full reset."
            )
        
        return _base_response(
            cmd_name,
            warning,
            {"needs_confirmation": True, "reset_type": reset_type}
        )
    
    if is_hard:
        manager.hard_reset()
        return _base_response(
            cmd_name,
            "✓ **Hard reset complete.**\n\nAll identity data has been cleared.",
        )
    else:
        manager.soft_reset()
        state = manager.get_state()
        return _base_response(
            cmd_name,
            f"✓ **Soft reset complete.**\n\n"
            f"Progression reset. Profile preserved:\n"
            f"• Name: {state.display_name}\n"
            f"• Theme: {state.archetype.base_theme}\n"
            f"• Vibe: {', '.join(state.vibe_tags) if state.vibe_tags else 'Not set'}\n"
            f"• Goals: {len(state.goals)} preserved",
        )


def _handle_legacy_identity_clear(cmd_name: str, args: Dict[str, Any], manager: Any) -> CommandResponse:
    """Fallback handler for legacy PlayerProfileManager."""
    confirm = args.get("confirm", "") if isinstance(args, dict) else ""
    
    if confirm.lower() != "yes":
        return _base_response(
            cmd_name,
            "⚠️ This will reset your entire player profile (level, XP, titles, etc.).\n\n"
            "Run `#identity-clear confirm=yes` to confirm.",
            {"needs_confirmation": True},
        )
    
    manager.reset_profile()
    return _base_response(cmd_name, "✓ Player profile has been reset.")


# =============================================================================
# HANDLER REGISTRY
# =============================================================================

IDENTITY_HANDLERS = {
    "handle_identity_show": handle_identity_show,
    "handle_identity_set": handle_identity_set,
    "handle_identity_clear": handle_identity_clear,
}


def get_identity_handlers():
    """Get all identity handlers for registration."""
    return IDENTITY_HANDLERS
