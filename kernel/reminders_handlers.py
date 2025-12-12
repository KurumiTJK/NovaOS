# kernel/reminders_handlers.py
"""
NovaOS Reminders Command Handlers — v2.0.0

Implements all reminder commands:
- reminders-list, reminders-due, reminders-show
- reminders-add, reminders-update, reminders-delete
- reminders-done, reminders-snooze
- reminders-pin, reminders-unpin
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from .command_types import CommandResponse
from .formatting import OutputFormatter as F
from .reminders_manager import (
    RemindersManager,
    Reminder,
    RepeatConfig,
    RepeatWindow,
    DEFAULT_TIMEZONE,
    WEEKDAY_ABBREV,
    WEEKDAY_MAP,
)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _base_response(cmd_name: str, summary: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Build a standard response dict."""
    response = {
        "ok": True,
        "command": cmd_name,
        "summary": summary,
    }
    if extra:
        response["extra"] = extra
    return response


def _error_response(cmd_name: str, message: str, error_code: str = "ERROR") -> Dict[str, Any]:
    """Build an error response dict."""
    return {
        "ok": False,
        "command": cmd_name,
        "summary": message,
        "error_code": error_code,
    }


def _get_manager(kernel) -> Optional[RemindersManager]:
    """Get the RemindersManager from kernel."""
    return getattr(kernel, 'reminders', None)


def _format_time(dt_str: str, tz_name: str = DEFAULT_TIMEZONE) -> str:
    """Format ISO datetime string to readable format."""
    if not dt_str:
        return "—"
    try:
        if dt_str.endswith("Z"):
            dt_str = dt_str[:-1] + "+00:00"
        dt = datetime.fromisoformat(dt_str)
        tz = ZoneInfo(tz_name)
        dt = dt.astimezone(tz)
        return dt.strftime("%Y-%m-%d · %I:%M %p").replace(" 0", " ").strip()
    except Exception:
        return dt_str[:16] if len(dt_str) > 16 else dt_str


def _format_time_short(dt_str: str, tz_name: str = DEFAULT_TIMEZONE) -> str:
    """Format time only."""
    if not dt_str:
        return "—"
    try:
        if dt_str.endswith("Z"):
            dt_str = dt_str[:-1] + "+00:00"
        dt = datetime.fromisoformat(dt_str)
        tz = ZoneInfo(tz_name)
        dt = dt.astimezone(tz)
        return dt.strftime("%I:%M %p").replace(" 0", " ").lstrip("0")
    except Exception:
        return dt_str


def _format_date(dt_str: str, tz_name: str = DEFAULT_TIMEZONE) -> str:
    """Format date only."""
    if not dt_str:
        return "—"
    try:
        if dt_str.endswith("Z"):
            dt_str = dt_str[:-1] + "+00:00"
        dt = datetime.fromisoformat(dt_str)
        tz = ZoneInfo(tz_name)
        dt = dt.astimezone(tz)
        return dt.strftime("%a %b %d")
    except Exception:
        return dt_str[:10] if len(dt_str) > 10 else dt_str


def _format_window(window: RepeatWindow) -> str:
    """Format a time window."""
    if not window:
        return ""
    try:
        # Convert HH:MM to readable format
        start_h, start_m = map(int, window.start.split(":"))
        end_h, end_m = map(int, window.end.split(":"))
        
        start_ampm = "AM" if start_h < 12 else "PM"
        end_ampm = "AM" if end_h < 12 else "PM"
        
        start_h = start_h % 12 or 12
        end_h = end_h % 12 or 12
        
        start_str = f"{start_h}:{start_m:02d} {start_ampm}" if start_m else f"{start_h}:00 {start_ampm}"
        end_str = f"{end_h}:{end_m:02d} {end_ampm}" if end_m else f"{end_h}:00 {end_ampm}"
        
        return f"{start_str}–{end_str}"
    except Exception:
        return f"{window.start}–{window.end}"


