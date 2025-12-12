# kernel/reminders_api.py
"""
NovaOS Reminders API — v2.0.0

Flask endpoints for real-time reminder checking.
Add these routes to your app.py for frontend integration.

Provides:
- GET /api/reminders/due - Check for due reminders (frontend polls this)
- GET /api/reminders/dismiss/<id> - Dismiss a reminder notification
- GET /api/reminders/snooze/<id> - Quick snooze from notification
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

# These will be set by init_reminders_api()
_reminders_manager = None
_dismissed_this_session: set = set()  # Track dismissed reminders for this session


def init_reminders_api(reminders_manager) -> None:
    """Initialize the API with the reminders manager."""
    global _reminders_manager
    _reminders_manager = reminders_manager


def get_due_reminders_for_ui() -> Dict[str, Any]:
    """
    Get due reminders formatted for the frontend.
    
    Returns:
        {
            "has_due": True/False,
            "count": 2,
            "reminders": [
                {
                    "id": "rem_001",
                    "title": "Take medication",
                    "due_at": "9:00 PM",
                    "priority": "normal",
                    "is_recurring": True,
                    "is_pinned": False,
                }
            ]
        }
    """
    if not _reminders_manager:
        return {"has_due": False, "count": 0, "reminders": [], "error": "Not initialized"}
    
    try:
        now = datetime.now(ZoneInfo("America/Los_Angeles"))
        due_now = _reminders_manager.get_due_now(now)
        
        # Filter out dismissed reminders
        due_now = [r for r in due_now if r.id not in _dismissed_this_session]
        
        if not due_now:
            return {"has_due": False, "count": 0, "reminders": []}
        
        reminders = []
        for r in due_now:
            # Format time for display
            try:
                due_dt = datetime.fromisoformat(r.due_at.replace("Z", "+00:00"))
                tz = ZoneInfo(r.timezone)
                due_dt = due_dt.astimezone(tz)
                time_str = due_dt.strftime("%I:%M %p").lstrip("0")
            except:
                time_str = r.due_at[:16]
            
            reminders.append({
                "id": r.id,
                "title": r.title,
                "due_at": time_str,
                "due_at_iso": r.due_at,
                "priority": r.priority,
                "is_recurring": r.is_recurring,
                "is_pinned": r.pinned,
                "notes": r.notes or "",
            })
        
        return {
            "has_due": True,
            "count": len(reminders),
            "reminders": reminders,
        }
    
    except Exception as e:
        return {"has_due": False, "count": 0, "reminders": [], "error": str(e)}


def dismiss_reminder_notification(reminder_id: str) -> Dict[str, Any]:
    """
    Dismiss a reminder notification for this session.
    Does NOT mark as done - just hides the UI notification.
    """
    _dismissed_this_session.add(reminder_id)
    return {"ok": True, "dismissed": reminder_id}


def clear_dismissed() -> None:
    """Clear dismissed reminders (call on session end or periodically)."""
    _dismissed_this_session.clear()


def quick_snooze(reminder_id: str, duration: str = "30m") -> Dict[str, Any]:
    """Quick snooze from the notification UI."""
    if not _reminders_manager:
        return {"ok": False, "error": "Not initialized"}
    
    try:
        result = _reminders_manager.snooze(reminder_id, duration)
        if result:
            _dismissed_this_session.add(reminder_id)  # Hide after snooze
            return {"ok": True, "snoozed_until": result.snoozed_until}
        return {"ok": False, "error": "Reminder not found"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def quick_done(reminder_id: str) -> Dict[str, Any]:
    """Quick mark done from the notification UI."""
    if not _reminders_manager:
        return {"ok": False, "error": "Not initialized"}
    
    try:
        result = _reminders_manager.complete(reminder_id)
        if result:
            _dismissed_this_session.add(reminder_id)  # Hide after done
            return {"ok": True, "completed": reminder_id, "is_recurring": result.is_recurring}
        return {"ok": False, "error": "Reminder not found"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# =============================================================================
# FLASK ROUTES - Add these to your app.py
# =============================================================================

FLASK_ROUTES = '''
# Add to app.py:

from kernel.reminders_api import (
    init_reminders_api,
    get_due_reminders_for_ui,
    dismiss_reminder_notification,
    quick_snooze,
    quick_done,
)

# After kernel initialization:
init_reminders_api(kernel.reminders)

# Add these routes:

@app.route("/api/reminders/due")
def api_reminders_due():
    """Frontend polls this to check for due reminders."""
    return jsonify(get_due_reminders_for_ui())

@app.route("/api/reminders/dismiss/<reminder_id>", methods=["POST"])
def api_reminders_dismiss(reminder_id):
    """Dismiss a reminder notification (hide it, don't mark done)."""
    return jsonify(dismiss_reminder_notification(reminder_id))

@app.route("/api/reminders/snooze/<reminder_id>", methods=["POST"])
def api_reminders_snooze(reminder_id):
    """Quick snooze from notification."""
    duration = request.json.get("duration", "30m") if request.is_json else "30m"
    return jsonify(quick_snooze(reminder_id, duration))

@app.route("/api/reminders/done/<reminder_id>", methods=["POST"])
def api_reminders_done(reminder_id):
    """Quick mark done from notification."""
    return jsonify(quick_done(reminder_id))
'''

print(FLASK_ROUTES)
