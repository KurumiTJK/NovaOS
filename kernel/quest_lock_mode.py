# kernel/quest_lock_mode.py
"""
NovaOS v0.10.0 — Quest Lock Mode

Implements the quest-locked state where:
- A quest is actively running
- Normal conversation (via GPT-5.1 + persona + WM) is allowed
- Only #complete and #halt syscommands work
- All other syscommands are blocked

This module manages:
1. Quest active state tracking
2. Quest conversation routing (GPT-5.1 with persona + working memory)
3. Command blocking logic
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from kernel.nova_kernel import NovaKernel
    from persona.nova_persona import NovaPersona


# =============================================================================
# QUEST LOCK STATE
# =============================================================================

@dataclass
class QuestLockState:
    """
    State for an active quest lock session.
    
    When quest_active is True:
    - Only #complete and #halt are allowed
    - Regular text is routed to quest conversation
    - Working memory is enhanced with quest context
    """
    quest_active: bool = False
    quest_id: Optional[str] = None
    quest_title: Optional[str] = None
    current_step_index: int = 0
    current_step_id: Optional[str] = None
    current_step_title: Optional[str] = None
    current_step_prompt: Optional[str] = None
    current_step_actions: List[str] = field(default_factory=list)
    run_id: Optional[str] = None
    started_at: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "quest_active": self.quest_active,
            "quest_id": self.quest_id,
            "quest_title": self.quest_title,
            "current_step_index": self.current_step_index,
            "current_step_id": self.current_step_id,
            "current_step_title": self.current_step_title,
            "current_step_prompt": self.current_step_prompt,
            "current_step_actions": self.current_step_actions,
            "run_id": self.run_id,
            "started_at": self.started_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "QuestLockState":
        return cls(
            quest_active=data.get("quest_active", False),
            quest_id=data.get("quest_id"),
            quest_title=data.get("quest_title"),
            current_step_index=data.get("current_step_index", 0),
            current_step_id=data.get("current_step_id"),
            current_step_title=data.get("current_step_title"),
            current_step_prompt=data.get("current_step_prompt"),
            current_step_actions=data.get("current_step_actions", []),
            run_id=data.get("run_id"),
            started_at=data.get("started_at"),
        )


# Global state storage (per session_id)
_quest_lock_states: Dict[str, QuestLockState] = {}


# =============================================================================
# STATE MANAGEMENT API
# =============================================================================

def get_quest_lock_state(session_id: str) -> QuestLockState:
    """Get or create quest lock state for a session."""
    if session_id not in _quest_lock_states:
        _quest_lock_states[session_id] = QuestLockState()
    return _quest_lock_states[session_id]


def set_quest_lock_state(session_id: str, state: QuestLockState) -> None:
    """Set quest lock state for a session."""
    _quest_lock_states[session_id] = state


def clear_quest_lock_state(session_id: str) -> None:
    """Clear quest lock state for a session."""
    _quest_lock_states.pop(session_id, None)


def is_quest_active(session_id: str) -> bool:
    """Check if a quest is currently active for this session."""
    state = _quest_lock_states.get(session_id)
    return state is not None and state.quest_active


# =============================================================================
# QUEST LOCK ACTIVATION
# =============================================================================

def activate_quest_lock(
    session_id: str,
    quest_id: str,
    quest_title: str,
    run_id: str,
    step_index: int,
    step_id: str,
    step_title: str,
    step_prompt: str,
    step_actions: List[str],
) -> QuestLockState:
    """
    Activate quest lock mode for a session.
    
    Called when a quest is started/resumed via the wizard.
    """
    state = QuestLockState(
        quest_active=True,
        quest_id=quest_id,
        quest_title=quest_title,
        current_step_index=step_index,
        current_step_id=step_id,
        current_step_title=step_title,
        current_step_prompt=step_prompt,
        current_step_actions=step_actions,
        run_id=run_id,
        started_at=datetime.now(timezone.utc).isoformat(),
    )
    _quest_lock_states[session_id] = state
    return state


def update_quest_lock_step(
    session_id: str,
    step_index: int,
    step_id: str,
    step_title: str,
    step_prompt: str,
    step_actions: List[str],
) -> Optional[QuestLockState]:
    """
    Update the current step in quest lock state.
    
    Called when advancing to the next step within a quest.
    """
    state = _quest_lock_states.get(session_id)
    if not state or not state.quest_active:
        return None
    
    state.current_step_index = step_index
    state.current_step_id = step_id
    state.current_step_title = step_title
    state.current_step_prompt = step_prompt
    state.current_step_actions = step_actions
    
    return state


def deactivate_quest_lock(session_id: str) -> Optional[QuestLockState]:
    """
    Deactivate quest lock mode for a session.
    
    Called by #complete (after finishing a lesson) or #halt.
    Returns the previous state before deactivation.
    """
    state = _quest_lock_states.get(session_id)
    if state:
        state.quest_active = False
    return state


# =============================================================================
# ALLOWED COMMANDS IN QUEST MODE
# =============================================================================

ALLOWED_QUEST_MODE_COMMANDS = {"complete", "halt"}


def is_command_allowed_in_quest_mode(command: str) -> bool:
    """Check if a command is allowed while a quest is active."""
    return command.lower() in ALLOWED_QUEST_MODE_COMMANDS


def get_quest_mode_blocked_message() -> str:
    """Get the message to show when a blocked command is attempted."""
    return (
        "🔒 A quest is currently active.\n\n"
        "Use **#complete** to finish today's lesson and save progress, or\n"
        "Use **#halt** to pause quest mode and return to normal NovaOS."
    )


# =============================================================================
# QUEST CONVERSATION CONTEXT
# =============================================================================

def build_quest_context_for_llm(state: QuestLockState) -> str:
    """
    Build a context string for the LLM when handling quest conversation.
    
    This provides the current quest/lesson context so Nova can answer
    questions about the current lesson material.
    """
    lines = [
        "═══ CURRENT QUEST CONTEXT ═══",
        "",
        f"Quest: {state.quest_title}",
        f"Current Lesson: Day {state.current_step_index + 1} — {state.current_step_title}",
        "",
        "Lesson Content:",
        state.current_step_prompt or "(No content)",
    ]
    
    if state.current_step_actions:
        lines.append("")
        lines.append("Today's Actions:")
        for i, action in enumerate(state.current_step_actions, 1):
            lines.append(f"  {i}. {action}")
    
    lines.append("")
    lines.append("═════════════════════════════")
    lines.append("")
    lines.append(
        "The user is asking a question about this lesson. "
        "Answer as Nova, staying grounded in the lesson content. "
        "Be helpful, warm, and supportive while keeping answers focused on the quest material."
    )
    
    return "\n".join(lines)


def handle_quest_conversation(
    session_id: str,
    user_message: str,
    kernel: "NovaKernel",
    persona: "NovaPersona",
) -> Dict[str, Any]:
    """
    Handle a conversational message while a quest is active.
    
    Routes through GPT-5.1 with Nova's persona + working memory + quest context.
    """
    from kernel.nova_wm import (
        wm_update,
        wm_record_response,
        wm_get_context_string,
        wm_answer_reference,
    )
    
    state = get_quest_lock_state(session_id)
    if not state.quest_active:
        return {
            "ok": False,
            "text": "No active quest.",
            "handled_by": "quest_lock_mode",
        }
    
    # Check if Working Memory can answer directly
    direct_answer = wm_answer_reference(session_id, user_message)
    
    # Update Working Memory with user message
    wm_update(session_id, user_message)
    
    # Get Working Memory context
    wm_context_string = wm_get_context_string(session_id)
    
    # Build quest-specific context
    quest_context = build_quest_context_for_llm(state)
    
    # Combine WM context with quest context
    combined_context = ""
    if wm_context_string:
        combined_context = wm_context_string + "\n\n"
    combined_context += quest_context
    
    # Generate response via persona (which uses GPT-5.1)
    response_text = persona.generate_response(
        text=user_message,
        session_id=session_id,
        wm_context_string=combined_context,
        direct_answer=direct_answer,
    )
    
    # Record response in Working Memory
    if response_text:
        wm_record_response(session_id, response_text)
    
    return {
        "ok": True,
        "text": response_text,
        "mode": "quest_conversation",
        "handled_by": "quest_lock_mode",
        "quest_id": state.quest_id,
        "step_index": state.current_step_index,
    }