def _format_repeat(repeat: RepeatConfig) -> str:
    """Format repeat configuration."""
    if not repeat:
        return ""
    
    result = repeat.type.capitalize()
    
    if repeat.interval > 1:
        result = f"Every {repeat.interval} {repeat.type}s"
    
    if repeat.type == "weekly" and repeat.by_day:
        days = [d for d in repeat.by_day]
        if days:
            result += f" on {', '.join(days)}"
    
    if repeat.type == "monthly" and repeat.by_month_day:
        days = [str(d) for d in repeat.by_month_day]
        if days:
            result += f" on day {', '.join(days)}"
    
    return result


def _format_reminder_line(r: Reminder, show_time: bool = True) -> str:
    """Format a single reminder for list display."""
    parts = [f"[{r.id}]"]
    
    if r.pinned:
        parts.append("📌")
    
    parts.append(r.title)
    
    if show_time:
        if r.has_window and r.repeat.window:
            parts.append(f"(window: {_format_window(r.repeat.window)})")
        else:
            parts.append(f"— {_format_time_short(r.due_at, r.timezone)}")
    
    if r.is_recurring and not r.has_window:
        parts.append(f"[{_format_repeat(r.repeat)}]")
    
    if r.snoozed_until:
        parts.append(f"(snoozed until {_format_time_short(r.snoozed_until, r.timezone)})")
    
    return " ".join(parts)


def _now_string(tz_name: str = DEFAULT_TIMEZONE) -> str:
    """Get current time as formatted string."""
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)
    return now.strftime("%Y-%m-%d · %I:%M %p").replace(" 0", " ")


def _parse_repeat_arg(repeat_str: str) -> Optional[Dict[str, Any]]:
    """Parse repeat argument string to dict."""
    if not repeat_str:
        return None
    
    repeat_str = repeat_str.lower().strip()
    
    # Simple types
    if repeat_str == "daily":
        return {"type": "daily", "interval": 1}
    
    if repeat_str == "weekly":
        return {"type": "weekly", "interval": 1}
    
    if repeat_str == "monthly":
        return {"type": "monthly", "interval": 1}
    
    # Weekly with days: weekly:MO,WE,FR
    match = re.match(r"weekly:([A-Za-z,]+)", repeat_str)
    if match:
        days = [d.strip().upper()[:2] for d in match.group(1).split(",")]
        return {"type": "weekly", "interval": 1, "by_day": days}
    
    # Monthly with days: monthly:1,15
    match = re.match(r"monthly:([\d,]+)", repeat_str)
    if match:
        days = [int(d.strip()) for d in match.group(1).split(",") if d.strip().isdigit()]
        return {"type": "monthly", "interval": 1, "by_month_day": days}
    
    return None


def _parse_window_arg(window_str: str) -> Optional[Dict[str, str]]:
    """Parse window argument string to dict."""
    if not window_str:
        return None
    
    # Format: HH:MM-HH:MM or HHam-HHpm
    window_str = window_str.replace(" ", "")
    
    # Try HH:MM-HH:MM format
    match = re.match(r"(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})", window_str)
    if match:
        return {
            "start": f"{int(match.group(1)):02d}:{match.group(2)}",
            "end": f"{int(match.group(3)):02d}:{match.group(4)}",
        }
    
    # Try HHam-HHpm format
    match = re.match(r"(\d{1,2})(am|pm)-(\d{1,2})(am|pm)", window_str.lower())
    if match:
        start_h = int(match.group(1))
        start_ampm = match.group(2)
        end_h = int(match.group(3))
        end_ampm = match.group(4)
        
        if start_ampm == "pm" and start_h < 12:
            start_h += 12
        elif start_ampm == "am" and start_h == 12:
            start_h = 0
        
        if end_ampm == "pm" and end_h < 12:
            end_h += 12
        elif end_ampm == "am" and end_h == 12:
            end_h = 0
        
        return {
            "start": f"{start_h:02d}:00",
            "end": f"{end_h:02d}:59",
        }
    
    return None


