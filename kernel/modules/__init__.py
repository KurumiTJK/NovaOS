# kernel/modules/__init__.py
"""
NovaOS Modules Subpackage

Contains:
- module_manager: World Map module system - domains/regions of life

All symbols are re-exported for backward compatibility.
"""

from .module_manager import (
    # Constants
    VALID_STATUSES,
    VALID_PHASES,
    VALID_CATEGORIES,
    DEFAULT_STATUS,
    DEFAULT_PHASE,
    DEFAULT_CATEGORY,
    DEFAULT_ICON,
    DEFAULT_COLOR,
    # Helper functions
    slugify,
    generate_module_id,
    # Data classes
    WorldMeta,
    Module,
    ModuleStore,
    # Integration helpers
    get_module_xp_from_identity,
    get_quests_for_module,
    check_module_has_xp,
    remove_module_from_identity,
    detach_quests_from_module,
    # Command handlers
    handle_section_modules,
    handle_modules_list,
    handle_modules_show,
    handle_modules_add,
    handle_modules_update,
    handle_modules_archive,
    handle_modules_delete,
    get_module_handlers,
)
