# kernel/quest_delete_wizard.py
"""
v0.8.4 — Interactive Quest Delete Wizard

An interactive wizard for deleting quests safely.
Supports:
- Deleting individual quests by index or ID
- Deleting all quests with confirmation
- Looping until cancelled or all quests deleted
- Integration with strict NovaOS mode

Usage:
    #quest-delete                    → Start interactive wizard
    #quest-delete id=jwt_intro       → Direct delete with confirmation
    #quest-delete all=true           → Delete all with confirmation
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .command_types import CommandResponse


# =============================================================================
# WIZARD SESSION STATE
# =============================================================================

@dataclass
class QuestDeleteSession:
    """
    State for an active quest-delete wizard session.
    
    Stages:
    - choice: Main menu, waiting for user to pick quest/all/cancel
    - confirm_single: Confirming deletion of a single quest
    - confirm_all: Confirming deletion of all quests
    """
    active: bool = True
    stage: str = "choice"
    pending_delete_id: Optional[str] = None
    pending_delete_title: Optional[str] = None
    quest_count: int = 0  # For "delete all" confirmation


# Global session storage (per session_id)
_delete_sessions: Dict[str, QuestDeleteSession] = {}


def get_delete_session(session_id: str) -> Optional[QuestDeleteSession]:
    """Get active delete session for a user session."""
    return _delete_sessions.get(session_id)


def set_delete_session(session_id: str, session: QuestDeleteSession) -> None:
    """Set delete session for a user session."""
    _delete_sessions[session_id] = session


def clear_delete_session(session_id: str) -> None:
    """Clear delete session for a user session."""
    _delete_sessions.pop(session_id, None)


def has_active_delete_session(session_id: str) -> bool:
    """Check if a delete wizard is active for this session."""
    session = _delete_sessions.get(session_id)
    return session is not None and session.active


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


def _format_quest_list(quests: List[Any]) -> str:
    """Format the quest list for display."""
    if not quests:
        return "_(No quests available)_"
    
    lines = []
    for i, q in enumerate(quests, 1):
        # Handle both dataclass objects and dicts
        if hasattr(q, 'id'):
            # It's a dataclass/object
            quest_id = getattr(q, 'id', '?')
            title = getattr(q, 'title', 'Untitled')
            category = getattr(q, 'category', 'general')
        else:
            # It's a dict
            quest_id = q.get('id', '?')
            title = q.get('title', 'Untitled')
            category = q.get('category', 'general')
        
        lines.append(f"  {i}) `{quest_id}` [{category}] {title}")
    
    return "\n".join(lines)


def _build_choice_prompt(quests: List[Any]) -> str:
    """Build the main choice prompt with quest list."""
    quest_list = _format_quest_list(quests)
    
    lines = [
        "═══ Quest Delete Wizard ═══",
        "",
        "**Current quests:**",
        quest_list,
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "**Options:**",
        "• Type a **number** or **quest id** to delete that quest",
        "• Type **all** to delete ALL quests",
        "• Type **cancel** to exit",
    ]
    
    return "\n".join(lines)


# =============================================================================
# MAIN WIZARD HANDLER
# =============================================================================

def handle_quest_delete_wizard(
    cmd_name: str,
    args: Dict[str, Any],
    session_id: str,
    context: Dict[str, Any],
    kernel: Any,
    meta: Dict[str, Any],
) -> CommandResponse:
    """
    Main handler for #quest-delete with interactive wizard support.
    
    Modes:
    1. Interactive wizard (no args): Guide user through deletion
    2. Direct delete (id=<id>): Delete specific quest with confirmation
    3. Delete all (all=true): Delete all quests with confirmation
    
    Usage:
        #quest-delete                    → Start wizard
        #quest-delete id=jwt_intro       → Direct delete with confirmation  
        #quest-delete all=true           → Delete all with confirmation
    """
    engine = kernel.quest_engine
    
    # Parse arguments
    quest_id = None
    delete_all = False
    confirm = None
    
    if isinstance(args, dict):
        quest_id = args.get("id") or args.get("name")
        positional = args.get("_", [])
        if positional and not quest_id:
            quest_id = positional[0]
        
        delete_all = str(args.get("all", "")).lower() in ("true", "yes", "1")
        confirm = str(args.get("confirm", "")).lower()
    
    # ─────────────────────────────────────────────────────────────────────
    # MODE 1: Direct delete by ID (existing behavior preserved)
    # ─────────────────────────────────────────────────────────────────────
    if quest_id:
        quest = engine.get_quest(quest_id)
        if not quest:
            return _error_response(cmd_name, f"Quest '{quest_id}' not found.", "NOT_FOUND")
        
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
    
    # ─────────────────────────────────────────────────────────────────────
    # MODE 2: Delete all (all=true argument)
    # ─────────────────────────────────────────────────────────────────────
    if delete_all:
        quests = engine.list_quests()
        if not quests:
            return _base_response(cmd_name, "No quests to delete.")
        
        if confirm != "yes":
            return _base_response(
                cmd_name,
                f"⚠️ **Delete ALL {len(quests)} quests?**\n\n"
                f"This cannot be undone.\n\n"
                f"Run `#quest-delete all=true confirm=yes` to confirm.",
                {"quest_count": len(quests), "needs_confirmation": True}
            )
        
        # Delete all quests
        deleted_count = 0
        for q in quests:
            quest_id = q.id if hasattr(q, 'id') else q.get('id') if isinstance(q, dict) else None
            if quest_id and engine.delete_quest(quest_id):
                deleted_count += 1
        
        return _base_response(
            cmd_name,
            f"✓ Deleted all {deleted_count} quests.",
            {"deleted_count": deleted_count}
        )
    
    # ─────────────────────────────────────────────────────────────────────
    # MODE 3: Interactive wizard (no args)
    # ─────────────────────────────────────────────────────────────────────
    
    # Check for existing session
    existing_session = get_delete_session(session_id)
    if existing_session and existing_session.active:
        # Continue existing session
        return _base_response(
            cmd_name,
            "A delete wizard is already active. Type **cancel** to exit it first.",
            {"wizard_active": True}
        )
    
    # Load quests
    quests = engine.list_quests()
    
    if not quests:
        return _base_response(
            cmd_name,
            "There are no quests to delete.\n\n"
            "Create one with `#quest-compose`.",
            {"quest_count": 0}
        )
    
    # Start new wizard session
    session = QuestDeleteSession(
        active=True,
        stage="choice",
        quest_count=len(quests),
    )
    set_delete_session(session_id, session)
    
    # Show the quest list and options
    prompt = _build_choice_prompt(quests)
    
    return _base_response(cmd_name, prompt, {
        "wizard_active": True,
        "stage": "choice",
        "quest_count": len(quests),
    })


# =============================================================================
# WIZARD INPUT PROCESSING
# =============================================================================

def process_delete_wizard_input(
    session_id: str,
    user_input: str,
    kernel: Any,
) -> CommandResponse:
    """
    Process user input for an active quest-delete wizard.
    
    Called by the mode router when wizard is active.
    """
    cmd_name = "quest-delete"
    
    session = get_delete_session(session_id)
    if not session or not session.active:
        return _error_response(cmd_name, "No active delete wizard.", "NO_SESSION")
    
    engine = kernel.quest_engine
    user_input = user_input.strip()
    user_lower = user_input.lower()
    
    # ─────────────────────────────────────────────────────────────────────
    # STAGE: choice - Main menu
    # ─────────────────────────────────────────────────────────────────────
    if session.stage == "choice":
        # Handle cancel
        if user_lower == "cancel":
            clear_delete_session(session_id)
            return _base_response(
                cmd_name,
                "Quest Delete Wizard cancelled.",
                {"wizard_active": False, "cancelled": True}
            )
        
        # Handle "all"
        if user_lower == "all":
            quests = engine.list_quests()
            if not quests:
                clear_delete_session(session_id)
                return _base_response(
                    cmd_name,
                    "All quests have been deleted.\n\nQuest Delete Wizard finished.",
                    {"wizard_active": False}
                )
            
            session.stage = "confirm_all"
            session.quest_count = len(quests)
            set_delete_session(session_id, session)
            
            return _base_response(
                cmd_name,
                f"⚠️ **You chose to delete ALL quests ({len(quests)} total).**\n\n"
                f"This cannot be undone.\n\n"
                f"• Type **confirm all** to delete everything\n"
                f"• Type **cancel** to go back",
                {"wizard_active": True, "stage": "confirm_all", "quest_count": len(quests)}
            )
        
        # Try to parse as index or quest ID
        quests = engine.list_quests()
        if not quests:
            clear_delete_session(session_id)
            return _base_response(
                cmd_name,
                "All quests have been deleted.\n\nQuest Delete Wizard finished.",
                {"wizard_active": False}
            )
        
        # Try as index (1-based)
        target_quest = None
        try:
            index = int(user_input)
            if 1 <= index <= len(quests):
                target_quest = quests[index - 1]
        except ValueError:
            pass
        
        # Try as quest ID
        if not target_quest:
            for q in quests:
                q_id = q.id if hasattr(q, 'id') else q.get('id') if isinstance(q, dict) else None
                if q_id and q_id.lower() == user_lower:
                    target_quest = q
                    break
        
        if not target_quest:
            # Invalid input
            prompt = _build_choice_prompt(quests)
            return _base_response(
                cmd_name,
                f"❌ I couldn't find quest '{user_input}'.\n\n"
                f"Please enter a number from the list, an existing quest id, **all**, or **cancel**.\n\n"
                f"{prompt}",
                {"wizard_active": True, "stage": "choice", "error": "not_found"}
            )
        
        # Found a quest - ask for confirmation
        quest_id = target_quest.id if hasattr(target_quest, 'id') else target_quest.get('id') if isinstance(target_quest, dict) else None
        quest_title = target_quest.title if hasattr(target_quest, 'title') else target_quest.get('title', 'Untitled') if isinstance(target_quest, dict) else 'Untitled'
        
        session.stage = "confirm_single"
        session.pending_delete_id = quest_id
        session.pending_delete_title = quest_title
        set_delete_session(session_id, session)
        
        return _base_response(
            cmd_name,
            f"Delete quest **{quest_id}** — {quest_title}?\n\n"
            f"• Type **yes** to delete\n"
            f"• Type **no** to go back",
            {"wizard_active": True, "stage": "confirm_single", "quest_id": quest_id}
        )
    
    # ─────────────────────────────────────────────────────────────────────
    # STAGE: confirm_single - Confirming single quest deletion
    # ─────────────────────────────────────────────────────────────────────
    elif session.stage == "confirm_single":
        if user_lower in ("yes", "y", "confirm"):
            # Delete the quest
            quest_id = session.pending_delete_id
            quest_title = session.pending_delete_title
            
            if engine.delete_quest(quest_id):
                # Check if there are more quests
                remaining_quests = engine.list_quests()
                
                if not remaining_quests:
                    clear_delete_session(session_id)
                    return _base_response(
                        cmd_name,
                        f"✓ Deleted quest **{quest_title}**.\n\n"
                        f"All quests have been deleted.\n\nQuest Delete Wizard finished.",
                        {"wizard_active": False, "deleted": quest_id}
                    )
                
                # Reset to choice stage and show updated list
                session.stage = "choice"
                session.pending_delete_id = None
                session.pending_delete_title = None
                set_delete_session(session_id, session)
                
                prompt = _build_choice_prompt(remaining_quests)
                
                return _base_response(
                    cmd_name,
                    f"✓ Deleted quest **{quest_title}**.\n\n{prompt}",
                    {"wizard_active": True, "stage": "choice", "deleted": quest_id}
                )
            else:
                # Delete failed
                session.stage = "choice"
                session.pending_delete_id = None
                session.pending_delete_title = None
                set_delete_session(session_id, session)
                
                quests = engine.list_quests()
                prompt = _build_choice_prompt(quests) if quests else ""
                
                return _base_response(
                    cmd_name,
                    f"❌ Failed to delete quest **{quest_id}**.\n\n{prompt}",
                    {"wizard_active": True, "stage": "choice", "error": "delete_failed"}
                )
        
        elif user_lower in ("no", "n", "cancel"):
            # Go back to choice
            session.stage = "choice"
            session.pending_delete_id = None
            session.pending_delete_title = None
            set_delete_session(session_id, session)
            
            quests = engine.list_quests()
            if not quests:
                clear_delete_session(session_id)
                return _base_response(
                    cmd_name,
                    "All quests have been deleted.\n\nQuest Delete Wizard finished.",
                    {"wizard_active": False}
                )
            
            prompt = _build_choice_prompt(quests)
            return _base_response(
                cmd_name,
                f"Deletion cancelled.\n\n{prompt}",
                {"wizard_active": True, "stage": "choice"}
            )
        
        else:
            # Invalid input
            return _base_response(
                cmd_name,
                f"Please type **yes** to delete quest **{session.pending_delete_title}**, or **no** to go back.",
                {"wizard_active": True, "stage": "confirm_single"}
            )
    
    # ─────────────────────────────────────────────────────────────────────
    # STAGE: confirm_all - Confirming deletion of all quests
    # ─────────────────────────────────────────────────────────────────────
    elif session.stage == "confirm_all":
        if user_lower == "confirm all":
            # Delete all quests
            quests = engine.list_quests()
            deleted_count = 0
            
            for q in quests:
                quest_id = q.id if hasattr(q, 'id') else q.get('id') if isinstance(q, dict) else None
                if quest_id and engine.delete_quest(quest_id):
                    deleted_count += 1
            
            clear_delete_session(session_id)
            return _base_response(
                cmd_name,
                f"✓ Deleted all {deleted_count} quests.\n\nQuest Delete Wizard finished.",
                {"wizard_active": False, "deleted_count": deleted_count}
            )
        
        elif user_lower == "cancel":
            # Go back to choice
            session.stage = "choice"
            set_delete_session(session_id, session)
            
            quests = engine.list_quests()
            if not quests:
                clear_delete_session(session_id)
                return _base_response(
                    cmd_name,
                    "All quests have been deleted.\n\nQuest Delete Wizard finished.",
                    {"wizard_active": False}
                )
            
            prompt = _build_choice_prompt(quests)
            return _base_response(
                cmd_name,
                f"Deletion cancelled.\n\n{prompt}",
                {"wizard_active": True, "stage": "choice"}
            )
        
        else:
            return _base_response(
                cmd_name,
                f"⚠️ **You chose to delete ALL quests ({session.quest_count} total).**\n\n"
                f"This cannot be undone.\n\n"
                f"• Type **confirm all** to delete everything\n"
                f"• Type **cancel** to go back",
                {"wizard_active": True, "stage": "confirm_all"}
            )
    
    # Unknown stage
    clear_delete_session(session_id)
    return _error_response(cmd_name, "Unknown wizard state. Wizard cancelled.", "UNKNOWN_STATE")


# =============================================================================
# PUBLIC API FOR INTEGRATION
# =============================================================================

def is_delete_wizard_active(session_id: str) -> bool:
    """
    Check if a quest-delete wizard is active for this session.
    
    Called by nova_kernel.py / mode_router.py to determine routing.
    """
    return has_active_delete_session(session_id)


def cancel_delete_wizard(session_id: str) -> None:
    """
    Cancel any active quest-delete wizard for a session.
    
    Called when user runs a different command or #reset.
    """
    clear_delete_session(session_id)
