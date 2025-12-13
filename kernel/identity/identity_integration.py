# kernel/identity_integration.py
"""
NovaOS Identity Section Integration v1.0.1

This module provides integration hooks for the Identity Section:
- Quest completion XP events
- Title generation hooks
- Timerhythm XP events (daily/weekly review, presence)
- Integration with existing PlayerProfileManager (for backwards compat)

v1.0.1 CHANGES:
- Added award_presence_xp function
- Updated award_daily_review_xp with new streak bonus formula
- Updated award_weekly_review_xp to handle macro goals

USAGE:
After quest completion, call:
    from kernel.identity_integration import award_quest_xp
    result = award_quest_xp(kernel, quest, xp_amount, titles=["Title 1"])

For other XP sources (timerhythm, presence):
    from kernel.identity_integration import award_xp
    result = award_xp(kernel, amount=50, source="timerhythm_daily", ...)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .identity_section import XPEventInput, XPEventResult

logger = logging.getLogger("nova.identity.integration")


# =============================================================================
# HELPER: Get the right manager
# =============================================================================

def get_identity_manager(kernel: Any):
    """
    Get the identity manager, preferring the new system over legacy.
    
    Returns:
        (manager, is_new_system) tuple
    """
    # Try new IdentitySectionManager first
    new_manager = getattr(kernel, 'identity_section_manager', None)
    if new_manager:
        return new_manager, True
    
    # Fall back to legacy PlayerProfileManager
    legacy_manager = getattr(kernel, 'player_profile_manager', None)
    if legacy_manager:
        return legacy_manager, False
    
    return None, False


# =============================================================================
# MAIN XP AWARDING FUNCTION
# =============================================================================

def award_xp(
    kernel: Any,
    amount: int,
    source: str,
    module: Optional[str] = None,
    description: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Award XP through the Identity Section.
    
    This is the universal XP awarding function that all sections should use.
    
    Args:
        kernel: NovaKernel instance
        amount: XP amount to award
        source: Source identifier ("workflow", "timerhythm_daily", "timerhythm_weekly", "presence", "debug")
        module: Optional module/domain name
        description: Human-readable description of why XP was awarded
        metadata: Optional extra metadata
    
    Returns:
        Dict with result info, or None if no manager available
    
    Example:
        result = award_xp(
            kernel,
            amount=150,
            source="workflow",
            module="Cybersecurity",
            description="Completed quest: Azure Identity Lab"
        )
    """
    manager, is_new_system = get_identity_manager(kernel)
    
    if not manager:
        logger.warning("No identity manager available, XP not awarded: %d", amount)
        return None
    
    if is_new_system:
        # Use new Identity Section
        from .identity_section import XPEventInput
        
        event = XPEventInput(
            source=source,
            amount=amount,
            module=module,
            description=description,
            metadata=metadata,
        )
        
        result = manager.apply_xp_event(event)
        
        return result.to_dict()
    else:
        # Use legacy PlayerProfileManager
        result = manager.award_xp(
            amount=amount,
            domain=module,
            quest_id=metadata.get("quest_id") if metadata else None,
            source=source,
        )
        
        return result


# =============================================================================
# QUEST COMPLETION INTEGRATION
# =============================================================================

