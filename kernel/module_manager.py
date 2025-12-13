# kernel/module_manager.py
"""
SHIM: This module has moved to kernel/modules/module_manager.py

This file re-exports all symbols for backward compatibility.
New code should import from kernel.modules.module_manager directly.
"""

from kernel.modules.module_manager import (
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

__all__ = [
    "VALID_STATUSES",
    "VALID_PHASES",
    "VALID_CATEGORIES",
    "DEFAULT_STATUS",
    "DEFAULT_PHASE",
    "DEFAULT_CATEGORY",
    "DEFAULT_ICON",
    "DEFAULT_COLOR",
    "slugify",
    "generate_module_id",
    "WorldMeta",
    "Module",
    "ModuleStore",
    "get_module_xp_from_identity",
    "get_quests_for_module",
    "check_module_has_xp",
    "remove_module_from_identity",
    "detach_quests_from_module",
    "handle_section_modules",
    "handle_modules_list",
    "handle_modules_show",
    "handle_modules_add",
    "handle_modules_update",
    "handle_modules_archive",
    "handle_modules_delete",
    "get_module_handlers",
]
