# kernel/memory_engine.py
"""
v0.5.4 — Nova Memory Engine v1 "Integrity Stack"

Layered memory system with:
- Working Memory: session-scoped, in-RAM only
- Long-Term Memory: persistent, typed (semantic/procedural/episodic)
- Memory Index: fast lookups by id, type, tags, salience, module
- Policy hooks: pre-store guards, recall transparency

Backward-compatible with MemoryManager v0.3 API.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Set, Callable
import threading


# -----------------------------------------------------------------------------
# Type Definitions
# -----------------------------------------------------------------------------

MemoryType = Literal["semantic", "procedural", "episodic"]
MemoryStatus = Literal["active", "stale", "archived", "pending_confirmation"]

# Default salience for different memory types
DEFAULT_SALIENCE: Dict[MemoryType, float] = {
    "semantic": 0.6,      # Facts, knowledge — medium importance
    "procedural": 0.7,    # How-to, skills — higher importance
    "episodic": 0.4,      # Events, logs — lower default, decays faster
}


# -----------------------------------------------------------------------------
# Memory Item (Enhanced Schema)
# -----------------------------------------------------------------------------

@dataclass
class MemoryItem:
    """
    Enhanced memory item with v0.5.4 fields.
    
    Backward-compatible: all new fields have defaults.
    """
    id: int
    type: MemoryType
    tags: List[str]
    payload: str
    timestamp: str  # ISO format, creation time
    trace: Dict[str, Any] = field(default_factory=dict)
    cluster_id: Optional[int] = None
    
    # v0.5.4 new fields
    source: str = "user"                    # user, system, import, inference
    salience: float = 0.5                   # 0.0–1.0, importance score
    status: MemoryStatus = "active"         # active, stale, archived, pending_confirmation
    confidence: float = 1.0                 # 0.0–1.0, certainty level
    last_used_at: Optional[str] = None      # ISO format, for decay tracking
    module_tag: Optional[str] = None        # linked module key
    version: int = 1                        # for conflict resolution

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryItem":
        """
        Create MemoryItem from dict, with backward compatibility.
        Missing v0.5.4 fields get defaults.
        """
        # Required fields
        item_id = int(data.get("id", 0))
        mem_type: MemoryType = data.get("type", "semantic")
        tags = list(data.get("tags", ["general"]))
        payload = data.get("payload", "")
        timestamp = data.get("timestamp", datetime.now(timezone.utc).isoformat())
        trace = data.get("trace") or {}
        cluster_id = data.get("cluster_id")

        # v0.5.4 fields with defaults
        source = data.get("source", "user")
        salience = float(data.get("salience", DEFAULT_SALIENCE.get(mem_type, 0.5)))
        status: MemoryStatus = data.get("status", "active")
        confidence = float(data.get("confidence", 1.0))
        last_used_at = data.get("last_used_at")
        module_tag = data.get("module_tag")
        version = int(data.get("version", 1))

        return cls(
            id=item_id,
            type=mem_type,
            tags=tags,
            payload=payload,
            timestamp=timestamp,
            trace=trace,
            cluster_id=cluster_id,
            source=source,
            salience=salience,
            status=status,
            confidence=confidence,
            last_used_at=last_used_at,
            module_tag=module_tag,
            version=version,
        )

    def touch(self) -> None:
        """Update last_used_at to now."""
        self.last_used_at = datetime.now(timezone.utc).isoformat()


# -----------------------------------------------------------------------------
# Working Memory (Session-scoped, RAM-only)
# -----------------------------------------------------------------------------

class WorkingMemory:
    """
    Session-scoped in-memory storage.
    
    - Not persisted to disk
    - Cleared on session reset
    - Used for temporary context, recent interactions
    """

    def __init__(self):
        self._sessions: Dict[str, List[MemoryItem]] = {}
        self._lock = threading.Lock()

    def add(self, session_id: str, item: MemoryItem) -> None:
        with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = []
            self._sessions[session_id].append(item)

    def get(self, session_id: str, limit: int = 10) -> List[MemoryItem]:
        with self._lock:
            items = self._sessions.get(session_id, [])
            return items[-limit:] if limit else items

    def clear(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def clear_all(self) -> None:
        with self._lock:
            self._sessions.clear()


# -----------------------------------------------------------------------------
# Memory Index (Fast Lookups)
# -----------------------------------------------------------------------------

class MemoryIndex:
    """
    In-memory index for fast memory lookups.
    
    Indexes:
    - by_id: id -> MemoryItem
    - by_type: type -> Set[id]
    - by_tag: tag -> Set[id]
    - by_salience: sorted list of (salience, id)
    - by_module: module_tag -> Set[id]
    - by_status: status -> Set[id]
    """

    def __init__(self):
        self.by_id: Dict[int, MemoryItem] = {}
        self.by_type: Dict[MemoryType, Set[int]] = {
            "semantic": set(),
            "procedural": set(),
            "episodic": set(),
        }
        self.by_tag: Dict[str, Set[int]] = {}
        self.by_module: Dict[str, Set[int]] = {}
        self.by_status: Dict[MemoryStatus, Set[int]] = {
            "active": set(),
            "stale": set(),
            "archived": set(),
            "pending_confirmation": set(),
        }
        self._lock = threading.Lock()

    def add(self, item: MemoryItem) -> None:
        with self._lock:
            self._add_unlocked(item)

    def _add_unlocked(self, item: MemoryItem) -> None:
        """Add item without lock (for bulk operations)."""
        self.by_id[item.id] = item
        self.by_type[item.type].add(item.id)
        
        for tag in item.tags:
            if tag not in self.by_tag:
                self.by_tag[tag] = set()
            self.by_tag[tag].add(item.id)
        
        if item.module_tag:
            if item.module_tag not in self.by_module:
                self.by_module[item.module_tag] = set()
            self.by_module[item.module_tag].add(item.id)
        
        if item.status in self.by_status:
            self.by_status[item.status].add(item.id)

    def remove(self, item_id: int) -> Optional[MemoryItem]:
        with self._lock:
            item = self.by_id.pop(item_id, None)
            if item:
                self.by_type[item.type].discard(item_id)
                for tag in item.tags:
                    if tag in self.by_tag:
                        self.by_tag[tag].discard(item_id)
                if item.module_tag and item.module_tag in self.by_module:
                    self.by_module[item.module_tag].discard(item_id)
                if item.status in self.by_status:
                    self.by_status[item.status].discard(item_id)
            return item

    def update(self, item: MemoryItem) -> None:
        """Update an item in the index."""
        with self._lock:
            # Remove old entry if exists
            old = self.by_id.get(item.id)
            if old:
                self.by_type[old.type].discard(item.id)
                for tag in old.tags:
                    if tag in self.by_tag:
                        self.by_tag[tag].discard(item.id)
                if old.module_tag and old.module_tag in self.by_module:
                    self.by_module[old.module_tag].discard(item.id)
                if old.status in self.by_status:
                    self.by_status[old.status].discard(item.id)
            # Add new
            self._add_unlocked(item)

    def get(self, item_id: int) -> Optional[MemoryItem]:
        return self.by_id.get(item_id)

    def query(
        self,
        mem_type: Optional[MemoryType] = None,
        tags: Optional[List[str]] = None,
        module_tag: Optional[str] = None,
        status: Optional[MemoryStatus] = None,
        min_salience: Optional[float] = None,
        limit: int = 50,
    ) -> List[MemoryItem]:
        """
        Query memories with filters.
        Returns items sorted by salience (desc), then timestamp (desc).
        """
        with self._lock:
            # Start with all IDs or filtered set
            candidate_ids: Optional[Set[int]] = None

            if mem_type:
                candidate_ids = self.by_type.get(mem_type, set()).copy()

            if tags:
                tag_ids: Set[int] = set()
                for tag in tags:
                    tag_ids |= self.by_tag.get(tag, set())
                if candidate_ids is None:
                    candidate_ids = tag_ids
                else:
                    candidate_ids &= tag_ids

            if module_tag:
                module_ids = self.by_module.get(module_tag, set())
                if candidate_ids is None:
                    candidate_ids = module_ids.copy()
                else:
                    candidate_ids &= module_ids

            if status:
                status_ids = self.by_status.get(status, set())
                if candidate_ids is None:
                    candidate_ids = status_ids.copy()
                else:
                    candidate_ids &= status_ids

            # If no filters, use all
            if candidate_ids is None:
                candidate_ids = set(self.by_id.keys())

            # Get items and filter by salience
            items: List[MemoryItem] = []
            for item_id in candidate_ids:
                item = self.by_id.get(item_id)
                if item:
                    if min_salience is not None and item.salience < min_salience:
                        continue
                    items.append(item)

            # Sort by salience desc, then timestamp desc
            items.sort(key=lambda x: (-x.salience, x.timestamp), reverse=False)
            items.sort(key=lambda x: x.salience, reverse=True)

            return items[:limit]

    def rebuild(self, items: List[MemoryItem]) -> None:
        """Rebuild index from scratch."""
        with self._lock:
            self.by_id.clear()
            for t in self.by_type.values():
                t.clear()
            self.by_tag.clear()
            self.by_module.clear()
            for s in self.by_status.values():
                s.clear()

            for item in items:
                self._add_unlocked(item)

    def stats(self) -> Dict[str, Any]:
        """Return index statistics."""
        with self._lock:
            return {
                "total": len(self.by_id),
                "by_type": {t: len(ids) for t, ids in self.by_type.items()},
                "by_status": {s: len(ids) for s, ids in self.by_status.items()},
                "unique_tags": len(self.by_tag),
                "unique_modules": len(self.by_module),
            }


# -----------------------------------------------------------------------------
# Long-Term Memory Store
# -----------------------------------------------------------------------------

class LongTermMemory:
    """
    Persistent memory storage with separate files per type.
    
    Files:
    - data/memory/semantic_memory.json
    - data/memory/procedural_memory.json
    - data/memory/episodic_memory.json
    - data/memory/memory_meta.json (next_id, version)
    
    Also maintains backward compatibility with data/memory.json
    """

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.memory_dir = data_dir / "memory"
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        # File paths
        self.files: Dict[MemoryType, Path] = {
            "semantic": self.memory_dir / "semantic_memory.json",
            "procedural": self.memory_dir / "procedural_memory.json",
            "episodic": self.memory_dir / "episodic_memory.json",
        }
        self.meta_file = self.memory_dir / "memory_meta.json"
        self.legacy_file = data_dir / "memory.json"

        # State
        self._items: Dict[int, MemoryItem] = {}
        self._next_id: int = 1
        self._loaded: bool = False
        self._lock = threading.Lock()

    def _load(self) -> None:
        """Load all memory files."""
        if self._loaded:
            return

        with self._lock:
            if self._loaded:
                return

            # Load meta
            if self.meta_file.exists():
                try:
                    meta = json.loads(self.meta_file.read_text(encoding="utf-8"))
                    self._next_id = int(meta.get("next_id", 1))
                except Exception:
                    self._next_id = 1

            # Load from typed files
            for mem_type, file_path in self.files.items():
                if file_path.exists():
                    try:
                        raw = json.loads(file_path.read_text(encoding="utf-8"))
                        items_list = raw.get("items", [])
                        for item_data in items_list:
                            try:
                                item = MemoryItem.from_dict(item_data)
                                self._items[item.id] = item
                                if item.id >= self._next_id:
                                    self._next_id = item.id + 1
                            except Exception:
                                continue
                    except Exception:
                        continue

            # Migrate from legacy file if typed files are empty
            if not self._items and self.legacy_file.exists():
                self._migrate_legacy()

            self._loaded = True

    def _migrate_legacy(self) -> None:
        """Migrate from legacy memory.json to typed files."""
        try:
            raw = json.loads(self.legacy_file.read_text(encoding="utf-8"))
            self._next_id = int(raw.get("next_id", 1))
            
            for item_data in raw.get("items", []):
                try:
                    item = MemoryItem.from_dict(item_data)
                    self._items[item.id] = item
                    if item.id >= self._next_id:
                        self._next_id = item.id + 1
                except Exception:
                    continue

            # Save to new format
            self._save_unlocked()
        except Exception:
            pass

    def _save(self) -> None:
        """Save all memory files."""
        with self._lock:
            self._save_unlocked()

    def _save_unlocked(self) -> None:
        """Save without lock (for internal use)."""
        # Group items by type
        by_type: Dict[MemoryType, List[Dict[str, Any]]] = {
            "semantic": [],
            "procedural": [],
            "episodic": [],
        }

        for item in self._items.values():
            by_type[item.type].append(item.to_dict())

        # Save typed files
        for mem_type, items in by_type.items():
            file_path = self.files[mem_type]
            data = {"version": "0.5.4", "items": items}
            file_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

        # Save meta
        meta = {"version": "0.5.4", "next_id": self._next_id}
        self.meta_file.write_text(json.dumps(meta, indent=2), encoding="utf-8")

        # Also update legacy file for backward compatibility
        legacy_data = {
            "version": "0.5.4",
            "next_id": self._next_id,
            "items": [item.to_dict() for item in self._items.values()],
        }
        self.legacy_file.write_text(json.dumps(legacy_data, indent=2, ensure_ascii=False), encoding="utf-8")

    def get_next_id(self) -> int:
        """Get and increment the next available ID."""
        self._load()
        with self._lock:
            nid = self._next_id
            self._next_id += 1
            return nid

    def store(self, item: MemoryItem) -> MemoryItem:
        """Store a memory item."""
        self._load()
        with self._lock:
            self._items[item.id] = item
            self._save_unlocked()
        return item

    def get(self, item_id: int) -> Optional[MemoryItem]:
        """Get a memory item by ID."""
        self._load()
        return self._items.get(item_id)

    def get_all(self) -> List[MemoryItem]:
        """Get all memory items."""
        self._load()
        return list(self._items.values())

    def delete(self, item_id: int) -> bool:
        """Delete a memory item."""
        self._load()
        with self._lock:
            if item_id in self._items:
                del self._items[item_id]
                self._save_unlocked()
                return True
        return False

    def delete_many(self, item_ids: List[int]) -> int:
        """Delete multiple memory items. Returns count deleted."""
        self._load()
        count = 0
        with self._lock:
            for item_id in item_ids:
                if item_id in self._items:
                    del self._items[item_id]
                    count += 1
            if count > 0:
                self._save_unlocked()
        return count

    def update(self, item: MemoryItem) -> bool:
        """Update a memory item."""
        self._load()
        with self._lock:
            if item.id in self._items:
                item.version = self._items[item.id].version + 1
                self._items[item.id] = item
                self._save_unlocked()
                return True
        return False

    def export_state(self) -> Dict[str, Any]:
        """Export all memory state for snapshots."""
        self._load()
        return {
            "version": "0.5.4",
            "next_id": self._next_id,
            "items": [item.to_dict() for item in self._items.values()],
        }

    def import_state(self, state: Dict[str, Any]) -> None:
        """Import memory state from snapshot."""
        with self._lock:
            self._items.clear()
            self._next_id = int(state.get("next_id", 1))
            
            for item_data in state.get("items", []):
                try:
                    item = MemoryItem.from_dict(item_data)
                    self._items[item.id] = item
                except Exception:
                    continue
            
            self._loaded = True
            self._save_unlocked()


# -----------------------------------------------------------------------------
# Memory Engine (Main Coordinator)
# -----------------------------------------------------------------------------

class MemoryEngine:
    """
    v0.5.4 Memory Engine — Main coordinator.
    
    Combines:
    - WorkingMemory (session-scoped)
    - LongTermMemory (persistent)
    - MemoryIndex (fast lookups)
    
    Provides the core API for memory operations.
    """

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.working = WorkingMemory()
        self.long_term = LongTermMemory(data_dir)
        self.index = MemoryIndex()
        
        # Policy hooks (set by MemoryManager)
        self.pre_store_hook: Optional[Callable[[MemoryItem, Dict[str, Any]], bool]] = None
        self.post_recall_hook: Optional[Callable[[MemoryItem], MemoryItem]] = None
        
        self._initialized = False

    def initialize(self) -> None:
        """Initialize the engine and build index."""
        if self._initialized:
            return
        
        # Load long-term memory and build index
        items = self.long_term.get_all()
        self.index.rebuild(items)
        self._initialized = True

    def store(
        self,
        payload: str,
        mem_type: MemoryType = "semantic",
        tags: Optional[List[str]] = None,
        trace: Optional[Dict[str, Any]] = None,
        source: str = "user",
        salience: Optional[float] = None,
        confidence: float = 1.0,
        module_tag: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> MemoryItem:
        """
        Store a new memory item.
        
        If session_id is provided, also adds to working memory.
        """
        self.initialize()
        
        # Determine salience
        if salience is None:
            salience = DEFAULT_SALIENCE.get(mem_type, 0.5)
        
        # Build item
        item = MemoryItem(
            id=self.long_term.get_next_id(),
            type=mem_type,
            tags=tags or ["general"],
            payload=payload,
            timestamp=datetime.now(timezone.utc).isoformat(),
            trace=trace or {},
            source=source,
            salience=salience,
            status="active",
            confidence=confidence,
            module_tag=module_tag,
        )
        
        # Pre-store hook (policy)
        if self.pre_store_hook:
            meta = {"source": source, "session_id": session_id}
            if not self.pre_store_hook(item, meta):
                # Hook rejected the store
                raise ValueError("Memory store rejected by policy")
        
        # Store in long-term
        self.long_term.store(item)
        
        # Update index
        self.index.add(item)
        
        # Add to working memory if session provided
        if session_id:
            self.working.add(session_id, item)
        
        return item

    def recall(
        self,
        mem_type: Optional[MemoryType] = None,
        tags: Optional[List[str]] = None,
        module_tag: Optional[str] = None,
        status: Optional[MemoryStatus] = None,
        min_salience: Optional[float] = None,
        limit: int = 20,
        touch: bool = True,
    ) -> List[MemoryItem]:
        """
        Recall memories matching filters.
        
        If touch=True, updates last_used_at for returned items.
        """
        self.initialize()
        
        items = self.index.query(
            mem_type=mem_type,
            tags=tags,
            module_tag=module_tag,
            status=status,
            min_salience=min_salience,
            limit=limit,
        )
        
        # Touch items and apply post-recall hook
        result = []
        for item in items:
            if touch:
                item.touch()
                self.long_term.update(item)
                self.index.update(item)
            
            if self.post_recall_hook:
                item = self.post_recall_hook(item)
            
            result.append(item)
        
        return result

    def forget(
        self,
        ids: Optional[List[int]] = None,
        tags: Optional[List[str]] = None,
        mem_type: Optional[MemoryType] = None,
    ) -> int:
        """
        Forget (delete) memories matching criteria.
        Returns count deleted.
        """
        self.initialize()
        
        to_delete: Set[int] = set()
        
        # By explicit IDs
        if ids:
            to_delete.update(ids)
        
        # By type (if no IDs specified)
        if mem_type and not ids:
            type_ids = self.index.by_type.get(mem_type, set())
            to_delete.update(type_ids)
        
        # By tags
        if tags:
            for tag in tags:
                tag_ids = self.index.by_tag.get(tag, set())
                if ids or mem_type:
                    # Intersect if other filters present
                    to_delete &= tag_ids
                else:
                    to_delete.update(tag_ids)
        
        # Delete
        for item_id in list(to_delete):
            self.index.remove(item_id)
        
        count = self.long_term.delete_many(list(to_delete))
        return count

    def trace(self, item_id: int) -> Optional[Dict[str, Any]]:
        """Get full trace/metadata for a memory item."""
        self.initialize()
        
        item = self.index.get(item_id)
        if not item:
            return None
        
        return {
            "id": item.id,
            "type": item.type,
            "tags": item.tags,
            "timestamp": item.timestamp,
            "trace": item.trace,
            "cluster_id": item.cluster_id,
            "source": item.source,
            "salience": item.salience,
            "status": item.status,
            "confidence": item.confidence,
            "last_used_at": item.last_used_at,
            "module_tag": item.module_tag,
            "version": item.version,
        }

    def bind_cluster(self, ids: List[int]) -> int:
        """Bind multiple memories into a cluster."""
        self.initialize()
        
        # Find next cluster ID
        existing_clusters = set()
        for item in self.long_term.get_all():
            if item.cluster_id is not None:
                existing_clusters.add(item.cluster_id)
        
        cluster_id = max(existing_clusters) + 1 if existing_clusters else 1
        
        # Update items
        for item_id in ids:
            item = self.index.get(item_id)
            if item:
                item.cluster_id = cluster_id
                self.long_term.update(item)
                self.index.update(item)
        
        return cluster_id

    def update_salience(self, item_id: int, salience: float) -> bool:
        """Update the salience of a memory item."""
        self.initialize()
        
        item = self.index.get(item_id)
        if not item:
            return False
        
        item.salience = max(0.0, min(1.0, salience))
        self.long_term.update(item)
        self.index.update(item)
        return True

    def update_status(self, item_id: int, status: MemoryStatus) -> bool:
        """Update the status of a memory item."""
        self.initialize()
        
        item = self.index.get(item_id)
        if not item:
            return False
        
        item.status = status
        self.long_term.update(item)
        self.index.update(item)
        return True

    def get_health(self) -> Dict[str, Any]:
        """Return memory health statistics."""
        self.initialize()
        
        stats = self.index.stats()
        return {
            "semantic_entries": stats["by_type"]["semantic"],
            "procedural_entries": stats["by_type"]["procedural"],
            "episodic_entries": stats["by_type"]["episodic"],
            "total": stats["total"],
            "active": stats["by_status"]["active"],
            "stale": stats["by_status"]["stale"],
            "archived": stats["by_status"]["archived"],
            "unique_tags": stats["unique_tags"],
            "unique_modules": stats["unique_modules"],
        }

    def get_working_memory(self, session_id: str, limit: int = 10) -> List[MemoryItem]:
        """Get recent working memory for a session."""
        return self.working.get(session_id, limit)

    def clear_working_memory(self, session_id: str) -> None:
        """Clear working memory for a session."""
        self.working.clear(session_id)

    def export_state(self) -> Dict[str, Any]:
        """Export all memory state for snapshots."""
        self.initialize()
        return self.long_term.export_state()

    def import_state(self, state: Dict[str, Any]) -> None:
        """Import memory state from snapshot."""
        self.long_term.import_state(state)
        items = self.long_term.get_all()
        self.index.rebuild(items)
        self._initialized = True

    # ---------- v0.5.6 Lifecycle Integration ----------

    def get_all_for_lifecycle(self) -> List[Dict[str, Any]]:
        """
        Get all memories as dicts for lifecycle processing.
        """
        self.initialize()
        return [item.to_dict() for item in self.long_term.get_all()]

    def apply_decay_updates(self, updates: List[Dict[str, Any]]) -> int:
        """
        Apply decay updates from lifecycle processing.
        
        Args:
            updates: List of {"id": X, "new_salience": Y, "new_status": Z}
            
        Returns:
            Count of memories updated
        """
        self.initialize()
        count = 0
        
        for update in updates:
            item_id = update.get("id")
            new_salience = update.get("new_salience")
            new_status = update.get("new_status")
            
            if item_id is None:
                continue
            
            item = self.index.get(item_id)
            if not item:
                continue
            
            changed = False
            
            if new_salience is not None and item.salience != new_salience:
                item.salience = new_salience
                changed = True
            
            if new_status is not None and item.status != new_status:
                item.status = new_status
                changed = True
            
            if changed:
                self.long_term.update(item)
                self.index.update(item)
                count += 1
        
        return count

    def get_stale_memories(self, limit: int = 50) -> List[MemoryItem]:
        """Get memories with stale status."""
        self.initialize()
        return self.index.query(status="stale", limit=limit)

    def get_archived_memories(self, limit: int = 50) -> List[MemoryItem]:
        """Get memories with archived status."""
        self.initialize()
        return self.index.query(status="archived", limit=limit)

    def bulk_update_status(self, ids: List[int], status: str) -> int:
        """
        Update status for multiple memories.
        
        Returns count updated.
        """
        self.initialize()
        count = 0
        
        for item_id in ids:
            item = self.index.get(item_id)
            if item and item.status != status:
                item.status = status
                self.long_term.update(item)
                self.index.update(item)
                count += 1
        
        return count

    def reconfirm_memory(self, item_id: int, new_salience: Optional[float] = None) -> bool:
        """
        Re-confirm a memory (restore to active with optional salience boost).
        
        Args:
            item_id: Memory ID to reconfirm
            new_salience: New salience value (default: restore to 0.5 or current if higher)
            
        Returns:
            True if memory was found and updated
        """
        self.initialize()
        
        item = self.index.get(item_id)
        if not item:
            return False
        
        # Update status to active
        item.status = "active"
        
        # Update salience
        if new_salience is not None:
            item.salience = max(0.0, min(1.0, new_salience))
        else:
            # Restore to at least 0.5, or keep current if higher
            item.salience = max(item.salience, 0.5)
        
        # Touch the memory
        item.touch()
        
        self.long_term.update(item)
        self.index.update(item)
        return True

