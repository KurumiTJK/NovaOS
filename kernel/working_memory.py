# kernel/working_memory.py
"""
v0.6.1 — Working Memory

Session-scoped conversational continuity for NovaOS.
Enables Nova to maintain context within a conversation like a human.

Working Memory:
- Tracks current topic, entities, and intent
- Enables pronoun resolution ("that", "it", "those")
- Supports multi-turn conversations
- Resets on topic shift, wizard start, or section menu

NOT stored to disk. NOT cross-session. NOT long-term memory.
Purely conversational state for natural dialogue flow.
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
import re
from datetime import datetime


# -----------------------------------------------------------------------------
# Working Memory State
# -----------------------------------------------------------------------------

@dataclass
class WorkingMemoryState:
    """
    Short-term conversational state for a single session.
    
    Attributes:
        last_topic: The current topic of conversation
        last_intent: High-level intent (question, planning, emotional, etc.)
        last_entities: Named entities or key concepts mentioned
        last_user_message: The previous user message
        last_nova_response: Nova's last response (for context)
        turn_count: Number of conversational turns in current topic
        topic_history: Recent topic shifts (for "go back to X")
        created_at: When this WM state was created
        last_updated: When WM was last updated
    """
    last_topic: Optional[str] = None
    last_intent: Optional[str] = None
    last_entities: List[str] = field(default_factory=list)
    last_user_message: Optional[str] = None
    last_nova_response: Optional[str] = None
    turn_count: int = 0
    topic_history: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    last_updated: datetime = field(default_factory=datetime.now)
    
    def clear(self) -> None:
        """Reset working memory (on topic shift, wizard, section menu)."""
        if self.last_topic:
            # Save to history before clearing
            self.topic_history.append(self.last_topic)
            if len(self.topic_history) > 5:
                self.topic_history = self.topic_history[-5:]
        
        self.last_topic = None
        self.last_intent = None
        self.last_entities = []
        self.last_user_message = None
        self.last_nova_response = None
        self.turn_count = 0
        self.last_updated = datetime.now()
    
    def update(
        self,
        message: str,
        topic: Optional[str] = None,
        intent: Optional[str] = None,
        entities: Optional[List[str]] = None,
        nova_response: Optional[str] = None,
    ) -> None:
        """Update working memory with new conversational turn."""
        self.last_user_message = message
        self.turn_count += 1
        self.last_updated = datetime.now()
        
        if topic:
            self.last_topic = topic
        if intent:
            self.last_intent = intent
        if entities:
            # Merge entities, keeping recent ones
            combined = list(set(self.last_entities + entities))
            self.last_entities = combined[-10:]  # Keep max 10
        if nova_response:
            self.last_nova_response = nova_response
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize for debugging/logging."""
        return {
            "last_topic": self.last_topic,
            "last_intent": self.last_intent,
            "last_entities": self.last_entities,
            "last_user_message": self.last_user_message,
            "turn_count": self.turn_count,
            "topic_history": self.topic_history,
        }
    
    def has_context(self) -> bool:
        """Check if WM has meaningful context."""
        return self.last_topic is not None or self.turn_count > 0


# -----------------------------------------------------------------------------
# Topic & Intent Extraction
# -----------------------------------------------------------------------------

# Intent patterns (high-level categorization)
INTENT_PATTERNS = {
    "question": [
        r"^(what|who|where|when|why|how|which|can|could|would|should|is|are|do|does|did)\b",
        r"\?$",
        r"\bwhat do you think\b",
        r"\bdo you know\b",
    ],
    "planning": [
        r"\b(plan|planning|schedule|organize|prepare|need to|going to|want to)\b",
        r"\b(next steps?|action items?|to.?do)\b",
        r"\b(tomorrow|this week|later|soon)\b",
    ],
    "emotional": [
        r"\bi('m| am) (feeling|so|really|kind of|kinda)\b",
        r"\b(stressed|anxious|happy|sad|frustrated|excited|worried|overwhelmed)\b",
        r"\b(ugh|oof|damn|shit|fuck|yay|wow)\b",
        r"\bfeeling (good|bad|great|terrible|off|weird)\b",
    ],
    "reflection": [
        r"\b(thinking about|reflecting on|wondering|considering)\b",
        r"\b(been thinking|thought about|realize|noticed)\b",
        r"\b(makes sense|interesting|curious)\b",
    ],
    "opinion": [
        r"\b(think|believe|feel like|seems like|sounds like)\b",
        r"\b(in my opinion|personally|honestly)\b",
        r"\b(agree|disagree|prefer|like|dislike)\b",
    ],
    "request": [
        r"\b(help|assist|show|tell|give|explain)\b",
        r"\b(can you|could you|would you|please)\b",
    ],
    "continuation": [
        r"^(yeah|yes|no|right|exactly|sure|ok|okay|hmm|and|but|so|also)\b",
        r"^(what about|how about|speaking of)\b",
        r"\b(that|it|this|those|these|the one)\b",
    ],
}

