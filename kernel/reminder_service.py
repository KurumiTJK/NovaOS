# kernel/reminder_service.py
"""
NovaOS Reminder Background Service — v2.0.0

Runs as a background thread to check for due reminders and send notifications.

Notification methods supported:
1. WebSocket push to connected clients
2. Desktop notifications via ntfy.sh (self-hosted or cloud)
3. Email notifications (SMTP)
4. Webhook callbacks

Usage:
    from kernel.reminder_service import ReminderService
    
    # In app.py or nova_kernel.py __init__:
    reminder_service = ReminderService(
        reminders_manager=kernel.reminders,
        config={
            "check_interval": 60,  # seconds
            "ntfy_topic": "novaos-reminders",  # optional
            "ntfy_server": "https://ntfy.sh",  # or self-hosted
            "webhook_url": None,  # optional callback URL
        }
    )
    reminder_service.start()
    
    # On shutdown:
    reminder_service.stop()
"""

from __future__ import annotations

import json
import threading
import time
import smtplib
import ssl
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set
from zoneinfo import ZoneInfo

try:
    import requests
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False

from .reminders_manager import RemindersManager, Reminder, DEFAULT_TIMEZONE


# =============================================================================
# NOTIFICATION BACKENDS
# =============================================================================

class NotificationBackend:
    """Base class for notification backends."""
    
    def send(self, reminder: Reminder, message: str) -> bool:
        """Send a notification. Returns True if successful."""
        raise NotImplementedError


class NtfyBackend(NotificationBackend):
    """
    Send notifications via ntfy.sh (or self-hosted ntfy server).
    
    ntfy is a simple pub-sub notification service.
    - Cloud: https://ntfy.sh (free, no signup)
    - Self-hosted: https://github.com/binwiederhier/ntfy
    
    Subscribe on your phone/desktop to receive push notifications.
    """
    
    def __init__(self, topic: str, server: str = "https://ntfy.sh", priority: str = "default"):
        self.topic = topic
        self.server = server.rstrip("/")
        self.priority = priority
    
    def send(self, reminder: Reminder, message: str) -> bool:
        if not _HAS_REQUESTS:
            print("[ReminderService] ntfy backend requires 'requests' package", flush=True)
            return False
        
        try:
            url = f"{self.server}/{self.topic}"
            
            # Build notification
            title = f"⏰ Reminder: {reminder.title}"
            
            headers = {
                "Title": title,
                "Priority": self.priority,
                "Tags": "bell,reminder",
            }
            
            # Add click action to open NovaOS (if you have a URL)
            # headers["Click"] = "https://your-novaos-url.com"
            
            response = requests.post(url, data=message, headers=headers, timeout=10)
            
            if response.status_code == 200:
                print(f"[ReminderService] ntfy notification sent: {reminder.id}", flush=True)
                return True
            else:
                print(f"[ReminderService] ntfy error {response.status_code}: {response.text}", flush=True)
                return False
                
        except Exception as e:
            print(f"[ReminderService] ntfy exception: {e}", flush=True)
            return False


class WebhookBackend(NotificationBackend):
    """Send notifications via HTTP webhook."""
    
    def __init__(self, url: str, method: str = "POST", headers: Optional[Dict[str, str]] = None):
        self.url = url
        self.method = method.upper()
        self.headers = headers or {"Content-Type": "application/json"}
    
    def send(self, reminder: Reminder, message: str) -> bool:
        if not _HAS_REQUESTS:
            print("[ReminderService] webhook backend requires 'requests' package", flush=True)
            return False
        
        try:
            payload = {
                "type": "reminder",
                "reminder_id": reminder.id,
                "title": reminder.title,
                "message": message,
                "due_at": reminder.due_at,
                "priority": reminder.priority,
                "timestamp": datetime.now(ZoneInfo("UTC")).isoformat(),
            }
            
            if self.method == "POST":
                response = requests.post(self.url, json=payload, headers=self.headers, timeout=10)
            else:
                response = requests.get(self.url, params=payload, headers=self.headers, timeout=10)
            
            if response.status_code in (200, 201, 202, 204):
                print(f"[ReminderService] webhook sent: {reminder.id}", flush=True)
                return True
            else:
                print(f"[ReminderService] webhook error {response.status_code}", flush=True)
                return False
                
        except Exception as e:
            print(f"[ReminderService] webhook exception: {e}", flush=True)
            return False


