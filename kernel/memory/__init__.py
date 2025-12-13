# kernel/memory/__init__.py
"""
NovaOS Memory Subpackage

Contains:
- memory_engine: Core memory storage with indexing and lifecycle
- memory_manager: Facade for memory operations (backward compatible API)
- memory_helpers: ChatGPT-style memory features (auto-extraction, search)
- memory_syscommands: Memory management command handlers
- nova_wm: Working Memory engine
- nova_wm_behavior: Behavior layer for conversational continuity
- nova_wm_episodic: Episodic memory bridge (WM ↔ LTM)
- memory_lifecycle: Decay, drift, and re-confirmation
- memory_policy: Policy layer for memory operations

All symbols are re-exported for backward compatibility.
"""

# Core engine - always available
from .memory_engine import (
    MemoryEngine,
    MemoryItem,
    MemoryType,
    MemoryStatus,
    DEFAULT_SALIENCE,
    WorkingMemory,
    MemoryIndex,
    LongTermMemory,
)

# Manager facade - always available
from .memory_manager import MemoryManager

# Working Memory - always available
from .nova_wm import (
    NovaWorkingMemory,
    get_wm,
    wm_update,
    wm_record_response,
    wm_get_context,
    wm_get_context_string,
    wm_answer_reference,
    wm_clear,
)

# Memory helpers - safe import
try:
    from .memory_helpers import (
        get_profile_memories,
        search_by_keywords,
        run_memory_decay,
        handle_remember_intent,
        build_ltm_context_for_persona,
        run_auto_extraction,
    )
except ImportError:
    pass

# Syscommand handlers - safe import
try:
    from .memory_syscommands import (
        get_memory_syscommand_handlers,
        MEMORY_SYSCOMMAND_HANDLERS,
    )
except ImportError:
    pass

# Lifecycle - safe import
try:
    from .memory_lifecycle import (
        DecayConfig,
        DriftReport,
        MemoryLifecycle,
    )
except ImportError:
    pass

# Policy - safe import
try:
    from .memory_policy import (
        MemoryPolicy,
        MemoryPolicyConfig,
    )
except ImportError:
    pass

# Behavior layer - safe import
try:
    from .nova_wm_behavior import (
        get_behavior_engine,
        behavior_update,
        behavior_after_response,
        behavior_get_context,
        behavior_clear,
    )
except ImportError:
    pass

# Episodic bridge - safe import
try:
    from .nova_wm_episodic import (
        episodic_snapshot,
        episodic_restore,
        episodic_list,
        EPISODIC_ENABLED,
    )
except ImportError:
    pass
