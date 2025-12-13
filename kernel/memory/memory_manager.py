# kernel/memory_manager.py
"""
v0.5.4 MemoryManager — Facade for Memory Engine

Maintains backward compatibility with v0.3 API while using the new
MemoryEngine internally for layered storage and indexing.

Public API unchanged:
- store(), recall(), forget(), trace(), bind_cluster()
- get_health(), export_state(), import_state()
- maybe_store_nl_interaction() (legacy hook)
"""

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Literal, Callable

from system.config import Config

# Import from new engine
from .memory_engine import (
    MemoryEngine,
    MemoryItem as EngineMemoryItem,
    MemoryType,
    MemoryStatus,
    DEFAULT_SALIENCE,
)


# -----------------------------------------------------------------------------
# Legacy MemoryItem (for backward compatibility)
# -----------------------------------------------------------------------------

@dataclass
class MemoryItem:
    """
    v0.3-compatible MemoryItem dataclass.
    
    PATCHED v0.11.0-fix1:
    - Added all v0.5.4 fields with defaults for backward compatibility
    - from_engine_item() now copies ALL fields
    
    The internal MemoryEngine uses an enhanced version with more fields.
    This class provides backward compatibility for code that imports
    MemoryItem directly from memory_manager.
    """
    id: int
    type: MemoryType
    tags: List[str]
    payload: str
    timestamp: str
    trace: Dict[str, Any]
    cluster_id: Optional[int] = None
    
    # v0.5.4 fields — ADDED in v0.11.0-fix1
    source: str = "user"
    salience: float = 0.5
    status: MemoryStatus = "active"
    confidence: float = 1.0
    last_used_at: Optional[str] = None
    module_tag: Optional[str] = None
    version: int = 1

    @classmethod
    def from_engine_item(cls, item: EngineMemoryItem) -> "MemoryItem":
        """
        Convert from EngineMemoryItem to legacy MemoryItem.
        
        PATCHED v0.11.0-fix1: Now copies ALL fields from engine item.
        """
        return cls(
            id=item.id,
            type=item.type,
            tags=item.tags,
            payload=item.payload,
            timestamp=item.timestamp,
            trace=item.trace,
            cluster_id=item.cluster_id,
            # v0.5.4 fields — ADDED in v0.11.0-fix1
            source=getattr(item, 'source', 'user'),
            salience=getattr(item, 'salience', 0.5),
            status=getattr(item, 'status', 'active'),
            confidence=getattr(item, 'confidence', 1.0),
            last_used_at=getattr(item, 'last_used_at', None),
            module_tag=getattr(item, 'module_tag', None),
            version=getattr(item, 'version', 1),
        )


# -----------------------------------------------------------------------------
# MemoryManager (v0.5.4 — Engine-backed)
# -----------------------------------------------------------------------------

