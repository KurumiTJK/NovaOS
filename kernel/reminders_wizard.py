# kernel/reminders_wizard.py
"""
NovaOS Reminders Wizard — v2.0.0

Interactive wizard for reminders commands that need arguments.
Shows a list of reminders and lets user pick one.

Commands with wizard support:
- reminders-show: Pick reminder to view details
- reminders-update: Pick reminder to update
- reminders-delete: Pick reminder to delete
- reminders-done: Pick reminder to mark done
- reminders-snooze: Pick reminder to snooze
- reminders-pin: Pick reminder to pin
- reminders-unpin: Pick reminder to unpin
- reminders-add: Guided creation wizard
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from .command_types import CommandResponse
from .reminders_manager import RemindersManager, Reminder, DEFAULT_TIMEZONE


# =============================================================================
# WIZARD STATE
# =============================================================================

@dataclass
class RemindersWizardSession:
    """Track wizard state for a session."""
    command: str  # The command being wizarded (e.g., "reminders-show")
    stage: str = "select"  # "select", "confirm", "input"
    selected_id: Optional[str] = None
    collected: Dict[str, Any] = field(default_factory=dict)


# Session storage: session_id -> RemindersWizardSession
_wizard_sessions: Dict[str, RemindersWizardSession] = {}


def get_wizard_session(session_id: str) -> Optional[RemindersWizardSession]:
    return _wizard_sessions.get(session_id)


def set_wizard_session(session_id: str, session: RemindersWizardSession) -> None:
    _wizard_sessions[session_id] = session


def clear_wizard_session(session_id: str) -> None:
    _wizard_sessions.pop(session_id, None)


def has_active_wizard(session_id: str) -> bool:
    return session_id in _wizard_sessions


# =============================================================================
# COMMANDS THAT USE WIZARDS
# =============================================================================

# Commands that need an ID selected
ID_COMMANDS = {
    "reminders-show",
    "reminders-update",
    "reminders-delete",
    "reminders-done",
    "reminders-snooze",
    "reminders-pin",
    "reminders-unpin",
}

# Commands with custom wizards
CUSTOM_WIZARD_COMMANDS = {
    "reminders-add",
}

WIZARD_COMMANDS = ID_COMMANDS | CUSTOM_WIZARD_COMMANDS


def is_reminders_wizard_command(cmd_name: str) -> bool:
    """Check if command should use wizard when called without args."""
    return cmd_name in WIZARD_COMMANDS


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _base_response(cmd_name: str, summary: str, data: Optional[Dict[str, Any]] = None) -> CommandResponse:
    return CommandResponse(
        ok=True,
        command=cmd_name,
        summary=summary,
        data=data or {},
        type="syscommand",
    )


def _error_response(cmd_name: str, message: str, code: str = "ERROR") -> CommandResponse:
    return CommandResponse(
        ok=False,
        command=cmd_name,
        summary=message,
        error_code=code,
        error_message=message,
        type="error",
    )


def _get_manager(kernel) -> Optional[RemindersManager]:
    return getattr(kernel, 'reminders', None)


def _format_time_short(dt_str: str, tz_name: str = DEFAULT_TIMEZONE) -> str:
    """Format datetime to short readable format."""
    if not dt_str:
        return "—"
    try:
        if dt_str.endswith("Z"):
            dt_str = dt_str[:-1] + "+00:00"
        dt = datetime.fromisoformat(dt_str)
        tz = ZoneInfo(tz_name)
        dt = dt.astimezone(tz)
        return dt.strftime("%m/%d %I:%M%p").replace(" 0", " ").lower()
    except Exception:
        return dt_str[:16]


def _format_reminder_option(idx: int, r: Reminder) -> str:
    """Format reminder as a selectable option."""
    time_str = _format_time_short(r.due_at, r.timezone)
    status_icon = "📌" if r.pinned else ("✓" if r.status == "done" else "")
    recurring = " 🔄" if r.is_recurring else ""
    return f"{idx}) [{r.id}] {r.title} @ {time_str}{recurring} {status_icon}".strip()


def _build_reminder_selection_list(manager: RemindersManager, filter_status: str = "active") -> tuple[str, List[Reminder]]:
    """Build a numbered list of reminders for selection."""
    all_reminders = manager.list_all()
    
    if filter_status == "active":
        reminders = [r for r in all_reminders if r.status == "active"]
    elif filter_status == "pinned":
        reminders = [r for r in all_reminders if r.pinned]
    else:
        reminders = all_reminders
    
    if not reminders:
        return "No reminders found.", []
    
    lines = ["Select a reminder:", ""]
    for idx, r in enumerate(reminders, 1):
        lines.append(_format_reminder_option(idx, r))
    
    lines.append("")
    lines.append("Type the number or ID (e.g., '1' or 'rem_001'):")
    
    return "\n".join(lines), reminders


def _parse_selection(user_input: str, reminders: List[Reminder]) -> Optional[str]:
    """Parse user selection (number or ID) and return reminder ID."""
    user_input = user_input.strip()
    
    # Try as number
    if user_input.isdigit():
        idx = int(user_input) - 1
        if 0 <= idx < len(reminders):
            return reminders[idx].id
        return None
    
    # Try as ID
    for r in reminders:
        if r.id == user_input or r.id.lower() == user_input.lower():
            return r.id
    
    return None


# =============================================================================
# WIZARD START
# =============================================================================

def start_reminders_wizard(session_id: str, cmd_name: str, kernel) -> CommandResponse:
    """Start a wizard for a reminders command."""
    manager = _get_manager(kernel)
    if not manager:
        return _error_response(cmd_name, "Reminders system not available.", "NO_MANAGER")
    
    # Special case: reminders-add has its own wizard
    if cmd_name == "reminders-add":
        return _start_add_wizard(session_id, cmd_name, manager)
    
    # ID-based commands: show reminder list for selection
    if cmd_name in ID_COMMANDS:
        # For pin, show active. For unpin, show pinned only
        if cmd_name == "reminders-unpin":
            filter_status = "pinned"
        else:
            filter_status = "active"
        
        list_text, reminders = _build_reminder_selection_list(manager, filter_status)
        
        if not reminders:
            return _base_response(cmd_name, f"╔══ {cmd_name} ══╗\n\n{list_text}", {"wizard_complete": True})
        
        # Store wizard state
        session = RemindersWizardSession(command=cmd_name, stage="select")
        set_wizard_session(session_id, session)
        
        # Build header based on command
        headers = {
            "reminders-show": "View Reminder Details",
            "reminders-update": "Update Reminder",
            "reminders-delete": "Delete Reminder",
            "reminders-done": "Mark Reminder Done",
            "reminders-snooze": "Snooze Reminder",
            "reminders-pin": "Pin Reminder",
            "reminders-unpin": "Unpin Reminder",
        }
        header = headers.get(cmd_name, cmd_name)
        
        return _base_response(
            cmd_name,
            f"╔══ {header} ══╗\n\n{list_text}",
            {"wizard_active": True, "stage": "select", "reminder_count": len(reminders)}
        )
    
    return _error_response(cmd_name, f"No wizard for '{cmd_name}'.", "NO_WIZARD")


def _start_add_wizard(session_id: str, cmd_name: str, manager: RemindersManager) -> CommandResponse:
    """Start the add reminder wizard."""
    session = RemindersWizardSession(command=cmd_name, stage="title")
    set_wizard_session(session_id, session)
    
    return _base_response(
        cmd_name,
        "╔══ Add Reminder ══╗\n\n"
        "Let's create a new reminder.\n\n"
        "What should the reminder say?\n"
        "(e.g., 'Call mom', 'Take medication', 'Weekly review')",
        {"wizard_active": True, "stage": "title"}
    )


# =============================================================================
# WIZARD INPUT PROCESSING
# =============================================================================

def process_reminders_wizard_input(session_id: str, user_input: str, kernel) -> Optional[CommandResponse]:
    """Process user input for an active reminders wizard."""
    session = get_wizard_session(session_id)
    if not session:
        return None
    
    manager = _get_manager(kernel)
    if not manager:
        clear_wizard_session(session_id)
        return _error_response(session.command, "Reminders system not available.", "NO_MANAGER")
    
    user_input = user_input.strip()
    
    # Handle cancel
    if user_input.lower() in ("cancel", "exit", "quit", "q"):
        clear_wizard_session(session_id)
        return _base_response(session.command, "Wizard cancelled.", {"wizard_complete": True})
    
    # Route to appropriate handler
    if session.command == "reminders-add":
        return _process_add_wizard(session_id, session, user_input, manager)
    elif session.command in ID_COMMANDS:
        return _process_id_wizard(session_id, session, user_input, manager, kernel)
    
    clear_wizard_session(session_id)
    return None


def _process_id_wizard(
    session_id: str,
    session: RemindersWizardSession,
    user_input: str,
    manager: RemindersManager,
    kernel
) -> CommandResponse:
    """Process ID-based command wizard (show, update, delete, done, snooze, pin, unpin)."""
    cmd_name = session.command
    
    if session.stage == "select":
        # User is selecting a reminder
        if cmd_name == "reminders-unpin":
            filter_status = "pinned"
        else:
            filter_status = "active"
        
        _, reminders = _build_reminder_selection_list(manager, filter_status)
        selected_id = _parse_selection(user_input, reminders)
        
        if not selected_id:
            return _base_response(
                cmd_name,
                f"Invalid selection '{user_input}'. Please enter a number or reminder ID:",
                {"wizard_active": True, "stage": "select"}
            )
        
        session.selected_id = selected_id
        
        # For some commands, we need more input
        if cmd_name == "reminders-snooze":
            session.stage = "duration"
            set_wizard_session(session_id, session)
            return _base_response(
                cmd_name,
                f"Selected: {selected_id}\n\n"
                "How long to snooze?\n\n"
                "Options: 10m, 30m, 1h, 3h, 1d\n"
                "(or type a custom duration like '2h', '45m')",
                {"wizard_active": True, "stage": "duration", "selected_id": selected_id}
            )
        
        elif cmd_name == "reminders-update":
            session.stage = "field"
            set_wizard_session(session_id, session)
            reminder = manager.get(selected_id)
            return _base_response(
                cmd_name,
                f"Selected: {selected_id} — \"{reminder.title if reminder else ''}\"\n\n"
                "What would you like to update?\n\n"
                "1) title\n"
                "2) due (date/time)\n"
                "3) notes\n"
                "4) priority (low/normal/high)\n\n"
                "Type the field name or number:",
                {"wizard_active": True, "stage": "field", "selected_id": selected_id}
            )
        
        elif cmd_name == "reminders-delete":
            # Confirm deletion
            session.stage = "confirm"
            set_wizard_session(session_id, session)
            reminder = manager.get(selected_id)
            return _base_response(
                cmd_name,
                f"⚠️ Delete this reminder?\n\n"
                f"  [{selected_id}] {reminder.title if reminder else 'Unknown'}\n\n"
                "Type 'yes' to confirm or 'cancel' to abort:",
                {"wizard_active": True, "stage": "confirm", "selected_id": selected_id}
            )
        
        else:
            # Execute directly: show, done, pin, unpin
            clear_wizard_session(session_id)
            return _execute_command(cmd_name, {"id": selected_id}, kernel)
    
    elif session.stage == "duration":
        # Snooze duration input
        duration = user_input.lower().strip()
        clear_wizard_session(session_id)
        return _execute_command(cmd_name, {"id": session.selected_id, "duration": duration}, kernel)
    
    elif session.stage == "confirm":
        # Delete confirmation
        if user_input.lower() in ("yes", "y", "confirm"):
            clear_wizard_session(session_id)
            return _execute_command(cmd_name, {"id": session.selected_id}, kernel)
        else:
            clear_wizard_session(session_id)
            return _base_response(cmd_name, "Deletion cancelled.", {"wizard_complete": True})
    
    elif session.stage == "field":
        # Update field selection
        field_map = {"1": "title", "2": "due", "3": "notes", "4": "priority"}
        field = field_map.get(user_input, user_input.lower())
        
        if field not in ("title", "due", "notes", "priority"):
            return _base_response(
                cmd_name,
                f"Unknown field '{user_input}'. Please choose: title, due, notes, or priority",
                {"wizard_active": True, "stage": "field", "selected_id": session.selected_id}
            )
        
        session.stage = "value"
        session.collected["field"] = field
        set_wizard_session(session_id, session)
        
        prompts = {
            "title": "Enter the new title:",
            "due": "Enter new due date/time:\n(e.g., '5pm', 'tomorrow 9am', '2025-12-25 10:00')",
            "notes": "Enter new notes (or 'clear' to remove):",
            "priority": "Enter priority: low, normal, or high",
        }
        
        return _base_response(
            cmd_name,
            prompts[field],
            {"wizard_active": True, "stage": "value", "field": field}
        )
    
    elif session.stage == "value":
        # Update value input
        field = session.collected.get("field")
        value = user_input
        
        if field == "notes" and value.lower() == "clear":
            value = ""
        
        clear_wizard_session(session_id)
        return _execute_command(cmd_name, {"id": session.selected_id, field: value}, kernel)
    
    clear_wizard_session(session_id)
    return None


def _process_add_wizard(
    session_id: str,
    session: RemindersWizardSession,
    user_input: str,
    manager: RemindersManager
) -> CommandResponse:
    """Process add reminder wizard."""
    cmd_name = session.command
    
    if session.stage == "title":
        session.collected["title"] = user_input
        session.stage = "due"
        set_wizard_session(session_id, session)
        
        return _base_response(
            cmd_name,
            f"Title: \"{user_input}\"\n\n"
            "When should I remind you?\n\n"
            "Examples:\n"
            "  • 5pm\n"
            "  • tomorrow 9am\n"
            "  • 2025-12-25 10:00\n"
            "  • in 2 hours",
            {"wizard_active": True, "stage": "due"}
        )
    
    elif session.stage == "due":
        session.collected["due"] = user_input
        session.stage = "repeat"
        set_wizard_session(session_id, session)
        
        return _base_response(
            cmd_name,
            f"Due: {user_input}\n\n"
            "Should this repeat?\n\n"
            "Options:\n"
            "  • no (one-time)\n"
            "  • daily\n"
            "  • weekly\n"
            "  • weekly:MO,WE,FR (specific days)\n"
            "  • monthly\n"
            "  • monthly:1,15 (specific days)",
            {"wizard_active": True, "stage": "repeat"}
        )
    
    elif session.stage == "repeat":
        if user_input.lower() not in ("no", "none", ""):
            session.collected["repeat"] = user_input
        
        session.stage = "window"
        set_wizard_session(session_id, session)
        
        repeat_info = session.collected.get("repeat", "none")
        if repeat_info and repeat_info != "none":
            return _base_response(
                cmd_name,
                f"Repeat: {repeat_info}\n\n"
                "Set a catch window? (when the reminder is active)\n\n"
                "Examples:\n"
                "  • no (remind at exact time)\n"
                "  • 5pm-11pm (evening window)\n"
                "  • 9am-12pm (morning window)",
                {"wizard_active": True, "stage": "window"}
            )
        else:
            # Skip window for non-repeating
            session.stage = "confirm"
            set_wizard_session(session_id, session)
            return _build_add_confirmation(cmd_name, session)
    
    elif session.stage == "window":
        if user_input.lower() not in ("no", "none", ""):
            session.collected["window"] = user_input
        
        session.stage = "confirm"
        set_wizard_session(session_id, session)
        return _build_add_confirmation(cmd_name, session)
    
    elif session.stage == "confirm":
        if user_input.lower() in ("yes", "y", "confirm", "create"):
            clear_wizard_session(session_id)
            
            # Build args for add command
            args = {
                "title": session.collected.get("title"),
                "due": session.collected.get("due"),
            }
            if session.collected.get("repeat"):
                args["repeat"] = session.collected["repeat"]
            if session.collected.get("window"):
                args["window"] = session.collected["window"]
            
            # Import and call the handler
            from .reminders_handlers import handle_reminders_add
            return handle_reminders_add(cmd_name, args, session_id, None, type('K', (), {'reminders': manager})(), None)
        else:
            clear_wizard_session(session_id)
            return _base_response(cmd_name, "Reminder creation cancelled.", {"wizard_complete": True})
    
    clear_wizard_session(session_id)
    return None


def _build_add_confirmation(cmd_name: str, session: RemindersWizardSession) -> CommandResponse:
    """Build confirmation prompt for add wizard."""
    c = session.collected
    lines = [
        "╔══ Confirm New Reminder ══╗",
        "",
        f"Title:  {c.get('title', '')}",
        f"Due:    {c.get('due', '')}",
    ]
    
    if c.get("repeat"):
        lines.append(f"Repeat: {c['repeat']}")
    if c.get("window"):
        lines.append(f"Window: {c['window']}")
    
    lines.extend(["", "Create this reminder? (yes/no)"])
    
    return _base_response(
        cmd_name,
        "\n".join(lines),
        {"wizard_active": True, "stage": "confirm", "collected": c}
    )


# =============================================================================
# COMMAND EXECUTION
# =============================================================================

def _execute_command(cmd_name: str, args: Dict[str, Any], kernel) -> CommandResponse:
    """Execute a reminders command with the given args."""
    from . import reminders_handlers as rh
    
    handler_map = {
        "reminders-show": rh.handle_reminders_show,
        "reminders-update": rh.handle_reminders_update,
        "reminders-delete": rh.handle_reminders_delete,
        "reminders-done": rh.handle_reminders_done,
        "reminders-snooze": rh.handle_reminders_snooze,
        "reminders-pin": rh.handle_reminders_pin,
        "reminders-unpin": rh.handle_reminders_unpin,
    }
    
    handler = handler_map.get(cmd_name)
    if not handler:
        return _error_response(cmd_name, f"Unknown command '{cmd_name}'", "UNKNOWN_CMD")
    
    return handler(cmd_name, args, "", None, kernel, None)


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    "is_reminders_wizard_command",
    "has_active_wizard",
    "start_reminders_wizard",
    "process_reminders_wizard_input",
    "clear_wizard_session",
    "WIZARD_COMMANDS",
]
