# kernel/quest_complete_halt_handlers.py
"""
NovaOS v0.10.0 — #complete and #halt Command Handlers

Implements:
- #complete: Finish the current lesson, save progress, show tomorrow preview
- #halt: Pause quest mode and return to normal NovaOS

These commands are the ONLY syscommands allowed while quest lock mode is active.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .command_types import CommandResponse
from .quest_lock_mode import (
    get_quest_lock_state,
    is_quest_active,
    deactivate_quest_lock,
    update_quest_lock_step,
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


# =============================================================================
# TOMORROW PREVIEW HELPERS
# =============================================================================

def _extract_preview_text(prompt: str, max_sentences: int = 5) -> str:
    """
    Extract a short preview from a lesson prompt.
    
    Strategy:
    1. If prompt has "📋 Actions:" or similar, use only text before that
    2. Otherwise, use first N sentences or ~200 chars
    """
    if not prompt:
        return "(No preview available)"
    
    # Check for common action section markers
    action_markers = [
        "📋 Actions:",
        "Actions:",
        "━━━━━",
        "───────",
        "Today you'll:",
        "What you'll do:",
    ]
    
    preview = prompt
    for marker in action_markers:
        if marker in preview:
            preview = preview.split(marker)[0]
            break
    
    # Clean up
    preview = preview.strip()
    
    # If still too long, truncate to first few sentences
    if len(preview) > 400:
        sentences = []
        current = ""
        for char in preview:
            current += char
            if char in ".!?" and len(current) > 20:
                sentences.append(current.strip())
                current = ""
                if len(sentences) >= max_sentences:
                    break
        
        if sentences:
            preview = " ".join(sentences)
        else:
            preview = preview[:400] + "..."
    
    return preview


def _format_tomorrow_preview(
    quest_title: str,
    step_num: int,
    total_steps: int,
    step_title: str,
    step_prompt: str,
) -> str:
    """Format the preview for tomorrow's lesson."""
    preview_text = _extract_preview_text(step_prompt)
    
    lines = [
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📅 **Tomorrow: Day {step_num}/{total_steps}**",
        "",
        f"**{step_title}**",
        "",
        preview_text,
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "Use **#quest** to resume tomorrow!",
    ]
    
    return "\n".join(lines)


# =============================================================================
# #complete HANDLER
# =============================================================================

def handle_complete(
    cmd_name: str,
    args: Dict[str, Any],
    session_id: str,
    context: Dict[str, Any],
    kernel: Any,
    meta: Any,
) -> CommandResponse:
    """
    Finish the current lesson, save progress, and show tomorrow's preview.
    
    Usage:
        #complete
    
    Behavior:
    1. Validate that a quest is active
    2. Mark current step as completed
    3. Advance to next step
    4. Persist progress
    5. Show completion confirmation + tomorrow preview
    6. Deactivate quest lock mode (return to normal NovaOS)
    """
    # Check if quest is active
    if not is_quest_active(session_id):
        return _error_response(
            cmd_name,
            "No active quest to complete. Use **#quest** to start one.",
            "NO_ACTIVE_QUEST"
        )
    
    lock_state = get_quest_lock_state(session_id)
    engine = kernel.quest_engine
    
    if not engine:
        return _error_response(cmd_name, "Quest engine not available.", "NO_ENGINE")
    
    # Get current quest and run
    quest = engine.get_quest(lock_state.quest_id)
    active_run = engine.get_active_run()
    
    if not quest or not active_run:
        deactivate_quest_lock(session_id)
        return _error_response(cmd_name, "Quest or run not found.", "NOT_FOUND")
    
    # Get current step info before advancing
    current_step_index = lock_state.current_step_index
    current_step = quest.steps[current_step_index] if current_step_index < len(quest.steps) else None
    
    if not current_step:
        deactivate_quest_lock(session_id)
        return _error_response(cmd_name, "No current step found.", "NO_STEP")
    
    # Advance the quest (this saves progress)
    # We pass empty input since #complete doesn't require an answer
    run, result = engine.advance_quest(active_run.run_id, "__COMPLETE__")
    
    if not run:
        deactivate_quest_lock(session_id)
        return _error_response(cmd_name, "Failed to advance quest.", "ADVANCE_FAILED")
    
    # Build response
    lines = []
    
    # Show completion confirmation
    step_title = current_step.title or f"Day {current_step_index + 1}"
    lines.append(f"✅ **Step {current_step_index + 1}/{len(quest.steps)}** — \"{step_title}\" completed and saved.")
    
    # Check if quest is complete
    if result and result.quest_completed:
        lines.append("")
        lines.append("🎉 **Quest Complete!**")
        lines.append("")
        if quest.rewards:
            lines.append(f"**Rewards:** +{quest.rewards.xp} XP")
            if quest.rewards.visual_unlock:
                lines.append(f"**Unlocked:** {quest.rewards.visual_unlock}")
        lines.append("")
        lines.append("View your progress with **#quest-log**.")
        
        # Deactivate quest lock
        deactivate_quest_lock(session_id)
        
        return _base_response(cmd_name, "\n".join(lines), {
            "quest_completed": True,
            "quest_id": lock_state.quest_id,
            "quest_active": False,
        })
    
    # Quest not complete - show tomorrow's preview
    next_step_index = run.current_step_index
    
    if next_step_index < len(quest.steps):
        next_step = quest.steps[next_step_index]
        next_step_title = next_step.title or f"Day {next_step_index + 1}"
        
        preview = _format_tomorrow_preview(
            quest_title=quest.title,
            step_num=next_step_index + 1,
            total_steps=len(quest.steps),
            step_title=next_step_title,
            step_prompt=next_step.prompt,
        )
        lines.append(preview)
    
    # Deactivate quest lock mode
    deactivate_quest_lock(session_id)
    
    return _base_response(cmd_name, "\n".join(lines), {
        "quest_completed": False,
        "quest_id": lock_state.quest_id,
        "quest_active": False,
        "next_step_index": next_step_index,
    })


