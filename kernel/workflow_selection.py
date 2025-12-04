# kernel/workflow_selection.py
"""
v0.7.11: Workflow selection state management.

Tracks when the user is in a workflow selection wizard and handles
number-based selection input.
"""

from typing import Dict, Optional, List, Any

# Session -> pending selection state
_pending_selections: Dict[str, Dict[str, Any]] = {}


def set_workflow_selection(
    session_id: str, 
    command: str, 
    workflows: List[Dict[str, Any]]
) -> None:
    """
    Store pending workflow selection state.
    
    Args:
        session_id: User session ID
        command: The command waiting for selection (flow, advance, halt)
        workflows: List of workflow summaries that were displayed
    """
    _pending_selections[session_id] = {
        "command": command,
        "workflows": workflows,
    }


def get_workflow_selection(session_id: str) -> Optional[Dict[str, Any]]:
    """Get pending workflow selection state for a session."""
    return _pending_selections.get(session_id)


def clear_workflow_selection(session_id: str) -> None:
    """Clear pending workflow selection state."""
    _pending_selections.pop(session_id, None)


def has_pending_selection(session_id: str) -> bool:
    """Check if session has a pending workflow selection."""
    return session_id in _pending_selections


def resolve_selection(session_id: str, user_input: str) -> Optional[Dict[str, Any]]:
    """
    Resolve user's numeric input to a workflow selection.
    
    Args:
        session_id: User session ID
        user_input: The user's input (should be a number or 'cancel')
    
    Returns:
        Dict with 'command' and 'workflow_id' if valid selection,
        Dict with 'cancelled' if user cancelled,
        None if invalid input
    """
    state = _pending_selections.get(session_id)
    if not state:
        return None
    
    user_input = user_input.strip().lower()
    
    # Check for cancel
    if user_input == "cancel":
        clear_workflow_selection(session_id)
        return {"cancelled": True}
    
    # Try to parse as number
    try:
        idx = int(user_input) - 1  # Convert to 0-based
        workflows = state.get("workflows", [])
        
        if 0 <= idx < len(workflows):
            workflow_id = workflows[idx].get("id")
            command = state["command"]
            clear_workflow_selection(session_id)
            return {
                "command": command,
                "workflow_id": workflow_id,
            }
        else:
            # Invalid number, but keep state for retry
            return None
    except ValueError:
        # Not a number, not cancel - invalid
        return None
