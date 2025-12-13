# kernel/reminders_handlers.py
"""
NovaOS Reminders Command Handlers — v2.0.0

Implements all reminder commands:
- reminders-list, reminders-due, reminders-show
- reminders-add, reminders-update, reminders-delete
- reminders-done, reminders-snooze
- reminders-pin, reminders-unpin

v2.0.1: Added wizard support for commands needing args
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from ..command_types import CommandResponse
from ..formatting import OutputFormatter as F
from .reminders_manager import (
    RemindersManager,
    Reminder,
    RepeatConfig,
    RepeatWindow,
    DEFAULT_TIMEZONE,
    WEEKDAY_ABBREV,
    WEEKDAY_MAP,
)

# Wizard support
from .reminders_wizard import (
    is_reminders_wizard_command,
    has_active_wizard,
    start_reminders_wizard,
    process_reminders_wizard_input,
    clear_wizard_session,
    WIZARD_COMMANDS,
)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _base_response(cmd_name: str, summary: str, data: Optional[Dict[str, Any]] = None) -> CommandResponse:
    """Build a standard CommandResponse object."""
    return CommandResponse(
        ok=True,
        command=cmd_name,
        summary=summary,
        data=data or {},
        type="syscommand",
    )


def _error_response(cmd_name: str, message: str, error_code: str = "ERROR") -> CommandResponse:
    """Build an error CommandResponse object."""
    return CommandResponse(
        ok=False,
        command=cmd_name,
        summary=message,
        error_code=error_code,
        error_message=message,
        type="error",
    )


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
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return dt_str[:10] if len(dt_str) > 10 else dt_str


def _format_window(window: Optional[RepeatWindow]) -> str:
    """Format a window to readable string."""
    if not window:
        return "—"
    try:
        start_h, start_m = map(int, window.start.split(":"))
        end_h, end_m = map(int, window.end.split(":"))
        
        start_ampm = "AM" if start_h < 12 else "PM"
        end_ampm = "AM" if end_h < 12 else "PM"
        
        start_h_12 = start_h % 12 or 12
        end_h_12 = end_h % 12 or 12
        
        return f"{start_h_12}:{start_m:02d} {start_ampm}–{end_h_12}:{end_m:02d} {end_ampm}"
    except Exception:
        return f"{window.start}–{window.end}"


def _format_repeat(repeat: Optional[RepeatConfig]) -> str:
    """Format repeat config to readable string."""
    if not repeat:
        return "One-time"
    
    parts = []
    
    if repeat.type == "daily":
        if repeat.interval == 1:
            parts.append("Daily")
        else:
            parts.append(f"Every {repeat.interval} days")
    elif repeat.type == "weekly":
        if repeat.by_day:
            # by_day contains abbreviations like "MO", "TU", etc.
            # Just use them directly (they're already readable)
            day_names = repeat.by_day
            parts.append(f"Weekly on {', '.join(day_names)}")
        else:
            parts.append("Weekly")
    elif repeat.type == "monthly":
        if repeat.by_month_day:
            days = ", ".join(str(d) for d in repeat.by_month_day)
            parts.append(f"Monthly on day(s) {days}")
        else:
            parts.append("Monthly")
    
    if repeat.window:
        parts.append(f"window {_format_window(repeat.window)}")
    
    return " · ".join(parts) if parts else "Recurring"


def _format_reminder_line(r: Reminder, show_id: bool = True) -> str:
    """Format a single reminder as a line."""
    parts = []
    
    if show_id:
        parts.append(f"[{r.id}]")
    
    parts.append(r.title)
    
    if r.due_at:
        parts.append(f"@ {_format_time(r.due_at, r.timezone)}")
    
    if r.is_recurring:
        parts.append(f"({_format_repeat(r.repeat)})")
    
    if r.snoozed_until:
        parts.append(f"💤 until {_format_time_short(r.snoozed_until, r.timezone)}")
    
    return " ".join(parts)


def _format_reminder_detail(r: Reminder) -> str:
    """Format a reminder with full details."""
    lines = [
        f"╔══ {r.title} ══╗",
        "",
        f"ID:        {r.id}",
        f"Status:    {r.status}",
        f"Priority:  {r.priority}",
        f"Pinned:    {'Yes' if r.pinned else 'No'}",
        "",
        f"Due:       {_format_time(r.due_at, r.timezone)}",
        f"Timezone:  {r.timezone}",
    ]
    
    if r.is_recurring:
        lines.append(f"Repeat:    {_format_repeat(r.repeat)}")
        if r.has_window and r.repeat and r.repeat.window:
            lines.append(f"Window:    {_format_window(r.repeat.window)}")
    
    if r.snoozed_until:
        lines.append(f"Snoozed:   Until {_format_time(r.snoozed_until, r.timezone)}")
    
    if r.notes:
        lines.append("")
        lines.append(f"Notes:     {r.notes}")
    
    lines.append("")
    lines.append(f"Created:   {_format_time(r.created_at, r.timezone)}")
    lines.append(f"Updated:   {_format_time(r.updated_at, r.timezone)}")
    
    if r.last_fired_at:
        lines.append(f"Last fired: {_format_time(r.last_fired_at, r.timezone)}")
    
    if r.missed_count > 0:
        lines.append(f"Missed:    {r.missed_count} time(s)")
    
    return "\n".join(lines)


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

def handle_reminders_list(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    List all reminders grouped by status.
    
    Usage: #reminders-list [status=active|done|all]
    """
    manager = _get_manager(kernel)
    if not manager:
        return _error_response(cmd_name, "Reminders system not available.", "NO_MANAGER")
    
    # Parse status filter - handle both dict and non-dict args
    status_filter = "active"
    if isinstance(args, dict):
        status_filter = args.get("status", "active")
    elif isinstance(args, list) and len(args) > 0:
        status_filter = str(args[0]) if args[0] in ("active", "done", "all") else "active"
    
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
    
    lines = ["╔══ Reminders ══╗", ""]
    
    if pinned:
        lines.append("📌 PINNED")
        for r in pinned:
            lines.append(f"  {_format_reminder_line(r)}")
        lines.append("")
    
    if due_now:
        lines.append("🔴 DUE NOW")
        for r in due_now:
            lines.append(f"  {_format_reminder_line(r)}")
        lines.append("")
    
    if due_today:
        lines.append("🟡 TODAY")
        for r in due_today:
            lines.append(f"  {_format_reminder_line(r)}")
        lines.append("")
    
    if upcoming:
        lines.append("🟢 UPCOMING")
        for r in upcoming:
            lines.append(f"  {_format_reminder_line(r)}")
        lines.append("")
    
    if done and status_filter in ("done", "all"):
        lines.append("✓ DONE")
        for r in done[:5]:  # Limit to 5
            lines.append(f"  {_format_reminder_line(r)}")
        if len(done) > 5:
            lines.append(f"  ... and {len(done) - 5} more")
        lines.append("")
    
    lines.append(f"Total: {len(reminders)} reminder(s)")
    
    return _base_response(cmd_name, "\n".join(lines), {"count": len(reminders)})