# =============================================================================
# COMMAND HANDLERS
# =============================================================================

def handle_reminders_list(cmd_name, args, session_id, context, kernel, meta) -> Dict[str, Any]:
    """
    List all reminders grouped by status.
    
    Usage: #reminders-list [status=active|done|all]
    """
    manager = _get_manager(kernel)
    if not manager:
        return _error_response(cmd_name, "Reminders system not available.", "NO_MANAGER")
    
    # Parse status filter
    status_filter = "active"
    if isinstance(args, dict):
        status_filter = args.get("status", "active")
    
    all_reminders = manager.list_all()
    tz = DEFAULT_TIMEZONE
    now = datetime.now(ZoneInfo(tz))
    
    # Filter by status
    if status_filter == "all":
        reminders = all_reminders
    elif status_filter == "done":
        reminders = [r for r in all_reminders if r.status == "done"]
    else:
        reminders = [r for r in all_reminders if r.status == "active"]
    
    if not reminders:
        return _base_response(cmd_name, "╔══ Reminders ══╗\n\nNo reminders found.", {"count": 0})
    
    # Group reminders
    pinned = []
    due_now = []
    due_today = []
    upcoming = []
    done = []
    
    for r in reminders:
        if r.status == "done":
            done.append(r)
        elif r.pinned:
            pinned.append(r)
        elif manager.is_due_now(r, now):
            due_now.append(r)
        elif manager.is_due_today(r, now):
            due_today.append(r)
        else:
            upcoming.append(r)
    
    # Sort upcoming by due date
    upcoming.sort(key=lambda r: r.due_at or "")
    
    # Build output
    lines = [
        "╔══ Reminders — List ══╗",
        f"Now: {_now_string(tz)}",
        "",
    ]
    
    if pinned:
        lines.append("📌 Pinned:")
        for r in pinned:
            lines.append(f"  • {_format_reminder_line(r)}")
        lines.append("")
    
    if due_now:
        lines.append("🔴 Due now:")
        for r in due_now:
            lines.append(f"  • {_format_reminder_line(r)}")
        lines.append("")
    
    if due_today:
        lines.append("🟡 Today:")
        for r in due_today:
            lines.append(f"  • {_format_reminder_line(r)}")
        lines.append("")
    
    if upcoming:
        lines.append("🟢 Upcoming:")
        for r in upcoming[:10]:  # Limit to 10
            lines.append(f"  • {_format_reminder_line(r)} — {_format_date(r.due_at, r.timezone)}")
        if len(upcoming) > 10:
            lines.append(f"  ... and {len(upcoming) - 10} more")
        lines.append("")
    
    if done and status_filter in ("all", "done"):
        lines.append("✓ Done:")
        for r in done[:5]:
            lines.append(f"  • [{r.id}] {r.title}")
        lines.append("")
    
    return _base_response(cmd_name, "\n".join(lines), {
        "count": len(reminders),
        "pinned": len(pinned),
        "due_now": len(due_now),
        "due_today": len(due_today),
        "upcoming": len(upcoming),
    })


def handle_reminders_due(cmd_name, args, session_id, context, kernel, meta) -> Dict[str, Any]:
    """
    Show reminders that are currently due.
    
    Usage: #reminders-due
    """
    manager = _get_manager(kernel)
    if not manager:
        return _error_response(cmd_name, "Reminders system not available.", "NO_MANAGER")
    
    tz = DEFAULT_TIMEZONE
    now = datetime.now(ZoneInfo(tz))
    
    due_now = manager.get_due_now(now)
    due_today = [r for r in manager.get_due_today(now) if r not in due_now]
    pinned = [r for r in manager.get_pinned() if r not in due_now]
    
    lines = [
        "╔══ Reminders — Due ══╗",
        f"Now: {_now_string(tz)}",
        "",
    ]
    
    if due_now:
        lines.append("Due now:")
        for r in due_now:
            line = f"  • {_format_reminder_line(r)}"
            lines.append(line)
        lines.append("")
    else:
        lines.append("Due now: None")
        lines.append("")
    
    if due_today:
        lines.append("Today:")
        for r in due_today:
            lines.append(f"  • {_format_reminder_line(r)}")
        lines.append("")
    
    if pinned:
        lines.append("📌 Pinned:")
        for r in pinned:
            lines.append(f"  • {_format_reminder_line(r)}")
        lines.append("")
    
    return _base_response(cmd_name, "\n".join(lines), {
        "due_now": len(due_now),
        "due_today": len(due_today),
        "pinned": len(pinned),
    })