# Common entity patterns
ENTITY_PATTERNS = {
    "person": r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b",  # Capitalized names
    "project": r"\b(project|task|work|job|assignment)\s+(\w+)\b",
    "time": r"\b(today|tomorrow|yesterday|monday|tuesday|wednesday|thursday|friday|saturday|sunday|next week|this week)\b",
    "topic_marker": r"\b(about|regarding|concerning|on the topic of)\s+(.+?)(?:\.|,|$)",
}

# Pronoun patterns that need resolution
PRONOUN_PATTERNS = [
    r"\b(that|it|this)\b(?!\s+(is|was|will|would|could|should|has|have|had))",
    r"\b(those|these|they|them)\b",
    r"\bthe (one|earlier|previous|last)\b",
    r"\b(same|that one|the other)\b",
]


def extract_intent(text: str) -> str:
    """
    Extract high-level intent from user message.
    
    Returns: question, planning, emotional, reflection, opinion, request, continuation, or statement
    """
    text_lower = text.lower().strip()
    
    # Check each intent category
    for intent, patterns in INTENT_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return intent
    
    return "statement"  # Default


def extract_topic(text: str, previous_topic: Optional[str] = None) -> Optional[str]:
    """
    Extract or infer the topic of conversation.
    
    Simple heuristic-based extraction:
    1. Look for explicit topic markers ("about X", "regarding X")
    2. Look for main nouns/concepts
    3. Fall back to previous topic if continuation detected
    """
    text_lower = text.lower().strip()
    
    # If it's a continuation, ALWAYS keep previous topic
    if is_continuation(text) and previous_topic:
        return previous_topic
    
    # Check for explicit topic markers
    topic_match = re.search(r"\b(about|regarding|concerning)\s+(.+?)(?:\.|,|$|\?)", text_lower)
    if topic_match:
        return topic_match.group(2).strip()[:50]  # Cap at 50 chars
    
    # Check for "let's talk about X" patterns
    talk_match = re.search(r"\b(talk|discuss|chat)\s+about\s+(.+?)(?:\.|,|$|\?)", text_lower)
    if talk_match:
        return talk_match.group(2).strip()[:50]
    
    # Extract key nouns (simple heuristic)
    # Remove common words and get the main subject
    stop_words = {
        "i", "me", "my", "you", "your", "we", "our", "it", "this", "that",
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "can", "may", "might", "must", "shall", "to", "of", "in",
        "for", "on", "with", "at", "by", "from", "as", "into", "through",
        "during", "before", "after", "above", "below", "between", "under",
        "again", "further", "then", "once", "here", "there", "when", "where",
        "why", "how", "all", "each", "few", "more", "most", "other", "some",
        "such", "no", "nor", "not", "only", "own", "same", "so", "than",
        "too", "very", "just", "and", "but", "if", "or", "because", "as",
        "until", "while", "although", "though", "even", "also", "still",
        "already", "always", "never", "often", "sometimes", "usually",
        "really", "actually", "basically", "honestly", "literally",
        "yeah", "yes", "no", "okay", "ok", "sure", "right", "well",
        "um", "uh", "hmm", "like", "know", "think", "want", "need",
        "get", "got", "make", "go", "going", "come", "say", "said",
    }
    
    words = re.findall(r'\b[a-z]+\b', text_lower)
    content_words = [w for w in words if w not in stop_words and len(w) > 2]
    
    if content_words:
        # Return first 2-3 content words as topic
        topic_words = content_words[:3]
        return " ".join(topic_words)
    
    return previous_topic  # Fall back to previous