def handle_reminders_due(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    Show reminders that are due now + today + pinned.
    
    Usage: #reminders-due
    """
    manager = _get_manager(kernel)
    if not manager:
        return _error_response(cmd_name, "Reminders system not available.", "NO_MANAGER")
    
    tz = DEFAULT_TIMEZONE
    now = datetime.now(ZoneInfo(tz))
    
    # Get due reminders
    due_now = manager.get_due_now(now)
    due_today = manager.get_due_today(now)
    pinned = manager.get_pinned()
    
    # Remove duplicates (pinned items might also be due)
    due_now_ids = {r.id for r in due_now}
    due_today = [r for r in due_today if r.id not in due_now_ids]
    pinned = [r for r in pinned if r.id not in due_now_ids and r.id not in {r2.id for r2 in due_today}]
    
    if not due_now and not due_today and not pinned:
        return _base_response(cmd_name, "╔══ Due Reminders ══╗\n\nNo reminders due right now. 🎉", {"count": 0})
    
    lines = ["╔══ Due Reminders ══╗", ""]
    
    if due_now:
        lines.append("🔴 DUE NOW")
        for r in due_now:
            lines.append(f"  {_format_reminder_line(r)}")
        lines.append("")
    
    if due_today:
        lines.append("🟡 LATER TODAY")
        for r in due_today:
            lines.append(f"  {_format_reminder_line(r)}")
        lines.append("")
    
    if pinned:
        lines.append("📌 PINNED")
        for r in pinned:
            lines.append(f"  {_format_reminder_line(r)}")
        lines.append("")
    
    total = len(due_now) + len(due_today) + len(pinned)
    return _base_response(cmd_name, "\n".join(lines), {"count": total, "due_now": len(due_now)})


def handle_reminders_show(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    Show full details for a reminder.
    
    Usage: #reminders-show id=rem_001
    
    If called without args, starts interactive wizard.
    """
    manager = _get_manager(kernel)
    if not manager:
        return _error_response(cmd_name, "Reminders system not available.", "NO_MANAGER")
    
    # Get reminder ID
    reminder_id = None
    if isinstance(args, dict):
        reminder_id = args.get("id") or (args.get("_", [None])[0] if args.get("_") else None)
    
    # No ID provided - start wizard
    if not reminder_id:
        return start_reminders_wizard(session_id, cmd_name, kernel)
    
    reminder = manager.get(reminder_id)
    if not reminder:
        return _error_response(cmd_name, f"Reminder '{reminder_id}' not found.", "NOT_FOUND")
    
    detail = _format_reminder_detail(reminder)
    return _base_response(cmd_name, detail, {"reminder": reminder.to_dict()})


def handle_reminders_add(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    Create a new reminder.
    
    Usage: #reminders-add title="Call mom" due="5pm" [repeat=daily] [window=5pm-11pm] [notes="..."] [priority=high]
    
    If called without args, starts interactive wizard.
    """
    manager = _get_manager(kernel)
    if not manager:
        return _error_response(cmd_name, "Reminders system not available.", "NO_MANAGER")
    
    if not isinstance(args, dict):
        args = {}
    
    title = args.get("title")
    due = args.get("due") or args.get("at") or args.get("when")
    
    # No required args - start wizard
    if not title or not due:
        return start_reminders_wizard(session_id, cmd_name, kernel)
    
    # Parse optional args
    repeat = _parse_repeat_arg(args.get("repeat", ""))
    window = _parse_window_arg(args.get("window", ""))
    notes = args.get("notes")
    priority = args.get("priority", "normal")
    pinned = args.get("pinned", "").lower() in ("true", "yes", "1") if isinstance(args.get("pinned"), str) else bool(args.get("pinned"))
    
    try:
        reminder = manager.add(
            title=title,
            due=due,
            notes=notes,
            priority=priority,
            repeat=repeat,
            window=window,
            pinned=pinned,
        )
        
        summary = f"✓ Reminder created: {reminder.title}\n\nDue: {_format_time(reminder.due_at, reminder.timezone)}"
        if reminder.is_recurring:
            summary += f"\nRepeat: {_format_repeat(reminder.repeat)}"
        
        return _base_response(cmd_name, summary, {"id": reminder.id, "reminder": reminder.to_dict()})
    
    except Exception as e:
        return _error_response(cmd_name, f"Failed to create reminder: {str(e)}", "CREATE_FAILED")


def handle_reminders_update(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    Update a reminder's fields.
    
    Usage: #reminders-update id=rem_001 [title="..."] [due="..."] [notes="..."] [priority=...]
    
    If called without id, starts interactive wizard.
    """
    manager = _get_manager(kernel)
    if not manager:
        return _error_response(cmd_name, "Reminders system not available.", "NO_MANAGER")
    
    if not isinstance(args, dict):
        args = {}
    
    reminder_id = args.get("id") or (args.get("_", [None])[0] if args.get("_") else None)
    
    # No ID - start wizard
    if not reminder_id:
        return start_reminders_wizard(session_id, cmd_name, kernel)
    
    # Get current reminder
    reminder = manager.get(reminder_id)
    if not reminder:
        return _error_response(cmd_name, f"Reminder '{reminder_id}' not found.", "NOT_FOUND")
    
    # Build update fields
    updates = {}
    if "title" in args:
        updates["title"] = args["title"]
    if "notes" in args:
        updates["notes"] = args["notes"]
    if "priority" in args:
        updates["priority"] = args["priority"]
    if "due" in args or "at" in args or "when" in args:
        updates["due"] = args.get("due") or args.get("at") or args.get("when")
    if "repeat" in args:
        updates["repeat"] = _parse_repeat_arg(args["repeat"])
    if "window" in args:
        updates["window"] = _parse_window_arg(args["window"])
    
    if not updates:
        return _error_response(cmd_name, "No fields to update.", "NO_UPDATES")
    
    try:
        updated = manager.update(reminder_id, updates)
        if not updated:
            return _error_response(cmd_name, f"Failed to update reminder '{reminder_id}'.", "UPDATE_FAILED")
        
        summary = f"✓ Reminder updated: {updated.title}\n\nDue: {_format_time(updated.due_at, updated.timezone)}"
        return _base_response(cmd_name, summary, {"id": updated.id, "reminder": updated.to_dict()})
    
    except Exception as e:
        return _error_response(cmd_name, f"Failed to update reminder: {str(e)}", "UPDATE_FAILED")


def handle_reminders_delete(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    Delete a reminder.
    
    Usage: #reminders-delete id=rem_001
    
    If called without id, starts interactive wizard.
    """
    manager = _get_manager(kernel)
    if not manager:
        return _error_response(cmd_name, "Reminders system not available.", "NO_MANAGER")
    
    reminder_id = None
    if isinstance(args, dict):
        reminder_id = args.get("id") or (args.get("_", [None])[0] if args.get("_") else None)
    
    # No ID - start wizard
    if not reminder_id:
        return start_reminders_wizard(session_id, cmd_name, kernel)
    
    # Get reminder info before deleting
    reminder = manager.get(reminder_id)
    if not reminder:
        return _error_response(cmd_name, f"Reminder '{reminder_id}' not found.", "NOT_FOUND")
    
    title = reminder.title
    ok = manager.delete(reminder_id)
    
    if not ok:
        return _error_response(cmd_name, f"Failed to delete reminder '{reminder_id}'.", "DELETE_FAILED")
    
    return _base_response(cmd_name, f"✓ Reminder deleted: {title}", {"id": reminder_id})


def handle_reminders_done(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    Mark a reminder as done. For recurring reminders, advances to next occurrence.
    
    Usage: #reminders-done id=rem_001
    
    If called without id, starts interactive wizard.
    """
    manager = _get_manager(kernel)
    if not manager:
        return _error_response(cmd_name, "Reminders system not available.", "NO_MANAGER")
    
    reminder_id = None
    if isinstance(args, dict):
        reminder_id = args.get("id") or (args.get("_", [None])[0] if args.get("_") else None)
    
    # No ID - start wizard
    if not reminder_id:
        return start_reminders_wizard(session_id, cmd_name, kernel)
    
    reminder = manager.get(reminder_id)
    if not reminder:
        return _error_response(cmd_name, f"Reminder '{reminder_id}' not found.", "NOT_FOUND")
    
    was_recurring = reminder.is_recurring
    title = reminder.title
    
    try:
        completed = manager.complete(reminder_id)
        
        if was_recurring:
            summary = f"✓ Completed: {title}\n\nNext due: {_format_time(completed.due_at, completed.timezone)}"
        else:
            summary = f"✓ Done: {title}"
        
        return _base_response(cmd_name, summary, {"id": reminder_id, "recurring": was_recurring})
    
    except Exception as e:
        return _error_response(cmd_name, f"Failed to complete reminder: {str(e)}", "COMPLETE_FAILED")


def handle_reminders_snooze(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    Snooze a reminder for a duration.
    
    Usage: #reminders-snooze id=rem_001 [duration=1h]
    
    Durations: 10m, 30m, 1h, 3h, 1d
    
    If called without id, starts interactive wizard.
    """
    manager = _get_manager(kernel)
    if not manager:
        return _error_response(cmd_name, "Reminders system not available.", "NO_MANAGER")
    
    if not isinstance(args, dict):
        args = {}
    
    reminder_id = args.get("id") or (args.get("_", [None])[0] if args.get("_") else None)
    
    # No ID - start wizard
    if not reminder_id:
        return start_reminders_wizard(session_id, cmd_name, kernel)
    
    duration = args.get("duration", "1h")
    
    reminder = manager.get(reminder_id)
    if not reminder:
        return _error_response(cmd_name, f"Reminder '{reminder_id}' not found.", "NOT_FOUND")
    
    try:
        snoozed = manager.snooze(reminder_id, duration)
        
        summary = f"💤 Snoozed: {snoozed.title}\n\nUntil: {_format_time(snoozed.snoozed_until, snoozed.timezone)}"
        return _base_response(cmd_name, summary, {"id": reminder_id, "snoozed_until": snoozed.snoozed_until})
    
    except Exception as e:
        return _error_response(cmd_name, f"Failed to snooze reminder: {str(e)}", "SNOOZE_FAILED")


def handle_reminders_pin(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    Pin a reminder so it always shows in due view.
    
    Usage: #reminders-pin id=rem_001
    
    If called without id, starts interactive wizard.
    """
    manager = _get_manager(kernel)
    if not manager:
        return _error_response(cmd_name, "Reminders system not available.", "NO_MANAGER")
    
    reminder_id = None
    if isinstance(args, dict):
        reminder_id = args.get("id") or (args.get("_", [None])[0] if args.get("_") else None)
    
    # No ID - start wizard
    if not reminder_id:
        return start_reminders_wizard(session_id, cmd_name, kernel)
    
    reminder = manager.get(reminder_id)
    if not reminder:
        return _error_response(cmd_name, f"Reminder '{reminder_id}' not found.", "NOT_FOUND")
    
    try:
        pinned = manager.pin(reminder_id)
        return _base_response(cmd_name, f"📌 Pinned: {pinned.title}", {"id": reminder_id})
    
    except Exception as e:
        return _error_response(cmd_name, f"Failed to pin reminder: {str(e)}", "PIN_FAILED")


def handle_reminders_unpin(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    Unpin a reminder.
    
    Usage: #reminders-unpin id=rem_001
    
    If called without id, starts interactive wizard.
    """
    manager = _get_manager(kernel)
    if not manager:
        return _error_response(cmd_name, "Reminders system not available.", "NO_MANAGER")
    
    reminder_id = None
    if isinstance(args, dict):
        reminder_id = args.get("id") or (args.get("_", [None])[0] if args.get("_") else None)
    
    # No ID - start wizard
    if not reminder_id:
        return start_reminders_wizard(session_id, cmd_name, kernel)
    
    reminder = manager.get(reminder_id)
    if not reminder:
        return _error_response(cmd_name, f"Reminder '{reminder_id}' not found.", "NOT_FOUND")
    
    try:
        unpinned = manager.unpin(reminder_id)
        return _base_response(cmd_name, f"Unpinned: {unpinned.title}", {"id": reminder_id})
    
    except Exception as e:
        return _error_response(cmd_name, f"Failed to unpin reminder: {str(e)}", "UNPIN_FAILED")


def handle_reminders_settings(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    Open reminder notification settings.
    
    Usage: #reminders-settings
    
    Opens the settings panel in the UI where you can:
    - Enable/disable push notifications (ntfy.sh)
    - Set your ntfy topic
    - Configure notification priority
    - Send test notifications
    """
    # Return a special response that tells the frontend to open settings
    return _base_response(
        cmd_name,
        "Opening reminder settings...\n\n"
        "Configure push notifications to your phone via ntfy.sh:\n"
        "1. Install ntfy app (iOS/Android)\n"
        "2. Subscribe to your topic\n"
        "3. Enable notifications in settings",
        {
            "action": "open_settings",
            "ui_command": "openReminderSettings()",
        }
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
    "handle_reminders_settings": handle_reminders_settings,
}


def get_reminders_handlers():
    """Return the reminders handlers dict for registration."""
    return REMINDERS_HANDLERS


# Re-export wizard functions for kernel integration
__all__ = [
    "get_reminders_handlers",
    "REMINDERS_HANDLERS",
    # Wizard exports
    "is_reminders_wizard_command",
    "has_active_wizard",
    "start_reminders_wizard",
    "process_reminders_wizard_input",
    "clear_wizard_session",
    "WIZARD_COMMANDS",
]
