# kernel/inbox_manager.py
"""
v0.8.0 — Inbox Manager for NovaOS Life RPG

The Inbox is a quick-capture layer for thoughts, ideas, and tasks.
Items in the inbox can later be:
- Converted to quests
- Converted to reminders
- Tagged and organized
- Archived or deleted

This implements the "capture everything, process later" workflow
from GTD (Getting Things Done).

Data stored in data/inbox.json
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


# =============================================================================
# INBOX ITEM MODEL
# =============================================================================

@dataclass
class InboxItem:
    """
    A single item in the inbox.
    
    Attributes:
        id: Unique identifier
        content: The captured text/thought
        tags: Optional tags for organization
        source: Where this came from (manual, voice, auto)
        priority: Optional priority (1=high, 2=medium, 3=low)
        created_at: When captured
        processed: Whether this has been processed (converted/archived)
        processed_at: When processed
        processed_to: What it was converted to (quest, reminder, etc.)
    """
    id: str
    content: str
    tags: List[str] = field(default_factory=list)
    source: str = "manual"
    priority: Optional[int] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    processed: bool = False
    processed_at: Optional[str] = None
    processed_to: Optional[str] = None  # "quest:id", "reminder:id", "archived"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "tags": self.tags,
            "source": self.source,
            "priority": self.priority,
            "created_at": self.created_at,
            "processed": self.processed,
            "processed_at": self.processed_at,
            "processed_to": self.processed_to,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InboxItem":
        return cls(
            id=data.get("id", str(uuid.uuid4())[:8]),
            content=data.get("content", ""),
            tags=data.get("tags", []),
            source=data.get("source", "manual"),
            priority=data.get("priority"),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            processed=data.get("processed", False),
            processed_at=data.get("processed_at"),
            processed_to=data.get("processed_to"),
        )
    
    @property
    def priority_icon(self) -> str:
        """Get priority indicator."""
        if self.priority == 1:
            return "🔴"
        elif self.priority == 2:
            return "🟡"
        elif self.priority == 3:
            return "🟢"
        return "⚪"
    
    @property
    def age_str(self) -> str:
        """Get human-readable age."""
        try:
            created = datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            delta = now - created
            
            if delta.days > 0:
                return f"{delta.days}d ago"
            elif delta.seconds >= 3600:
                return f"{delta.seconds // 3600}h ago"
            elif delta.seconds >= 60:
                return f"{delta.seconds // 60}m ago"
            else:
                return "just now"
        except:
            return ""


# =============================================================================
# INBOX STORE
# =============================================================================

class InboxStore:
    """
    Manages inbox items.
    
    Data stored in data/inbox.json:
    {
        "items": [
            {"id": "abc123", "content": "...", ...}
        ]
    }
    """
    
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.inbox_file = self.data_dir / "inbox.json"
        self._items: Dict[str, InboxItem] = {}
        self._load()
    
    def _load(self) -> None:
        """Load inbox from disk."""
        if not self.inbox_file.exists():
            self._items = {}
            self._save()
            return
        
        try:
            with open(self.inbox_file) as f:
                raw = json.load(f)
        except (json.JSONDecodeError, IOError):
            self._items = {}
            self._save()
            return
        
        items_list = raw.get("items", [])
        for item_data in items_list:
            if isinstance(item_data, dict):
                item = InboxItem.from_dict(item_data)
                self._items[item.id] = item
    
    def _save(self) -> None:
        """Save inbox to disk."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        data = {
            "items": [item.to_dict() for item in self._items.values()]
        }
        
        with open(self.inbox_file, "w") as f:
            json.dump(data, f, indent=2)
    
    # -------------------------------------------------------------------------
    # CRUD Operations
    # -------------------------------------------------------------------------
    
    def capture(
        self,
        content: str,
        tags: Optional[List[str]] = None,
        source: str = "manual",
        priority: Optional[int] = None,
    ) -> InboxItem:
        """Capture a new item to the inbox."""
        item = InboxItem(
            id=str(uuid.uuid4())[:8],
            content=content,
            tags=tags or [],
            source=source,
            priority=priority,
        )
        self._items[item.id] = item
        self._save()
        return item
    
    def get(self, item_id: str) -> Optional[InboxItem]:
        """Get an item by ID."""
        return self._items.get(item_id)
    
    def list_unprocessed(self) -> List[InboxItem]:
        """Get all unprocessed items, newest first."""
        items = [i for i in self._items.values() if not i.processed]
        items.sort(key=lambda x: x.created_at, reverse=True)
        return items
    
    def list_all(self) -> List[InboxItem]:
        """Get all items, newest first."""
        items = list(self._items.values())
        items.sort(key=lambda x: x.created_at, reverse=True)
        return items
    
    def count_unprocessed(self) -> int:
        """Count unprocessed items."""
        return sum(1 for i in self._items.values() if not i.processed)
    
    def update(self, item_id: str, **kwargs) -> Optional[InboxItem]:
        """Update an item's properties."""
        item = self._items.get(item_id)
        if not item:
            return None
        
        if "content" in kwargs:
            item.content = kwargs["content"]
        if "tags" in kwargs:
            item.tags = kwargs["tags"]
        if "priority" in kwargs:
            item.priority = kwargs["priority"]
        
        self._save()
        return item
    
    def mark_processed(
        self,
        item_id: str,
        processed_to: str,
    ) -> Optional[InboxItem]:
        """Mark an item as processed."""
        item = self._items.get(item_id)
        if not item:
            return None
        
        item.processed = True
        item.processed_at = datetime.now(timezone.utc).isoformat()
        item.processed_to = processed_to
        self._save()
        return item
    
    def delete(self, item_id: str) -> bool:
        """Delete an item. Returns True if deleted."""
        if item_id not in self._items:
            return False
        
        del self._items[item_id]
        self._save()
        return True
    
    def clear_processed(self) -> int:
        """Remove all processed items. Returns count deleted."""
        to_delete = [i.id for i in self._items.values() if i.processed]
        for item_id in to_delete:
            del self._items[item_id]
        self._save()
        return len(to_delete)