def extract_entities(text: str) -> List[str]:
    """
    Extract named entities and key concepts from text.
    
    Simple pattern-based extraction (no ML).
    """
    entities = []
    
    # Extract capitalized names (likely proper nouns)
    names = re.findall(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b', text)
    # Filter out sentence starters
    names = [n for n in names if not text.strip().startswith(n)]
    entities.extend(names[:3])  # Max 3 names
    
    # Extract quoted phrases
    quoted = re.findall(r'"([^"]+)"', text)
    entities.extend(quoted[:2])
    
    # Extract time references
    times = re.findall(
        r'\b(today|tomorrow|yesterday|monday|tuesday|wednesday|thursday|friday|saturday|sunday|next week|this week|this month)\b',
        text.lower()
    )
    entities.extend(times)
    
    # Deduplicate and limit
    seen = set()
    unique = []
    for e in entities:
        e_lower = e.lower()
        if e_lower not in seen:
            seen.add(e_lower)
            unique.append(e)
    
    return unique[:5]  # Max 5 entities


def is_continuation(text: str) -> bool:
    """
    Detect if message is a continuation of previous topic.
    
    Looks for:
    - Pronouns referring to previous context
    - Continuation markers (yeah, and, but, so)
    - Short responses that need context
    """
    text_lower = text.lower().strip()
    
    # Short messages are often continuations
    if len(text_lower.split()) <= 3:
        return True
    
    # Check for continuation starters
    continuation_starters = [
        r"^(yeah|yes|no|right|exactly|sure|ok|okay|hmm|mhm)\b",
        r"^(and|but|so|also|plus|or)\b",
        r"^(what about|how about|speaking of)\b",
        r"^(that|it|this|those|these)\b",
    ]
    
    for pattern in continuation_starters:
        if re.match(pattern, text_lower):
            return True
    
    # Check for pronouns that need resolution
    for pattern in PRONOUN_PATTERNS:
        if re.search(pattern, text_lower):
            return True
    
    return False


def detect_topic_shift(
    current_message: str,
    wm_state: WorkingMemoryState,
) -> bool:
    """
    Detect if user has shifted to a new topic.
    
    Returns True if topic has clearly changed.
    """
    if not wm_state.has_context():
        return False  # No previous context, can't be a shift
    
    text_lower = current_message.lower().strip()
    
    # Explicit shift markers
    shift_markers = [
        r"\b(anyway|moving on|different topic|new topic|change of subject)\b",
        r"\b(forget about that|never mind|forget it)\b",
        r"\b(let's talk about|can we discuss|I want to ask about)\b",
        r"\b(completely different|unrelated|on another note)\b",
    ]
    
    for pattern in shift_markers:
        if re.search(pattern, text_lower):
            return True
    
    # If message is long and shares no entities with previous context
    if len(text_lower.split()) > 10:
        current_entities = set(e.lower() for e in extract_entities(current_message))
        previous_entities = set(e.lower() for e in wm_state.last_entities)
        previous_topic_words = set(wm_state.last_topic.lower().split()) if wm_state.last_topic else set()
        
        # No overlap = likely topic shift
        if not (current_entities & previous_entities) and not (current_entities & previous_topic_words):
            # But only if it's not a clear continuation
            if not is_continuation(current_message):
                return True
    
    return False


# -----------------------------------------------------------------------------
# Working Memory Manager
# -----------------------------------------------------------------------------

class WorkingMemoryManager:
    """
    Manages working memory state for all sessions.
    """
    
    def __init__(self):
        self._states: Dict[str, WorkingMemoryState] = {}
    
    def get_state(self, session_id: str) -> WorkingMemoryState:
        """Get or create working memory state for session."""
        if session_id not in self._states:
            self._states[session_id] = WorkingMemoryState()
        return self._states[session_id]
    
    def clear_state(self, session_id: str) -> None:
        """Clear working memory for session."""
        if session_id in self._states:
            self._states[session_id].clear()
    
    def delete_state(self, session_id: str) -> None:
        """Completely remove session state."""
        if session_id in self._states:
            del self._states[session_id]
    
    def process_message(
        self,
        session_id: str,
        message: str,
    ) -> Dict[str, Any]:
        """
        Process a new message and update working memory.
        
        Returns enriched context for persona.
        """
        wm = self.get_state(session_id)
        
        # Check for topic shift
        if detect_topic_shift(message, wm):
            wm.clear()
        
        # Extract from current message
        intent = extract_intent(message)
        topic = extract_topic(message, wm.last_topic)
        entities = extract_entities(message)
        is_cont = is_continuation(message)
        
        # Build enriched context
        context = {
            "is_continuation": is_cont,
            "previous_topic": wm.last_topic,
            "previous_intent": wm.last_intent,
            "previous_entities": wm.last_entities.copy(),
            "previous_message": wm.last_user_message,
            "previous_response": wm.last_nova_response,
            "turn_count": wm.turn_count,
            "current_topic": topic,
            "current_intent": intent,
            "current_entities": entities,
            "topic_history": wm.topic_history.copy(),
        }
        
        # Update WM state
        wm.update(
            message=message,
            topic=topic,
            intent=intent,
            entities=entities,
        )
        
        return context
    
    def record_response(self, session_id: str, response: str) -> None:
        """Record Nova's response for context."""
        wm = self.get_state(session_id)
        wm.last_nova_response = response[:500]  # Cap at 500 chars
        wm.last_updated = datetime.now()


# Global manager instance
_wm_manager = WorkingMemoryManager()


def get_working_memory(session_id: str) -> WorkingMemoryState:
    """Get working memory state for session."""
    return _wm_manager.get_state(session_id)


def process_for_persona(session_id: str, message: str) -> Dict[str, Any]:
    """
    Process message and return enriched context for persona fallback.
    
    This is the main entry point called before persona fallback.
    """
    return _wm_manager.process_message(session_id, message)


def record_nova_response(session_id: str, response: str) -> None:
    """Record Nova's response after persona generates it."""
    _wm_manager.record_response(session_id, response)


def clear_working_memory(session_id: str) -> None:
    """Clear working memory (on reset, wizard start, section menu)."""
    _wm_manager.clear_state(session_id)


def delete_working_memory(session_id: str) -> None:
    """Completely remove working memory for session."""
    _wm_manager.delete_state(session_id)
