# kernel/quest_handlers.py
"""
v0.8.3 — Quest Command Handlers

Handlers for all quest-related syscommands:
- quest         - Open Quest Board, start/resume quests
- next          - Advance to next step
- pause         - Pause active quest
- quest-log     - View progress, XP, skills, streaks
- quest-reset   - Reset quest progress
- quest-compose - Create new quest with interactive wizard
- quest-delete  - Delete a quest
- quest-list    - List all quest definitions
- quest-inspect - Inspect quest details
- quest-debug   - Debug output

IMPORTANT: These commands are EXPLICIT only.
The NL router should NEVER auto-execute these commands.
It should only SUGGEST them.

v0.8.3 CHANGES:
- Refactored #quest-compose to use interactive multi-step wizard
- Added support for pre-filling wizard from arguments
- Added non-interactive mode for scripted usage
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from .command_types import CommandResponse
from .formatting import OutputFormatter as F

# Import the quest compose wizard
from .quest_compose_wizard import (
    handle_quest_compose_wizard,
    is_compose_wizard_active,
    process_compose_wizard_input,
    clear_compose_session,
)


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
        #quest              - Show Quest Board
        #quest 1            - Start/resume quest by index
        #quest id=jwt_intro - Start/resume quest by ID
        #quest region=cyber - Filter by region/module
    """
    engine = kernel.quest_engine
    
    # Try to get module store for region names
    module_store = None
    try:
        from .module_manager import ModuleStore
        module_store = ModuleStore(kernel.config)
    except Exception:
        pass
    
    # Parse arguments
    quest_id = None
    region_filter = None
    
    if isinstance(args, dict):
        quest_id = args.get("id") or args.get("name")
        region_filter = args.get("region") or args.get("module")
        
        # Check for positional argument (index)
        positional = args.get("_", [])
        if positional and not quest_id:
            try:
                # If numeric, treat as index
                idx = int(positional[0])
                quests = engine.list_quests()
                if 1 <= idx <= len(quests):
                    quest_id = quests[idx - 1].id
                else:
                    return _error_response(cmd_name, f"Invalid quest index: {idx}", "INVALID_INDEX")
            except ValueError:
                # Not numeric, treat as quest ID
                quest_id = positional[0]
    
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
    
    # Group quests by module (if modules exist)
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
            lines.append(f"{i}. {status_icon} **{q.title}** {boss_icon}")
            lines.append(f"   {_difficulty_stars(q.difficulty)} • {q.step_count} steps")
    else:
        # Full view - group by category/module
        by_category: Dict[str, list] = {}
        for q in quests:
            cat = q.module_id or q.category
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(q)
        
        quest_num = 1
        for category, cat_quests in by_category.items():
            # Get category display name
            module = module_store.get(category) if module_store else None
            cat_name = module.realm_name if module else category.title()
            
            lines.append(f"**{cat_name}**")
            for q in cat_quests:
                status_icon = _status_emoji(q.status)
                boss_icon = "👑" if q.has_boss else ""
                lines.append(f"  {quest_num}. {status_icon} {q.title} {boss_icon}")
                quest_num += 1
            lines.append("")
    
    lines.append("")
    lines.append("Start a quest: `#quest <number>` or `#quest id=<id>`")
    
    return _base_response(cmd_name, "\n".join(lines), {
        "quest_count": len(quests),
        "active_quest": active_run.quest_id if active_run else None,
    })


# =============================================================================
# NEXT (ADVANCE STEP)
# =============================================================================