# =============================================================================
# #halt HANDLER
# =============================================================================

def handle_halt(
    cmd_name: str,
    args: Dict[str, Any],
    session_id: str,
    context: Dict[str, Any],
    kernel: Any,
    meta: Any,
) -> CommandResponse:
    """
    Pause quest mode and return to normal NovaOS.
    
    Usage:
        #halt
    
    Behavior:
    1. Save current quest state (do NOT advance)
    2. Persist progress
    3. Deactivate quest lock mode
    4. Return friendly confirmation message
    """
    # Check if quest is active
    if not is_quest_active(session_id):
        return _base_response(
            cmd_name,
            "No quest is currently active. You're already in normal NovaOS mode.",
            {"quest_active": False}
        )
    
    lock_state = get_quest_lock_state(session_id)
    engine = kernel.quest_engine
    
    if not engine:
        deactivate_quest_lock(session_id)
        return _error_response(cmd_name, "Quest engine not available.", "NO_ENGINE")
    
    # Get quest info for the message
    quest = engine.get_quest(lock_state.quest_id)
    quest_title = quest.title if quest else lock_state.quest_title or lock_state.quest_id
    step_num = lock_state.current_step_index + 1
    total_steps = len(quest.steps) if quest else "?"
    step_title = lock_state.current_step_title or f"Day {step_num}"
    
    # Pause the quest in the engine (this persists progress)
    active_run = engine.get_active_run()
    if active_run:
        engine.pause_quest(active_run.run_id, reason="user_halt")
    
    # Deactivate quest lock mode
    deactivate_quest_lock(session_id)
    
    # Build response
    lines = [
        f"⏸️ Quest **\"{quest_title}\"** paused at Step {step_num}/{total_steps} — \"{step_title}\".",
        "",
        "Use **#quest** to resume or pick another quest.",
    ]
    
    return _base_response(cmd_name, "\n".join(lines), {
        "quest_active": False,
        "quest_id": lock_state.quest_id,
        "paused_at_step": step_num,
    })


# =============================================================================
# HANDLER REGISTRY
# =============================================================================

COMPLETE_HALT_HANDLERS = {
    "handle_complete": handle_complete,
    "handle_halt": handle_halt,
}


def get_complete_halt_handlers() -> Dict[str, Any]:
    """Get handlers for registration in SYS_HANDLERS."""
    return COMPLETE_HALT_HANDLERS