class EmailBackend(NotificationBackend):
    """Send notifications via email (SMTP)."""
    
    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        username: str,
        password: str,
        from_email: str,
        to_email: str,
        use_tls: bool = True,
    ):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.from_email = from_email
        self.to_email = to_email
        self.use_tls = use_tls
    
    def send(self, reminder: Reminder, message: str) -> bool:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"⏰ NovaOS Reminder: {reminder.title}"
            msg["From"] = self.from_email
            msg["To"] = self.to_email
            
            # Plain text version
            text_body = f"""
NovaOS Reminder

{reminder.title}

{message}

---
Reminder ID: {reminder.id}
Due: {reminder.due_at}
Priority: {reminder.priority}
"""
            
            # HTML version
            html_body = f"""
<html>
<body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
    <div style="background: #1a1a2e; color: #eee; padding: 20px; border-radius: 8px;">
        <h2 style="color: #00d4ff; margin-top: 0;">⏰ {reminder.title}</h2>
        <p style="font-size: 16px;">{message}</p>
        <hr style="border-color: #333;">
        <p style="font-size: 12px; color: #888;">
            Reminder ID: {reminder.id}<br>
            Due: {reminder.due_at}<br>
            Priority: {reminder.priority}
        </p>
    </div>
</body>
</html>
"""
            
            msg.attach(MIMEText(text_body, "plain"))
            msg.attach(MIMEText(html_body, "html"))
            
            # Send email
            if self.use_tls:
                context = ssl.create_default_context()
                with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                    server.starttls(context=context)
                    server.login(self.username, self.password)
                    server.sendmail(self.from_email, self.to_email, msg.as_string())
            else:
                with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port) as server:
                    server.login(self.username, self.password)
                    server.sendmail(self.from_email, self.to_email, msg.as_string())
            
            print(f"[ReminderService] email sent: {reminder.id}", flush=True)
            return True
            
        except Exception as e:
            print(f"[ReminderService] email exception: {e}", flush=True)
            return False


class ConsoleBackend(NotificationBackend):
    """Print notifications to console (for testing)."""
    
    def send(self, reminder: Reminder, message: str) -> bool:
        print(f"\n{'='*60}", flush=True)
        print(f"⏰ REMINDER DUE: {reminder.title}", flush=True)
        print(f"   {message}", flush=True)
        print(f"   ID: {reminder.id} | Priority: {reminder.priority}", flush=True)
        print(f"{'='*60}\n", flush=True)
        return True


# =============================================================================
# REMINDER SERVICE
# =============================================================================

