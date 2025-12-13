# kernel/quest_start_wizard.py
"""
NovaOS v0.10.0 — Quest Start Wizard

Implements the new #quest wizard flow:
1. When #quest is called with no args and no active quest:
   - Show list of available quests with progress info
   - Accept selection by number, id, or title
2. After quest selection:
   - Show lessons/steps within that quest
   - Accept selection by number or title (or Enter for next incomplete)
3. Start the selected lesson and activate quest lock mode

This replaces the old behavior where #quest id=<id> was required.
The old #quest id=<id> syntax is preserved as a shortcut.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from ..command_types import CommandResponse
from .quest_lock_mode import (
    activate_quest_lock,
    is_quest_active,
    get_quest_lock_state,
)

if TYPE_CHECKING:
    from kernel.quest_engine import Quest, QuestEngine


# =============================================================================
# WIZARD SESSION STATE
# =============================================================================

@dataclass
class QuestStartWizardSession:
    """
    State for the quest start wizard.
    
    Stages:
    - choose_quest: Showing quest list, waiting for selection
    - choose_lesson: Showing lessons for selected quest, waiting for selection
    """
    active: bool = True
    stage: str = "choose_quest"
    
    # Quest list (cached for selection by index)
    quest_list: List[Dict[str, Any]] = field(default_factory=list)
    
    # Selected quest info
    selected_quest_id: Optional[str] = None
    selected_quest_title: Optional[str] = None
    
    # Lesson list for selected quest
    lesson_list: List[Dict[str, Any]] = field(default_factory=list)
    
    # Progress info
    next_incomplete_index: int = 0


# Global session storage
_wizard_sessions: Dict[str, QuestStartWizardSession] = {}


def get_wizard_session(session_id: str) -> Optional[QuestStartWizardSession]:
    """Get active wizard session."""
    return _wizard_sessions.get(session_id)


def set_wizard_session(session_id: str, session: QuestStartWizardSession) -> None:
    """Set wizard session."""
    _wizard_sessions[session_id] = session


def clear_wizard_session(session_id: str) -> None:
    """Clear wizard session."""
    _wizard_sessions.pop(session_id, None)


def has_active_wizard_session(session_id: str) -> bool:
    """Check if a wizard session is active."""
    session = _wizard_sessions.get(session_id)
    return session is not None and session.active


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


# =============================================================================
# QUEST LIST FORMATTING
# =============================================================================

def _get_status_emoji(status: str) -> str:
    """Get emoji for quest status."""
    return {
        "not_started": "⬜",
        "in_progress": "🔶",
        "paused": "⏸️",
        "completed": "✅",
        "abandoned": "❌",
    }.get(status, "⬜")


def _get_lesson_status(step_index: int, completed_steps: int, total_steps: int) -> str:
    """Get status label for a lesson."""
    if step_index < completed_steps:
        return "✅ done"
    elif step_index == completed_steps:
        return "▶️ in progress" if completed_steps > 0 else "⬜ not started"
    else:
        return "⬜ not started"


def _format_quest_list(quests: List[Dict[str, Any]]) -> str:
    """Format quest list for display."""
    lines = [
        "╔══ Available Quests ══╗",
        "",
    ]
    
    for i, q in enumerate(quests, 1):
        status_emoji = _get_status_emoji(q["status"])
        progress = q.get("progress", "")
        
        lines.append(f"[{i}] {status_emoji} {q['title']}")
        if q.get("subtitle"):
            lines.append(f"    {q['subtitle']}")
        if progress:
            lines.append(f"    {progress}")
        lines.append("")
    
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("Type the **number** or **title** to start/resume:")
    
    return "\n".join(lines)


def _format_lesson_list(quest_title: str, lessons: List[Dict[str, Any]], next_incomplete: int) -> str:
    """Format lesson list for display."""
    lines = [
        f"╔══ Lessons for \"{quest_title}\" ══╗",
        "",
    ]
    
    for i, lesson in enumerate(lessons):
        status = lesson["status"]
        title = lesson["title"]
        
        # Highlight the next incomplete lesson
        if i == next_incomplete:
            lines.append(f"[{i + 1}] {status} **{title}** ← starting")
        else:
            lines.append(f"[{i + 1}] {status} {title}")
    
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("Type **start** to begin.")
    
    return "\n".join(lines)


# =============================================================================
# WIZARD HANDLERS
# =============================================================================

def handle_quest_wizard_start(
    cmd_name: str,
    session_id: str,
    kernel: Any,
) -> CommandResponse:
    """
    Start the quest selection wizard.
    
    Called when #quest is run with no arguments and no active quest.
    """
    engine = kernel.quest_engine
    if not engine:
        return _error_response(cmd_name, "Quest engine not available.", "NO_ENGINE")
    
    # Check if quest is already active
    if is_quest_active(session_id):
        lock_state = get_quest_lock_state(session_id)
        return _error_response(
            cmd_name,
            f"Quest **{lock_state.quest_title}** is already active.\n\n"
            f"Use **#complete** to finish the current lesson, or **#halt** to pause.",
            "QUEST_ACTIVE"
        )
    
    # Get all quests with progress info
    quests = engine.list_quests()
    progress = engine.get_progress()
    
    if not quests:
        return _base_response(
            cmd_name,
            "No quests available.\n\nCreate one with `#quest-compose`.",
            {"quest_count": 0}
        )
    
    # Build quest list with status and progress
    quest_list = []
    for q in quests:
        quest_obj = engine.get_quest(q.id)
        quest_progress = progress.quest_runs.get(q.id)
        
        status = q.status
        progress_str = ""
        
        if quest_progress:
            if quest_progress.status == "completed":
                status = "completed"
                progress_str = "(Completed)"
            elif quest_progress.last_step_id:
                # Find step index
                step_idx = 0
                if quest_obj:
                    for i, step in enumerate(quest_obj.steps):
                        if step.id == quest_progress.last_step_id:
                            step_idx = i + 1
                            break
                total = len(quest_obj.steps) if quest_obj else "?"
                progress_str = f"(Step {step_idx}/{total})"
                status = "in_progress"
        else:
            progress_str = f"(Step 1/{len(quest_obj.steps)})" if quest_obj else ""
        
        quest_list.append({
            "id": q.id,
            "title": q.title,
            "subtitle": getattr(q, "subtitle", "") or "",
            "status": status,
            "progress": progress_str,
            "step_count": q.step_count,
        })
    
    # Create wizard session
    session = QuestStartWizardSession(
        active=True,
        stage="choose_quest",
        quest_list=quest_list,
    )
    set_wizard_session(session_id, session)
    
    # Format and return quest list
    display = _format_quest_list(quest_list)
    
    return _base_response(cmd_name, display, {
        "wizard_active": True,
        "stage": "choose_quest",
        "quest_count": len(quest_list),
    })


def process_quest_wizard_input(
    session_id: str,
    user_input: str,
    kernel: Any,
) -> Optional[CommandResponse]:
    """
    Process user input for the quest start wizard.
    
    Returns None if no wizard is active.
    """
    cmd_name = "quest"
    
    session = get_wizard_session(session_id)
    if not session or not session.active:
        return None
    
    engine = kernel.quest_engine
    user_input = user_input.strip()
    user_lower = user_input.lower()
    
    # Handle cancel
    if user_lower in ("cancel", "exit", "quit"):
        clear_wizard_session(session_id)
        return _base_response(cmd_name, "Quest wizard cancelled.", {"wizard_active": False})
    
    # =================================================================
    # STAGE: choose_quest
    # =================================================================
    if session.stage == "choose_quest":
        return _handle_quest_selection(cmd_name, session, session_id, user_input, engine)
    
    # =================================================================
    # STAGE: choose_lesson
    # =================================================================
    elif session.stage == "choose_lesson":
        return _handle_lesson_selection(cmd_name, session, session_id, user_input, engine)
    
    # Unknown stage
    clear_wizard_session(session_id)
    return _error_response(cmd_name, "Unknown wizard state.", "UNKNOWN_STATE")


def _handle_quest_selection(
    cmd_name: str,
    session: QuestStartWizardSession,
    session_id: str,
    user_input: str,
    engine: Any,
) -> CommandResponse:
    """Handle quest selection in the wizard."""
    quest_list = session.quest_list
    
    # Try to match input to a quest
    selected_quest = None
    
    # Try numeric index first
    try:
        idx = int(user_input)
        if 1 <= idx <= len(quest_list):
            selected_quest = quest_list[idx - 1]
    except ValueError:
        pass
    
    # Try exact ID match
    if not selected_quest:
        for q in quest_list:
            if q["id"].lower() == user_input.lower():
                selected_quest = q
                break
    
    # Try title match (case-insensitive, partial)
    if not selected_quest:
        user_lower = user_input.lower()
        for q in quest_list:
            if user_lower in q["title"].lower():
                selected_quest = q
                break
    
    if not selected_quest:
        return _base_response(
            cmd_name,
            f"Could not find quest matching '{user_input}'.\n\n"
            "Please enter a valid number, ID, or title:",
            {"wizard_active": True, "stage": "choose_quest"}
        )
    
    # Quest found - now show lessons
    quest_id = selected_quest["id"]
    quest_obj = engine.get_quest(quest_id)
    
    if not quest_obj:
        return _error_response(cmd_name, f"Quest '{quest_id}' not found.", "NOT_FOUND")
    
    # Get progress to determine next incomplete step
    progress = engine.get_progress()
    quest_progress = progress.quest_runs.get(quest_id)
    
    completed_steps = 0
    if quest_progress and quest_progress.last_step_id:
        for i, step in enumerate(quest_obj.steps):
            if step.id == quest_progress.last_step_id:
                completed_steps = i + 1
                break
    
    # Build lesson list
    lesson_list = []
    for i, step in enumerate(quest_obj.steps):
        status = _get_lesson_status(i, completed_steps, len(quest_obj.steps))
        lesson_list.append({
            "index": i,
            "id": step.id,
            "title": step.title or f"Day {i + 1}",
            "status": status,
            "prompt": step.prompt,
            "actions": getattr(step, "actions", []) or [],
        })
    
    # Update session
    session.stage = "choose_lesson"
    session.selected_quest_id = quest_id
    session.selected_quest_title = quest_obj.title
    session.lesson_list = lesson_list
    session.next_incomplete_index = completed_steps
    set_wizard_session(session_id, session)
    
    # Format and return lesson list
    display = _format_lesson_list(quest_obj.title, lesson_list, completed_steps)
    
    return _base_response(cmd_name, display, {
        "wizard_active": True,
        "stage": "choose_lesson",
        "quest_id": quest_id,
        "lesson_count": len(lesson_list),
        "next_incomplete": completed_steps,
    })


def _handle_lesson_selection(
    cmd_name: str,
    session: QuestStartWizardSession,
    session_id: str,
    user_input: str,
    engine: Any,
) -> CommandResponse:
    """Handle lesson selection and start the quest.
    
    v0.10.0: Always starts the next incomplete lesson regardless of input.
    User input is ignored - we just use it as confirmation to start.
    """
    lesson_list = session.lesson_list
    quest_id = session.selected_quest_id
    
    # Always use next incomplete lesson - user input is just confirmation
    selected_idx = session.next_incomplete_index
    
    # Validate index
    if selected_idx < 0 or selected_idx >= len(lesson_list):
        selected_idx = 0
    
    # Get the quest and lesson
    quest_obj = engine.get_quest(quest_id)
    if not quest_obj or selected_idx >= len(quest_obj.steps):
        clear_wizard_session(session_id)
        return _error_response(cmd_name, "Invalid lesson selection.", "INVALID_SELECTION")
    
    selected_lesson = lesson_list[selected_idx]
    step = quest_obj.steps[selected_idx]
    
    # Start/resume the quest at the selected step
    # First, update the engine's progress to reflect our starting point
    run = engine.start_quest(quest_id)
    if not run:
        clear_wizard_session(session_id)
        return _error_response(cmd_name, f"Failed to start quest '{quest_id}'.", "START_FAILED")
    
    # Override the step index if user selected a different one
    run.current_step_index = selected_idx
    engine._save_active_run()
    
    # Get actions from step
    step_actions = getattr(step, "actions", []) or []
    
    # Activate quest lock mode
    activate_quest_lock(
        session_id=session_id,
        quest_id=quest_id,
        quest_title=quest_obj.title,
        run_id=run.run_id,
        step_index=selected_idx,
        step_id=step.id,
        step_title=step.title or f"Day {selected_idx + 1}",
        step_prompt=step.prompt,
        step_actions=step_actions,
    )
    
    # Clear wizard session
    clear_wizard_session(session_id)
    
    # Format the lesson display
    lines = _format_lesson_display(
        quest_title=quest_obj.title,
        step=step,
        step_num=selected_idx + 1,
        total_steps=len(quest_obj.steps),
    )
    
    return _base_response(cmd_name, "\n".join(lines), {
        "wizard_active": False,
        "quest_active": True,
        "quest_id": quest_id,
        "step_index": selected_idx,
        "step_type": step.type,
    })


def _format_lesson_display(
    quest_title: str,
    step: Any,
    step_num: int,
    total_steps: int,
) -> List[str]:
    """Format a lesson for display after starting."""
    lines = [
        f"╔══ {quest_title} ══╗",
        f"Day {step_num}/{total_steps} • {step.type.upper()}",
        "",
    ]
    
    if step.title:
        lines.append(f"**{step.title}**")
        lines.append("")
    
    lines.append(step.prompt)
    
    # Show actions if present
    actions = getattr(step, "actions", []) or []
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
# INTEGRATION API
# =============================================================================

def is_quest_wizard_active(session_id: str) -> bool:
    """Check if the quest start wizard is active."""
    return has_active_wizard_session(session_id)


def cancel_quest_wizard(session_id: str) -> None:
    """Cancel the quest start wizard."""
    clear_wizard_session(session_id)
