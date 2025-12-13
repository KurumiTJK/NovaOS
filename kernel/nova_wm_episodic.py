# kernel/nova_wm_episodic.py
"""
SHIM: This module has moved to kernel/memory/nova_wm_episodic.py

This file re-exports all symbols for backward compatibility.
New code should import from kernel.memory.nova_wm_episodic directly.
"""

from kernel.memory.nova_wm_episodic import (
    # Configuration constants
    EPISODIC_ENABLED,
    MAX_EPISODIC_AGE_DAYS,
    MAX_EPISODICS_PER_QUERY,
    MIN_RELEVANCE_SCORE,
    AUTO_REHYDRATE_ON_MODULE,
    # Enums and classes
    RehydrationMode,
    EpisodicSnapshot,
    RelevanceResult,
    EpisodicIndex,
    # Public API functions
    get_episodic_index,
    clear_episodic_index,
    create_snapshot_from_wm,
    episodic_snapshot,
    episodic_restore,
    find_relevant_episodics,
    episodic_rehydrate_for_module,
    episodic_list,
    episodic_debug,
    set_episodic_enabled,
    is_episodic_enabled,
    set_auto_rehydrate,
    episodic_clear,
    episodic_delete,
)

__all__ = [
    # Configuration constants
    "EPISODIC_ENABLED",
    "MAX_EPISODIC_AGE_DAYS",
    "MAX_EPISODICS_PER_QUERY",
    "MIN_RELEVANCE_SCORE",
    "AUTO_REHYDRATE_ON_MODULE",
    # Enums and classes
    "RehydrationMode",
    "EpisodicSnapshot",
    "RelevanceResult",
    "EpisodicIndex",
    # Public API functions
    "get_episodic_index",
    "clear_episodic_index",
    "create_snapshot_from_wm",
    "episodic_snapshot",
    "episodic_restore",
    "find_relevant_episodics",
    "episodic_rehydrate_for_module",
    "episodic_list",
    "episodic_debug",
    "set_episodic_enabled",
    "is_episodic_enabled",
    "set_auto_rehydrate",
    "episodic_clear",
    "episodic_delete",
]
