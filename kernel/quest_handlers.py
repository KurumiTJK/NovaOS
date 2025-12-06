# kernel/quest_handlers.py
"""
v0.8.0 — Quest Command Handlers

Handlers for all quest-related syscommands:
- quest         - Open Quest Board, start/resume quests
- next          - Advance to next step
- pause         - Pause active quest
- quest-log     - View progress, XP, skills, streaks
- quest-reset   - Reset quest progress
- quest-compose - Create new quest with LLM
- quest-delete  - Delete a quest
- quest-list    - List all quest definitions
- quest-inspect - Inspect quest details
- quest-debug   - Debug output

IMPORTANT: These commands are EXPLICIT only.
The NL router should NEVER auto-execute these commands.
It should only SUGGEST them.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from .command_types import CommandResponse
from .formatting import OutputFormatter as F


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


def _difficulty_stars(difficulty: int) -> str:
    """Convert difficulty to star display."""
    return "⭐" * difficulty + "☆" * (5 - difficulty)


def _status_emoji(status: str) -> str:
    """Get emoji for quest status."""
    return {
        "not_started": "⬜",
        "in_progress": "🔶",
        "paused": "⏸️",
        "completed": "✅",
        "abandoned": "❌",
    }.get(status, "⬜")


# =============================================================================
# QUEST BOARD / START
# =============================================================================

def handle_quest(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    Open the Quest Board to list, start, or resume a quest.
    
    Usage:
        #quest              - Show quest board (all regions)
        #quest cyber        - Show quests in cyber region
        #quest id=jwt_t1    - Start/resume specific quest
        #quest 1            - Start quest by index
    """
    engine = kernel.quest_engine
    module_store = getattr(kernel, 'module_store', None)
    
    # Check if specific quest or region requested
    quest_id = None
    region_filter = None
    
    if isinstance(args, dict):
        quest_id = args.get("id") or args.get("name")
        region_filter = args.get("region") or args.get("module")
        
        # Check for positional argument
        positional = args.get("_", [])
        if positional and not quest_id and not region_filter:
            arg = positional[0]
            
            # Check if it's a number (quest index)
            try:
                index = int(arg) - 1  # 1-based to 0-based
                quests = engine.list_quests()
                if 0 <= index < len(quests):
                    quest_id = quests[index].id
            except (ValueError, IndexError):
                # Not a number - check if it's a module ID
                if module_store and module_store.exists(arg):
                    region_filter = arg
                else:
                    # Treat as quest ID
                    quest_id = arg
    
    # If quest ID provided, start/resume that quest
    if quest_id:
        quest = engine.get_quest(quest_id)
        if not quest:
            return _error_response(cmd_name, f"Quest '{quest_id}' not found.", "NOT_FOUND")
        
        run = engine.start_quest(quest_id)
        if not run:
            return _error_response(cmd_name, f"Failed to start quest '{quest_id}'.", "START_FAILED")
        
        # Get current step
        current_step = quest.steps[run.current_step_index] if run.current_step_index < len(quest.steps) else None
        
        if not current_step:
            return _error_response(cmd_name, "Quest has no steps.", "NO_STEPS")
        
        # Build step display
        step_num = run.current_step_index + 1
        total_steps = len(quest.steps)
        
        lines = [
            f"╔══ {quest.title} ══╗",
            f"Step {step_num}/{total_steps} • {current_step.type.upper()} • {_difficulty_stars(current_step.difficulty)}",
            "",
        ]
        
        if current_step.title:
            lines.append(f"**{current_step.title}**")
            lines.append("")
        
        lines.append(current_step.prompt)
        
        if current_step.help_text:
            lines.append("")
            lines.append(f"💡 *{current_step.help_text}*")
        
        lines.append("")
        lines.append("Type your answer and run **#next** to continue.")
        
        return _base_response(cmd_name, "\n".join(lines), {
            "quest_id": quest.id,
            "step_index": run.current_step_index,
            "step_type": current_step.type,
        })
    
    # No quest ID - show Quest Board (optionally filtered by region)
    quests = engine.list_quests()
    active_run = engine.get_active_run()
    
    # Apply region filter if specified
    if region_filter:
        quests = [q for q in quests if (q.module_id or q.category) == region_filter]
        module = module_store.get(region_filter) if module_store else None
        region_name = module.realm_name if module else region_filter.title()
        lines = [f"╔══ {region_name} Quests ══╗", ""]
    else:
        lines = ["╔══ Quest Board ══╗", ""]
    
    # Show active quest if any
    if active_run:
        active_quest = engine.get_quest(active_run.quest_id)
        if active_quest:
            step_num = active_run.current_step_index + 1
            lines.append(f"🎯 **Active Quest:** {active_quest.title}")
            lines.append(f"   Step {step_num}/{len(active_quest.steps)} • Run `#next` to continue")
            lines.append("")
    
    # v0.8.1: Group quests by module (if modules exist)
    if not quests:
        if region_filter:
            lines.append(f"No quests in this module yet.")
        else:
            lines.append("No quests available. Create one with `#quest-compose`.")
    elif region_filter:
        # Filtered view - show flat list for the specific module
        for i, q in enumerate(quests, 1):
            status_icon = _status_emoji(q.status)
            boss_icon = "👑" if q.has_boss else ""
            lines.append(f"{i}. {status_icon} **{q.title}** {_difficulty_stars(q.difficulty)} {boss_icon}")
            lines.append(f"   └─ {q.step_count} steps • id: `{q.id}`")
    elif module_store and module_store.count() > 0:
        # Group by module
        modules = module_store.list_all()
        module_map = {m.id: m for m in modules}
        
        # Organize quests by module
        quests_by_module: Dict[str, List] = {}
        uncategorized = []
        
        for q in quests:
            module_id = q.module_id or q.category
            if module_id in module_map:
                if module_id not in quests_by_module:
                    quests_by_module[module_id] = []
                quests_by_module[module_id].append(q)
            else:
                uncategorized.append(q)
        
        # Display by module
        quest_index = 1
        for module in modules:
            if module.id not in quests_by_module:
                continue
            
            module_quests = quests_by_module[module.id]
            icon = module.icon
            realm = module.realm_name
            
            lines.append(f"{icon} **{realm}**")
            
            for q in module_quests:
                status_icon = _status_emoji(q.status)
                boss_icon = "👑" if q.has_boss else ""
                lines.append(f"   {quest_index}. {status_icon} {q.title} {_difficulty_stars(q.difficulty)} {boss_icon}")
                quest_index += 1
            
            lines.append("")
        
        # Uncategorized quests (module_id doesn't match any module)
        if uncategorized:
            lines.append("📁 **Unassigned**")
            for q in uncategorized:
                status_icon = _status_emoji(q.status)
                boss_icon = "👑" if q.has_boss else ""
                lines.append(f"   {quest_index}. {status_icon} {q.title} {_difficulty_stars(q.difficulty)} {boss_icon}")
                quest_index += 1
            lines.append("")
    else:
        # Flat list (no modules defined)
        for i, q in enumerate(quests, 1):
            status_icon = _status_emoji(q.status)
            boss_icon = "👑" if q.has_boss else ""
            lines.append(f"{i}. {status_icon} **{q.title}** {_difficulty_stars(q.difficulty)} {boss_icon}")
            lines.append(f"   └─ {q.step_count} steps • id: `{q.id}`")
    
    lines.append("")
    lines.append("**Commands:**")
    lines.append("• `#quest <number>` or `#quest id=<id>` — Start/resume quest")
    if region_filter:
        lines.append("• `#quest` — View all quests")
    elif module_store and module_store.count() > 0:
        lines.append("• `#quest <module>` — Filter by module")
    lines.append("• `#quest-log` — View your progress")
    lines.append("• `#modules` — View world map")
    
    return _base_response(cmd_name, "\n".join(lines), {"quests": [q.to_dict() for q in quests], "region_filter": region_filter})