class MemoryManager:
    """
    v0.5.4 MemoryManager
    
    Facade over MemoryEngine that maintains v0.3 API compatibility.
    
    New capabilities (via engine):
    - Layered storage (working + long-term)
    - Fast indexed queries
    - Salience and status tracking
    - Module-tagged memories
    
    Backward-compatible:
    - Same public API as v0.3
    - Same file format (also writes to memory.json)
    - MemoryItem dataclass unchanged
    """

    def __init__(self, config: Config):
        self.config = config
        self.memory_file: Path = config.data_dir / "memory.json"
        self.memory_file.parent.mkdir(parents=True, exist_ok=True)

        # Initialize the new engine
        self._engine = MemoryEngine(config.data_dir)
        
        # Policy hooks (can be set by kernel/policy_engine)
        self._pre_store_hook: Optional[Callable[[EngineMemoryItem, Dict[str, Any]], bool]] = None

        # Legacy compatibility: ensure file exists
        self._ensure_file()

    def _ensure_file(self) -> None:
        """Ensure memory.json exists (for backward compatibility)."""
        if not self.memory_file.exists() or self.memory_file.stat().st_size == 0:
            initial = {
                "version": "0.5.4",
                "next_id": 1,
                "items": [],
            }
            with self.memory_file.open("w", encoding="utf-8") as f:
                json.dump(initial, f, indent=2)

    # ---------- Policy Hooks (v0.5.4) ----------

    def set_pre_store_hook(self, hook: Callable[[EngineMemoryItem, Dict[str, Any]], bool]) -> None:
        """
        Set a pre-store policy hook.
        
        The hook receives (item, meta) and returns True to allow, False to reject.
        """
        self._pre_store_hook = hook
        self._engine.pre_store_hook = hook

    def set_post_recall_hook(self, hook: Callable[[EngineMemoryItem], EngineMemoryItem]) -> None:
        """
        Set a post-recall hook for transparency/annotation.
        """
        self._engine.post_recall_hook = hook

    # ---------- Public health API (used by status) ----------

    def get_health(self) -> Dict[str, Any]:
        """Return memory health (number of entries per type + v0.5.4 stats)."""
        try:
            return self._engine.get_health()
        except Exception as e:
            return {"error": f"Error while fetching memory health: {str(e)}"}

    # ---------- v0.2 compatibility helper ----------

    def maybe_store_nl_interaction(self, user_text: str, llm_output: str, context) -> None:
        """
        Legacy hook from v0.2.
        
        Stores an episodic memory when called explicitly.
        """
        try:
            payload = f"User: {user_text}\nNova: {llm_output}"
            trace = {
                "source": "legacy:nl_interaction",
                "session_id": getattr(context, "session_id", "default"),
            }
            self.store(
                payload=payload,
                mem_type="episodic",
                tags=["nl_interaction"],
                trace=trace,
            )
        except Exception:
            # best-effort only; never raise
            return

    # ---------- Core v0.3 memory API ----------

    def store(
        self,
        *,
        payload: str,
        mem_type: MemoryType = "semantic",
        tags: Optional[List[str]] = None,
        trace: Optional[Dict[str, Any]] = None,
        # v0.5.4 new parameters (optional)
        source: str = "user",
        salience: Optional[float] = None,
        confidence: float = 1.0,
        module_tag: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> MemoryItem:
        """
        Store a memory item.
        
        v0.3 compatible + v0.5.4 enhancements.
        """
        if tags is None:
            tags = ["general"]

        engine_item = self._engine.store(
            payload=payload,
            mem_type=mem_type,
            tags=tags,
            trace=trace,
            source=source,
            salience=salience,
            confidence=confidence,
            module_tag=module_tag,
            session_id=session_id,
        )

        # Return v0.3-compatible MemoryItem
        return MemoryItem.from_engine_item(engine_item)

    def recall(
        self,
        *,
        mem_type: Optional[MemoryType] = None,
        tags: Optional[List[str]] = None,
        limit: int = 20,
        # v0.5.4 new parameters (optional)
        module_tag: Optional[str] = None,
        status: Optional[MemoryStatus] = None,
        min_salience: Optional[float] = None,
    ) -> List[MemoryItem]:
        """
        Recall memory items matching filters.
        
        v0.3 compatible + v0.5.4 enhancements.
        """
        engine_items = self._engine.recall(
            mem_type=mem_type,
            tags=tags,
            module_tag=module_tag,
            status=status,
            min_salience=min_salience,
            limit=limit,
        )

        return [MemoryItem.from_engine_item(item) for item in engine_items]

    def forget(
        self,
        *,
        ids: Optional[List[int]] = None,
        tags: Optional[List[str]] = None,
        mem_type: Optional[MemoryType] = None,
    ) -> int:
        """
        Forget memory items matching criteria.
        Returns count deleted.
        """
        return self._engine.forget(ids=ids, tags=tags, mem_type=mem_type)

    def get(self, mem_id: int) -> Optional[Dict[str, Any]]:
        """
        Get a single memory item by ID as a dict.
        
        ADDED v0.11.0-fix4: Required by nova_wm_episodic.py for restore functionality.
        
        Returns:
            Dict with memory fields including 'trace' for metadata, or None if not found.
        """
        # Get trace info which includes the item data
        trace_info = self._engine.trace(mem_id)
        if trace_info is None:
            return None
        
        # trace() returns a dict with the memory fields
        # We need to ensure it has the expected structure
        return trace_info

    def trace(self, mem_id: int) -> Optional[Dict[str, Any]]:
        """Get trace/metadata for a memory item."""
        return self._engine.trace(mem_id)

    def bind_cluster(self, ids: List[int]) -> int:
        """Bind multiple memories into a cluster."""
        return self._engine.bind_cluster(ids)

    # ---------- v0.5.4 Enhanced API ----------

    def update_salience(self, mem_id: int, salience: float) -> bool:
        """Update the salience of a memory item."""
        return self._engine.update_salience(mem_id, salience)

    def update_status(self, mem_id: int, status: MemoryStatus) -> bool:
        """Update the status of a memory item."""
        return self._engine.update_status(mem_id, status)

    def get_by_module(self, module_tag: str, limit: int = 20) -> List[MemoryItem]:
        """Get memories linked to a specific module."""
        engine_items = self._engine.recall(module_tag=module_tag, limit=limit)
        return [MemoryItem.from_engine_item(item) for item in engine_items]

    def get_high_salience(self, min_salience: float = 0.7, limit: int = 20) -> List[MemoryItem]:
        """Get high-salience memories."""
        engine_items = self._engine.recall(min_salience=min_salience, limit=limit)
        return [MemoryItem.from_engine_item(item) for item in engine_items]

    def get_working_memory(self, session_id: str, limit: int = 10) -> List[MemoryItem]:
        """Get recent working memory for a session."""
        engine_items = self._engine.get_working_memory(session_id, limit)
        return [MemoryItem.from_engine_item(item) for item in engine_items]

    def clear_working_memory(self, session_id: str) -> None:
        """Clear working memory for a session."""
        self._engine.clear_working_memory(session_id)

    # ---------- Snapshot integration ----------

    def export_state(self) -> Dict[str, Any]:
        """Export all memory state for snapshots."""
        return self._engine.export_state()

    def import_state(self, state: Dict[str, Any]) -> None:
        """Import memory state from snapshot."""
        self._engine.import_state(state)

    # ---------- Statistics (v0.5.4) ----------

    def get_stats(self) -> Dict[str, Any]:
        """
        Get detailed memory statistics.
        
        Returns more info than get_health() for debugging/introspection.
        """
        health = self._engine.get_health()
        return {
            "health": health,
            "engine_version": "0.5.4",
            "data_dir": str(self.config.data_dir),
        }
