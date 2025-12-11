# kernel/memory_helpers.py
"""
NovaOS v0.11.0 — Memory Helpers Module

ChatGPT-style memory features:
- Profile memory auto-extraction (identity + preferences)
- Natural-language "remember this" flow
- LTM context injection for persona prompts
- Keyword-based retrieval
- Memory decay/archiving
- Quest completion episodic memories

All functions are designed to be safe — they swallow exceptions and log errors
rather than crashing the system.
"""

from __future__ import annotations

import re
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from kernel.memory_manager import MemoryManager
    from kernel.nova_wm import NovaWorkingMemory

# Logger for memory operations
logger = logging.getLogger("nova.memory")


# =============================================================================
# PHASE 1: PROFILE MEMORY AUTO-EXTRACTION
# =============================================================================

# Identity patterns — stored as profile:identity
# PATCHED v0.11.0-fix2: Changed regex to stop at period or end-of-string only (not comma)
IDENTITY_PATTERNS = [
    (r"\bmy name is\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", "name"),
    (r"\bi(?:'m| am)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b", "name"),
    (r"\bi work at\s+(.+?)(?:\.|$)", "employer"),
    (r"\bi(?:'m| am) (?:a|an)\s+(.+?)\s+at\s+(.+?)(?:\.|$)", "role_employer"),
    (r"\bi(?:'m| am) currently working as\s+(?:a|an)?\s*(.+?)(?:\.|$)", "role"),
    (r"\bmy (?:long-term )?goal is\s+(.+?)(?:\.|$)", "goal"),
    (r"\bi(?:'m| am) (?:a|an)\s+(.+?)(?:\.|$)", "role"),
    (r"\bi live in\s+(.+?)(?:\.|$)", "location"),
    (r"\bi(?:'m| am) from\s+(.+?)(?:\.|$)", "origin"),
    (r"\bi(?:'m| am)\s+(\d+)\s+years old", "age"),
]

# Preference patterns — stored as profile:preference
# PATCHED v0.11.0-fix2: Changed regex to stop at period or end-of-string only (not comma)
# This prevents "I prefer a warm, gentle tone" from being cut at the comma
PREFERENCE_PATTERNS = [
    (r"\bi prefer\s+(.+?)(?:\.|$)", "preference"),
    (r"\bi like\s+(.+?)(?:\.|$)", "like"),
    (r"\bi don(?:'t| not) like\s+(.+?)(?:\.|$)", "dislike"),
    (r"\bmy favorite\s+(.+?)\s+is\s+(.+?)(?:\.|$)", "favorite"),
    (r"\bi want nova to\s+(.+?)(?:\.|$)", "nova_preference"),
    (r"\bi(?:'d| would) prefer\s+(.+?)(?:\.|$)", "preference"),
    (r"\bplease (?:always|don't|never)\s+(.+?)(?:\.|$)", "behavior_preference"),
    (r"\bi love\s+(.+?)(?:\.|$)", "like"),
    (r"\bi hate\s+(.+?)(?:\.|$)", "dislike"),
]


def _check_duplicate_profile_memory(
    memory_manager: "MemoryManager",
    payload: str,
    tag: str,
) -> bool:
    """
    Check if a similar profile memory already exists.
    
    Returns True if duplicate found, False otherwise.
    """
    try:
        # Get existing profile memories with this tag
        existing = memory_manager.recall(
            mem_type="semantic",
            tags=[tag],
            limit=100,
        )
        
        # Normalize for comparison
        payload_normalized = payload.lower().strip()
        
        for item in existing:
            if item.payload.lower().strip() == payload_normalized:
                return True
            # Also check for very similar content (80% overlap)
            existing_words = set(item.payload.lower().split())
            new_words = set(payload_normalized.split())
            if existing_words and new_words:
                overlap = len(existing_words & new_words) / max(len(existing_words), len(new_words))
                if overlap > 0.8:
                    return True
        
        return False
    except Exception as e:
        logger.warning("Error checking duplicate profile memory: %s", e, exc_info=True)
        return False  # Don't block on errors