# =============================================================================
# NEXT (ADVANCE)
# =============================================================================

def handle_next(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    Submit your last answer and advance to the next step.
    
    Usage:
        #next
    """
    engine = kernel.quest_engine
    active_run = engine.get_active_run()
    
    if not active_run:
        return _error_response(
            cmd_name,
            "No active quest. Start one with `#quest`.",
            "NO_ACTIVE_QUEST"
        )
    
    quest = engine.get_quest(active_run.quest_id)
    if not quest:
        return _error_response(cmd_name, "Quest not found.", "QUEST_NOT_FOUND")
    
    # Get user input from previous message (stored in context or args)
    user_input = ""
    if isinstance(args, dict):
        user_input = args.get("full_input", "") or args.get("answer", "") or args.get("input", "")
    if not user_input and context:
        user_input = context.get("last_user_message", "") or context.get("raw_text", "")
    
    # If no input, check if current step is info type (just needs to advance)
    current_step = quest.steps[active_run.current_step_index]
    if not user_input and current_step.type != "info":
        # Allow advancing without input for simplicity
        user_input = "[no response]"
    
    # Advance the quest
    updated_run, result = engine.advance_quest(active_run.run_id, user_input)
    
    if not result:
        return _error_response(cmd_name, "Failed to advance quest.", "ADVANCE_FAILED")
    
    lines = []
    
    # Show feedback
    if result.feedback_text:
        lines.append(result.feedback_text)
    
    # Show XP gained
    if result.xp_gained > 0:
        lines.append(f"**+{result.xp_gained} XP**")
    
    # Check if quest completed
    if result.quest_completed:
        lines.append("")
        lines.append("═══════════════════════════════")
        lines.append(f"🎉 **Quest Complete: {quest.title}**")
        lines.append("═══════════════════════════════")
        
        # v0.8.0: Award XP to Player Profile
        profile_manager = getattr(kernel, 'player_profile_manager', None)
        if profile_manager:
            # Calculate total XP from quest
            progress = engine.get_progress()
            quest_progress = progress.quest_runs.get(quest.id)
            total_quest_xp = quest_progress.xp_earned if quest_progress else 0
            
            # Get domain from module_id or category
            domain = quest.module_id or quest.category
            
            # Get rewards
            titles = quest.rewards.titles if quest.rewards else []
            shortcuts = quest.rewards.shortcuts if quest.rewards else []
            visual = quest.rewards.visual_unlock if quest.rewards else None
            
            # Apply all rewards
            reward_result = profile_manager.apply_quest_rewards(
                xp=total_quest_xp,
                domain=domain,
                quest_id=quest.id,
                titles=titles,
                shortcuts=shortcuts,
                visual_unlock=visual,
            )
            
            # Show player profile updates
            xp_info = reward_result.get("xp_result", {})
            if xp_info.get("level_up"):
                lines.append(f"🎊 **LEVEL UP!** You are now level {xp_info['new_level']}!")
            if xp_info.get("tier_up"):
                from .player_profile import get_tier_name
                tier_name = get_tier_name(xp_info.get("new_tier", 1))
                lines.append(f"⬆️ **{domain.title()} tier up!** Now: {tier_name}")
            
            lines.append(f"Total XP earned: **{total_quest_xp}**")
            
            if reward_result.get("titles_added"):
                for title in reward_result["titles_added"]:
                    lines.append(f"🏆 **New Title:** {title}")
            
            if reward_result.get("shortcuts_added"):
                for shortcut in reward_result["shortcuts_added"]:
                    lines.append(f"⚡ **New Shortcut:** {shortcut}")
            
            if reward_result.get("visual_added"):
                lines.append(f"✨ **Visual Unlock:** {reward_result['visual_added']}")
        else:
            # Fallback if no profile manager
            progress = engine.get_progress()
            quest_progress = progress.quest_runs.get(quest.id)
            if quest_progress:
                lines.append(f"Total XP earned: **{quest_progress.xp_earned}**")
        
        # Show boss cleared
        progress = engine.get_progress()
        quest_progress = progress.quest_runs.get(quest.id)
        if quest_progress and quest_progress.boss_cleared:
            lines.append("👑 Boss defeated!")
        
        # Show skill progress
        skill = progress.skills.get(quest.skill_tree_path)
        if skill:
            lines.append(f"Skill: **{quest.skill_tree_path}** — {skill.xp} XP (Tier {skill.current_tier})")
        
        # Show streak
        streak = progress.streaks.get("learning_days")
        if streak and streak.current > 0:
            lines.append(f"🔥 Learning streak: **{streak.current} days**")
        
        lines.append("")
        lines.append("Run `#quest` to see more quests, or `#quest-log` to see your progress.")
        
    elif result.next_step:
        # Show next step
        lines.append("")
        lines.append("───────────────────────────────")
        
        step_num = updated_run.current_step_index + 1
        total_steps = len(quest.steps)
        next_step = result.next_step
        
        lines.append(f"Step {step_num}/{total_steps} • {next_step.type.upper()} • {_difficulty_stars(next_step.difficulty)}")
        lines.append("")
        
        if next_step.title:
            lines.append(f"**{next_step.title}**")
            lines.append("")
        
        lines.append(next_step.prompt)
        
        if next_step.help_text:
            lines.append("")
            lines.append(f"💡 *{next_step.help_text}*")
        
        lines.append("")
        lines.append("Type your answer and run **#next** to continue.")
    
    return _base_response(cmd_name, "\n".join(lines), result.to_dict())


# =============================================================================
# PAUSE
# =============================================================================

def handle_pause(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    Pause the active quest and save progress.
    
    Usage:
        #pause
    """
    engine = kernel.quest_engine
    active_run = engine.get_active_run()
    
    if not active_run:
        return _error_response(
            cmd_name,
            "No active quest to pause. Start one with `#quest`.",
            "NO_ACTIVE_QUEST"
        )
    
    quest = engine.get_quest(active_run.quest_id)
    step_num = active_run.current_step_index + 1
    total_steps = len(quest.steps) if quest else 0
    
    engine.pause_quest(active_run.run_id)
    
    lines = [
        "⏸️ **Quest Paused**",
        "",
        f"Quest: {quest.title if quest else active_run.quest_id}",
        f"Progress: Step {step_num}/{total_steps}",
        "",
        "Resume anytime with `#quest`.",
    ]
    
    return _base_response(cmd_name, "\n".join(lines), {"quest_id": active_run.quest_id})


# =============================================================================
# QUEST LOG
# =============================================================================

def handle_quest_log(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    View your current quest, recent completions, XP, skills, and learning streak.
    
    v0.8.0: Now shows Player Profile data (level, domain XP, titles).
    
    Usage:
        #quest-log
    """
    engine = kernel.quest_engine
    progress = engine.get_progress()
    active_run = engine.get_active_run()
    
    lines = ["╔══ Quest Log ══╗", ""]
    
    # v0.8.0: Show Player Profile summary first
    profile_manager = getattr(kernel, 'player_profile_manager', None)
    if profile_manager:
        profile = profile_manager.get_profile()
        
        lines.append(f"⭐ **Level {profile.level}** — {profile.total_xp} XP total")
        lines.append(f"   Progress to next: {profile.get_level_progress_pct():.0f}% ({profile.get_xp_to_next_level()} XP needed)")
        
        if profile.titles:
            lines.append(f"🏆 Titles: {', '.join(profile.titles)}")
        
        lines.append("")
        
        # Domain breakdown
        domain_summary = profile_manager.get_domain_summary()
        active_domains = [d for d in domain_summary if d["xp"] > 0]
        
        if active_domains:
            lines.append("🗺️ **Domain Progress**")
            for d in active_domains[:5]:  # Top 5
                tier_stars = "⭐" * d["tier"]
                lines.append(f"   {d['domain'].title()}: {d['xp']} XP • {d['tier_name']} {tier_stars}")
            lines.append("")
    
    # Active quest
    if active_run:
        quest = engine.get_quest(active_run.quest_id)
        if quest:
            step_num = active_run.current_step_index + 1
            current_step = quest.steps[active_run.current_step_index] if active_run.current_step_index < len(quest.steps) else None
            
            lines.append("🎯 **Active Quest**")
            lines.append(f"   {quest.title}")
            lines.append(f"   Step {step_num}/{len(quest.steps)}")
            if current_step:
                lines.append(f"   Type: {current_step.type} • Difficulty: {_difficulty_stars(current_step.difficulty)}")
            lines.append(f"   Started: {active_run.started_at[:10]}")
            lines.append("")
    else:
        lines.append("No active quest. Start one with `#quest`.")
        lines.append("")
    
    # Recent completions
    completed = [
        (qid, qp) for qid, qp in progress.quest_runs.items()
        if qp.status == "completed"
    ]
    if completed:
        lines.append("📜 **Recent Completions**")
        for qid, qp in completed[-5:]:  # Last 5
            quest = engine.get_quest(qid)
            name = quest.title if quest else qid
            boss_icon = "👑" if qp.boss_cleared else ""
            lines.append(f"   ✅ {name} — {qp.xp_earned} XP {boss_icon}")
        lines.append("")
    
    # Skills (from quest engine)
    if progress.skills:
        lines.append("🎓 **Skill Trees**")
        for path, skill in progress.skills.items():
            lines.append(f"   {path} — {skill.xp} XP (Tier {skill.current_tier})")
        lines.append("")
    
    # Streak
    streak = progress.streaks.get("learning_days")
    if streak:
        lines.append("🔥 **Learning Streak**")
        lines.append(f"   Current: {streak.current} days")
        lines.append(f"   Longest: {streak.longest} days")
        if streak.last_date:
            lines.append(f"   Last activity: {streak.last_date}")
        lines.append("")
    
    # Total XP
    total_xp = sum(s.xp for s in progress.skills.values())
    lines.append(f"**Total XP:** {total_xp}")
    
    return _base_response(cmd_name, "\n".join(lines), progress.to_dict())


# =============================================================================
# QUEST RESET
# =============================================================================

def handle_quest_reset(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    Reset a quest's progress so you can replay it from the start.
    
    Usage:
        #quest-reset              - List quests that can be reset
        #quest-reset id=jwt_t1    - Reset specific quest
    """
    engine = kernel.quest_engine
    
    # Get quest ID
    quest_id = None
    if isinstance(args, dict):
        quest_id = args.get("id") or args.get("name")
        positional = args.get("_", [])
        if positional and not quest_id:
            quest_id = positional[0]
    
    if not quest_id:
        # List quests with progress
        progress = engine.get_progress()
        resetable = [
            (qid, qp) for qid, qp in progress.quest_runs.items()
            if qp.status in ("in_progress", "completed")
        ]
        
        if not resetable:
            return _base_response(cmd_name, "No quests with progress to reset.")
        
        lines = ["**Quests with progress:**", ""]
        for qid, qp in resetable:
            quest = engine.get_quest(qid)
            name = quest.title if quest else qid
            lines.append(f"• {name} ({qp.status}) — `#quest-reset id={qid}`")
        
        return _base_response(cmd_name, "\n".join(lines))
    
    # Reset specific quest
    quest = engine.get_quest(quest_id)
    if not quest:
        return _error_response(cmd_name, f"Quest '{quest_id}' not found.", "NOT_FOUND")
    
    engine.reset_quest_progress(quest_id)
    
    return _base_response(
        cmd_name,
        f"✓ Progress reset for **{quest.title}**.\n\nStart fresh with `#quest id={quest_id}`.",
        {"quest_id": quest_id}
    )


# =============================================================================
# QUEST COMPOSE (AUTHORING)
# =============================================================================

def handle_quest_compose(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    Compose a new questline with LLM assistance.
    
    Usage:
        #quest-compose
        #quest-compose name="JWT Tier 1"
    """
    # This is a placeholder - full implementation would use LLM
    # For now, provide instructions
    
    lines = [
        "╔══ Quest Composer ══╗",
        "",
        "Quest composition is a multi-step process:",
        "",
        "1. Define quest metadata (title, category, difficulty)",
        "2. Outline learning objectives",
        "3. Design steps (info, recall, apply, reflect, boss)",
        "4. Set validation rules",
        "",
        "**Manual creation:**",
        "Create a JSON file in `data/quests.json` with the quest structure.",
        "",
        "**Quest structure:**",
        "```json",
        "{",
        '  "id": "unique_id",',
        '  "title": "Quest Title",',
        '  "category": "cyber|finance|meta|...",',
        '  "difficulty": 1-5,',
        '  "skill_tree_path": "category.skill.tier",',
        '  "tags": ["learning"],',
        '  "steps": [...]',
        "}",
        "```",
        "",
        "See `#quest-inspect id=jwt_intro` for an example.",
    ]
    
    return _base_response(cmd_name, "\n".join(lines))


# =============================================================================
# QUEST DELETE (ADMIN)
# =============================================================================

def handle_quest_delete(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    Delete a questline and its saved progress.
    
    Usage:
        #quest-delete id=jwt_t1
    """
    engine = kernel.quest_engine
    
    # Get quest ID
    quest_id = None
    if isinstance(args, dict):
        quest_id = args.get("id") or args.get("name")
        positional = args.get("_", [])
        if positional and not quest_id:
            quest_id = positional[0]
    
    if not quest_id:
        return _error_response(cmd_name, "Usage: `#quest-delete id=<quest_id>`", "MISSING_ID")
    
    quest = engine.get_quest(quest_id)
    if not quest:
        return _error_response(cmd_name, f"Quest '{quest_id}' not found.", "NOT_FOUND")
    
    # Check for confirmation
    confirm = None
    if isinstance(args, dict):
        confirm = args.get("confirm", "").lower()
    
    if confirm != "yes":
        return _base_response(
            cmd_name,
            f"⚠️ Delete quest **{quest.title}** and all progress?\n\n"
            f"Run `#quest-delete id={quest_id} confirm=yes` to confirm.",
            {"quest_id": quest_id, "needs_confirmation": True}
        )
    
    engine.delete_quest(quest_id)
    
    return _base_response(
        cmd_name,
        f"✓ Deleted quest **{quest.title}** and all progress.",
        {"quest_id": quest_id, "deleted": True}
    )


# =============================================================================
# QUEST LIST (ADMIN)
# =============================================================================

def handle_quest_list(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    List all quest definitions with IDs, categories, and difficulty.
    
    Usage:
        #quest-list
    """
    engine = kernel.quest_engine
    quests = engine.list_quest_definitions()
    
    if not quests:
        return _base_response(cmd_name, "No quests defined. Create one with `#quest-compose`.")
    
    lines = ["╔══ Quest Definitions ══╗", ""]
    
    for q in quests:
        boss_icon = "👑" if q.has_boss else ""
        lines.append(f"**{q.title}** {boss_icon}")
        lines.append(f"  ID: `{q.id}` • Category: {q.category}")
        lines.append(f"  Difficulty: {_difficulty_stars(q.difficulty)} • Steps: {q.step_count}")
        lines.append("")
    
    lines.append(f"Total: {len(quests)} quests")
    
    return _base_response(cmd_name, "\n".join(lines), {"quests": [q.to_dict() for q in quests]})


# =============================================================================
# QUEST INSPECT (ADMIN)
# =============================================================================

def handle_quest_inspect(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    Inspect a quest definition and all its steps.
    
    Usage:
        #quest-inspect id=jwt_t1
    """
    engine = kernel.quest_engine
    
    # Get quest ID
    quest_id = None
    if isinstance(args, dict):
        quest_id = args.get("id") or args.get("name")
        positional = args.get("_", [])
        if positional and not quest_id:
            quest_id = positional[0]
    
    if not quest_id:
        return _error_response(cmd_name, "Usage: `#quest-inspect id=<quest_id>`", "MISSING_ID")
    
    quest = engine.inspect_quest(quest_id)
    if not quest:
        return _error_response(cmd_name, f"Quest '{quest_id}' not found.", "NOT_FOUND")
    
    lines = [
        f"╔══ Quest: {quest.title} ══╗",
        "",
        f"**ID:** `{quest.id}`",
    ]
    
    if quest.subtitle:
        lines.append(f"**Subtitle:** {quest.subtitle}")
    if quest.description:
        lines.append(f"**Description:** {quest.description}")
    
    lines.append(f"**Category:** {quest.category}")
    lines.append(f"**Skill Path:** {quest.skill_tree_path}")
    lines.append(f"**Difficulty:** {_difficulty_stars(quest.difficulty)}")
    lines.append(f"**Estimated Time:** {quest.estimated_minutes} minutes")
    lines.append(f"**Tags:** {', '.join(quest.tags) if quest.tags else 'none'}")
    lines.append(f"**Total XP:** {quest.total_xp}")
    
    # Steps
    lines.append("")
    lines.append(f"**Steps ({len(quest.steps)}):**")
    for i, step in enumerate(quest.steps, 1):
        type_icon = {"info": "📖", "recall": "🧠", "apply": "🔧", "reflect": "💭", "boss": "👑", "mini_boss": "⚔️"}.get(step.type, "•")
        title = step.title or step.prompt[:40] + "..."
        lines.append(f"  {i}. {type_icon} [{step.type}] {title}")
    
    # Boss
    if quest.boss_step:
        lines.append("")
        lines.append(f"**Boss:** {quest.boss_step.title or 'Final Challenge'}")
        lines.append(f"  Passing threshold: {quest.boss_step.passing_threshold * 100:.0f}%")
    
    # Rewards
    if quest.rewards:
        lines.append("")
        lines.append("**Rewards:**")
        lines.append(f"  XP: {quest.rewards.xp}")
        if quest.rewards.shortcuts:
            lines.append(f"  Shortcuts: {', '.join(quest.rewards.shortcuts)}")
        if quest.rewards.visual_unlock:
            lines.append(f"  Unlock: {quest.rewards.visual_unlock}")
    
    return _base_response(cmd_name, "\n".join(lines), quest.to_dict())


# =============================================================================
# QUEST DEBUG (DEV)
# =============================================================================

def handle_quest_debug(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    Show raw quest engine state for debugging.
    
    Usage:
        #quest-debug
    """
    engine = kernel.quest_engine
    debug_state = engine.get_debug_state()
    
    lines = [
        "╔══ Quest Engine Debug ══╗",
        "",
        "**Active Run:**",
        f"```json",
        json.dumps(debug_state["active_run"], indent=2, default=str),
        "```",
        "",
        "**Quest Count:** " + str(debug_state["quest_count"]),
        "**Quest IDs:** " + ", ".join(debug_state["quest_ids"]),
        "",
        "**Progress State:**",
        "```json",
        json.dumps(debug_state["progress"], indent=2, default=str),
        "```",
    ]
    
    return _base_response(cmd_name, "\n".join(lines), debug_state)


# =============================================================================
# HANDLER REGISTRY
# =============================================================================

QUEST_HANDLERS = {
    "handle_quest": handle_quest,
    "handle_next": handle_next,
    "handle_pause": handle_pause,
    "handle_quest_log": handle_quest_log,
    "handle_quest_reset": handle_quest_reset,
    "handle_quest_compose": handle_quest_compose,
    "handle_quest_delete": handle_quest_delete,
    "handle_quest_list": handle_quest_list,
    "handle_quest_inspect": handle_quest_inspect,
    "handle_quest_debug": handle_quest_debug,
}


def get_quest_handlers() -> Dict[str, Any]:
    """Get all quest handlers for registration in SYS_HANDLERS."""
    return QUEST_HANDLERS