def handle_reminders_show(cmd_name, args, session_id, context, kernel, meta) -> Dict[str, Any]:
    """
    Show full details for a specific reminder.
    
    Usage: #reminders-show id=rem_001
    """
    manager = _get_manager(kernel)
    if not manager:
        return _error_response(cmd_name, "Reminders system not available.", "NO_MANAGER")
    
    # Parse ID
    rid = None
    if isinstance(args, dict):
        rid = args.get("id") or args.get("_", [None])[0]
    elif isinstance(args, str):
        rid = args.strip()
    
    if not rid:
        return _error_response(cmd_name, "Usage: #reminders-show id=<id>", "MISSING_ID")
    
    reminder = manager.get(rid)
    if not reminder:
        return _error_response(cmd_name, f"Reminder '{rid}' not found.", "NOT_FOUND")
    
    tz = reminder.timezone
    
    lines = [
        f"╔══ Reminder: {reminder.title} ══╗",
        "",
        f"ID: {reminder.id}",
        f"Status: {reminder.status}",
        f"Priority: {reminder.priority}",
        f"Pinned: {'Yes' if reminder.pinned else 'No'}",
        "",
        f"Due at: {_format_time(reminder.due_at, tz)}",
        f"Timezone: {tz}",
    ]
    
    if reminder.repeat:
        lines.append(f"Repeat: {_format_repeat(reminder.repeat)}")
        if reminder.repeat.window:
            lines.append(f"Window: {_format_window(reminder.repeat.window)}")
    
    if reminder.snoozed_until:
        lines.append(f"Snoozed until: {_format_time(reminder.snoozed_until, tz)}")
    
    if reminder.notes:
        lines.append("")
        lines.append(f"Notes: {reminder.notes}")
    
    lines.append("")
    lines.append(f"Created: {_format_time(reminder.created_at, tz)}")
    lines.append(f"Updated: {_format_time(reminder.updated_at, tz)}")
    
    if reminder.last_fired_at:
        lines.append(f"Last fired: {_format_time(reminder.last_fired_at, tz)}")
    
    if reminder.missed_count > 0:
        lines.append(f"Missed: {reminder.missed_count} times")
    
    return _base_response(cmd_name, "\n".join(lines), {"reminder": reminder.to_dict()})


