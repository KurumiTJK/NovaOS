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
# PATCHED v0.11.0-fix7: Added many more patterns for robust extraction
IDENTITY_PATTERNS = [
    # Name patterns
    (r"\bmy name is\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", "name"),
    (r"\bi(?:'m| am)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b", "name"),
    (r"\bcall me\s+([A-Z][a-z]+)", "name"),
    (r"\bpeople call me\s+([A-Z][a-z]+)", "name"),
    (r"\bmy friends call me\s+([A-Z][a-z]+)", "name"),
    
    # Role + Employer combined (most specific - check first)
    (r"\bi(?:'m| am) (?:a|an)\s+(.+?)\s+at\s+(.+?)(?:\.|$)", "role_employer"),
    (r"\bi work as\s+(?:a|an)?\s*(.+?)\s+at\s+(.+?)(?:\.|$)", "role_employer"),
    (r"\bi(?:'m| am) (?:a|an)\s+(.+?)\s+(?:for|with)\s+(.+?)(?:\.|$)", "role_employer"),
    (r"\bi work as\s+(?:a|an)?\s*(.+?)\s+(?:for|with)\s+(.+?)(?:\.|$)", "role_employer"),
    
    # Employer patterns
    (r"\bi work (?:at|for)\s+(.+?)(?:\.|$)", "employer"),
    (r"\bi(?:'m| am) (?:employed|working) (?:at|for|with)\s+(.+?)(?:\.|$)", "employer"),
    (r"\bi(?:'ve| have) been working (?:at|for)\s+(.+?)(?:\.|$)", "employer"),
    (r"\bi just (?:started|joined|got a (?:new )?job) (?:at|for|with)\s+(.+?)(?:\.|$)", "employer"),
    (r"\bi(?:'ve| have) (?:just )?(?:started|joined|accepted a (?:job|position|role)) (?:at|for|with)\s+(.+?)(?:\.|$)", "employer"),
    (r"\bi(?:'m| am) (?:now|starting) (?:at|with)\s+(.+?)(?:\.|$)", "employer"),
    (r"\bi got (?:a |an )?(?:new )?(?:job|position|role|offer) (?:at|from|with)\s+(.+?)(?:\.|$)", "employer"),
    (r"\bi(?:'m| am) joining\s+(.+?)(?:\.|$)", "employer"),
    (r"\bi(?:'m| am) moving to\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)(?:\.|$)", "employer"),
    (r"\bmy (?:company|employer|workplace) is\s+(.+?)(?:\.|$)", "employer"),
    (r"\bi(?:'m| am) with\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)(?:\.|$)", "employer"),
    
    # Role/job patterns
    (r"\bi work as\s+(?:a|an)?\s*(.+?)(?:\.|$)", "role"),
    (r"\bi(?:'m| am) (?:a|an)\s+(.+?)(?:\.|$)", "role"),
    (r"\bi(?:'m| am) currently working as\s+(?:a|an)?\s*(.+?)(?:\.|$)", "role"),
    (r"\bmy job is\s+(.+?)(?:\.|$)", "role"),
    (r"\bmy role is\s+(.+?)(?:\.|$)", "role"),
    (r"\bmy title is\s+(.+?)(?:\.|$)", "role"),
    (r"\bi(?:'m| am) currently (?:a|an)\s+(.+?)(?:\.|$)", "role"),
    (r"\bmy profession is\s+(.+?)(?:\.|$)", "role"),
    (r"\bi do\s+(.+?)\s+for (?:a living|work)(?:\.|$)", "role"),
    
    # Background/expertise patterns  
    (r"\bmy background is (?:in\s+)?(.+?)(?:\.|$)", "background"),
    (r"\bi specialize in\s+(.+?)(?:\.|$)", "expertise"),
    (r"\bmy expertise is (?:in\s+)?(.+?)(?:\.|$)", "expertise"),
    (r"\bi(?:'m| am) (?:an? )?expert in\s+(.+?)(?:\.|$)", "expertise"),
    (r"\bi(?:'ve| have) been doing\s+(.+?)\s+for\s+(\d+)\s+years", "experience"),
    (r"\bi have\s+(\d+)\s+years (?:of )?experience in\s+(.+?)(?:\.|$)", "experience"),
    
    # Location patterns
    (r"\bi live in\s+(.+?)(?:\.|$)", "location"),
    (r"\bi(?:'m| am) based (?:in|out of)\s+(.+?)(?:\.|$)", "location"),
    (r"\bi(?:'m| am) located in\s+(.+?)(?:\.|$)", "location"),
    (r"\bi(?:'m| am) from\s+(.+?)(?:\.|$)", "origin"),
    (r"\bi grew up in\s+(.+?)(?:\.|$)", "origin"),
    (r"\bmy hometown is\s+(.+?)(?:\.|$)", "origin"),
    
    # Goal patterns
    (r"\bmy (?:long-term )?goal is\s+(.+?)(?:\.|$)", "goal"),
    (r"\bi(?:'m| am) (?:trying|working|learning) to\s+(.+?)(?:\.|$)", "goal"),
    (r"\bi want to\s+(?:become|be|learn|master)\s+(.+?)(?:\.|$)", "goal"),
    (r"\bmy objective is\s+(.+?)(?:\.|$)", "goal"),
    
    # Age pattern
    (r"\bi(?:'m| am)\s+(\d+)\s+years old", "age"),
    (r"\bi(?:'m| am)\s+(\d+)", "age"),
    
    # Education patterns
    (r"\bi studied\s+(.+?)(?:\s+at\s+.+?)?(?:\.|$)", "education"),
    (r"\bi have (?:a|an)\s+(.+?)\s+degree", "education"),
    (r"\bi graduated from\s+(.+?)(?:\.|$)", "education"),
    (r"\bmy degree is in\s+(.+?)(?:\.|$)", "education"),
]

