# kernel/__init__.py
"""
NovaOS Kernel Package

The kernel is organized into subpackages:
- routing/     : Command routing (nl_router, syscommand_router, section_defs, section_handlers)
- memory/      : Memory systems (memory_engine, memory_manager, nova_wm, etc.)
- quests/      : Quest engine and handlers
- identity/    : Identity/profile system
- timerhythm/  : Daily review system
- reminders/   : Reminders system
- modules/     : World Map module system
- utils/       : Shared utilities (command_types, formatting, gemini_helper)

Shim files at the root provide backward compatibility for old import paths.

Example imports:
    # Via shims (backward compatible)
    from kernel.quest_engine import QuestEngine
    from kernel.reminders_manager import RemindersManager
    
    # Direct from subpackages (preferred for new code)
    from kernel.quests import QuestEngine
    from kernel.reminders import RemindersManager
    
    # Via package root (convenience)
    from kernel import QuestEngine, RemindersManager
"""

# Re-export key symbols for convenience (safe imports)

try:
    from .routing import NLRouter, SyscommandRouter
except ImportError:
    pass

try:
    from .memory import MemoryManager, get_wm
except ImportError:
    pass

try:
    from .quests import Quest, QuestEngine, is_quest_active
except ImportError:
    pass

try:
    from .identity import IdentitySectionManager, PlayerProfileManager
except ImportError:
    pass

try:
    from .timerhythm import TimerhythmManager
except ImportError:
    pass

try:
    from .reminders import RemindersManager, ReminderService
except ImportError:
    pass

try:
    from .modules import ModuleStore, Module
except ImportError:
    pass

try:
    from .utils import CommandRequest, CommandResponse, OutputFormatter
except ImportError:
    pass