def handle_reminders_add(cmd_name, args, session_id, context, kernel, meta) -> Dict[str, Any]:
    """
    Add a new reminder.
    
    Usage: #reminders-add title="Call mom" due="2025-12-15 17:00"
           #reminders-add title="Weekly sync" due="sunday 10am" repeat=weekly window=10am-12pm
    """
    manager = _get_manager(kernel)
    if not manager:
        return _error_response(cmd_name, "Reminders system not available.", "NO_MANAGER")
    
    if not isinstance(args, dict):
        return _error_response(
            cmd_name,
            'Usage: #reminders-add title="..." due="YYYY-MM-DD HH:MM"',
            "INVALID_ARGS"
        )
    
    # Required fields
    title = args.get("title") or args.get("_", [None])[0]
    due = args.get("due") or args.get("at") or args.get("when")
    
    if not title:
        return _error_response(cmd_name, "Missing title. Usage: #reminders-add title=\"...\" due=\"...\"", "MISSING_TITLE")
    
    if not due:
        return _error_response(cmd_name, "Missing due time. Usage: #reminders-add title=\"...\" due=\"...\"", "MISSING_DUE")
    
    # Optional fields
    notes = args.get("notes")
    priority = args.get("priority", "normal")
    pinned = args.get("pinned", "").lower() in ("true", "yes", "1")
    timezone = args.get("timezone", DEFAULT_TIMEZONE)
    
    # Parse repeat
    repeat_config = None
    repeat_str = args.get("repeat")
    if repeat_str:
        repeat_config = _parse_repeat_arg(repeat_str)
    
    # Parse window
    window_config = None
    window_str = args.get("window")
    if window_str:
        window_config = _parse_window_arg(window_str)
    
    # Create reminder
    try:
        reminder = manager.add(
            title=title,
            due=due,
            notes=notes,
            priority=priority,
            repeat=repeat_config,
            window=window_config,
            pinned=pinned,
            timezone=timezone,
        )
    except Exception as e:
        return _error_response(cmd_name, f"Failed to create reminder: {e}", "CREATE_ERROR")
    
    lines = [
        "╔══ Reminder Created ══╗",
        "",
        f"ID: {reminder.id}",
        f"Title: {reminder.title}",
        f"Due: {_format_time(reminder.due_at, reminder.timezone)}",
    ]
    
    if reminder.repeat:
        lines.append(f"Repeat: {_format_repeat(reminder.repeat)}")
        if reminder.repeat.window:
            lines.append(f"Window: {_format_window(reminder.repeat.window)}")
    
    if reminder.notes:
        lines.append(f"Notes: {reminder.notes}")
    
    return _base_response(cmd_name, "\n".join(lines), {"reminder": reminder.to_dict()})


def handle_reminders_update(cmd_name, args, session_id, context, kernel, meta) -> Dict[str, Any]:
    """
    Update an existing reminder.
    
    Usage: #reminders-update id=rem_001 title="New title"
           #reminders-update id=rem_001 due="tomorrow 9am" priority=high
    """
    manager = _get_manager(kernel)
    if not manager:
        return _error_response(cmd_name, "Reminders system not available.", "NO_MANAGER")
    
    if not isinstance(args, dict):
        return _error_response(cmd_name, "Usage: #reminders-update id=<id> field=value ...", "INVALID_ARGS")
    
    rid = args.get("id") or args.get("_", [None])[0]
    if not rid:
        return _error_response(cmd_name, "Missing id. Usage: #reminders-update id=<id> ...", "MISSING_ID")
    
    # Build update fields
    fields = {}
    for key in ["title", "notes", "priority", "pinned", "timezone"]:
        if key in args:
            value = args[key]
            if key == "pinned":
                value = str(value).lower() in ("true", "yes", "1")
            fields[key] = value
    
    if "due" in args or "due_at" in args:
        fields["due"] = args.get("due") or args.get("due_at")
    
    if "repeat" in args:
        repeat_config = _parse_repeat_arg(args["repeat"])
        if repeat_config:
            fields["repeat"] = repeat_config
    
    if not fields:
        return _error_response(cmd_name, "No fields to update.", "NO_FIELDS")
    
    reminder = manager.update(rid, fields)
    if not reminder:
        return _error_response(cmd_name, f"Reminder '{rid}' not found.", "NOT_FOUND")
    
    lines = [
        "╔══ Reminder Updated ══╗",
        "",
        f"ID: {reminder.id}",
        f"Title: {reminder.title}",
        f"Due: {_format_time(reminder.due_at, reminder.timezone)}",
    ]
    
    return _base_response(cmd_name, "\n".join(lines), {"reminder": reminder.to_dict()})