def handle_next(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    Submit your answer and advance to the next step in the active quest.
    
    Usage:
        #next
        #next skip  - Skip current step
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
        return _error_response(cmd_name, "Quest not found.", "NOT_FOUND")
    
    # Get user's answer from context
    user_input = ""
    if context:
        user_input = context.get("last_user_message", "") or context.get("raw_text", "")
    
    # Check for skip
    skip = False
    if isinstance(args, dict):
        positional = args.get("_", [])
        if positional and positional[0].lower() == "skip":
            skip = True
    
    # Advance the quest
    run, result = engine.advance_quest(active_run.run_id, user_input if not skip else "__SKIP__")
    
    if not run:
        return _error_response(cmd_name, "Failed to advance quest.", "ADVANCE_FAILED")
    
    # Build response
    lines = []
    
    if result:
        # Show feedback from previous step
        if result.status == "passed":
            lines.append(f"✅ **Step passed!** (+{result.xp_gained} XP)")
        elif result.status == "skipped":
            lines.append("⏭️ Step skipped.")
        elif result.status == "failed":
            lines.append(f"❌ {result.feedback_text}")
        
        if result.feedback_text and result.status == "passed":
            lines.append(f"_{result.feedback_text}_")
        
        lines.append("")
        
        # Quest completed?
        if result.quest_completed:
            lines.append("🎉 **Quest Complete!**")
            lines.append("")
            if quest.rewards:
                lines.append(f"**Rewards:** +{quest.rewards.xp} XP")
                if quest.rewards.visual_unlock:
                    lines.append(f"**Unlocked:** {quest.rewards.visual_unlock}")
            lines.append("")
            lines.append("View progress with `#quest-log`.")
            
            return _base_response(cmd_name, "\n".join(lines), {
                "quest_completed": True,
                "quest_id": quest.id,
                "xp_gained": quest.rewards.xp if quest.rewards else 0,
            })
    
    # Show next step
    if result and result.next_step:
        next_step = result.next_step
        step_num = run.current_step_index + 1
        total_steps = len(quest.steps)
        
        lines.append(f"╔══ {quest.title} ══╗")
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
    
    return _base_response(cmd_name, "\n".join(lines), {
        "quest_id": quest.id,
        "step_index": run.current_step_index,
    })


# =============================================================================
# PAUSE
# =============================================================================

def handle_pause(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    Pause the active quest and save your progress.
    
    Usage:
        #pause
    """
    engine = kernel.quest_engine
    active_run = engine.get_active_run()
    
    if not active_run:
        return _error_response(
            cmd_name,
            "No active quest to pause.",
            "NO_ACTIVE_QUEST"
        )
    
    quest = engine.get_quest(active_run.quest_id)
    run = engine.pause_quest(active_run.run_id)
    
    if not run:
        return _error_response(cmd_name, "Failed to pause quest.", "PAUSE_FAILED")
    
    quest_name = quest.title if quest else active_run.quest_id
    step_num = run.current_step_index + 1
    
    return _base_response(
        cmd_name,
        f"⏸️ **{quest_name}** paused at step {step_num}.\n\n"
        f"Resume anytime with `#quest id={active_run.quest_id}`.",
        {"quest_id": active_run.quest_id, "step": step_num}
    )


# =============================================================================
# QUEST LOG
# =============================================================================

def handle_quest_log(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    View your quest progress, XP, skills, and learning streak.
    
    Usage:
        #quest-log
    """
    engine = kernel.quest_engine
    progress = engine.get_progress()
    active_run = engine.get_active_run()
    
    lines = ["╔══ Quest Log ══╗", ""]
    
    # Active quest
    if active_run:
        quest = engine.get_quest(active_run.quest_id)
        if quest:
            step_num = active_run.current_step_index + 1
            lines.append(f"🎯 **Current Quest:** {quest.title}")
            lines.append(f"   Step {step_num}/{len(quest.steps)}")
            lines.append("")
    
    # Recent completions
    completed = [
        (qid, qp) for qid, qp in progress.quest_runs.items()
        if qp.status == "completed"
    ]
    if completed:
        lines.append("**Recent Completions:**")
        for qid, qp in completed[-5:]:  # Last 5
            quest = engine.get_quest(qid)
            name = quest.title if quest else qid
            lines.append(f"  ✅ {name}")
        lines.append("")
    
    # Skills / XP (if any)
    if progress.skills:
        lines.append("**Skills:**")
        for skill_path, skill in progress.skills.items():
            lines.append(f"  • {skill_path}: {skill.xp} XP (Tier {skill.tier})")
        lines.append("")
    
    # Streaks
    if progress.streaks:
        lines.append("**Streaks:**")
        for streak_name, streak in progress.streaks.items():
            lines.append(f"  🔥 {streak_name}: {streak.current_streak} days")
        lines.append("")
    
    # Total stats
    total_completed = len([qp for qp in progress.quest_runs.values() if qp.status == "completed"])
    total_xp = sum(s.xp for s in progress.skills.values()) if progress.skills else 0
    
    lines.append(f"**Total:** {total_completed} quests completed • {total_xp} XP earned")
    
    return _base_response(cmd_name, "\n".join(lines), {
        "completed_count": total_completed,
        "total_xp": total_xp,
    })


# =============================================================================
# QUEST RESET
# =============================================================================

def handle_quest_reset(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    Reset a quest's progress so you can replay it from the start.
    
    Usage:
        #quest-reset            - List quests with progress
        #quest-reset id=jwt_t1  - Reset specific quest
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
            if qp.status in ("in_progress", "completed", "paused")
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
# QUEST COMPOSE (INTERACTIVE WIZARD)
# =============================================================================

def handle_quest_compose(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    Compose a new quest with an interactive wizard.
    
    Usage:
        #quest-compose                              - Start interactive wizard
        #quest-compose title="My Quest"             - Pre-fill title, ask for rest
        #quest-compose title="..." category=cyber   - Pre-fill multiple fields
        #quest-compose mode=noninteractive ...      - Create immediately (all fields required)
    
    Interactive wizard guides you through:
    1. Quest metadata (title, category, difficulty, skill path)
    2. Learning objectives (1-3 goals)
    3. Steps (info, recall, apply, reflect, boss)
    4. Completion criteria
    5. Tags
    
    Then shows a preview and asks for confirmation before saving.
    
    Arguments (for pre-filling or non-interactive mode):
        title         - Quest title
        category      - Category (cyber, finance, meta, etc.)
        difficulty    - 1-5
        skill_path    - Skill tree path (e.g., cyber.jwt.intro)
        objectives    - Comma-separated objectives
        steps         - Multi-line step definitions (type: description)
        validation    - Comma-separated completion criteria
        tags          - Comma-separated tags
        mode          - "interactive" (default) or "noninteractive"
    """
    # Delegate to the wizard handler
    return handle_quest_compose_wizard(cmd_name, args, session_id, context, kernel, meta)


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
        lines.append(f"**{q.id}** {boss_icon}")
        lines.append(f"  {q.title} • {q.category} • {_difficulty_stars(q.difficulty)}")
        lines.append(f"  {q.step_count} steps • {_status_emoji(q.status)} {q.status}")
        lines.append("")
    
    lines.append(f"Total: {len(quests)} quests")
    lines.append("")
    lines.append("Inspect: `#quest-inspect id=<id>`")
    lines.append("Create: `#quest-compose`")
    
    return _base_response(cmd_name, "\n".join(lines), {"quest_count": len(quests)})


# =============================================================================
# QUEST INSPECT
# =============================================================================

def handle_quest_inspect(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    Inspect a quest definition and all its steps.
    
    Usage:
        #quest-inspect id=jwt_intro
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
    
    quest = engine.get_quest(quest_id)
    if not quest:
        return _error_response(cmd_name, f"Quest '{quest_id}' not found.", "NOT_FOUND")
    
    # Build detailed view
    lines = [
        f"╔══ {quest.title} ══╗",
        "",
        f"**ID:** {quest.id}",
        f"**Category:** {quest.category}",
        f"**Difficulty:** {_difficulty_stars(quest.difficulty)}",
        f"**Skill Path:** {quest.skill_tree_path}",
        f"**Est. Time:** {quest.estimated_minutes} min",
    ]
    
    if quest.tags:
        lines.append(f"**Tags:** {', '.join(quest.tags)}")
    
    if quest.description:
        lines.append("")
        lines.append(f"_{quest.description}_")
    
    # Steps
    lines.append("")
    lines.append("**Steps:**")
    for i, step in enumerate(quest.steps, 1):
        type_icon = {
            "info": "📖",
            "recall": "🧠",
            "apply": "🔧",
            "reflect": "💭",
            "boss": "👑",
            "mini_boss": "⚔️",
            "action": "▶️",
            "transfer": "↗️",
        }.get(step.type, "•")
        
        title = step.title or step.prompt[:40] + "..." if len(step.prompt) > 40 else step.prompt
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


# =============================================================================
# WIZARD INTEGRATION HELPERS
# =============================================================================

def check_quest_compose_wizard(session_id: str) -> bool:
    """
    Check if a quest-compose wizard is active for this session.
    
    Called by nova_kernel.py to determine if input should be routed to wizard.
    """
    return is_compose_wizard_active(session_id)


def route_to_quest_compose_wizard(session_id: str, user_input: str, kernel: Any) -> CommandResponse:
    """
    Route user input to the active quest-compose wizard.
    
    Called by nova_kernel.py when wizard is active.
    """
    return process_compose_wizard_input(session_id, user_input, kernel)


def cancel_quest_compose_wizard(session_id: str) -> None:
    """
    Cancel any active quest-compose wizard for a session.
    
    Called when user runs a different command or #reset.
    """
    clear_compose_session(session_id)
