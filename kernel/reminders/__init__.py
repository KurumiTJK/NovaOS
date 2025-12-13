# kernel/reminders/__init__.py
"""
NovaOS Reminders Subpackage

Contains:
- reminders_manager: Core reminders data model and persistence
- reminders_handlers: Reminder command handlers
- reminders_wizard: Interactive wizard for reminders
- reminder_service: Background service for notifications
- reminder_settings: Persistent settings
- reminders_api: Flask API endpoints
- reminders_integration: Kernel-level wizard integration

All symbols are re-exported for backward compatibility.
"""

# Core manager - always available
from .reminders_manager import (
    RemindersManager,
    Reminder,
    RepeatConfig,
    RepeatWindow,
    DEFAULT_TIMEZONE,
    WEEKDAY_MAP,
    WEEKDAY_ABBREV,
)

# Settings
from .reminder_settings import (
    ReminderSettings,
    get_reminder_settings,
    init_reminder_settings,
    DEFAULT_SETTINGS,
)

# Wizard
from .reminders_wizard import (
    RemindersWizardSession,
    has_active_wizard,
    get_wizard_session,
    set_wizard_session,
    clear_wizard_session,
    start_reminders_wizard,
    process_reminders_wizard_input,
    is_reminders_wizard_command,
    WIZARD_COMMANDS,
)

# Safe imports for optional modules
try:
    from .reminders_handlers import (
        handle_reminders_list,
        handle_reminders_due,
        handle_reminders_show,
        handle_reminders_add,
        handle_reminders_update,
        handle_reminders_delete,
        handle_reminders_done,
        handle_reminders_snooze,
        handle_reminders_pin,
        handle_reminders_unpin,
        handle_reminders_settings,
        get_reminders_handlers,
    )
except ImportError:
    pass

try:
    from .reminder_service import (
        ReminderService,
        get_reminder_service,
        init_reminder_service,
        stop_reminder_service,
    )
except ImportError:
    pass

try:
    from .reminders_api import (
        init_reminders_api,
        get_due_reminders_for_ui,
        dismiss_reminder_notification,
        quick_snooze,
        quick_done,
        clear_dismissed,
    )
except ImportError:
    pass

try:
    from .reminders_integration import check_reminders_wizard
except ImportError:
    pass
