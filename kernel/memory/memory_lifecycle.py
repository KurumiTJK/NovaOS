# kernel/memory_lifecycle.py
"""
v0.5.6 — Drift, Decay & Re-Confirmation

Memory lifecycle management with:
- Decay scoring: reduce salience over time for unused memories
- Drift detection: identify stale or potentially outdated memories
- Re-confirmation: flag identity-critical memories for user verification
- Status transitions: active → stale → archived

Decay Rates (days until salience halves):
- Episodic: 30 days (fastest decay — events fade)
- Semantic: 90 days (medium — facts need refresh)
- Procedural: 180 days (slowest — skills persist)

Core Principle: Memory Integrity
- Stale memories don't disappear, they get flagged
- User controls what gets archived or re-confirmed
- High-salience memories decay slower
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Literal, TYPE_CHECKING

if TYPE_CHECKING:
    from .memory_engine import MemoryEngine, MemoryItem, MemoryType, MemoryStatus


# -----------------------------------------------------------------------------
# Decay Configuration
# -----------------------------------------------------------------------------

@dataclass
class DecayConfig:
    """
    Configuration for memory decay behavior.
    
    half_life_days: Days until salience halves (per memory type)
    stale_threshold: Salience below which memory becomes "stale"
    archive_threshold: Salience below which memory becomes "archived"
    min_salience: Floor for salience (never decays below this)
    high_salience_protection: Memories above this decay 50% slower
    """
    half_life_days: Dict[str, float] = field(default_factory=lambda: {
        "episodic": 30.0,      # Events fade fastest
        "semantic": 90.0,      # Facts need periodic refresh
        "procedural": 180.0,   # Skills persist longest
    })
    
    stale_threshold: float = 0.2       # Below this → stale
    archive_threshold: float = 0.05    # Below this → archived
    min_salience: float = 0.01         # Floor
    high_salience_protection: float = 0.8  # Above this → slower decay
    
    # Re-confirmation settings
    reconfirm_after_days: int = 60     # Days without use before flagging
    identity_reconfirm_days: int = 30  # Stricter for identity-tagged


# -----------------------------------------------------------------------------
# Drift Detection
# -----------------------------------------------------------------------------

@dataclass
class DriftReport:
    """
    Report of potential memory drift/staleness.
    """
    memory_id: int
    memory_type: str
    payload_preview: str
    current_salience: float
    days_since_use: int
    drift_reason: str
    recommended_action: Literal["reconfirm", "archive", "review", "keep"]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "memory_type": self.memory_type,
            "payload_preview": self.payload_preview,
            "current_salience": self.current_salience,
            "days_since_use": self.days_since_use,
            "drift_reason": self.drift_reason,
            "recommended_action": self.recommended_action,
        }


# -----------------------------------------------------------------------------
# Re-Confirmation Queue
# -----------------------------------------------------------------------------

@dataclass
class ReconfirmationItem:
    """
    A memory flagged for re-confirmation.
    """
    memory_id: int
    memory_type: str
    payload_preview: str
    original_salience: float
    flagged_at: str
    reason: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "memory_type": self.memory_type,
            "payload_preview": self.payload_preview,
            "original_salience": self.original_salience,
            "flagged_at": self.flagged_at,
            "reason": self.reason,
        }


# -----------------------------------------------------------------------------
# Memory Lifecycle Manager
# -----------------------------------------------------------------------------

class MemoryLifecycle:
    """
    v0.5.6 Memory Lifecycle Manager
    
    Manages:
    - Decay: Reduce salience over time based on usage
    - Drift: Detect potentially stale memories
    - Re-confirmation: Flag important memories for user review
    - Status transitions: active → stale → archived
    
    Does NOT automatically delete memories — only flags and transitions.
    User always has final control.
    """

    def __init__(self, config: Optional[DecayConfig] = None):
        self.config = config or DecayConfig()
        self._reconfirm_queue: List[ReconfirmationItem] = []

    # ---------- Decay Calculation ----------

    def calculate_decay(
        self,
        memory_type: str,
        original_salience: float,
        last_used_at: Optional[str],
        created_at: str,
    ) -> float:
        """
        Calculate decayed salience for a memory.
        
        Uses exponential decay: S(t) = S₀ * (0.5)^(t/half_life)
        
        Args:
            memory_type: semantic, procedural, or episodic
            original_salience: Starting salience value
            last_used_at: ISO timestamp of last access (or None)
            created_at: ISO timestamp of creation
            
        Returns:
            New salience value after decay
        """
        # Get half-life for this type
        half_life = self.config.half_life_days.get(memory_type, 90.0)
        
        # High-salience memories decay slower
        if original_salience >= self.config.high_salience_protection:
            half_life *= 1.5  # 50% slower decay
        
        # Calculate days since last use
        now = datetime.now(timezone.utc)
        
        if last_used_at:
            try:
                last_used = datetime.fromisoformat(last_used_at.replace("Z", "+00:00"))
            except ValueError:
                last_used = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        else:
            try:
                last_used = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            except ValueError:
                last_used = now - timedelta(days=30)  # Default assumption
        
        days_elapsed = (now - last_used).total_seconds() / 86400.0
        
        if days_elapsed <= 0:
            return original_salience
        
        # Exponential decay: S(t) = S₀ * (0.5)^(t/half_life)
        decay_factor = math.pow(0.5, days_elapsed / half_life)
        new_salience = original_salience * decay_factor
        
        # Apply floor
        return max(new_salience, self.config.min_salience)

    def get_recommended_status(self, salience: float) -> str:
        """
        Get recommended status based on salience level.
        """
        if salience <= self.config.archive_threshold:
            return "archived"
        elif salience <= self.config.stale_threshold:
            return "stale"
        else:
            return "active"

    # ---------- Drift Detection ----------

    def detect_drift(
        self,
        memory_id: int,
        memory_type: str,
        payload: str,
        salience: float,
        last_used_at: Optional[str],
        created_at: str,
        tags: List[str],
        module_tag: Optional[str] = None,
    ) -> Optional[DriftReport]:
        """
        Detect if a memory has drifted (become stale or needs attention).
        
        Returns DriftReport if drift detected, None otherwise.
        """
        now = datetime.now(timezone.utc)
        
        # Calculate days since use
        if last_used_at:
            try:
                last_used = datetime.fromisoformat(last_used_at.replace("Z", "+00:00"))
                days_since_use = int((now - last_used).total_seconds() / 86400)
            except ValueError:
                days_since_use = 999
        else:
            try:
                created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                days_since_use = int((now - created).total_seconds() / 86400)
            except ValueError:
                days_since_use = 999
        
        # Check for drift conditions
        drift_reason = None
        recommended_action = "keep"
        
        # 1. Low salience
        if salience <= self.config.archive_threshold:
            drift_reason = f"Very low salience ({salience:.3f}) — memory has decayed significantly"
            recommended_action = "archive"
        
        elif salience <= self.config.stale_threshold:
            drift_reason = f"Low salience ({salience:.3f}) — memory becoming stale"
            recommended_action = "review"
        
        # 2. Long time without use
        elif days_since_use >= self.config.reconfirm_after_days:
            # Check if identity-related (stricter threshold)
            is_identity = "identity" in tags or module_tag == "identity"
            threshold = self.config.identity_reconfirm_days if is_identity else self.config.reconfirm_after_days
            
            if days_since_use >= threshold:
                drift_reason = f"Not accessed in {days_since_use} days"
                recommended_action = "reconfirm" if is_identity else "review"
        
        # 3. Procedural memories with very old timestamps (skills may need refresh)
        elif memory_type == "procedural" and days_since_use >= 180:
            drift_reason = f"Procedural memory not practiced in {days_since_use} days"
            recommended_action = "reconfirm"
        
        if drift_reason:
            return DriftReport(
                memory_id=memory_id,
                memory_type=memory_type,
                payload_preview=payload[:80] + "..." if len(payload) > 80 else payload,
                current_salience=salience,
                days_since_use=days_since_use,
                drift_reason=drift_reason,
                recommended_action=recommended_action,
            )
        
        return None

    # ---------- Batch Processing ----------

    def process_memories(
        self,
        memories: List[Dict[str, Any]],
        apply_decay: bool = True,
        detect_drift: bool = True,
    ) -> Dict[str, Any]:
        """
        Process a batch of memories for decay and drift.
        
        Args:
            memories: List of memory dicts with id, type, salience, last_used_at, etc.
            apply_decay: Whether to calculate new salience values
            detect_drift: Whether to detect drift issues
            
        Returns:
            {
                "decay_updates": [{"id": X, "new_salience": Y, "new_status": Z}, ...],
                "drift_reports": [DriftReport, ...],
                "reconfirm_queue": [ReconfirmationItem, ...],
                "summary": {...}
            }
        """
        decay_updates = []
        drift_reports = []
        reconfirm_items = []
        
        for mem in memories:
            mem_id = mem.get("id", 0)
            mem_type = mem.get("type", "semantic")
            salience = float(mem.get("salience", 0.5))
            last_used_at = mem.get("last_used_at")
            created_at = mem.get("timestamp", "")
            payload = mem.get("payload", "")
            tags = mem.get("tags", [])
            module_tag = mem.get("module_tag")
            status = mem.get("status", "active")
            
            # Skip already archived
            if status == "archived":
                continue
            
            # Calculate decay
            if apply_decay:
                new_salience = self.calculate_decay(
                    memory_type=mem_type,
                    original_salience=salience,
                    last_used_at=last_used_at,
                    created_at=created_at,
                )
                
                new_status = self.get_recommended_status(new_salience)
                
                # Only report if changed significantly
                if abs(new_salience - salience) > 0.01 or new_status != status:
                    decay_updates.append({
                        "id": mem_id,
                        "old_salience": salience,
                        "new_salience": round(new_salience, 4),
                        "old_status": status,
                        "new_status": new_status,
                    })
                
                # Use new values for drift detection
                salience = new_salience
            
            # Detect drift
            if detect_drift:
                drift = self.detect_drift(
                    memory_id=mem_id,
                    memory_type=mem_type,
                    payload=payload,
                    salience=salience,
                    last_used_at=last_used_at,
                    created_at=created_at,
                    tags=tags,
                    module_tag=module_tag,
                )
                
                if drift:
                    drift_reports.append(drift)
                    
                    # Add to reconfirm queue if needed
                    if drift.recommended_action == "reconfirm":
                        reconfirm_items.append(ReconfirmationItem(
                            memory_id=mem_id,
                            memory_type=mem_type,
                            payload_preview=drift.payload_preview,
                            original_salience=salience,
                            flagged_at=datetime.now(timezone.utc).isoformat(),
                            reason=drift.drift_reason,
                        ))
        
        # Update internal queue
        self._reconfirm_queue.extend(reconfirm_items)
        
        return {
            "decay_updates": decay_updates,
            "drift_reports": [d.to_dict() for d in drift_reports],
            "reconfirm_queue": [r.to_dict() for r in reconfirm_items],
            "summary": {
                "processed": len(memories),
                "decay_changes": len(decay_updates),
                "drift_detected": len(drift_reports),
                "needs_reconfirm": len(reconfirm_items),
            },
        }

    # ---------- Re-Confirmation Queue ----------

    def get_reconfirm_queue(self, limit: int = 20) -> List[ReconfirmationItem]:
        """Get items needing re-confirmation."""
        return self._reconfirm_queue[:limit]

    def clear_reconfirm_item(self, memory_id: int) -> bool:
        """Remove an item from the re-confirmation queue."""
        original_len = len(self._reconfirm_queue)
        self._reconfirm_queue = [
            item for item in self._reconfirm_queue
            if item.memory_id != memory_id
        ]
        return len(self._reconfirm_queue) < original_len

    def clear_reconfirm_queue(self) -> int:
        """Clear the entire re-confirmation queue."""
        count = len(self._reconfirm_queue)
        self._reconfirm_queue = []
        return count

    # ---------- Utilities ----------

    def estimate_decay_preview(
        self,
        memory_type: str,
        current_salience: float,
        days_ahead: int = 30,
    ) -> List[Dict[str, Any]]:
        """
        Preview how a memory's salience will decay over time.
        
        Returns list of {day, salience, status} predictions.
        """
        predictions = []
        half_life = self.config.half_life_days.get(memory_type, 90.0)
        
        for day in [0, 7, 14, 30, 60, 90, 180]:
            if day > days_ahead:
                break
            
            decay_factor = math.pow(0.5, day / half_life)
            future_salience = max(current_salience * decay_factor, self.config.min_salience)
            future_status = self.get_recommended_status(future_salience)
            
            predictions.append({
                "day": day,
                "salience": round(future_salience, 4),
                "status": future_status,
            })
        
        return predictions

    def get_config_summary(self) -> Dict[str, Any]:
        """Get current decay configuration."""
        return {
            "half_life_days": self.config.half_life_days,
            "stale_threshold": self.config.stale_threshold,
            "archive_threshold": self.config.archive_threshold,
            "min_salience": self.config.min_salience,
            "high_salience_protection": self.config.high_salience_protection,
            "reconfirm_after_days": self.config.reconfirm_after_days,
            "identity_reconfirm_days": self.config.identity_reconfirm_days,
        }
