# kernel/reminder_settings.py
"""
NovaOS Reminder Settings — v2.0.0

Persistent settings for the reminder service.
Settings are stored in data/reminder_settings.json and can be
updated via the UI or API.

Settings:
- ntfy_enabled: bool - Enable/disable ntfy push notifications
- ntfy_topic: str - Your ntfy topic name
- ntfy_server: str - ntfy server URL (default: https://ntfy.sh)
- ntfy_priority: str - Notification priority (low/default/high/urgent)
- check_interval: int - How often to check for due reminders (seconds)
- console_notifications: bool - Log to console (for debugging)
- email_enabled: bool - Enable email notifications
- email_to: str - Email recipient
- (email SMTP settings stored separately for security)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional


DEFAULT_SETTINGS = {
    # ntfy.sh push notifications
    "ntfy_enabled": False,
    "ntfy_topic": "",
    "ntfy_server": "https://ntfy.sh",
    "ntfy_priority": "default",
    
    # Service settings
    "check_interval": 60,
    "console_notifications": True,
    
    # In-app notifications
    "inapp_enabled": True,
    "inapp_poll_interval": 30,  # seconds
    
    # Email (disabled by default, requires SMTP setup)
    "email_enabled": False,
    "email_to": "",
    
    # Webhook
    "webhook_enabled": False,
    "webhook_url": "",
}


class ReminderSettings:
    """
    Manages reminder service settings with persistence.
    """
    
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.file = self.data_dir / "reminder_settings.json"
        self._settings: Dict[str, Any] = {}
        self._loaded = False
    
    def _load(self) -> None:
        """Load settings from disk."""
        if self._loaded:
            return
        
        self._settings = DEFAULT_SETTINGS.copy()
        
        if self.file.exists():
            try:
                with open(self.file, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                # Merge saved settings over defaults
                self._settings.update(saved)
            except Exception as e:
                print(f"[ReminderSettings] Load error: {e}", flush=True)
        
        self._loaded = True
    
    def _save(self) -> None:
        """Save settings to disk."""
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            with open(self.file, "w", encoding="utf-8") as f:
                json.dump(self._settings, f, indent=2)
        except Exception as e:
            print(f"[ReminderSettings] Save error: {e}", flush=True)
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a setting value."""
        self._load()
        return self._settings.get(key, default)
    
    def set(self, key: str, value: Any) -> None:
        """Set a setting value."""
        self._load()
        self._settings[key] = value
        self._save()
    
    def get_all(self) -> Dict[str, Any]:
        """Get all settings."""
        self._load()
        return self._settings.copy()
    
    def update(self, updates: Dict[str, Any]) -> None:
        """Update multiple settings at once."""
        self._load()
        for key, value in updates.items():
            if key in DEFAULT_SETTINGS:  # Only allow known settings
                self._settings[key] = value
        self._save()
    
    def reset(self) -> None:
        """Reset to default settings."""
        self._settings = DEFAULT_SETTINGS.copy()
        self._save()
    
    def to_service_config(self) -> Dict[str, Any]:
        """
        Convert settings to reminder_service config format.
        This is used when initializing or reconfiguring the service.
        """
        self._load()
        
        config = {
            "check_interval": self._settings.get("check_interval", 60),
            "console_notifications": self._settings.get("console_notifications", True),
        }
        
        # ntfy settings
        if self._settings.get("ntfy_enabled") and self._settings.get("ntfy_topic"):
            config["ntfy_topic"] = self._settings["ntfy_topic"]
            config["ntfy_server"] = self._settings.get("ntfy_server", "https://ntfy.sh")
            config["ntfy_priority"] = self._settings.get("ntfy_priority", "default")
        
        # Webhook settings
        if self._settings.get("webhook_enabled") and self._settings.get("webhook_url"):
            config["webhook_url"] = self._settings["webhook_url"]
        
        return config


# Global instance
_settings_instance: Optional[ReminderSettings] = None


def get_reminder_settings(data_dir: Optional[Path] = None) -> ReminderSettings:
    """Get or create the global settings instance."""
    global _settings_instance
    
    if _settings_instance is None:
        if data_dir is None:
            data_dir = Path("data")
        _settings_instance = ReminderSettings(data_dir)
    
    return _settings_instance


def init_reminder_settings(data_dir: Path) -> ReminderSettings:
    """Initialize the global settings instance."""
    global _settings_instance
    _settings_instance = ReminderSettings(data_dir)
    return _settings_instance


__all__ = [
    "ReminderSettings",
    "get_reminder_settings",
    "init_reminder_settings",
    "DEFAULT_SETTINGS",
]
