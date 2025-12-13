# kernel/quests/__init__.py
"""
NovaOS Quests Subpackage

Contains:
- quest_engine: Core quest data structures and persistence
- quest_handlers: Original quest command handlers
- quest_handlers_v10: Updated v0.10.0 handlers with wizard
- quest_compose_wizard: Interactive quest creation wizard
- quest_compose_wizard_streaming: Streaming extension
- quest_delete_wizard: Interactive quest deletion wizard
- quest_start_wizard: Quest start/resume wizard
- quest_complete_halt_handlers: #complete and #halt handlers
- quest_lock_mode: Quest lock state management
- quest_v10_integration: Integration helper module

All symbols are re-exported for backward compatibility.
"""

# Core engine - always available
from .quest_engine import (
    Quest,
    Step,
    RunState,
    QuestEngine,
    ValidationConfig,
)

# Quest lock mode - always available
from .quest_lock_mode import (
    QuestLockState,
    is_quest_active,
    get_quest_lock_state,
    activate_quest_lock,
    deactivate_quest_lock,
    is_command_allowed_in_quest_mode,
    get_quest_mode_blocked_message,
)

# Safe imports for optional modules
try:
    from .quest_handlers import (
        handle_quest,
        handle_next,
        handle_pause,
        handle_quest_log,
        handle_quest_reset,
        handle_quest_compose,
        handle_quest_delete,
        get_quest_handlers,
    )
except ImportError:
    pass

try:
    from .quest_handlers_v10 import (
        handle_quest_v10,
        handle_next_v10,
        check_and_route_quest_wizard,
    )
except ImportError:
    pass

try:
    from .quest_complete_halt_handlers import (
        handle_complete,
        handle_halt,
        get_complete_halt_handlers,
    )
except ImportError:
    pass

try:
    from .quest_start_wizard import (
        handle_quest_wizard_start,
        process_quest_wizard_input,
        is_quest_wizard_active,
        cancel_quest_wizard,
    )
except ImportError:
    pass

try:
    from .quest_compose_wizard import (
        handle_quest_compose_wizard,
        is_compose_wizard_active,
        process_compose_wizard_input,
        clear_compose_session,
    )
except ImportError:
    pass

try:
    from .quest_delete_wizard import (
        handle_quest_delete_wizard,
        is_delete_wizard_active,
        process_delete_wizard_input,
        cancel_delete_wizard,
    )
except ImportError:
    pass

try:
    from .quest_v10_integration import (
        apply_quest_v10_integration,
        check_quest_mode_routing,
    )
except ImportError:
    pass