def handle_reminders_delete(cmd_name, args, session_id, context, kernel, meta) -> Dict[str, Any]:
    """
    Delete a reminder.
    
    Usage: #reminders-delete id=rem_001
    """
    manager = _get_manager(kernel)
    if not manager:
        return _error_response(cmd_name, "Reminders system not available.", "NO_MANAGER")
    
    rid = None
    if isinstance(args, dict):
        rid = args.get("id") or args.get("_", [None])[0]
    elif isinstance(args, str):
        rid = args.strip()
    
    if not rid:
        return _error_response(cmd_name, "Usage: #reminders-delete id=<id>", "MISSING_ID")
    
    # Get reminder first for confirmation message
    reminder = manager.get(rid)
    if not reminder:
        return _error_response(cmd_name, f"Reminder '{rid}' not found.", "NOT_FOUND")
    
    title = reminder.title
    success = manager.delete(rid)
    
    if success:
        return _base_response(
            cmd_name,
            f"╔══ Reminder Deleted ══╗\n\nDeleted: [{rid}] {title}",
            {"id": rid, "title": title}
        )
    else:
        return _error_response(cmd_name, f"Failed to delete reminder '{rid}'.", "DELETE_ERROR")


def handle_reminders_done(cmd_name, args, session_id, context, kernel, meta) -> Dict[str, Any]:
    """
    Mark a reminder as done/completed.
    
    Usage: #reminders-done id=rem_001
    """
    manager = _get_manager(kernel)
    if not manager:
        return _error_response(cmd_name, "Reminders system not available.", "NO_MANAGER")
    
    rid = None
    if isinstance(args, dict):
        rid = args.get("id") or args.get("_", [None])[0]
    elif isinstance(args, str):
        rid = args.strip()
    
    if not rid:
        return _error_response(cmd_name, "Usage: #reminders-done id=<id>", "MISSING_ID")
    
    # Get reminder before completing for status message
    reminder = manager.get(rid)
    if not reminder:
        return _error_response(cmd_name, f"Reminder '{rid}' not found.", "NOT_FOUND")
    
    was_recurring = reminder.is_recurring
    
    completed = manager.complete(rid)
    if not completed:
        return _error_response(cmd_name, f"Failed to complete reminder '{rid}'.", "COMPLETE_ERROR")
    
    lines = ["╔══ Reminder Completed ══╗", ""]
    
    if was_recurring:
        lines.append(f"✓ [{completed.id}] {completed.title}")
        lines.append(f"  Next occurrence: {_format_time(completed.due_at, completed.timezone)}")
    else:
        lines.append(f"✓ [{completed.id}] {completed.title} — Done!")
    
    return _base_response(cmd_name, "\n".join(lines), {
        "id": completed.id,
        "recurring": was_recurring,
        "next_due": completed.due_at if was_recurring else None,
    })


def handle_reminders_snooze(cmd_name, args, session_id, context, kernel, meta) -> Dict[str, Any]:
    """
    Snooze a reminder for a specified duration.
    
    Usage: #reminders-snooze id=rem_001 duration=10m
           #reminders-snooze id=rem_001 duration=1h
           #reminders-snooze id=rem_001 duration=1d
    """
    manager = _get_manager(kernel)
    if not manager:
        return _error_response(cmd_name, "Reminders system not available.", "NO_MANAGER")
    
    if not isinstance(args, dict):
        return _error_response(cmd_name, "Usage: #reminders-snooze id=<id> duration=10m|1h|3h|1d", "INVALID_ARGS")
    
    rid = args.get("id") or args.get("_", [None])[0]
    duration = args.get("duration") or args.get("for") or args.get("_", [None, None])[1] if len(args.get("_", [])) > 1 else None
    
    if not rid:
        return _error_response(cmd_name, "Missing id. Usage: #reminders-snooze id=<id> duration=...", "MISSING_ID")
    
    if not duration:
        return _error_response(cmd_name, "Missing duration. Usage: #reminders-snooze id=<id> duration=10m|1h|3h|1d", "MISSING_DURATION")
    
    snoozed = manager.snooze(rid, duration)
    if not snoozed:
        return _error_response(cmd_name, f"Failed to snooze reminder '{rid}'. Check duration format (10m, 1h, 3h, 1d).", "SNOOZE_ERROR")
    
    lines = [
        "╔══ Reminder Snoozed ══╗",
        "",
        f"⏰ [{snoozed.id}] {snoozed.title}",
        f"   Snoozed until: {_format_time(snoozed.snoozed_until, snoozed.timezone)}",
    ]
    
    return _base_response(cmd_name, "\n".join(lines), {
        "id": snoozed.id,
        "snoozed_until": snoozed.snoozed_until,
    })