class ReminderService:
    """
    Background service that checks for due reminders and sends notifications.
    
    Runs in a separate thread, checking every `check_interval` seconds.
    Tracks which reminders have been notified to avoid duplicates.
    """
    
    def __init__(
        self,
        reminders_manager: RemindersManager,
        config: Optional[Dict[str, Any]] = None,
        data_dir: Optional[Path] = None,
    ):
        self.manager = reminders_manager
        self.config = config or {}
        self.data_dir = Path(data_dir) if data_dir else Path("data")
        
        # Service state
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
        # Track notified reminders to avoid spam
        # Key: reminder_id, Value: last_notified timestamp
        self._notified: Dict[str, datetime] = {}
        self._notified_file = self.data_dir / "reminder_notifications.json"
        self._load_notified_state()
        
        # Notification backends
        self._backends: List[NotificationBackend] = []
        self._setup_backends()
        
        # Config
        self.check_interval = self.config.get("check_interval", 60)  # seconds
        self.snooze_renotify_delay = self.config.get("snooze_renotify_delay", 300)  # 5 min
        self.window_renotify_delay = self.config.get("window_renotify_delay", 1800)  # 30 min
    
    def _setup_backends(self) -> None:
        """Configure notification backends from config."""
        
        # Always add console backend for debugging
        if self.config.get("console_notifications", True):
            self._backends.append(ConsoleBackend())
        
        # ntfy.sh notifications
        ntfy_topic = self.config.get("ntfy_topic")
        if ntfy_topic:
            ntfy_server = self.config.get("ntfy_server", "https://ntfy.sh")
            ntfy_priority = self.config.get("ntfy_priority", "default")
            self._backends.append(NtfyBackend(ntfy_topic, ntfy_server, ntfy_priority))
            print(f"[ReminderService] ntfy backend enabled: {ntfy_server}/{ntfy_topic}", flush=True)
        
        # Webhook notifications
        webhook_url = self.config.get("webhook_url")
        if webhook_url:
            webhook_method = self.config.get("webhook_method", "POST")
            webhook_headers = self.config.get("webhook_headers")
            self._backends.append(WebhookBackend(webhook_url, webhook_method, webhook_headers))
            print(f"[ReminderService] webhook backend enabled: {webhook_url}", flush=True)
        
        # Email notifications
        smtp_host = self.config.get("smtp_host")
        if smtp_host:
            self._backends.append(EmailBackend(
                smtp_host=smtp_host,
                smtp_port=self.config.get("smtp_port", 587),
                username=self.config.get("smtp_username", ""),
                password=self.config.get("smtp_password", ""),
                from_email=self.config.get("email_from", ""),
                to_email=self.config.get("email_to", ""),
                use_tls=self.config.get("smtp_use_tls", True),
            ))
            print(f"[ReminderService] email backend enabled: {smtp_host}", flush=True)
    
    def add_backend(self, backend: NotificationBackend) -> None:
        """Add a custom notification backend."""
        self._backends.append(backend)
    
    def _load_notified_state(self) -> None:
        """Load notification history from disk."""
        if self._notified_file.exists():
            try:
                with open(self._notified_file, "r") as f:
                    data = json.load(f)
                # Convert ISO strings back to datetime
                for rid, ts_str in data.items():
                    try:
                        self._notified[rid] = datetime.fromisoformat(ts_str)
                    except (ValueError, TypeError):
                        pass
            except Exception as e:
                print(f"[ReminderService] Failed to load notification state: {e}", flush=True)
    
    def _save_notified_state(self) -> None:
        """Save notification history to disk."""
        try:
            self._notified_file.parent.mkdir(parents=True, exist_ok=True)
            # Convert datetime to ISO strings
            data = {rid: ts.isoformat() for rid, ts in self._notified.items()}
            with open(self._notified_file, "w") as f:
                json.dump(data, f)
        except Exception as e:
            print(f"[ReminderService] Failed to save notification state: {e}", flush=True)
    
    def _should_notify(self, reminder: Reminder, now: datetime) -> bool:
        """Check if we should send a notification for this reminder."""
        rid = reminder.id
        
        # Never notified? Send it
        if rid not in self._notified:
            return True
        
        last_notified = self._notified[rid]
        
        # For windowed reminders, re-notify periodically during the window
        if reminder.has_window:
            elapsed = (now - last_notified).total_seconds()
            return elapsed >= self.window_renotify_delay
        
        # For regular reminders, don't re-notify unless snoozed
        if reminder.snoozed_until:
            # Was snoozed after last notification? Re-notify when snooze ends
            try:
                snooze_end = datetime.fromisoformat(reminder.snoozed_until.replace("Z", "+00:00"))
                if snooze_end > last_notified and now >= snooze_end:
                    return True
            except (ValueError, TypeError):
                pass
        
        # Check if enough time has passed for re-notification
        elapsed = (now - last_notified).total_seconds()
        return elapsed >= self.snooze_renotify_delay
    
    def _mark_notified(self, reminder: Reminder, now: datetime) -> None:
        """Mark a reminder as notified."""
        self._notified[reminder.id] = now
        self._save_notified_state()
    
    def _build_message(self, reminder: Reminder) -> str:
        """Build the notification message."""
        parts = []
        
        if reminder.notes:
            parts.append(reminder.notes)
        
        # Add due time info
        try:
            tz = ZoneInfo(reminder.timezone)
            due_dt = datetime.fromisoformat(reminder.due_at.replace("Z", "+00:00")).astimezone(tz)
            parts.append(f"Due: {due_dt.strftime('%I:%M %p')}")
        except (ValueError, TypeError):
            pass
        
        if reminder.is_recurring:
            parts.append("(Recurring)")
        
        if reminder.priority == "high":
            parts.append("⚠️ High Priority")
        
        return " | ".join(parts) if parts else "Time for this reminder!"
    
    def _check_and_notify(self) -> None:
        """Check for due reminders and send notifications."""
        try:
            tz = ZoneInfo(DEFAULT_TIMEZONE)
            now = datetime.now(tz)
            
            # Get all due reminders
            due_reminders = self.manager.get_due_now(now)
            
            for reminder in due_reminders:
                if self._should_notify(reminder, now):
                    message = self._build_message(reminder)
                    
                    # Send to all backends
                    success = False
                    for backend in self._backends:
                        try:
                            if backend.send(reminder, message):
                                success = True
                        except Exception as e:
                            print(f"[ReminderService] Backend error: {e}", flush=True)
                    
                    if success:
                        self._mark_notified(reminder, now)
                        
                        # Update reminder's last_fired_at
                        self.manager.mark_fired(reminder.id)
        
        except Exception as e:
            print(f"[ReminderService] Check error: {e}", flush=True)
    
    def _run_loop(self) -> None:
        """Main service loop."""
        print(f"[ReminderService] Started (interval={self.check_interval}s)", flush=True)
        
        while not self._stop_event.is_set():
            self._check_and_notify()
            
            # Wait for interval or stop signal
            self._stop_event.wait(self.check_interval)
        
        print("[ReminderService] Stopped", flush=True)
    
    def start(self) -> None:
        """Start the background service."""
        if self._running:
            print("[ReminderService] Already running", flush=True)
            return
        
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
    
    def stop(self) -> None:
        """Stop the background service."""
        if not self._running:
            return
        
        self._running = False
        self._stop_event.set()
        
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
    
    def is_running(self) -> bool:
        """Check if service is running."""
        return self._running
    
    def check_now(self) -> None:
        """Manually trigger a check (useful for testing)."""
        self._check_and_notify()
    
    def get_status(self) -> Dict[str, Any]:
        """Get service status."""
        return {
            "running": self._running,
            "check_interval": self.check_interval,
            "backends": [type(b).__name__ for b in self._backends],
            "notified_count": len(self._notified),
        }


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

_service_instance: Optional[ReminderService] = None


def get_reminder_service() -> Optional[ReminderService]:
    """Get the global reminder service instance."""
    return _service_instance


def init_reminder_service(
    reminders_manager: RemindersManager,
    config: Optional[Dict[str, Any]] = None,
    data_dir: Optional[Path] = None,
    auto_start: bool = True,
) -> ReminderService:
    """
    Initialize the global reminder service.
    
    Call this once during app startup (e.g., in app.py).
    """
    global _service_instance
    
    if _service_instance is not None:
        _service_instance.stop()
    
    _service_instance = ReminderService(reminders_manager, config, data_dir)
    
    if auto_start:
        _service_instance.start()
    
    return _service_instance


def stop_reminder_service() -> None:
    """Stop the global reminder service."""
    global _service_instance
    
    if _service_instance:
        _service_instance.stop()
        _service_instance = None


__all__ = [
    "ReminderService",
    "NotificationBackend",
    "NtfyBackend",
    "WebhookBackend",
    "EmailBackend",
    "ConsoleBackend",
    "get_reminder_service",
    "init_reminder_service",
    "stop_reminder_service",
]