def award_quest_xp(
    kernel: Any,
    quest_id: str,
    quest_title: str,
    xp_amount: int,
    module: Optional[str] = None,
    difficulty: Optional[int] = None,
    titles: Optional[List[str]] = None,
    visual_unlock: Optional[str] = None,
    shortcuts: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Award XP and rewards for quest completion.
    
    This should be called by the quest completion handler.
    
    Args:
        kernel: NovaKernel instance
        quest_id: Quest identifier
        quest_title: Quest title for description
        xp_amount: XP to award
        module: Module/domain the quest belongs to
        difficulty: Quest difficulty (1-5)
        titles: List of title strings to award
        visual_unlock: Visual unlock string
        shortcuts: List of shortcut strings to unlock
    
    Returns:
        Dict with result info including any level-ups, title awards, etc.
    """
    manager, is_new_system = get_identity_manager(kernel)
    
    result = {
        "xp_awarded": xp_amount,
        "quest_id": quest_id,
        "quest_title": quest_title,
        "level_up": False,
        "module_level_up": False,
        "titles_added": [],
        "visual_added": None,
        "shortcuts_added": [],
    }
    
    if not manager:
        logger.warning("No identity manager available for quest XP award")
        return result
    
    if is_new_system:
        # Use new Identity Section
        from .identity_section import XPEventInput
        
        # Award XP
        event = XPEventInput(
            source="workflow",
            amount=xp_amount,
            module=module,
            description=f"Completed quest: {quest_title}",
            metadata={
                "quest_id": quest_id,
                "difficulty": difficulty,
            },
        )
        
        xp_result = manager.apply_xp_event(event)
        
        result["level_up"] = xp_result.level_up
        result["levels_gained"] = xp_result.levels_gained
        result["new_level"] = xp_result.new_level
        result["module_level_up"] = xp_result.module_level_up
        result["new_module_level"] = xp_result.new_module_level
        result["archetype_evolved"] = xp_result.archetype_evolved
        result["new_archetype"] = xp_result.new_archetype
        
        # Award titles
        if titles:
            for title_text in titles:
                title = manager.add_title(
                    text=title_text,
                    source="workflow",
                    module=module,
                    meta={"quest_id": quest_id, "difficulty": difficulty},
                    auto_equip=(len(titles) == 1),  # Auto-equip if only one title
                )
                result["titles_added"].append(title_text)
        
        # Handle visual unlocks and shortcuts (store in state)
        state = manager.get_state()
        
        if visual_unlock and visual_unlock not in state.visual_unlocks:
            state.visual_unlocks.append(visual_unlock)
            result["visual_added"] = visual_unlock
            manager._save()
        
        if shortcuts:
            for sc in shortcuts:
                if sc not in state.unlocked_shortcuts:
                    state.unlocked_shortcuts.append(sc)
                    result["shortcuts_added"].append(sc)
            if result["shortcuts_added"]:
                manager._save()
        
    else:
        # Use legacy PlayerProfileManager
        legacy_result = manager.apply_quest_rewards(
            xp=xp_amount,
            domain=module,
            quest_id=quest_id,
            titles=titles,
            shortcuts=shortcuts,
            visual_unlock=visual_unlock,
        )
        
        if legacy_result.get("xp_result"):
            result["level_up"] = legacy_result["xp_result"].get("level_up", False)
            result["new_level"] = legacy_result["xp_result"].get("new_level")
            result["module_level_up"] = legacy_result["xp_result"].get("tier_up", False)
        
        result["titles_added"] = legacy_result.get("titles_added", [])
        result["visual_added"] = legacy_result.get("visual_added")
        result["shortcuts_added"] = legacy_result.get("shortcuts_added", [])
    
    logger.info(
        "Quest XP awarded: %d XP for '%s' (module=%s, level_up=%s)",
        xp_amount, quest_title, module, result["level_up"]
    )
    
    return result


# =============================================================================
# TIMERHYTHM INTEGRATION
# =============================================================================

def award_presence_xp(
    kernel: Any,
    xp_amount: int = 10,
) -> Optional[Dict[str, Any]]:
    """
    Award XP for daily presence (first interaction of the day).
    
    Args:
        kernel: NovaKernel instance
        xp_amount: XP amount (default 10)
    
    Returns:
        Dict with result info, or None if no manager available
    """
    return award_xp(
        kernel,
        amount=xp_amount,
        source="presence",
        module=None,
        description="First interaction today",
        metadata={"type": "presence"},
    )


def award_daily_review_xp(
    kernel: Any,
    streak: int = 0,
    notes: str = "",
) -> Optional[Dict[str, Any]]:
    """
    Award XP for completing a daily review.
    
    XP Formula:
    - Base: 20 XP
    - Streak 1-3: +0 bonus
    - Streak 4-6: +5 bonus
    - Streak 7+: +10 bonus
    
    Args:
        kernel: NovaKernel instance
        streak: Current daily review streak (after this completion)
        notes: Optional notes about the review
    
    Returns:
        Dict with result info
    """
    # Calculate XP based on streak
    base_xp = 20
    
    if streak >= 7:
        bonus = 10
    elif streak >= 4:
        bonus = 5
    else:
        bonus = 0
    
    total_xp = base_xp + bonus
    
    description = f"Daily review (streak {streak} days)"
    
    return award_xp(
        kernel,
        amount=total_xp,
        source="timerhythm_daily",
        module=None,  # Daily reviews don't go to a specific module
        description=description,
        metadata={"streak": streak, "notes": notes, "base_xp": base_xp, "bonus": bonus},
    )


def award_weekly_review_xp(
    kernel: Any,
    xp_amount: int,
    goal_name: str,
    module: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Award XP for completing a weekly macro goal.
    
    Args:
        kernel: NovaKernel instance
        xp_amount: XP amount for this goal
        goal_name: Name of the macro goal achieved
        module: Module to attribute XP to (if applicable)
    
    Returns:
        Dict with result info
    """
    return award_xp(
        kernel,
        amount=xp_amount,
        source="timerhythm_weekly",
        module=module,
        description=f"Weekly macro: {goal_name}",
        metadata={"goal": goal_name},
    )


# =============================================================================
# DEBUG / MANUAL XP
# =============================================================================

def award_debug_xp(
    kernel: Any,
    amount: int,
    module: Optional[str] = None,
    description: str = "Debug XP award",
) -> Optional[Dict[str, Any]]:
    """
    Award debug XP (for testing).
    
    This is marked with source="debug" so it can be identified as test XP.
    """
    return award_xp(
        kernel,
        amount=amount,
        source="debug",
        module=module,
        description=description,
    )


# =============================================================================
# MODULE EXPORTS
# =============================================================================

__all__ = [
    "get_identity_manager",
    "award_xp",
    "award_quest_xp",
    "award_presence_xp",
    "award_daily_review_xp",
    "award_weekly_review_xp",
    "award_debug_xp",
]