def handle_reminders_pin(cmd_name, args, session_id, context, kernel, meta) -> Dict[str, Any]:
    """
    Pin a reminder.
    
    Usage: #reminders-pin id=rem_001
    """
    manager = _get_manager(kernel)
    if not manager:
        return _error_response(cmd_name, "Reminders system not available.", "NO_MANAGER")
    
    rid = None
    if isinstance(args, dict):
        rid = args.get("id") or args.get("_", [None])[0]
    elif isinstance(args, str):
        rid = args.strip()
    
    if not rid:
        return _error_response(cmd_name, "Usage: #reminders-pin id=<id>", "MISSING_ID")
    
    reminder = manager.pin(rid)
    if not reminder:
        return _error_response(cmd_name, f"Reminder '{rid}' not found.", "NOT_FOUND")
    
    return _base_response(
        cmd_name,
        f"╔══ Reminder Pinned ══╗\n\n📌 [{reminder.id}] {reminder.title}",
        {"id": reminder.id}
    )


def handle_reminders_unpin(cmd_name, args, session_id, context, kernel, meta) -> Dict[str, Any]:
    """
    Unpin a reminder.
    
    Usage: #reminders-unpin id=rem_001
    """
    manager = _get_manager(kernel)
    if not manager:
        return _error_response(cmd_name, "Reminders system not available.", "NO_MANAGER")
    
    rid = None
    if isinstance(args, dict):
        rid = args.get("id") or args.get("_", [None])[0]
    elif isinstance(args, str):
        rid = args.strip()
    
    if not rid:
        return _error_response(cmd_name, "Usage: #reminders-unpin id=<id>", "MISSING_ID")
    
    reminder = manager.unpin(rid)
    if not reminder:
        return _error_response(cmd_name, f"Reminder '{rid}' not found.", "NOT_FOUND")
    
    return _base_response(
        cmd_name,
        f"╔══ Reminder Unpinned ══╗\n\n[{reminder.id}] {reminder.title} — unpinned",
        {"id": reminder.id}
    )


# =============================================================================
# HANDLER REGISTRY
# =============================================================================

REMINDERS_HANDLERS = {
    "handle_reminders_list": handle_reminders_list,
    "handle_reminders_due": handle_reminders_due,
    "handle_reminders_show": handle_reminders_show,
    "handle_reminders_add": handle_reminders_add,
    "handle_reminders_update": handle_reminders_update,
    "handle_reminders_delete": handle_reminders_delete,
    "handle_reminders_done": handle_reminders_done,
    "handle_reminders_snooze": handle_reminders_snooze,
    "handle_reminders_pin": handle_reminders_pin,
    "handle_reminders_unpin": handle_reminders_unpin,
}


def get_reminders_handlers() -> Dict[str, Any]:
    """Get all reminders handlers for registration in SYS_HANDLERS."""
    return REMINDERS_HANDLERS


# =============================================================================
# MODULE EXPORTS
# =============================================================================

__all__ = [
    "handle_reminders_list",
    "handle_reminders_due",
    "handle_reminders_show",
    "handle_reminders_add",
    "handle_reminders_update",
    "handle_reminders_delete",
    "handle_reminders_done",
    "handle_reminders_snooze",
    "handle_reminders_pin",
    "handle_reminders_unpin",
    "get_reminders_handlers",
    "REMINDERS_HANDLERS",
]