def maybe_extract_profile_memory(
    user_text: str,
    memory_manager: "MemoryManager",
    module_tag: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Heuristic v1: detect identity/preference statements in user_text and
    store them as semantic profile memories.
    
    - Conservative: better to under-save than over-save.
    - Avoid exact-duplicate entries.
    - Log successes at INFO and failures at WARNING.
    
    Args:
        user_text: The user's message
        memory_manager: MemoryManager instance
        module_tag: Optional module context
    
    Returns:
        List of stored memory info dicts (for debugging/testing)
    """
    if not user_text or not memory_manager:
        return []
    
    stored = []
    text_lower = user_text.lower()
    
    # Check identity patterns
    for pattern, pattern_type in IDENTITY_PATTERNS:
        try:
            match = re.search(pattern, user_text, re.IGNORECASE)
            if match:
                # Build payload from match groups
                if pattern_type == "role_employer":
                    payload = f"I'm a {match.group(1)} at {match.group(2)}"
                elif pattern_type == "name":
                    payload = f"My name is {match.group(1)}"
                else:
                    payload = match.group(0).strip()
                
                # Skip if too short or too vague
                if len(payload) < 10:
                    continue
                
                tag = "profile:identity"
                
                # Check for duplicates
                if _check_duplicate_profile_memory(memory_manager, payload, tag):
                    logger.debug("Skipping duplicate profile memory: %s", payload[:50])
                    continue
                
                # Store
                try:
                    item = memory_manager.store(
                        payload=payload,
                        mem_type="semantic",
                        tags=[tag],
                        salience=0.9,
                        trace={"source": "auto_profile_extraction", "pattern": pattern_type},
                        module_tag=module_tag,
                    )
                    logger.info("Stored profile memory (identity): id=%s payload='%s'", item.id, payload[:50])
                    stored.append({"id": item.id, "tag": tag, "payload": payload})
                except Exception as e:
                    logger.warning("Failed to store profile memory: %s", e, exc_info=True)
                    
        except Exception as e:
            logger.warning("Error in identity pattern matching: %s", e, exc_info=True)
    
    # Check preference patterns
    for pattern, pattern_type in PREFERENCE_PATTERNS:
        try:
            match = re.search(pattern, user_text, re.IGNORECASE)
            if match:
                # Build payload
                if pattern_type == "favorite":
                    payload = f"My favorite {match.group(1)} is {match.group(2)}"
                else:
                    payload = match.group(0).strip()
                
                # Skip if too short
                if len(payload) < 10:
                    continue
                
                tag = "profile:preference"
                
                # Check for duplicates
                if _check_duplicate_profile_memory(memory_manager, payload, tag):
                    logger.debug("Skipping duplicate profile memory: %s", payload[:50])
                    continue
                
                # Store
                try:
                    item = memory_manager.store(
                        payload=payload,
                        mem_type="semantic",
                        tags=[tag],
                        salience=0.9,
                        trace={"source": "auto_profile_extraction", "pattern": pattern_type},
                        module_tag=module_tag,
                    )
                    logger.info("Stored profile memory (preference): id=%s payload='%s'", item.id, payload[:50])
                    stored.append({"id": item.id, "tag": tag, "payload": payload})
                except Exception as e:
                    logger.warning("Failed to store profile memory: %s", e, exc_info=True)
                    
        except Exception as e:
            logger.warning("Error in preference pattern matching: %s", e, exc_info=True)
    
    return stored


# =============================================================================
# PHASE 1.5: NATURAL-LANGUAGE "REMEMBER THIS" FLOW
# =============================================================================

# Patterns that indicate "remember this" intent
REMEMBER_INTENT_PATTERNS = [
    r"^(?:nova[,\s]+)?(?:please\s+)?remember\s+this\b",
    r"^(?:nova[,\s]+)?(?:please\s+)?remember\s+that\s+(.+)",
    r"^(?:nova[,\s]+)?(?:please\s+)?remember\s+this\s+(?:idea|thought|for later)\b",
    r"\bremember\s+this\s+for\s+(?:me|later)\b",
    r"^(?:please\s+)?save\s+this\s+(?:to\s+)?memory\b",
    r"^(?:nova[,\s]+)?(?:please\s+)?don't forget\s+(?:that\s+)?(.+)",
]


def _detect_remember_intent(text: str) -> Tuple[bool, Optional[str]]:
    """
    Detect if user wants Nova to remember something.
    
    Returns:
        Tuple of (has_intent, extracted_content)
        - has_intent: True if remember intent detected
        - extracted_content: The content to remember (may be None if "remember this")
    """
    text_lower = text.lower().strip()
    
    for pattern in REMEMBER_INTENT_PATTERNS:
        match = re.search(pattern, text_lower, re.IGNORECASE)
        if match:
            # Try to extract the content after "remember that..."
            if match.lastindex and match.group(match.lastindex):
                return True, match.group(match.lastindex).strip()
            return True, None
    
    return False, None


def _classify_remember_content(content: str) -> Tuple[str, List[str]]:
    """
    Classify what type of memory this should be and what tags to use.
    
    Returns:
        Tuple of (mem_type, tags)
    """
    content_lower = content.lower()
    
    # Check if it's identity-like
    identity_keywords = ["my name", "i work", "i'm a", "i am a", "i live", "my goal"]
    if any(kw in content_lower for kw in identity_keywords):
        return "semantic", ["profile:identity", "manual:remember"]
    
    # Check if it's preference-like
    preference_keywords = ["i prefer", "i like", "i don't like", "my favorite", "i want nova"]
    if any(kw in content_lower for kw in preference_keywords):
        return "semantic", ["profile:preference", "manual:remember"]
    
    # Default to general semantic memory
    return "semantic", ["manual:remember"]


def handle_remember_intent(
    session_id: str,
    user_text: str,
    memory_manager: "MemoryManager",
    wm: Optional["NovaWorkingMemory"] = None,
    module_tag: Optional[str] = None,
) -> Optional[str]:
    """
    Detects 'remember this' style phrases and, if present, stores an appropriate
    long-term memory and returns a confirmation message.
    
    If no remember intent is detected, returns None.
    
    This function is safe: it never raises uncaught exceptions.
    
    PATCHED v0.11.0-fix3: Now looks for user_message (full text) first,
    then falls back to user_summary (truncated). Also stores full payload
    up to 500 chars instead of relying on WM's 100-char summaries.
    
    Args:
        session_id: Session identifier
        user_text: The user's message
        memory_manager: MemoryManager instance
        wm: Optional NovaWorkingMemory for context
        module_tag: Optional module context
    
    Returns:
        Confirmation message if remembered, None otherwise
    """
    try:
        has_intent, extracted_content = _detect_remember_intent(user_text)
        
        if not has_intent:
            return None
        
        # Determine what to store
        memory_payload = None
        
        if extracted_content and len(extracted_content.strip()) > 10:
            # Content was provided after "remember that..."
            memory_payload = extracted_content.strip()
        else:
            # "Remember this" with no content — try to get from WM turn history
            # PATCHED: Look for full user_message first, then fall back to user_summary
            if wm and hasattr(wm, 'turn_history') and wm.turn_history:
                # Get the last user message from turn history (skip "remember this" itself)
                for turn in reversed(wm.turn_history):
                    # First try: user_message (full text, if WM stores it)
                    if hasattr(turn, 'user_message') and turn.user_message:
                        # Skip if this IS the "remember this" message
                        if not _detect_remember_intent(turn.user_message)[0]:
                            memory_payload = turn.user_message
                            break
                    # Fallback: user_summary (truncated)
                    elif hasattr(turn, 'user_summary') and turn.user_summary:
                        # Skip if this IS the "remember this" message
                        if not _detect_remember_intent(turn.user_summary)[0]:
                            memory_payload = turn.user_summary
                            break
        
        if not memory_payload or len(memory_payload.strip()) < 10:
            return (
                "I'm not sure what to remember — try saying "
                "'Remember that I…' with more detail, or say something first, "
                "then 'Remember this.'"
            )
        
        # Clean up the payload
        memory_payload = memory_payload.strip()
        
        # ─────────────────────────────────────────────────────────────────
        # v0.11.0: Check for similar existing memory to avoid duplicates
        # ─────────────────────────────────────────────────────────────────
        try:
            existing = memory_manager.recall(mem_type="semantic", limit=30)
            for item in existing:
                existing_words = set(item.payload.lower().split())
                new_words = set(memory_payload.lower().split())
                if existing_words and new_words:
                    overlap = len(existing_words & new_words) / max(len(existing_words), len(new_words))
                    if overlap > 0.8:
                        short = item.payload[:60] + "..." if len(item.payload) > 60 else item.payload
                        logger.debug("Skipping duplicate remember: %.0f%% overlap with #%s", overlap * 100, item.id)
                        return f"I already have something similar saved: \"{short}\""
        except Exception as e:
            logger.debug("Duplicate check failed (non-fatal): %s", e)
            # Don't block on dedup check failure — continue to store
        
        # Classify and get tags
        mem_type, tags = _classify_remember_content(memory_payload)
        
        # Add module tag if available
        if module_tag:
            tags.append(f"module:{module_tag}")
        
        # Store the memory
        try:
            item = memory_manager.store(
                payload=memory_payload,
                mem_type=mem_type,
                tags=tags,
                salience=0.8,
                trace={
                    "source": "manual_remember",
                    "session_id": session_id,
                },
                module_tag=module_tag,
            )
            logger.info("Manual remember: stored memory id=%s payload='%s'", item.id, memory_payload[:50])
            
            # Build confirmation (PATCHED: increased from 80 to 150)
            short_payload = memory_payload[:150] + "..." if len(memory_payload) > 150 else memory_payload
            return f"Got it — I'll remember this: \"{short_payload}\""
            
        except Exception as e:
            logger.warning("Failed to store manual remember memory: %s", e, exc_info=True)
            return "I tried to remember that, but something went wrong while saving it."
            
    except Exception as e:
        logger.warning("Error in handle_remember_intent: %s", e, exc_info=True)
        return None


# =============================================================================
# PHASE 1: LTM CONTEXT INJECTION FOR PROMPTS
# =============================================================================

def get_profile_memories(
    memory_manager: "MemoryManager",
    limit: int = 20,
) -> List[Any]:
    """
    Retrieve profile memories (identity + preferences).
    
    Returns list of MemoryItem objects.
    """
    try:
        # Get all semantic memories with high salience
        all_memories = memory_manager.recall(
            mem_type="semantic",
            min_salience=0.7,
            limit=100,
        )
        
        # Filter to profile memories
        profile_memories = [
            m for m in all_memories
            if any(tag.startswith("profile:") for tag in m.tags)
        ]
        
        return profile_memories[:limit]
    except Exception as e:
        logger.warning("Error retrieving profile memories: %s", e, exc_info=True)
        return []


def get_relevant_semantic_memories(
    memory_manager: "MemoryManager",
    module_tag: Optional[str] = None,
    limit: int = 5,
) -> List[Any]:
    """
    Retrieve relevant semantic memories (non-profile, module-scoped if available).
    
    Returns list of MemoryItem objects.
    """
    try:
        memories = memory_manager.recall(
            mem_type="semantic",
            module_tag=module_tag,
            min_salience=0.5,
            limit=limit * 2,  # Get more, then filter
        )
        
        # Filter out profile memories
        non_profile = [
            m for m in memories
            if not any(tag.startswith("profile:") for tag in m.tags)
        ]
        
        return non_profile[:limit]
    except Exception as e:
        logger.warning("Error retrieving semantic memories: %s", e, exc_info=True)
        return []


def format_ltm_context(
    profile_memories: List[Any],
    semantic_memories: List[Any],
    max_profile: int = 5,
    max_semantic: int = 3,
    max_payload_length: int = 150,
) -> str:
    """
    Format LTM memories into a context string for injection into persona prompts.
    
    Args:
        profile_memories: List of profile MemoryItem objects
        semantic_memories: List of non-profile semantic MemoryItem objects
        max_profile: Maximum profile items to include
        max_semantic: Maximum semantic items to include
        max_payload_length: Truncate payloads longer than this
    
    Returns:
        Formatted context string, or empty string if no memories
    """
    lines = []
    
    # Profile section
    if profile_memories:
        identity_items = []
        preference_items = []
        
        for m in profile_memories[:max_profile * 2]:
            payload = m.payload
            if len(payload) > max_payload_length:
                payload = payload[:max_payload_length] + "..."
            
            if any("profile:identity" in tag for tag in m.tags):
                identity_items.append(f"- {payload}")
            elif any("profile:preference" in tag for tag in m.tags):
                preference_items.append(f"- {payload}")
        
        if identity_items or preference_items:
            lines.append("[LONG-TERM MEMORY — USER PROFILE]")
            lines.append("")
            
            if identity_items:
                lines.append("Identity:")
                lines.extend(identity_items[:max_profile])
            
            if preference_items:
                if identity_items:
                    lines.append("")
                lines.append("Preferences:")
                lines.extend(preference_items[:max_profile])
            
            lines.append("")
    
    # Relevant knowledge section
    if semantic_memories:
        lines.append("[RELEVANT KNOWLEDGE]")
        lines.append("")
        
        for m in semantic_memories[:max_semantic]:
            payload = m.payload
            if len(payload) > max_payload_length:
                payload = payload[:max_payload_length] + "..."
            lines.append(f"- {payload}")
        
        lines.append("")
    
    if not lines:
        return ""
    
    return "\n".join(lines)


def build_ltm_context_for_persona(
    memory_manager: "MemoryManager",
    module_tag: Optional[str] = None,
    # PATCHED v0.11.0-fix1: Accept both old and new parameter names
    current_module: Optional[str] = None,  # Alias for module_tag (backward compat)
    user_text: Optional[str] = None,       # For future relevance scoring
) -> str:
    """
    Build the full LTM context string for injection into persona prompts.
    
    This is the main entry point for LTM injection.
    
    PATCHED v0.11.0-fix1:
    - Now accepts both `module_tag` and `current_module` parameters
    - Added `user_text` parameter for future semantic search
    
    Args:
        memory_manager: MemoryManager instance
        module_tag: Optional current module for scoped retrieval
        current_module: Alias for module_tag (for backward compatibility with callers)
        user_text: Optional user text for relevance scoring (future use)
    
    Returns:
        Formatted LTM context string
    """
    # PATCHED: Support both parameter names
    effective_module = module_tag or current_module
    
    try:
        profile_memories = get_profile_memories(memory_manager, limit=10)
        semantic_memories = get_relevant_semantic_memories(
            memory_manager, 
            module_tag=effective_module,
            limit=5
        )
        
        context = format_ltm_context(profile_memories, semantic_memories)
        
        if context:
            logger.debug(
                "LTM context: %d profile memories, %d semantic memories",
                len(profile_memories), len(semantic_memories)
            )
        
        return context
    except Exception as e:
        logger.warning("Error building LTM context: %s", e, exc_info=True)
        return ""


# =============================================================================
# PHASE 5: KEYWORD-BASED RETRIEVAL
# =============================================================================

def _tokenize_query(query: str) -> List[str]:
    """
    Tokenize a query into keywords.
    
    - Lowercase
    - Remove punctuation
    - Filter short words
    """
    # Remove punctuation and split
    cleaned = re.sub(r'[^\w\s]', ' ', query.lower())
    words = cleaned.split()
    
    # Filter short words and common stop words
    stop_words = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
                  'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
                  'should', 'may', 'might', 'must', 'shall', 'can', 'to', 'of', 'in',
                  'for', 'on', 'with', 'at', 'by', 'from', 'as', 'into', 'through',
                  'during', 'before', 'after', 'above', 'below', 'between', 'and', 'or',
                  'but', 'if', 'then', 'else', 'when', 'where', 'why', 'how', 'all',
                  'each', 'every', 'both', 'few', 'more', 'most', 'other', 'some', 'such',
                  'no', 'not', 'only', 'same', 'so', 'than', 'too', 'very', 'just', 'i',
                  'me', 'my', 'myself', 'we', 'our', 'ours', 'you', 'your', 'yours',
                  'he', 'him', 'his', 'she', 'her', 'hers', 'it', 'its', 'they', 'them',
                  'their', 'what', 'which', 'who', 'whom', 'this', 'that', 'these', 'those'}
    
    keywords = [w for w in words if len(w) > 2 and w not in stop_words]
    return keywords


def _score_memory(item: Any, keywords: List[str]) -> float:
    """
    Score a memory item based on keyword matches.
    
    Returns:
        Score combining match count + salience
    """
    payload_lower = item.payload.lower()
    
    match_count = 0
    for keyword in keywords:
        if keyword in payload_lower:
            match_count += 1
    
    # Combine match count with salience
    salience = getattr(item, 'salience', 0.5) or 0.5
    score = match_count + salience
    
    return score


def search_by_keywords(
    memory_manager: "MemoryManager",
    query: str,
    mem_type: Optional[str] = None,
    module_tag: Optional[str] = None,
    status: Optional[str] = "active",
    limit: int = 20,
) -> List[Tuple[Any, float]]:
    """
    Simple keyword-based retrieval over MemoryItem.payload.
    
    - Tokenize 'query' into keywords (lowercased).
    - Filter candidates by type/module/status.
    - Score each candidate: match_count + salience.
    - Return top 'limit' items by score.
    
    Args:
        memory_manager: MemoryManager instance
        query: Search query string
        mem_type: Optional filter by memory type
        module_tag: Optional filter by module
        status: Optional filter by status (default "active")
        limit: Maximum results to return
    
    Returns:
        List of (MemoryItem, score) tuples sorted by score descending
    """
    try:
        keywords = _tokenize_query(query)
        
        if not keywords:
            logger.debug("No valid keywords in query: %s", query)
            return []
        
        # Get candidate memories
        candidates = memory_manager.recall(
            mem_type=mem_type,
            module_tag=module_tag,
            status=status,
            limit=100,  # Get more candidates for scoring
        )
        
        # Score each candidate
        scored = []
        for item in candidates:
            score = _score_memory(item, keywords)
            if score > 0:  # Only include items with at least one match
                scored.append((item, score))
        
        # Sort by score descending
        scored.sort(key=lambda x: x[1], reverse=True)
        
        logger.debug("Keyword search '%s': %d results from %d candidates", query, len(scored[:limit]), len(candidates))
        
        return scored[:limit]
        
    except Exception as e:
        logger.warning("Error in keyword search: %s", e, exc_info=True)
        return []


# =============================================================================
# PHASE 4: MEMORY DECAY / ARCHIVING
# =============================================================================

def run_memory_decay(
    memory_manager: "MemoryManager",
    now: Optional[datetime] = None,
) -> Dict[str, int]:
    """
    Apply simple decay rules to long-term memories.
    
    Rules:
    - For status == "active":
      - If last_used_at is None and created_at > 60 days ago:
        - salience *= 0.7
      - If last_used_at exists and last_used_at > 90 days ago:
        - status = "stale"
    
    - For status == "stale":
      - If salience < 0.2:
        - status = "archived"
    
    Args:
        memory_manager: MemoryManager instance
        now: Optional datetime for testing (defaults to now)
    
    Returns:
        {
            "decayed_salience": X,
            "marked_stale": Y,
            "archived": Z,
            "errors": W,
        }
    
    All errors are logged and swallowed.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    
    results = {
        "decayed_salience": 0,
        "marked_stale": 0,
        "archived": 0,
        "errors": 0,
    }
    
    try:
        # Get all memories
        all_active = memory_manager.recall(status="active", limit=1000)
        all_stale = memory_manager.recall(status="stale", limit=1000)
        
        # Process active memories
        for item in all_active:
            try:
                # Parse timestamp
                created_at = None
                if hasattr(item, 'timestamp') and item.timestamp:
                    try:
                        created_at = datetime.fromisoformat(item.timestamp.replace('Z', '+00:00'))
                    except ValueError:
                        pass
                
                # Parse last_used_at
                last_used_at = None
                trace = getattr(item, 'trace', {}) or {}
                if hasattr(item, 'last_used_at') and item.last_used_at:
                    try:
                        last_used_at = datetime.fromisoformat(item.last_used_at.replace('Z', '+00:00'))
                    except ValueError:
                        pass
                
                current_salience = getattr(item, 'salience', 0.5) or 0.5
                
                # Rule 1: Decay salience for never-used old memories
                if last_used_at is None and created_at:
                    days_old = (now - created_at).days
                    if days_old > 60:
                        new_salience = max(0.1, current_salience * 0.7)
                        if new_salience != current_salience:
                            memory_manager.update_salience(item.id, new_salience)
                            results["decayed_salience"] += 1
                            logger.debug("Decayed salience for memory #%d: %.2f -> %.2f", item.id, current_salience, new_salience)
                
                # Rule 2: Mark stale for long-unused memories
                if last_used_at:
                    days_unused = (now - last_used_at).days
                    if days_unused > 90:
                        memory_manager.update_status(item.id, "stale")
                        results["marked_stale"] += 1
                        logger.debug("Marked memory #%d as stale (unused for %d days)", item.id, days_unused)
                        
            except Exception as e:
                logger.warning("Error processing active memory #%d: %s", item.id, e, exc_info=True)
                results["errors"] += 1
        
        # Process stale memories
        for item in all_stale:
            try:
                current_salience = getattr(item, 'salience', 0.5) or 0.5
                
                # Rule 3: Archive very low salience stale memories
                if current_salience < 0.2:
                    memory_manager.update_status(item.id, "archived")
                    results["archived"] += 1
                    logger.debug("Archived memory #%d (salience %.2f)", item.id, current_salience)
                    
            except Exception as e:
                logger.warning("Error processing stale memory #%d: %s", item.id, e, exc_info=True)
                results["errors"] += 1
        
        logger.info(
            "Memory decay complete: decayed=%d, stale=%d, archived=%d, errors=%d",
            results["decayed_salience"], results["marked_stale"], 
            results["archived"], results["errors"]
        )
        
    except Exception as e:
        logger.warning("Error in run_memory_decay: %s", e, exc_info=True)
        results["errors"] += 1
    
    return results


# =============================================================================
# PHASE 3: QUEST COMPLETION EPISODIC MEMORY
# =============================================================================

def store_quest_completion_memory(
    memory_manager: "MemoryManager",
    quest_id: str,
    quest_title: str,
    xp_gained: int = 0,
    category: Optional[str] = None,
    module_tag: Optional[str] = None,
    completed_at: Optional[datetime] = None,
) -> Optional[int]:
    """
    Store an episodic memory for quest completion.
    
    Called by #complete when a quest is fully finished.
    
    Args:
        memory_manager: MemoryManager instance
        quest_id: Quest identifier
        quest_title: Quest title
        xp_gained: XP earned from completion
        category: Optional quest category
        module_tag: Optional module tag
        completed_at: Optional completion timestamp
    
    Returns:
        Memory ID if stored, None on failure
    """
    if completed_at is None:
        completed_at = datetime.now(timezone.utc)
    
    try:
        payload = (
            f"Completed quest: {quest_title} "
            f"(id={quest_id}, category={category or 'unknown'}). "
            f"XP gained: {xp_gained}. "
            f"Completed at: {completed_at.isoformat()}."
        )
        
        tags = ["quest", "quest:completed", f"quest:{quest_id}"]
        if module_tag:
            tags.append(f"module:{module_tag}")
        
        item = memory_manager.store(
            payload=payload,
            mem_type="episodic",
            tags=tags,
            salience=0.7,
            trace={
                "source": "quest_completion",
                "quest_id": quest_id,
                "xp_gained": xp_gained,
            },
            module_tag=module_tag,
        )
        
        logger.info("Stored quest completion memory id=%d for quest_id=%s", item.id, quest_id)
        return item.id
        
    except Exception as e:
        logger.warning("Failed to store quest completion memory for quest_id=%s: %s", quest_id, e, exc_info=True)
        return None


# =============================================================================
# PHASE 7: AUTO-EXTRACTION OF PROCEDURAL / EPISODIC INSIGHTS
# =============================================================================

# Procedural patterns
PROCEDURAL_PATTERNS = [
    r"\bstep\s*1[:\.\)]\s*.+step\s*2[:\.\)]",
    r"\b1[:\.\)]\s*.+2[:\.\)]",
    r"\bmy routine is\b",
    r"\bhere'?s how i do\b",
    r"\bfirst[,\s]+.+then[,\s]+.+(?:finally|lastly)\b",
    r"\bi (?:always|usually) start by\b.+then\b",
]

# Episodic patterns
EPISODIC_PATTERNS = [
    r"\btoday i\s+(?:did|finished|completed|learned|discovered|realized)\b",
    r"\bthis week i\s+(?:did|finished|completed|learned)\b",
    r"\bearlier i\s+(?:did|finished|completed)\b",
    r"\bjust\s+(?:finished|completed|did)\b",
    r"\bi finally\s+(?:finished|completed|did)\b",
]


def maybe_extract_procedural_memory(
    user_text: str,
    memory_manager: "MemoryManager",
    module_tag: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Auto-extract procedural memories (routines, step-by-step instructions).
    
    Trigger on patterns like:
    - "step 1 / step one / 1)" combined with "2)"
    - "my routine is …"
    - "here's how I do …"
    
    Args:
        user_text: User's message
        memory_manager: MemoryManager instance
        module_tag: Optional module context
    
    Returns:
        Dict with stored memory info, or None
    """
    if not user_text or len(user_text) < 30:
        return None
    
    text_lower = user_text.lower()
    
    for pattern in PROCEDURAL_PATTERNS:
        try:
            if re.search(pattern, text_lower, re.IGNORECASE | re.DOTALL):
                # Store it
                try:
                    item = memory_manager.store(
                        payload=user_text.strip()[:500],  # Limit length
                        mem_type="procedural",
                        tags=["auto:procedural"],
                        salience=0.6,
                        trace={"source": "auto_procedural_extraction"},
                        module_tag=module_tag,
                    )
                    logger.info("Stored procedural memory id=%d", item.id)
                    return {"id": item.id, "type": "procedural"}
                except Exception as e:
                    logger.warning("Failed to store procedural memory: %s", e, exc_info=True)
                    return None
        except Exception:
            continue
    
    return None


def maybe_extract_episodic_memory(
    user_text: str,
    memory_manager: "MemoryManager",
    module_tag: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Auto-extract episodic memories (events, accomplishments).
    
    Trigger on patterns like:
    - "today I …"
    - "this week I …"
    - "earlier I did …"
    
    Args:
        user_text: User's message
        memory_manager: MemoryManager instance
        module_tag: Optional module context
    
    Returns:
        Dict with stored memory info, or None
    """
    if not user_text or len(user_text) < 20:
        return None
    
    text_lower = user_text.lower()
    
    for pattern in EPISODIC_PATTERNS:
        try:
            if re.search(pattern, text_lower, re.IGNORECASE):
                # Store it
                try:
                    item = memory_manager.store(
                        payload=user_text.strip()[:300],  # Limit length
                        mem_type="episodic",
                        tags=["auto:episodic"],
                        salience=0.5,
                        trace={
                            "source": "auto_episodic_extraction",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        },
                        module_tag=module_tag,
                    )
                    logger.info("Stored episodic memory id=%d", item.id)
                    return {"id": item.id, "type": "episodic"}
                except Exception as e:
                    logger.warning("Failed to store episodic memory: %s", e, exc_info=True)
                    return None
        except Exception:
            continue
    
    return None


# =============================================================================
# COMBINED AUTO-EXTRACTION ENTRY POINT
# =============================================================================

def run_auto_extraction(
    user_text: str,
    memory_manager: "MemoryManager",
    module_tag: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Run all auto-extraction routines on user text.
    
    This is the main entry point called from the kernel on each message.
    
    Args:
        user_text: User's message
        memory_manager: MemoryManager instance
        module_tag: Optional module context
    
    Returns:
        Dict summarizing what was extracted
    """
    results = {
        "profile": [],
        "procedural": None,
        "episodic": None,
    }
    
    # Profile extraction
    profile_results = maybe_extract_profile_memory(user_text, memory_manager, module_tag)
    if profile_results:
        results["profile"] = profile_results
    
    # Procedural extraction
    proc_result = maybe_extract_procedural_memory(user_text, memory_manager, module_tag)
    if proc_result:
        results["procedural"] = proc_result
    
    # Episodic extraction
    epis_result = maybe_extract_episodic_memory(user_text, memory_manager, module_tag)
    if epis_result:
        results["episodic"] = epis_result
    
    return results


# =============================================================================
# MODULE EXPORTS
# =============================================================================

__all__ = [
    # Profile extraction
    "maybe_extract_profile_memory",
    
    # Remember intent
    "handle_remember_intent",
    
    # LTM context
    "get_profile_memories",
    "get_relevant_semantic_memories",
    "format_ltm_context",
    "build_ltm_context_for_persona",
    
    # Keyword search
    "search_by_keywords",
    
    # Decay
    "run_memory_decay",
    
    # Quest completion
    "store_quest_completion_memory",
    
    # Auto-extraction
    "maybe_extract_procedural_memory",
    "maybe_extract_episodic_memory",
    "run_auto_extraction",
]
