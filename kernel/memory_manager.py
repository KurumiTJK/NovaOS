# kernel/memory_manager.py
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Literal

from system.config import Config

MemoryType = Literal["semantic", "procedural", "episodic"]


@dataclass
class MemoryItem:
    id: int
    type: MemoryType
    tags: List[str]
    payload: str
    timestamp: str
    trace: Dict[str, Any]
    cluster_id: Optional[int] = None


class MemoryManager:
    """
    v0.3 MemoryManager

    - Single backing file: data/memory.json
    - Structured memory items with id/type/tags/payload/timestamp/trace/cluster_id
    - No automatic storage from raw conversation; only explicit calls.
    """

    def __init__(self, config: Config):
        self.config = config
        self.memory_file: Path = config.data_dir / "memory.json"
        self.memory_file.parent.mkdir(parents=True, exist_ok=True)

        self._items: List[MemoryItem] = []
        self._next_id: int = 1
        self._loaded: bool = False
        self._ensure_file()

    # ---------- Internal file helpers ----------

    def _ensure_file(self) -> None:
        if not self.memory_file.exists() or self.memory_file.stat().st_size == 0:
            initial = {
                "version": "0.3",
                "next_id": 1,
                "items": [],
            }
            with self.memory_file.open("w", encoding="utf-8") as f:
                json.dump(initial, f, indent=2)
            self._items = []
            self._next_id = 1
            self._loaded = True

    def _load_file(self) -> None:
        if self._loaded:
            return
        self._ensure_file()
        try:
            with self.memory_file.open("r", encoding="utf-8") as f:
                raw = json.load(f)
        except json.JSONDecodeError:
            # Hard reset on corrupt file
            self._loaded = False
            try:
                self.memory_file.unlink()
            except FileNotFoundError:
                pass
            self._ensure_file()
            return

        self._next_id = int(raw.get("next_id", 1))
        self._items = []
        for item in raw.get("items", []):
            try:
                self._items.append(
                    MemoryItem(
                        id=int(item["id"]),
                        type=item["type"],
                        tags=list(item.get("tags", [])),
                        payload=item.get("payload", ""),
                        timestamp=item.get("timestamp", ""),
                        trace=item.get("trace", {}) or {},
                        cluster_id=item.get("cluster_id"),
                    )
                )
            except Exception:
                # Skip malformed records but keep others
                continue
        self._loaded = True

    def _save_file(self) -> None:
        self.memory_file.parent.mkdir(parents=True, exist_ok=True)
        raw = {
            "version": "0.3",
            "next_id": self._next_id,
            "items": [asdict(i) for i in self._items],
        }
        with self.memory_file.open("w", encoding="utf-8") as f:
            json.dump(raw, f, indent=2, ensure_ascii=False)

    # ---------- Public health API (used by status) ----------

    def get_health(self) -> Dict[str, Any]:
        """Return memory health (number of entries per type)."""
        try:
            self._load_file()
            semantic = sum(1 for i in self._items if i.type == "semantic")
            procedural = sum(1 for i in self._items if i.type == "procedural")
            episodic = sum(1 for i in self._items if i.type == "episodic")
            return {
                "semantic_entries": semantic,
                "procedural_entries": procedural,
                "episodic_entries": episodic,
                "total": len(self._items),
            }
        except Exception as e:
            return {"error": f"Error while fetching memory health: {str(e)}"}

    # ---------- v0.2 compatibility helper ----------

    def maybe_store_nl_interaction(self, user_text: str, llm_output: str, context) -> None:
        """
        Legacy hook from v0.2.

        In v0.3 we still implement it, but it simply stores an episodic memory item
        when called explicitly. Nothing is automatic; kernel never calls this by default.
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

    def _next_id_value(self) -> int:
        nid = self._next_id
        self._next_id += 1
        return nid

    def store(
        self,
        *,
        payload: str,
        mem_type: MemoryType = "semantic",
        tags: Optional[List[str]] = None,
        trace: Optional[Dict[str, Any]] = None,
    ) -> MemoryItem:
        self._load_file()
        if tags is None:
            tags = ["general"]
        item = MemoryItem(
            id=self._next_id_value(),
            type=mem_type,
            tags=tags,
            payload=payload,
            timestamp=datetime.now(timezone.utc).isoformat(),
            trace=trace or {},
            cluster_id=None,
        )
        self._items.append(item)
        self._save_file()
        return item

    def recall(
        self,
        *,
        mem_type: Optional[MemoryType] = None,
        tags: Optional[List[str]] = None,
        limit: int = 20,
    ) -> List[MemoryItem]:
        self._load_file()
        results: List[MemoryItem] = []
        for item in self._items:
            if mem_type and item.type != mem_type:
                continue
            if tags:
                if not (set(tags) & set(item.tags)):
                    continue
            results.append(item)
            if len(results) >= limit:
                break
        return results

    def forget(
        self,
        *,
        ids: Optional[List[int]] = None,
        tags: Optional[List[str]] = None,
        mem_type: Optional[MemoryType] = None,
    ) -> int:
        self._load_file()
        to_keep: List[MemoryItem] = []
        removed = 0
        id_set = set(ids or [])
        tag_set = set(tags or [])

        for item in self._items:
            kill = False
            if id_set and item.id in id_set:
                kill = True
            if mem_type and item.type == mem_type:
                # if no ids or tags specified, remove by type
                if not id_set and not tag_set:
                    kill = True
            if tag_set and (set(item.tags) & tag_set):
                kill = True
            if kill:
                removed += 1
            else:
                to_keep.append(item)

        self._items = to_keep
        if removed:
            self._save_file()
        return removed

    def trace(self, mem_id: int) -> Optional[Dict[str, Any]]:
        self._load_file()
        for item in self._items:
            if item.id == mem_id:
                return {
                    "id": item.id,
                    "type": item.type,
                    "tags": item.tags,
                    "timestamp": item.timestamp,
                    "trace": item.trace,
                    "cluster_id": item.cluster_id,
                }
        return None

    def bind_cluster(self, ids: List[int]) -> int:
        self._load_file()
        existing_ids = {i.cluster_id for i in self._items if i.cluster_id is not None}
        cluster_id = (max(existing_ids) + 1) if existing_ids else 1
        id_set = set(ids)
        for item in self._items:
            if item.id in id_set:
                item.cluster_id = cluster_id
        self._save_file()
        return cluster_id

    # ---------- Snapshot integration ----------

    def export_state(self) -> Dict[str, Any]:
        self._load_file()
        return {
            "next_id": self._next_id,
            "items": [asdict(i) for i in self._items],
        }

    def import_state(self, state: Dict[str, Any]) -> None:
        self._items = []
        self._next_id = int(state.get("next_id", 1))
        for item in state.get("items", []):
            try:
                self._items.append(
                    MemoryItem(
                        id=int(item["id"]),
                        type=item["type"],
                        tags=list(item.get("tags", [])),
                        payload=item.get("payload", ""),
                        timestamp=item.get("timestamp", ""),
                        trace=item.get("trace", {}) or {},
                        cluster_id=item.get("cluster_id"),
                    )
                )
            except Exception:
                continue
        self._loaded = True
        self._save_file()