# Preference patterns — stored as profile:preference
# PATCHED v0.11.0-fix2: Changed regex to stop at period or end-of-string only (not comma)
# PATCHED v0.11.0-fix7: Added many more patterns for robust extraction
PREFERENCE_PATTERNS = [
    # Direct preferences
    (r"\bi prefer\s+(.+?)(?:\.|$)", "preference"),
    (r"\bi(?:'d| would) prefer\s+(.+?)(?:\.|$)", "preference"),
    (r"\bi(?:'d| would) rather\s+(.+?)(?:\.|$)", "preference"),
    
    # Likes/dislikes
    (r"\bi (?:really )?like\s+(.+?)(?:\.|$)", "like"),
    (r"\bi love\s+(.+?)(?:\.|$)", "like"),
    (r"\bi enjoy\s+(.+?)(?:\.|$)", "like"),
    (r"\bi(?:'m| am) (?:a )?fan of\s+(.+?)(?:\.|$)", "like"),
    (r"\bi(?:'m| am) into\s+(.+?)(?:\.|$)", "like"),
    (r"\bi don(?:'t| not) (?:really )?like\s+(.+?)(?:\.|$)", "dislike"),
    (r"\bi hate\s+(.+?)(?:\.|$)", "dislike"),
    (r"\bi can(?:'t| not) stand\s+(.+?)(?:\.|$)", "dislike"),
    (r"\bi(?:'m| am) not (?:a )?fan of\s+(.+?)(?:\.|$)", "dislike"),
    
    # Favorites
    (r"\bmy favorite\s+(.+?)\s+is\s+(.+?)(?:\.|$)", "favorite"),
    (r"\bi(?:'m| am) a big fan of\s+(.+?)(?:\.|$)", "favorite"),
    
    # Nova/communication preferences
    (r"\bi want (?:you|nova) to\s+(.+?)(?:\.|$)", "nova_preference"),
    (r"\bplease (?:always|never|don't)\s+(.+?)(?:\.|$)", "behavior_preference"),
    (r"\bi(?:'d| would) like (?:you|nova) to\s+(.+?)(?:\.|$)", "nova_preference"),
    (r"\bwhen (?:talking|responding|replying),?\s+(?:please\s+)?(.+?)(?:\.|$)", "communication_style"),
    (r"\bi prefer (?:when you|if you|you to)\s+(.+?)(?:\.|$)", "nova_preference"),
    (r"\bkeep (?:your )?(?:responses?|answers?)\s+(.+?)(?:\.|$)", "communication_style"),
    (r"\bbe (?:more\s+)?(.+?)\s+(?:when|in your)(?:\.|$)", "communication_style"),
    
    # Interest patterns
    (r"\bi(?:'m| am) interested in\s+(.+?)(?:\.|$)", "interest"),
    (r"\bi(?:'m| am) passionate about\s+(.+?)(?:\.|$)", "interest"),
    (r"\bmy hobbies? (?:is|are|include)\s+(.+?)(?:\.|$)", "hobby"),
    (r"\bin my (?:free|spare) time,?\s+i\s+(.+?)(?:\.|$)", "hobby"),
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
    result = _check_duplicate_or_contradiction(memory_manager, payload, tag)
    return result["is_duplicate"]


def _extract_semantic_category(payload: str) -> Optional[Tuple[str, str]]:
    """
    Extract the semantic category and key value from a payload.
    
    v0.11.0-fix8: Smart contradiction detection based on semantic meaning.
    
    Returns:
        Tuple of (category, extracted_value) or None if no category detected.
        
    Categories:
        - employer: Company/organization name
        - role: Job title/position
        - name: Person's name
        - location: Where they live
        - origin: Where they're from
    """
    payload_lower = payload.lower().strip()
    
    # Employer patterns - extract company name
    employer_patterns = [
        r"(?:work(?:s|ing|ed)?|job|position|role)\s+(?:at|for|with)\s+([A-Za-z][\w\s&.-]+?)(?:\s+as|\s*$|\.|,)",
        r"(?:joined|joining|started at|moving to|got (?:a )?(?:new )?(?:job|position|role) (?:at|with))\s+([A-Za-z][\w\s&.-]+?)(?:\s*$|\.|,)",
        r"(?:i'm|i am|i'm now|currently)\s+(?:at|with)\s+([A-Za-z][\w\s&.-]+?)(?:\s*$|\.|,)",
        r"(?:consultant|engineer|developer|manager|director|analyst|designer|architect)\s+at\s+([A-Za-z][\w\s&.-]+?)(?:\s*$|\.|,)",
        r"(?:my )?(?:company|employer|workplace)\s+is\s+([A-Za-z][\w\s&.-]+?)(?:\s*$|\.|,)",
    ]
    
    for pattern in employer_patterns:
        match = re.search(pattern, payload_lower, re.IGNORECASE)
        if match:
            return ("employer", match.group(1).strip())
    
    # Name patterns
    name_patterns = [
        r"(?:my name is|i'm|i am|call me)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
    ]
    
    for pattern in name_patterns:
        match = re.search(pattern, payload, re.IGNORECASE)  # Case-sensitive for names
        if match:
            return ("name", match.group(1).strip())
    
    # Location patterns (where they live now)
    location_patterns = [
        r"(?:live|living|based|located)\s+(?:in|at|out of)\s+([A-Za-z][\w\s,.-]+?)(?:\s*$|\.|,)",
    ]
    
    for pattern in location_patterns:
        match = re.search(pattern, payload_lower, re.IGNORECASE)
        if match:
            return ("location", match.group(1).strip())
    
    # Origin patterns (where they're from)
    origin_patterns = [
        r"(?:i'm|i am)\s+from\s+([A-Za-z][\w\s,.-]+?)(?:\s*$|\.|,)",
        r"grew up in\s+([A-Za-z][\w\s,.-]+?)(?:\s*$|\.|,)",
    ]
    
    for pattern in origin_patterns:
        match = re.search(pattern, payload_lower, re.IGNORECASE)
        if match:
            return ("origin", match.group(1).strip())
    
    return None


def _check_duplicate_or_contradiction(
    memory_manager: "MemoryManager",
    payload: str,
    tag: str,
) -> Dict[str, Any]:
    """
    Check if a similar profile memory exists OR if it contradicts existing ones.
    
    v0.11.0-fix6: Enhanced to detect contradictions and handle updates.
    v0.11.0-fix8: Smarter semantic-based contradiction detection.
                  Any employer statement contradicts another employer statement, etc.
    
    Returns:
        {
            "is_duplicate": bool,
            "is_contradiction": bool,
            "conflicting_memory_id": Optional[int],
            "conflicting_payload": Optional[str],
        }
    """
    result = {
        "is_duplicate": False,
        "is_contradiction": False,
        "conflicting_memory_id": None,
        "conflicting_payload": None,
    }
    
    try:
        # Get existing profile memories with this tag
        existing = memory_manager.recall(
            mem_type="semantic",
            tags=[tag],
            limit=100,
        )
        
        # Normalize for comparison
        payload_normalized = payload.lower().strip()
        payload_words = set(payload_normalized.split())
        
        # Extract semantic category from new payload
        new_category = _extract_semantic_category(payload)
        
        for item in existing:
            item_payload = item.payload.lower().strip()
            item_words = set(item_payload.split())
            
            # Check for exact duplicate
            if item_payload == payload_normalized:
                result["is_duplicate"] = True
                return result
            
            # Check for high word overlap (likely duplicate)
            if item_words and payload_words:
                overlap = len(item_words & payload_words) / max(len(item_words), len(payload_words))
                if overlap > 0.8:
                    result["is_duplicate"] = True
                    return result
            
            # v0.11.0-fix8: Semantic category contradiction
            # If both memories are about the same category (e.g., employer),
            # but have different values, it's a contradiction
            if new_category:
                old_category = _extract_semantic_category(item.payload)
                if old_category and old_category[0] == new_category[0]:
                    # Same category - check if values are different
                    old_value = old_category[1].lower()
                    new_value = new_category[1].lower()
                    
                    if old_value != new_value:
                        result["is_contradiction"] = True
                        result["conflicting_memory_id"] = item.id
                        result["conflicting_payload"] = item.payload
                        logger.info(
                            "Semantic contradiction detected [%s]: '%s' vs '%s'",
                            new_category[0], old_value, new_value
                        )
                        return result
        
        return result
    except Exception as e:
        logger.warning("Error checking duplicate/contradiction: %s", e, exc_info=True)
        return result


def _handle_contradiction(
    memory_manager: "MemoryManager",
    new_payload: str,
    conflicting_memory_id: int,
    tag: str,
    module_tag: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Handle a contradiction by replacing the old memory with the new one.
    
    v0.11.0-fix6: Auto-update for profile contradictions.
    
    Args:
        memory_manager: MemoryManager instance
        new_payload: The new payload to store
        conflicting_memory_id: ID of the conflicting memory to replace
        tag: The profile tag
        module_tag: Optional module context
    
    Returns:
        Info dict about the update, or None on failure
    """
    try:
        # Delete the old conflicting memory
        memory_manager.forget(ids=[conflicting_memory_id])
        logger.info("Deleted conflicting memory #%d for update", conflicting_memory_id)
        
        # Store the new memory
        item = memory_manager.store(
            payload=new_payload.strip(),
            mem_type="semantic",
            tags=[tag],
            salience=0.9,  # Profile memories are important
            trace={"source": "auto_profile_extraction", "pattern": "updated", "replaced_id": conflicting_memory_id},
            module_tag=module_tag,
        )
        
        logger.info("Stored updated profile memory #%d (replaced #%d)", item.id, conflicting_memory_id)
        
        return {
            "id": item.id,
            "payload": new_payload,
            "tag": tag,
            "action": "updated",
            "replaced_id": conflicting_memory_id,
        }
    except Exception as e:
        logger.warning("Error handling contradiction: %s", e, exc_info=True)
        return None


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
    - v0.11.0-fix6: Handle contradictions by updating existing memories.
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
                
                # v0.11.0-fix6: Check for duplicates AND contradictions
                check_result = _check_duplicate_or_contradiction(memory_manager, payload, tag)
                
                if check_result["is_duplicate"]:
                    logger.debug("Skipping duplicate profile memory: %s", payload[:50])
                    continue
                
                if check_result["is_contradiction"]:
                    # Handle contradiction by updating
                    update_result = _handle_contradiction(
                        memory_manager, payload, 
                        check_result["conflicting_memory_id"],
                        tag, module_tag
                    )
                    if update_result:
                        stored.append(update_result)
                    continue
                
                # Store new memory
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
                
                # v0.11.0-fix6: Check for duplicates AND contradictions
                check_result = _check_duplicate_or_contradiction(memory_manager, payload, tag)
                
                if check_result["is_duplicate"]:
                    logger.debug("Skipping duplicate profile memory: %s", payload[:50])
                    continue
                
                if check_result["is_contradiction"]:
                    # Handle contradiction by updating
                    update_result = _handle_contradiction(
                        memory_manager, payload,
                        check_result["conflicting_memory_id"],
                        tag, module_tag
                    )
                    if update_result:
                        stored.append(update_result)
                    continue
                
                # Store new memory
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
    
    v0.11.0-fix9: Added instructions for subtle, contextual memory usage.
    
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
    has_memories = False
    
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
            has_memories = True
            lines.append("[BACKGROUND CONTEXT — USER PROFILE]")
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
        has_memories = True
        lines.append("[BACKGROUND CONTEXT — RELEVANT KNOWLEDGE]")
        lines.append("")
        
        for m in semantic_memories[:max_semantic]:
            payload = m.payload
            if len(payload) > max_payload_length:
                payload = payload[:max_payload_length] + "..."
            lines.append(f"- {payload}")
        
        lines.append("")
    
    if not has_memories:
        return ""
    
    # v0.11.0-fix9: Add instructions for subtle memory usage
    memory_usage_instructions = """[MEMORY USAGE GUIDELINES]
This is background context you know about the user. Use it SUBTLY:

RULES:
1. DO NOT mention memories unless directly relevant to the user's current message.
2. DO NOT redirect conversations toward stored facts (e.g., "Since you work at X...")
3. DO NOT reference memories every few messages - most responses need no memory reference.
4. DO treat memories as quiet background knowledge, not conversation anchors.
5. If referencing a memory, integrate it naturally - never say "I recall" or "According to my memory."

RELEVANCE TEST (apply before mentioning ANY memory):
"Would mentioning this make my answer clearer, more accurate, or solve a problem the user explicitly raised?"
If not a strong YES → do NOT mention it.

CORRECT: User asks about interview prep → mention their career context naturally.
INCORRECT: User asks about organizing notes → force in their job/goals.

Be warm, present, and quietly aware - not pushy or scripted."""

    return "\n".join(lines) + "\n" + memory_usage_instructions


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
    
    PATCHED v0.11.0-fix6:
    - Touch memories on retrieval (update last_used_at)
    
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
        
        # v0.11.0-fix6: Use semantic search if user_text provided and embeddings available
        if user_text and _check_embeddings_available():
            semantic_memories = get_relevant_semantic_memories_v2(
                memory_manager,
                user_text=user_text,
                module_tag=effective_module,
                limit=5
            )
        else:
            semantic_memories = get_relevant_semantic_memories(
                memory_manager, 
                module_tag=effective_module,
                limit=5
            )
        
        # v0.11.0-fix6: Touch memories that are being used (update last_used_at)
        all_used_memories = profile_memories + semantic_memories
        _touch_memories(memory_manager, all_used_memories)
        
        context = format_ltm_context(profile_memories, semantic_memories)
        
        if context:
            logger.debug(
                "LTM context: %d profile memories, %d semantic memories (touched, semantic=%s)",
                len(profile_memories), len(semantic_memories), 
                user_text is not None and _check_embeddings_available()
            )
        
        return context
    except Exception as e:
        logger.warning("Error building LTM context: %s", e, exc_info=True)
        return ""


def _touch_memories(memory_manager: "MemoryManager", memories: List[Any]) -> int:
    """
    Update last_used_at for retrieved memories.
    
    v0.11.0-fix6: Touching memories prevents them from decaying.
    
    Args:
        memory_manager: MemoryManager instance
        memories: List of memory items to touch
    
    Returns:
        Number of memories successfully touched
    """
    touched = 0
    now = datetime.now(timezone.utc).isoformat()
    
    for item in memories:
        try:
            mem_id = getattr(item, 'id', None)
            if mem_id is not None:
                # Try to update via engine directly
                if hasattr(memory_manager, '_engine'):
                    engine = memory_manager._engine
                    engine_item = engine.index.get(mem_id)
                    if engine_item:
                        engine_item.last_used_at = now
                        engine.long_term.update(engine_item)
                        engine.index.update(engine_item)
                        touched += 1
        except Exception as e:
            logger.debug("Failed to touch memory #%s: %s", getattr(item, 'id', '?'), e)
    
    if touched > 0:
        logger.debug("Touched %d memories (updated last_used_at)", touched)
    
    return touched


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
    Apply decay rules to long-term memories using MemoryLifecycle.
    
    v0.11.0-fix6 IMPROVEMENTS:
    - Uses MemoryLifecycle class for proper exponential decay
    - Protects profile memories (higher min_salience)
    - Different decay rates by memory type (episodic fastest, procedural slowest)
    
    Args:
        memory_manager: MemoryManager instance
        now: Optional datetime for testing (defaults to now)
    
    Returns:
        {
            "decayed_salience": X,
            "marked_stale": Y,
            "archived": Z,
            "profile_protected": P,
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
        "profile_protected": 0,
        "errors": 0,
    }
    
    try:
        # Import MemoryLifecycle
        try:
            from kernel.memory_lifecycle import MemoryLifecycle, DecayConfig
            
            # Custom config with profile protection
            config = DecayConfig()
            lifecycle = MemoryLifecycle(config)
            use_lifecycle = True
        except ImportError:
            logger.warning("MemoryLifecycle not available, using fallback decay")
            use_lifecycle = False
        
        # Get all memories
        all_active = memory_manager.recall(status="active", limit=1000)
        all_stale = memory_manager.recall(status="stale", limit=1000)
        
        # Process active memories
        for item in all_active:
            try:
                tags = getattr(item, 'tags', []) or []
                current_salience = getattr(item, 'salience', 0.5) or 0.5
                mem_type = getattr(item, 'type', 'semantic')
                
                # v0.11.0-fix6: Profile memory protection
                is_profile = any(t.startswith("profile:") for t in tags)
                if is_profile:
                    # Profile memories have higher minimum salience (never go below 0.5)
                    min_salience_for_item = 0.5
                    results["profile_protected"] += 1
                else:
                    min_salience_for_item = 0.01
                
                # Parse timestamps
                created_at = getattr(item, 'timestamp', None)
                last_used_at = getattr(item, 'last_used_at', None)
                
                if use_lifecycle:
                    # Use MemoryLifecycle for proper exponential decay
                    new_salience = lifecycle.calculate_decay(
                        memory_type=mem_type,
                        original_salience=current_salience,
                        last_used_at=last_used_at,
                        created_at=created_at or now.isoformat(),
                    )
                    
                    # Apply profile protection floor
                    new_salience = max(new_salience, min_salience_for_item)
                    
                    # Get recommended status
                    if not is_profile:  # Don't change profile memory status
                        recommended_status = lifecycle.get_recommended_status(new_salience)
                    else:
                        recommended_status = "active"  # Profile always stays active
                    
                    # Apply salience change
                    if abs(new_salience - current_salience) > 0.01:
                        memory_manager.update_salience(item.id, new_salience)
                        results["decayed_salience"] += 1
                        logger.debug("Decayed memory #%d: %.2f -> %.2f (%s)", 
                                     item.id, current_salience, new_salience, mem_type)
                    
                    # Apply status change
                    if recommended_status == "stale" and not is_profile:
                        memory_manager.update_status(item.id, "stale")
                        results["marked_stale"] += 1
                        logger.debug("Marked memory #%d as stale", item.id)
                else:
                    # Fallback: Simple decay logic
                    if created_at:
                        try:
                            created_dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                            days_old = (now - created_dt).days
                            if days_old > 60 and not is_profile:
                                new_salience = max(min_salience_for_item, current_salience * 0.7)
                                if new_salience != current_salience:
                                    memory_manager.update_salience(item.id, new_salience)
                                    results["decayed_salience"] += 1
                        except ValueError:
                            pass
                        
            except Exception as e:
                logger.warning("Error processing active memory #%d: %s", item.id, e, exc_info=True)
                results["errors"] += 1
        
        # Process stale memories
        for item in all_stale:
            try:
                tags = getattr(item, 'tags', []) or []
                current_salience = getattr(item, 'salience', 0.5) or 0.5
                
                # Profile memories should never be stale, restore them
                is_profile = any(t.startswith("profile:") for t in tags)
                if is_profile:
                    memory_manager.update_status(item.id, "active")
                    results["profile_protected"] += 1
                    continue
                
                # Archive very low salience stale memories
                if current_salience < 0.2:
                    memory_manager.update_status(item.id, "archived")
                    results["archived"] += 1
                    logger.debug("Archived memory #%d (salience %.2f)", item.id, current_salience)
                    
            except Exception as e:
                logger.warning("Error processing stale memory #%d: %s", item.id, e, exc_info=True)
                results["errors"] += 1
        
        logger.info(
            "Memory decay complete: decayed=%d, stale=%d, archived=%d, profile_protected=%d, errors=%d",
            results["decayed_salience"], results["marked_stale"], 
            results["archived"], results["profile_protected"], results["errors"]
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

# v0.11.0-fix6: Counter for periodic decay
_extraction_call_count = 0
_DECAY_EVERY_N_CALLS = 50  # Run decay every 50 messages


def run_auto_extraction(
    user_text: str,
    memory_manager: "MemoryManager",
    module_tag: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Run all auto-extraction routines on user text.
    
    This is the main entry point called from the kernel on each message.
    
    v0.11.0-fix6: Added periodic background decay every N calls.
    
    Args:
        user_text: User's message
        memory_manager: MemoryManager instance
        module_tag: Optional module context
    
    Returns:
        Dict summarizing what was extracted
    """
    global _extraction_call_count
    
    results = {
        "profile": [],
        "procedural": None,
        "episodic": None,
        "llm_extracted": [],
        "decay_ran": False,
    }
    
    # Profile extraction (regex-based)
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
    
    # v0.11.0-fix7: LLM fallback - MORE AGGRESSIVE
    # Trigger LLM extraction when:
    # 1. No profile memories were extracted by regex, OR
    # 2. Message contains personal indicators but regex only got partial info
    # 3. Message is substantial (>30 chars)
    should_try_llm = False
    text_lower = user_text.lower()
    
    # Personal fact indicators - expanded list
    personal_indicators = [
        "i ", "i'm", "i am", "my ", "i've", "i have",
        "i work", "i live", "i like", "i prefer", "i love", "i hate",
        "i need", "i want", "i enjoy", "i specialize",
        "my name", "my job", "my role", "my goal", "my background",
        "my company", "my employer", "my title", "my expertise",
        "years of experience", "years experience",
        "based in", "based out of", "located in",
        "graduated from", "degree in", "studied",
    ]
    
    has_personal_indicators = any(ind in text_lower for ind in personal_indicators)
    
    if len(user_text) > 30 and has_personal_indicators:
        if not profile_results:
            # No regex matches at all - definitely try LLM
            should_try_llm = True
            logger.debug("LLM fallback: no regex matches, trying LLM")
        elif len(profile_results) == 1:
            # Only one match - might have missed something, try LLM for completeness
            # But only if message seems to have multiple facts
            multi_fact_indicators = [" and ", " also ", ", i ", " plus ", " as well as "]
            if any(ind in text_lower for ind in multi_fact_indicators):
                should_try_llm = True
                logger.debug("LLM fallback: partial match with multi-fact indicators")
    
    if should_try_llm:
        try:
            llm_results = llm_extract_facts(user_text, memory_manager, module_tag)
            if llm_results:
                results["llm_extracted"] = llm_results
                logger.info("LLM fallback extracted %d facts", len(llm_results))
        except Exception as e:
            logger.debug("LLM fallback failed (non-fatal): %s", e)
    
    # v0.11.0-fix6: Periodic background decay
    _extraction_call_count += 1
    if _extraction_call_count >= _DECAY_EVERY_N_CALLS:
        _extraction_call_count = 0
        try:
            decay_results = run_memory_decay(memory_manager)
            total_changes = (
                decay_results.get("decayed_salience", 0) +
                decay_results.get("marked_stale", 0) +
                decay_results.get("archived", 0)
            )
            if total_changes > 0:
                logger.info("Background decay processed %d memories", total_changes)
                results["decay_ran"] = True
        except Exception as e:
            logger.debug("Background decay error (non-fatal): %s", e)
    
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
    
    # v0.11.0-fix6: LLM and embedding features
    "llm_extract_facts",
    "semantic_search_memories",
]


# =============================================================================
# FIX 3: LLM EXTRACTION FALLBACK
# =============================================================================

# Cache for LLM client to avoid repeated initialization
_llm_client_cache = None


def _get_llm_client():
    """Get or create LLM client for extraction."""
    global _llm_client_cache
    if _llm_client_cache is not None:
        return _llm_client_cache
    
    try:
        from backend.llm_client import LLMClient
        _llm_client_cache = LLMClient()
        return _llm_client_cache
    except Exception as e:
        logger.debug("LLM client not available: %s", e)
        return None


def llm_extract_facts(
    user_text: str,
    memory_manager: "MemoryManager",
    module_tag: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Use LLM to extract personal facts when regex patterns fail.
    
    v0.11.0-fix6: LLM fallback for smarter extraction.
    
    This is called when regex extraction finds nothing but the message
    might still contain useful information.
    
    Args:
        user_text: User's message
        memory_manager: MemoryManager instance
        module_tag: Optional module context
    
    Returns:
        List of extracted and stored memory dicts
    """
    if not user_text or len(user_text) < 20:
        return []
    
    # Skip if text is a question or command
    text_lower = user_text.lower().strip()
    if text_lower.startswith(('#', '?', 'what', 'how', 'why', 'when', 'where', 'who', 'can you', 'could you')):
        return []
    
    client = _get_llm_client()
    if not client:
        return []
    
    stored = []
    
    try:
        # Use a cheap/fast model for extraction
        extraction_prompt = """Extract personal facts from this message. Return JSON only.

Categories:
- identity: name, job title, employer, location, age, education
- preference: likes, dislikes, preferences, communication style
- goal: objectives, projects, learning goals

If no personal facts found, return: {"facts": []}

Otherwise return:
{"facts": [{"category": "identity|preference|goal", "fact": "extracted fact"}]}

Message: "{text}"

JSON response:"""

        response = client.chat(
            messages=[{"role": "user", "content": extraction_prompt.format(text=user_text[:500])}],
            system_prompt="You extract personal facts from messages. Return valid JSON only, no explanation.",
            model="gpt-4.1-mini",  # Use fast/cheap model
            max_tokens=200,
            command="llm_extract_facts",
        )
        
        response_text = response.get("content", "") or response.get("text", "")
        
        # Parse JSON response
        import json
        
        # Clean up response (remove markdown if present)
        response_text = response_text.strip()
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
        response_text = response_text.strip()
        
        try:
            data = json.loads(response_text)
            facts = data.get("facts", [])
        except json.JSONDecodeError:
            logger.debug("LLM extraction returned invalid JSON: %s", response_text[:100])
            return []
        
        # Store each extracted fact
        for fact_item in facts:
            if not isinstance(fact_item, dict):
                continue
            
            category = fact_item.get("category", "").lower()
            fact = fact_item.get("fact", "").strip()
            
            if not fact or len(fact) < 10:
                continue
            
            # Map category to tag
            if category == "identity":
                tag = "profile:identity"
            elif category == "preference":
                tag = "profile:preference"
            elif category == "goal":
                tag = "profile:goal"
            else:
                tag = "profile:general"
            
            # Check for duplicates/contradictions
            check_result = _check_duplicate_or_contradiction(memory_manager, fact, tag)
            
            if check_result["is_duplicate"]:
                continue
            
            if check_result["is_contradiction"]:
                update_result = _handle_contradiction(
                    memory_manager, fact,
                    check_result["conflicting_memory_id"],
                    tag, module_tag
                )
                if update_result:
                    stored.append(update_result)
                continue
            
            # Store new fact
            try:
                item = memory_manager.store(
                    payload=fact,
                    mem_type="semantic",
                    tags=[tag],
                    salience=0.85,  # Slightly lower than regex extraction
                    trace={"source": "llm_extraction"},
                    module_tag=module_tag,
                )
                logger.info("LLM extracted fact: id=%d tag=%s fact='%s'", item.id, tag, fact[:50])
                stored.append({"id": item.id, "tag": tag, "payload": fact, "source": "llm"})
            except Exception as e:
                logger.warning("Failed to store LLM-extracted fact: %s", e)
        
        return stored
        
    except Exception as e:
        logger.debug("LLM extraction failed (non-fatal): %s", e)
        return []


# =============================================================================
# FIX 4: EMBEDDING-BASED SEMANTIC SEARCH
# =============================================================================

# Cache for embedding model
_embedding_model_cache = None
_embeddings_available = None


def _check_embeddings_available() -> bool:
    """Check if sentence-transformers is available."""
    global _embeddings_available
    if _embeddings_available is not None:
        return _embeddings_available
    
    try:
        from sentence_transformers import SentenceTransformer
        _embeddings_available = True
        return True
    except ImportError:
        _embeddings_available = False
        logger.info("sentence-transformers not installed - using keyword search fallback")
        return False


def _get_embedding_model():
    """Get or create embedding model (lazy loading)."""
    global _embedding_model_cache
    
    if not _check_embeddings_available():
        return None
    
    if _embedding_model_cache is not None:
        return _embedding_model_cache
    
    try:
        from sentence_transformers import SentenceTransformer
        # Use a small, fast model
        _embedding_model_cache = SentenceTransformer('all-MiniLM-L6-v2')
        logger.info("Loaded embedding model: all-MiniLM-L6-v2")
        return _embedding_model_cache
    except Exception as e:
        logger.warning("Failed to load embedding model: %s", e)
        return None


def _compute_embedding(text: str) -> Optional[List[float]]:
    """Compute embedding for text."""
    model = _get_embedding_model()
    if model is None:
        return None
    
    try:
        embedding = model.encode(text, convert_to_numpy=True)
        return embedding.tolist()
    except Exception as e:
        logger.debug("Failed to compute embedding: %s", e)
        return None


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two vectors."""
    import math
    
    dot_product = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    
    if norm_a == 0 or norm_b == 0:
        return 0.0
    
    return dot_product / (norm_a * norm_b)


def semantic_search_memories(
    query: str,
    memory_manager: "MemoryManager",
    limit: int = 10,
    min_similarity: float = 0.3,
    mem_type: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> List[Tuple[Any, float]]:
    """
    Search memories using semantic similarity (embeddings).
    
    v0.11.0-fix6: Embedding-based search for better retrieval.
    
    Falls back to keyword search if sentence-transformers is not available.
    
    Args:
        query: Search query
        memory_manager: MemoryManager instance
        limit: Maximum results to return
        min_similarity: Minimum cosine similarity threshold
        mem_type: Optional filter by memory type
        tags: Optional filter by tags
    
    Returns:
        List of (memory_item, similarity_score) tuples, sorted by score descending
    """
    if not query or not memory_manager:
        return []
    
    # Try embedding-based search first
    if _check_embeddings_available():
        query_embedding = _compute_embedding(query)
        
        if query_embedding is not None:
            try:
                # Get all candidate memories
                candidates = memory_manager.recall(
                    mem_type=mem_type,
                    tags=tags,
                    limit=500,  # Get more candidates for semantic filtering
                )
                
                scored_results = []
                
                for item in candidates:
                    payload = getattr(item, 'payload', '') or ''
                    if not payload:
                        continue
                    
                    # Check if item has cached embedding
                    trace = getattr(item, 'trace', {}) or {}
                    cached_embedding = trace.get('embedding')
                    
                    if cached_embedding:
                        item_embedding = cached_embedding
                    else:
                        # Compute embedding on the fly
                        item_embedding = _compute_embedding(payload)
                        if item_embedding is None:
                            continue
                    
                    # Compute similarity
                    similarity = _cosine_similarity(query_embedding, item_embedding)
                    
                    if similarity >= min_similarity:
                        scored_results.append((item, similarity))
                
                # Sort by similarity descending
                scored_results.sort(key=lambda x: x[1], reverse=True)
                
                logger.debug("Semantic search found %d results for '%s'", len(scored_results[:limit]), query[:30])
                return scored_results[:limit]
                
            except Exception as e:
                logger.debug("Semantic search failed, falling back to keywords: %s", e)
    
    # Fallback to keyword search
    return search_by_keywords(query, memory_manager, limit=limit)


def get_relevant_semantic_memories_v2(
    memory_manager: "MemoryManager",
    user_text: Optional[str] = None,
    module_tag: Optional[str] = None,
    limit: int = 5,
) -> List[Any]:
    """
    Get semantically relevant memories for the current context.
    
    v0.11.0-fix6: Uses embedding search when user_text is provided.
    
    Args:
        memory_manager: MemoryManager instance
        user_text: Optional user text for semantic matching
        module_tag: Optional module for scoping
        limit: Maximum memories to return
    
    Returns:
        List of relevant memory items
    """
    if user_text and _check_embeddings_available():
        # Use semantic search
        results = semantic_search_memories(
            query=user_text,
            memory_manager=memory_manager,
            limit=limit,
            min_similarity=0.35,
            mem_type="semantic",
        )
        # Extract just the items (not scores)
        memories = [item for item, score in results]
        
        # Touch these memories since they're being used
        _touch_memories(memory_manager, memories)
        
        return memories
    else:
        # Fallback to basic retrieval
        return get_relevant_semantic_memories(memory_manager, module_tag=module_tag, limit=limit)
