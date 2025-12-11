# kernel/nova_wm_episodic.py
"""
NovaOS v0.7.3 — Episodic Memory Bridge (Option B)

Bridges Working Memory to long-term episodic storage via MemoryManager.
Enables selective persistence and rehydration of conversation state.

Key Capabilities:
- Snapshot: Save WM state as episodic memory
- Restore: Rehydrate WM from saved episodic memory
- Auto-attach: Load relevant episodics when entering modules
- Relevance Engine: Determine which episodics to load

This module sits ABOVE NovaWM and Behavior Layer.
It does NOT modify their internal logic.

Usage:
    from nova_wm_episodic import (
        episodic_snapshot,
        episodic_restore,
        episodic_list,
        episodic_rehydrate_for_module,
    )
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Set, Tuple
from datetime import datetime, timedelta
from enum import Enum
import json
import re


# =============================================================================
# CONFIGURATION
# =============================================================================

# Global toggle - can be disabled without breaking WM/Behavior
EPISODIC_ENABLED: bool = True

# Relevance engine settings
MAX_EPISODIC_AGE_DAYS: int = 30
MAX_EPISODICS_PER_QUERY: int = 5
MIN_RELEVANCE_SCORE: float = 0.3

# Auto-rehydration settings
AUTO_REHYDRATE_ON_MODULE: bool = True


# =============================================================================
# DATA STRUCTURES
# =============================================================================

class RehydrationMode(Enum):
    """How to handle episodic restoration."""
    FULL = "full"          # Replace current WM state entirely
    MERGE = "merge"        # Merge with current WM state
    CONTEXT_ONLY = "context_only"  # Just add to context, don't modify WM


@dataclass
class EpisodicSnapshot:
    """
    A snapshot of WM/Behavior state for episodic storage.
    """
    id: str = ""
    topic: str = ""
    participants: List[str] = field(default_factory=list)
    goals: List[Dict[str, Any]] = field(default_factory=list)
    unresolved_questions: List[str] = field(default_factory=list)
    tone: str = "neutral"
    summary: str = ""
    turn_summaries: List[str] = field(default_factory=list)
    entities: List[Dict[str, Any]] = field(default_factory=list)
    pronoun_map: Dict[str, str] = field(default_factory=dict)
    module: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    timestamp: str = ""
    session_id: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize for storage."""
        return {
            "id": self.id,
            "topic": self.topic,
            "participants": self.participants,
            "goals": self.goals,
            "unresolved_questions": self.unresolved_questions,
            "tone": self.tone,
            "summary": self.summary,
            "turn_summaries": self.turn_summaries,
            "entities": self.entities,
            "pronoun_map": self.pronoun_map,
            "module": self.module,
            "tags": self.tags,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EpisodicSnapshot":
        """Deserialize from storage."""
        return cls(
            id=data.get("id", ""),
            topic=data.get("topic", ""),
            participants=data.get("participants", []),
            goals=data.get("goals", []),
            unresolved_questions=data.get("unresolved_questions", []),
            tone=data.get("tone", "neutral"),
            summary=data.get("summary", ""),
            turn_summaries=data.get("turn_summaries", []),
            entities=data.get("entities", []),
            pronoun_map=data.get("pronoun_map", {}),
            module=data.get("module"),
            tags=data.get("tags", []),
            timestamp=data.get("timestamp", ""),
            session_id=data.get("session_id", ""),
        )
    
    def to_payload_string(self) -> str:
        """Convert to human-readable payload for MemoryManager."""
        lines = [
            f"[EPISODIC SNAPSHOT: {self.topic or 'Untitled'}]",
            f"Timestamp: {self.timestamp}",
        ]
        
        if self.participants:
            lines.append(f"Participants: {', '.join(self.participants)}")
        
        if self.goals:
            goal_strs = [g.get("description", str(g)) for g in self.goals[:3]]
            lines.append(f"Goals: {'; '.join(goal_strs)}")
        
        if self.unresolved_questions:
            lines.append(f"Unresolved: {'; '.join(self.unresolved_questions[:3])}")
        
        if self.tone and self.tone != "neutral":
            lines.append(f"Tone: {self.tone}")
        
        if self.summary:
            lines.append(f"Summary: {self.summary}")
        
        if self.turn_summaries:
            lines.append("Recent turns:")
            for ts in self.turn_summaries[-3:]:
                # PATCHED v0.11.0-fix5: Increased from 100 to 300 chars for payload display
                lines.append(f"  - {ts[:300]}")
        
        return "\n".join(lines)


@dataclass
class RelevanceResult:
    """Result of relevance scoring."""
    memory_id: int
    snapshot: EpisodicSnapshot
    score: float
    match_reasons: List[str] = field(default_factory=list)


# =============================================================================
# EPISODIC INDEX (Per-Session)
# =============================================================================

class EpisodicIndex:
    """
    Per-session index of episodic snapshots.
    Tracks what's been saved and restored for conflict detection.
    """
    
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.saved_snapshots: Dict[str, str] = {}  # topic -> memory_id
        self.restored_from: Optional[str] = None   # memory_id if restored
        self.rehydrated_modules: Set[str] = set()  # modules already rehydrated
        self.context_rehydrated: bool = False
    
    def mark_saved(self, topic: str, memory_id: str) -> None:
        """Record that a snapshot was saved."""
        self.saved_snapshots[topic] = memory_id
    
    def mark_restored(self, memory_id: str) -> None:
        """Record that WM was restored from an episodic."""
        self.restored_from = memory_id
    
    def mark_module_rehydrated(self, module: str) -> None:
        """Record that a module context was rehydrated."""
        self.rehydrated_modules.add(module)
        self.context_rehydrated = True
    
    def was_module_rehydrated(self, module: str) -> bool:
        """Check if module was already rehydrated this session."""
        return module in self.rehydrated_modules
    
    def clear(self) -> None:
        """Clear index (on session reset)."""
        self.saved_snapshots.clear()
        self.restored_from = None
        self.rehydrated_modules.clear()
        self.context_rehydrated = False


# Global index store
_episodic_indices: Dict[str, EpisodicIndex] = {}


def get_episodic_index(session_id: str) -> EpisodicIndex:
    """Get or create episodic index for session."""
    if session_id not in _episodic_indices:
        _episodic_indices[session_id] = EpisodicIndex(session_id)
    return _episodic_indices[session_id]


def clear_episodic_index(session_id: str) -> None:
    """Clear episodic index for session."""
    if session_id in _episodic_indices:
        _episodic_indices[session_id].clear()


# =============================================================================
# SNAPSHOT CREATION
# =============================================================================

def create_snapshot_from_wm(
    session_id: str,
    wm,  # NovaWorkingMemory instance
    behavior_engine=None,  # WMBehaviorEngine instance
    topic_override: Optional[str] = None,
    module: Optional[str] = None,
    extra_tags: Optional[List[str]] = None,
) -> EpisodicSnapshot:
    """
    Create an EpisodicSnapshot from current WM and Behavior state.
    
    Args:
        session_id: Session identifier
        wm: NovaWorkingMemory instance
        behavior_engine: Optional WMBehaviorEngine instance
        topic_override: Optional topic name override
        module: Optional module tag
        extra_tags: Additional tags to include
    
    Returns:
        EpisodicSnapshot ready for storage
    """
    snapshot = EpisodicSnapshot()
    snapshot.session_id = session_id
    snapshot.timestamp = datetime.now().isoformat()
    
    # Topic
    if topic_override:
        snapshot.topic = topic_override
    elif wm.active_topic_id and wm.active_topic_id in wm.topics:
        snapshot.topic = wm.topics[wm.active_topic_id].name
    else:
        snapshot.topic = "conversation snapshot"
    
    # Participants (people entities)
    from .nova_wm import EntityType, GenderHint
    for entity in wm.entities.values():
        if entity.entity_type == EntityType.PERSON:
            participant_info = entity.name
            if entity.gender_hint and entity.gender_hint != GenderHint.NEUTRAL:
                participant_info += f" ({entity.gender_hint.value})"
            snapshot.participants.append(participant_info)
    
    # All entities
    for entity in wm.entities.values():
        snapshot.entities.append({
            "id": entity.id,
            "name": entity.name,
            "type": entity.entity_type.value,
            "gender_hint": entity.gender_hint.value if entity.gender_hint else None,
            "description": entity.description,
        })
    
    # Pronoun map
    for pronoun, referent in wm.referents.items():
        if referent.entity_id in wm.entities:
            snapshot.pronoun_map[pronoun] = wm.entities[referent.entity_id].name
    
    # Tone
    snapshot.tone = wm.emotional_tone.value
    
    # Turn summaries
    # PATCHED v0.11.0-fix3: Use correct field names with fallbacks
    # PATCHED v0.11.0-fix5: Increased truncation from 100 to 500 chars for maximum context
    # Fields: user_message/nova_message (full text) or user_summary/nova_summary (truncated)
    for turn in wm.turn_history[-5:]:
        # Try full message first, fall back to summary
        user_text = getattr(turn, 'user_message', None) or getattr(turn, 'user_summary', None)
        nova_text = getattr(turn, 'nova_message', None) or getattr(turn, 'nova_summary', None)
        
        if user_text:
            snapshot.turn_summaries.append(f"User: {user_text[:500]}")
        if nova_text:
            snapshot.turn_summaries.append(f"Nova: {nova_text[:500]}")
    
    # Behavior Layer data (if available)
    if behavior_engine:
        # Goals
        for goal_id, goal in behavior_engine.goals.items():
            snapshot.goals.append({
                "id": goal_id,
                "type": goal.goal_type.value if hasattr(goal.goal_type, 'value') else str(goal.goal_type),
                "description": goal.description,
                "status": goal.status.value if hasattr(goal.status, 'value') else str(goal.status),
            })
        
        # Unresolved questions
        for q in behavior_engine.open_questions:
            if not q.answered:
                snapshot.unresolved_questions.append(q.text)
        
        # Thread summary
        if behavior_engine.thread_summary.topic:
            snapshot.summary = behavior_engine.summarize_thread()
    
    # Tags
    snapshot.tags = ["wm-snapshot"]
    if module:
        snapshot.module = module
        snapshot.tags.append(f"module:{module}")
    if snapshot.topic:
        # Sanitize topic for tag
        safe_topic = re.sub(r'[^a-zA-Z0-9_-]', '-', snapshot.topic)[:30]
        snapshot.tags.append(f"topic:{safe_topic}")
    if extra_tags:
        snapshot.tags.extend(extra_tags)
    
    return snapshot


# =============================================================================
# STORAGE FUNCTIONS
# =============================================================================

def episodic_snapshot(
    session_id: str,
    memory_manager,  # MemoryManager instance
    wm,  # NovaWorkingMemory instance
    behavior_engine=None,
    topic: Optional[str] = None,
    module: Optional[str] = None,
    extra_tags: Optional[List[str]] = None,
) -> Tuple[bool, str, Optional[int]]:
    """
    Save current WM/Behavior state as an episodic memory.
    
    Args:
        session_id: Session identifier
        memory_manager: MemoryManager instance for storage
        wm: NovaWorkingMemory instance
        behavior_engine: Optional WMBehaviorEngine instance
        topic: Optional topic name override
        module: Optional module tag
        extra_tags: Additional tags
    
    Returns:
        Tuple of (success, message, memory_id)
    """
    if not EPISODIC_ENABLED:
        return False, "Episodic memory is disabled.", None
    
    if memory_manager is None:
        return False, "MemoryManager not available.", None
    
    try:
        # Create snapshot
        snapshot = create_snapshot_from_wm(
            session_id, wm, behavior_engine, topic, module, extra_tags
        )
        
        # Store in MemoryManager
        payload = snapshot.to_payload_string()
        
        # Also store full JSON in trace for restore
        # PATCHED v0.11.0-fix4: Changed type= to mem_type=, metadata= to trace=
        memory_item = memory_manager.store(
            mem_type="episodic",
            payload=payload,
            tags=snapshot.tags,
            trace={
                "wm_snapshot": snapshot.to_dict(),
                "snapshot_version": "0.7.3",
            }
        )
        
        # PATCHED v0.11.0-fix5: Extract .id from MemoryItem object
        memory_id = memory_item.id if hasattr(memory_item, 'id') else memory_item
        
        # Update index
        index = get_episodic_index(session_id)
        index.mark_saved(snapshot.topic, str(memory_id))
        
        return True, f"Snapshot saved as episodic memory #{memory_id}.", memory_id
    
    except Exception as e:
        return False, f"Error saving snapshot: {e}", None


# =============================================================================
# RESTORE FUNCTIONS
# =============================================================================

def episodic_restore(
    session_id: str,
    memory_id: int,
    memory_manager,
    wm,
    behavior_engine=None,
    mode: RehydrationMode = RehydrationMode.MERGE,
    force: bool = False,
) -> Tuple[bool, str]:
    """
    Restore WM state from a saved episodic memory.
    
    Args:
        session_id: Session identifier
        memory_id: ID of episodic memory to restore
        memory_manager: MemoryManager instance
        wm: NovaWorkingMemory instance to restore into
        behavior_engine: Optional WMBehaviorEngine instance
        mode: How to handle restoration (FULL, MERGE, CONTEXT_ONLY)
        force: If True, skip conflict warnings
    
    Returns:
        Tuple of (success, message)
    """
    if not EPISODIC_ENABLED:
        return False, "Episodic memory is disabled."
    
    if memory_manager is None:
        return False, "MemoryManager not available."
    
    try:
        # Fetch memory
        memory = memory_manager.get(memory_id)
        if memory is None:
            return False, f"Memory #{memory_id} not found."
        
        # Check it's an episodic with WM snapshot
        # PATCHED v0.11.0-fix4: Use 'type' attribute and 'trace' for snapshot data
        if memory.get("type") != "episodic":
            return False, f"Memory #{memory_id} is not an episodic memory."
        
        # Snapshot data is stored in trace (was called metadata in original code)
        trace_data = memory.get("trace", {})
        snapshot_data = trace_data.get("wm_snapshot")
        
        if not snapshot_data:
            return False, f"Memory #{memory_id} does not contain a WM snapshot."
        
        snapshot = EpisodicSnapshot.from_dict(snapshot_data)
        
        # Check for conflicts (if not forcing)
        if not force and mode != RehydrationMode.CONTEXT_ONLY:
            if wm.turn_count > 0:
                # WM has existing state
                if wm.entities:
                    return False, (
                        f"WM already has {len(wm.entities)} entities. "
                        f"Use #wm-restore {memory_id} force=yes to overwrite, "
                        f"or #wm-clear first."
                    )
        
        # Perform restoration based on mode
        if mode == RehydrationMode.FULL:
            # Clear existing state
            wm.clear()
            if behavior_engine:
                behavior_engine.clear()
        
        if mode in (RehydrationMode.FULL, RehydrationMode.MERGE):
            # Restore entities
            _restore_entities(wm, snapshot)
            
            # Restore topic
            if snapshot.topic:
                wm.push_topic(snapshot.topic)
            
            # Restore tone
            from .nova_wm import EmotionalTone
            try:
                wm.emotional_tone = EmotionalTone(snapshot.tone)
            except ValueError:
                pass
            
            # Restore behavior state
            if behavior_engine and snapshot.goals:
                _restore_behavior(behavior_engine, snapshot)
        
        # Update index
        index = get_episodic_index(session_id)
        index.mark_restored(str(memory_id))
        
        entity_count = len(snapshot.entities)
        return True, f"Restored {entity_count} entities from snapshot '{snapshot.topic}'."
    
    except Exception as e:
        return False, f"Error restoring snapshot: {e}"


def _restore_entities(wm, snapshot: EpisodicSnapshot) -> None:
    """Restore entities from snapshot into WM."""
    from .nova_wm import WMEntity, EntityType, GenderHint, ReferentCandidate
    
    for entity_data in snapshot.entities:
        # Skip if entity already exists
        existing = wm._find_entity_by_name(entity_data.get("name", ""))
        if existing:
            continue
        
        # Create entity
        try:
            entity_type = EntityType(entity_data.get("type", "unknown"))
        except ValueError:
            entity_type = EntityType.UNKNOWN
        
        try:
            gender_hint = GenderHint(entity_data.get("gender_hint")) if entity_data.get("gender_hint") else GenderHint.NEUTRAL
        except ValueError:
            gender_hint = GenderHint.NEUTRAL
        
        entity = WMEntity(
            id=wm._gen_entity_id(),
            name=entity_data.get("name", "unknown"),
            entity_type=entity_type,
            gender_hint=gender_hint,
            description=entity_data.get("description", ""),
            first_mentioned=0,
            last_mentioned=wm.turn_count,
        )
        
        wm.entities[entity.id] = entity
        
        # Add to pronoun groups if person
        if entity_type == EntityType.PERSON:
            candidate = ReferentCandidate(
                entity_id=entity.id,
                entity_name=entity.name,
                score=1.0,
                last_mentioned=wm.turn_count,
                gender_match=True,
            )
            
            if gender_hint == GenderHint.MASCULINE:
                wm.pronoun_groups["masculine"].add_candidate(candidate)
            elif gender_hint == GenderHint.FEMININE:
                wm.pronoun_groups["feminine"].add_candidate(candidate)
            
            wm.pronoun_groups["neutral"].add_candidate(candidate)


def _restore_behavior(behavior_engine, snapshot: EpisodicSnapshot) -> None:
    """Restore behavior state from snapshot."""
    # Restore thread summary
    if snapshot.topic:
        behavior_engine.thread_summary.topic = snapshot.topic
    if snapshot.participants:
        behavior_engine.thread_summary.participants = [
            p.split(" (")[0] for p in snapshot.participants  # Remove gender suffix
        ]
    if snapshot.unresolved_questions:
        behavior_engine.thread_summary.unresolved_questions = snapshot.unresolved_questions


# =============================================================================
# RELEVANCE ENGINE
# =============================================================================

def find_relevant_episodics(
    memory_manager,
    topic: Optional[str] = None,
    participants: Optional[List[str]] = None,
    module: Optional[str] = None,
    max_results: int = MAX_EPISODICS_PER_QUERY,
) -> List[RelevanceResult]:
    """
    Find relevant episodic memories based on criteria.
    
    Args:
        memory_manager: MemoryManager instance
        topic: Topic to match
        participants: List of participant names to match
        module: Module tag to match
        max_results: Maximum results to return
    
    Returns:
        List of RelevanceResult sorted by score
    """
    if not EPISODIC_ENABLED:
        return []
    
    if memory_manager is None:
        return []
    
    results = []
    cutoff_date = datetime.now() - timedelta(days=MAX_EPISODIC_AGE_DAYS)
    
    try:
        # Query all episodic memories with wm-snapshot tag
        # PATCHED v0.11.0-fix4: Changed type= to mem_type=, access .trace attribute
        memories = memory_manager.recall(mem_type="episodic", tags=["wm-snapshot"])
        
        for memory in memories:
            # recall() returns MemoryItem dataclass, use .trace attribute
            trace_data = getattr(memory, 'trace', {}) or {}
            snapshot_data = trace_data.get("wm_snapshot")
            
            if not snapshot_data:
                continue
            
            snapshot = EpisodicSnapshot.from_dict(snapshot_data)
            
            # Check age
            try:
                snap_time = datetime.fromisoformat(snapshot.timestamp)
                if snap_time < cutoff_date:
                    continue
            except:
                pass
            
            # Calculate relevance score
            score, reasons = _calculate_relevance(
                snapshot, topic, participants, module
            )
            
            if score >= MIN_RELEVANCE_SCORE:
                results.append(RelevanceResult(
                    memory_id=memory.get("id", 0),
                    snapshot=snapshot,
                    score=score,
                    match_reasons=reasons,
                ))
    
    except Exception:
        pass
    
    # Sort by score descending
    results.sort(key=lambda r: r.score, reverse=True)
    return results[:max_results]


def _calculate_relevance(
    snapshot: EpisodicSnapshot,
    topic: Optional[str],
    participants: Optional[List[str]],
    module: Optional[str],
) -> Tuple[float, List[str]]:
    """Calculate relevance score for a snapshot."""
    score = 0.0
    reasons = []
    
    # Module match (high priority)
    if module and snapshot.module == module:
        score += 0.5
        reasons.append(f"module:{module}")
    
    # Topic similarity
    if topic and snapshot.topic:
        topic_lower = topic.lower()
        snap_topic_lower = snapshot.topic.lower()
        
        if topic_lower == snap_topic_lower:
            score += 0.4
            reasons.append("exact topic match")
        elif topic_lower in snap_topic_lower or snap_topic_lower in topic_lower:
            score += 0.25
            reasons.append("partial topic match")
    
    # Participant overlap
    if participants and snapshot.participants:
        participant_names = set(p.lower() for p in participants)
        snap_participants = set(
            p.split(" (")[0].lower() for p in snapshot.participants
        )
        
        overlap = participant_names & snap_participants
        if overlap:
            score += 0.15 * len(overlap)
            reasons.append(f"participants: {', '.join(overlap)}")
    
    return score, reasons


# =============================================================================
# MODULE REHYDRATION
# =============================================================================

def episodic_rehydrate_for_module(
    session_id: str,
    module: str,
    memory_manager,
    wm,
    behavior_engine=None,
) -> Tuple[bool, str]:
    """
    Auto-rehydrate WM with relevant episodic memory for a module.
    
    Called when entering a module like #cyber, #business, etc.
    
    Args:
        session_id: Session identifier
        module: Module being entered
        memory_manager: MemoryManager instance
        wm: NovaWorkingMemory instance
        behavior_engine: Optional WMBehaviorEngine instance
    
    Returns:
        Tuple of (rehydrated, message)
    """
    if not EPISODIC_ENABLED or not AUTO_REHYDRATE_ON_MODULE:
        return False, ""
    
    # Check if already rehydrated for this module
    index = get_episodic_index(session_id)
    if index.was_module_rehydrated(module):
        return False, "Already rehydrated for this module."
    
    # Find relevant episodics
    relevant = find_relevant_episodics(
        memory_manager,
        module=module,
        max_results=1,
    )
    
    if not relevant:
        return False, "No relevant episodic memories found."
    
    best = relevant[0]
    
    # Restore with CONTEXT_ONLY mode (don't overwrite existing state)
    success, msg = episodic_restore(
        session_id=session_id,
        memory_id=best.memory_id,
        memory_manager=memory_manager,
        wm=wm,
        behavior_engine=behavior_engine,
        mode=RehydrationMode.MERGE if wm.turn_count == 0 else RehydrationMode.CONTEXT_ONLY,
    )
    
    if success:
        index.mark_module_rehydrated(module)
        return True, f"Loaded context from '{best.snapshot.topic}' (memory #{best.memory_id})."
    
    return False, msg


# =============================================================================
# LIST & DEBUG
# =============================================================================

def episodic_list(
    memory_manager,
    module: Optional[str] = None,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """
    List recent episodic snapshots.
    
    Args:
        memory_manager: MemoryManager instance
        module: Optional module filter
        limit: Max results
    
    Returns:
        List of snapshot summaries
    """
    if not EPISODIC_ENABLED or memory_manager is None:
        return []
    
    results = []
    
    try:
        tags = ["wm-snapshot"]
        if module:
            tags.append(f"module:{module}")
        
        # PATCHED v0.11.0-fix4: Changed type= to mem_type=, access .trace attribute
        memories = memory_manager.recall(mem_type="episodic", tags=tags)
        
        for memory in memories[:limit]:
            # recall() returns MemoryItem dataclass, use attributes not .get()
            trace_data = getattr(memory, 'trace', {}) or {}
            snapshot_data = trace_data.get("wm_snapshot", {})
            
            results.append({
                "id": getattr(memory, 'id', None),
                "topic": snapshot_data.get("topic", "Unknown"),
                "participants": snapshot_data.get("participants", []),
                "module": snapshot_data.get("module"),
                "timestamp": snapshot_data.get("timestamp", ""),
                "tags": getattr(memory, 'tags', []),
            })
    
    except Exception:
        pass
    
    return results


def episodic_debug(session_id: str) -> Dict[str, Any]:
    """
    Get episodic debug info for a session.
    
    Returns:
        Dict with index state and config
    """
    index = get_episodic_index(session_id)
    
    return {
        "enabled": EPISODIC_ENABLED,
        "auto_rehydrate": AUTO_REHYDRATE_ON_MODULE,
        "max_age_days": MAX_EPISODIC_AGE_DAYS,
        "session_id": session_id,
        "saved_snapshots": dict(index.saved_snapshots),
        "restored_from": index.restored_from,
        "rehydrated_modules": list(index.rehydrated_modules),
        "context_rehydrated": index.context_rehydrated,
    }


# =============================================================================
# PUBLIC API
# =============================================================================

def set_episodic_enabled(enabled: bool) -> None:
    """Enable or disable episodic memory."""
    global EPISODIC_ENABLED
    EPISODIC_ENABLED = enabled


def is_episodic_enabled() -> bool:
    """Check if episodic memory is enabled."""
    return EPISODIC_ENABLED


def set_auto_rehydrate(enabled: bool) -> None:
    """Enable or disable auto-rehydration on module entry."""
    global AUTO_REHYDRATE_ON_MODULE
    AUTO_REHYDRATE_ON_MODULE = enabled


# =============================================================================
# CLEANUP
# =============================================================================

def episodic_clear(session_id: str) -> None:
    """Clear episodic index for session (on reset)."""
    clear_episodic_index(session_id)


def episodic_delete(session_id: str) -> None:
    """Delete episodic index for session."""
    _episodic_indices.pop(session_id, None)
