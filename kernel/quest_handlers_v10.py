# kernel/quest_handlers_v10.py
"""
NovaOS v0.10.0 — Updated Quest Handlers

This file contains the UPDATED handle_quest function that:
1. Starts the wizard when #quest is called with no args
2. Preserves #quest id=<id> as a direct shortcut
3. Integrates with quest lock mode

To integrate:
1. Import this module's handle_quest_v10 in quest_handlers.py
2. Replace handle_quest with handle_quest_v10
3. Or patch via the QUEST_HANDLERS dict

Also provides handle_next_v10 which is backwards-compatible with #next
(kept as an alias for #complete for users who are used to it).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .command_types import CommandResponse
from .quest_lock_mode import (
    is_quest_active,
    get_quest_lock_state,
    activate_quest_lock,
)
from .quest_start_wizard import (
    handle_quest_wizard_start,
    process_quest_wizard_input,
    is_quest_wizard_active,
)


# =============================================================================
# RESPONSE HELPERS
# =============================================================================

def _base_response(cmd_name: str, summary: str, data: Dict[str, Any] = None) -> CommandResponse:
    return CommandResponse(
        ok=True,
        command=cmd_name,
        summary=summary,
        data=data or {},
        type=cmd_name,
    )


def _error_response(cmd_name: str, message: str, code: str = "ERROR") -> CommandResponse:
    return CommandResponse(
        ok=False,
        command=cmd_name,
        summary=message,
        error_code=code,
        error_message=message,
        type=cmd_name,
    )


def _difficulty_stars(difficulty: int) -> str:
    """Convert difficulty to star display."""
    return "⭐" * difficulty + "☆" * (5 - difficulty)


# =============================================================================
# STEP DISPLAY FORMATTING
# =============================================================================

def _format_step_display(quest_title: str, step: Any, step_num: int, total_steps: int) -> list:
    """
    Format a step for display with title, prompt, and actions.
    """
    lines = [
        f"╔══ {quest_title} ══╗",
        f"Day {step_num}/{total_steps} • {step.type.upper()} • {_difficulty_stars(getattr(step, 'difficulty', 1))}",
        "",
    ]
    
    if step.title:
        lines.append(f"**{step.title}**")
        lines.append("")
    
    lines.append(step.prompt)
    
    # Show actions if present
    actions = getattr(step, 'actions', None) or []
    if not actions and hasattr(step, 'to_dict'):
        step_dict = step.to_dict()
        actions = step_dict.get('actions', [])
    
    if actions:
        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("**📋 Actions:**")
        lines.append("")
        for i, action in enumerate(actions, 1):
            lines.append(f"   {i}. {action}")
            lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    
    if step.help_text:
        lines.append("")
        lines.append(f"💡 *{step.help_text}*")
    
    lines.append("")
    lines.append("🔒 Quest mode active. You can ask questions about this lesson.")
    lines.append("")
    lines.append("Type **#complete** when you've finished today's lesson.")
    lines.append("Type **#halt** to pause and exit quest mode.")
    
    return lines


# =============================================================================
# UPDATED handle_quest (v0.10.0)
# =============================================================================

def handle_quest_v10(
    cmd_name: str,
    args: Dict[str, Any],
    session_id: str,
    context: Dict[str, Any],
    kernel: Any,
    meta: Any,
) -> CommandResponse:
    """
    Open the Quest Board to list, start, or resume a quest.
    
    v0.10.0 CHANGES:
    - When called with NO args: Start the wizard
    - When called with id=<id>: Direct start (preserved for backwards compatibility)
    - Activates quest lock mode after starting
    
    Usage:
        #quest              - Start wizard to choose quest and lesson
        #quest 1            - Start/resume quest by index (via wizard quick-select)
        #quest id=jwt_intro - Direct start/resume by ID
        #quest region=cyber - Filter by region/module (shows wizard)
    """
    engine = kernel.quest_engine
    
    if not engine:
        return _error_response(cmd_name, "Quest engine not available.", "NO_ENGINE")
    
    # Parse arguments
    quest_id = None
    region_filter = None
    
    if isinstance(args, dict):
        quest_id = args.get("id") or args.get("name")
        region_filter = args.get("region") or args.get("module")
        
        # Check for positional argument
        positional = args.get("_", [])
        if positional and not quest_id:
            try:
                # If numeric, treat as index - but we'll use the wizard
                idx = int(positional[0])
                quests = engine.list_quests()
                if 1 <= idx <= len(quests):
                    quest_id = quests[idx - 1].id
                else:
                    return _error_response(cmd_name, f"Invalid quest index: {idx}", "INVALID_INDEX")
            except ValueError:
                # Not numeric, treat as quest ID
                quest_id = positional[0]
    
    # =================================================================
    # CASE 1: No quest ID provided → Start the wizard
    # =================================================================
    if not quest_id:
        # Check if quest is already active
        if is_quest_active(session_id):
            lock_state = get_quest_lock_state(session_id)
            return _base_response(
                cmd_name,
                f"🔒 Quest **\"{lock_state.quest_title}\"** is already active at Day {lock_state.current_step_index + 1}.\n\n"
                f"Use **#complete** to finish today's lesson, or **#halt** to pause.",
                {
                    "quest_active": True,
                    "quest_id": lock_state.quest_id,
                    "step_index": lock_state.current_step_index,
                }
            )
        
        # Start the wizard
        return handle_quest_wizard_start(cmd_name, session_id, kernel)
    
    # =================================================================
    # CASE 2: Quest ID provided → Direct start (backwards compatible)
    # =================================================================
    
    # Check if quest is already active
    if is_quest_active(session_id):
        lock_state = get_quest_lock_state(session_id)
        if lock_state.quest_id == quest_id:
            return _base_response(
                cmd_name,
                f"Quest **\"{lock_state.quest_title}\"** is already active at Day {lock_state.current_step_index + 1}.\n\n"
                f"Use **#complete** to finish today's lesson, or **#halt** to pause.",
                {
                    "quest_active": True,
                    "quest_id": quest_id,
                    "step_index": lock_state.current_step_index,
                }
            )
        else:
            return _error_response(
                cmd_name,
                f"Another quest (**{lock_state.quest_title}**) is already active.\n\n"
                f"Use **#halt** to pause it first, then start this quest.",
                "ANOTHER_QUEST_ACTIVE"
            )
    
    # Get the quest
    quest = engine.get_quest(quest_id)
    if not quest:
        return _error_response(cmd_name, f"Quest '{quest_id}' not found.", "NOT_FOUND")
    
    # Start the quest
    run = engine.start_quest(quest_id)
    if not run:
        return _error_response(cmd_name, f"Failed to start quest '{quest_id}'.", "START_FAILED")
    
    # Get current step
    current_step = quest.steps[run.current_step_index] if run.current_step_index < len(quest.steps) else None
    
    if not current_step:
        return _error_response(cmd_name, "Quest has no steps.", "NO_STEPS")
    
    # Get step details
    step_actions = getattr(current_step, "actions", []) or []
    step_title = current_step.title or f"Day {run.current_step_index + 1}"
    
    # Activate quest lock mode
    activate_quest_lock(
        session_id=session_id,
        quest_id=quest_id,
        quest_title=quest.title,
        run_id=run.run_id,
        step_index=run.current_step_index,
        step_id=current_step.id,
        step_title=step_title,
        step_prompt=current_step.prompt,
        step_actions=step_actions,
    )
    
    # Build step display
    step_num = run.current_step_index + 1
    total_steps = len(quest.steps)
    lines = _format_step_display(quest.title, current_step, step_num, total_steps)
    
    return _base_response(cmd_name, "\n".join(lines), {
        "quest_active": True,
        "quest_id": quest.id,
        "step_index": run.current_step_index,
        "step_type": current_step.type,
    })


# =============================================================================
# UPDATED handle_next (v0.10.0) - Now an alias for #complete
# =============================================================================

def handle_next_v10(
    cmd_name: str,
    args: Dict[str, Any],
    session_id: str,
    context: Dict[str, Any],
    kernel: Any,
    meta: Any,
) -> CommandResponse:
    """
    Legacy #next command - now an alias for #complete.
    
    v0.10.0: This is kept for backwards compatibility.
    Users should migrate to using #complete instead.
    """
    # Import here to avoid circular imports
    from .quest_complete_halt_handlers import handle_complete
    
    # Call #complete handler
    return handle_complete("complete", args, session_id, context, kernel, meta)


# =============================================================================
# INTEGRATION HELPERS
# =============================================================================

def check_and_route_quest_wizard(
    session_id: str,
    user_input: str,
    kernel: Any,
) -> Optional[CommandResponse]:
    """
    Check if quest start wizard is active and route input to it.
    
    Called by mode_router or nova_kernel to handle wizard input.
    Returns None if no wizard is active.
    """
    if is_quest_wizard_active(session_id):
        return process_quest_wizard_input(session_id, user_input, kernel)
    return None
