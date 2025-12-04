# kernel/nova_wm.py
"""
NovaOS v0.7.7 — Working Memory Engine (NovaWM)

A robust conversational memory system that makes Nova feel "alive" and continuous.
Tracks entities, topics, pronouns, goals, and conversation state across turns.

v0.7.7 CHANGES:
- Enhanced group entity layer with explicit members list
- Group-aware context strings for behavior layer
- Event-specific recall ("what did Sarah say?")
- Topic merge when same label reappears
- #wm-groups command support

v0.7.6 CHANGES:
- WM Persistence Layer (Option B) with episodic snapshots
- wm_snapshot() for saving WM state to long-term memory
- wm_bridge_load_relevant() for rehydrating from snapshots
- Snapshot-aware context strings

v0.7.5 CHANGES:
- Automatic group detection from "X and Y" patterns
- Enhanced topic stack with tangent/return-to-topic triggers
- Group pronoun resolution ("they" → "Steven and Sarah")
- "Who are they again?" meta-question support
- WM/Behavior control knobs fully wired

v0.7.3 CHANGES:
- Topic stack for multi-topic navigation
- Group entity support
- Snapshot/restore for episodic memory

v0.7.1 CHANGES:
- Gender-aware pronoun resolution (he→masculine, she→feminine)
- Multi-candidate pronoun tracking instead of "last entity wins"
- Pronoun inference from context ("Steven...he seemed" → Steven is masculine)
- Improved #wm-debug output showing per-pronoun-group mappings

Key Capabilities:
- Entity tracking (people, places, objects, concepts)
- Topic/thread management with active topic awareness
- Pronoun resolution ("he" → "Steven", "she" → "Sarah")
- Group entity support ("they" → "Steven and Sarah")
- Goal and unresolved question tracking
- Emotional tone awareness
- Turn-by-turn summaries with compression
- Context bundle generation for persona
- Episodic snapshot persistence (v0.7.6)

Lifecycle:
- Created per session
- Persists across turns within session
- Resets on new session or #reset
- Can snapshot to long-term memory (v0.7.6)

Usage:
    wm = NovaWorkingMemory(session_id)
    wm.update(user_message, assistant_response)
    context = wm.get_context_bundle()
    resolved = wm.resolve_pronoun("him")
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Set, Tuple
from enum import Enum
from datetime import datetime
import re
import json


# =============================================================================
# ENUMS & TYPES
# =============================================================================

class EntityType(Enum):
    """Types of entities that can be tracked."""
    PERSON = "person"
    PLACE = "place"
    OBJECT = "object"
    PROJECT = "project"
    ORGANIZATION = "organization"
    TIME = "time"
    CONCEPT = "concept"
    GROUP = "group"        # v0.7.3: Multiple people (e.g., "Steven and Sarah")
    UNKNOWN = "unknown"


class TopicStatus(Enum):
    """Status of a conversation topic."""
    ACTIVE = "active"
    PAUSED = "paused"
    RESOLVED = "resolved"
    ABANDONED = "abandoned"


class GoalStatus(Enum):
    """Status of a user goal."""
    ACTIVE = "active"
    ACHIEVED = "achieved"
    ABANDONED = "abandoned"
    BLOCKED = "blocked"


class EmotionalTone(Enum):
    """Detected emotional tone."""
    NEUTRAL = "neutral"
    POSITIVE = "positive"
    NEGATIVE = "negative"
    STRESSED = "stressed"
    CONFUSED = "confused"
    EXCITED = "excited"
    FRUSTRATED = "frustrated"
    UNCERTAIN = "uncertain"


class GenderHint(Enum):
    """
    v0.7.1: Gender hint for pronoun resolution.
    """
    MASCULINE = "masculine"      # he/him/his
    FEMININE = "feminine"        # she/her/hers
    NEUTRAL = "neutral"          # they/them/their (or unknown)
    OBJECT = "object"            # it/its/this/that


# =============================================================================
# PRONOUN GROUPS (v0.7.1)
# =============================================================================

# Pronoun families for gender-aware resolution
MASCULINE_PRONOUNS = {"he", "him", "his"}
FEMININE_PRONOUNS = {"she", "her", "hers"}
NEUTRAL_PRONOUNS = {"they", "them", "their"}
OBJECT_PRONOUNS = {"it", "its", "this", "that"}

# Map each pronoun to its gender hint
PRONOUN_TO_GENDER: Dict[str, GenderHint] = {
    "he": GenderHint.MASCULINE,
    "him": GenderHint.MASCULINE,
    "his": GenderHint.MASCULINE,
    "she": GenderHint.FEMININE,
    "her": GenderHint.FEMININE,
    "hers": GenderHint.FEMININE,
    "they": GenderHint.NEUTRAL,
    "them": GenderHint.NEUTRAL,
    "their": GenderHint.NEUTRAL,
    "it": GenderHint.OBJECT,
    "its": GenderHint.OBJECT,
    "this": GenderHint.OBJECT,
    "that": GenderHint.OBJECT,
}

# Pronoun to entity type mapping
PRONOUN_ENTITY_MAP = {
    "he": [EntityType.PERSON],
    "him": [EntityType.PERSON],
    "his": [EntityType.PERSON],
    "she": [EntityType.PERSON],
    "her": [EntityType.PERSON],
    "hers": [EntityType.PERSON],
    "they": [EntityType.PERSON, EntityType.ORGANIZATION],
    "them": [EntityType.PERSON, EntityType.ORGANIZATION],
    "their": [EntityType.PERSON, EntityType.ORGANIZATION],
    "it": [EntityType.PROJECT, EntityType.OBJECT, EntityType.CONCEPT],
    "its": [EntityType.PROJECT, EntityType.OBJECT, EntityType.CONCEPT],
    "this": [EntityType.PROJECT, EntityType.OBJECT, EntityType.CONCEPT],
    "that": [EntityType.PROJECT, EntityType.OBJECT, EntityType.CONCEPT],
}


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class WMEntity:
    """
    A tracked entity in working memory.
    
    v0.7.1: Added gender_hint for pronoun-aware resolution.
    v0.7.7: Added members list for GROUP entities.
    """
    id: str
    name: str
    entity_type: EntityType
    aliases: List[str] = field(default_factory=list)
    pronouns: List[str] = field(default_factory=list)
    gender_hint: GenderHint = GenderHint.NEUTRAL  # v0.7.1
    description: Optional[str] = None
    attributes: Dict[str, Any] = field(default_factory=dict)
    first_mentioned: int = 0
    last_mentioned: int = 0
    mention_count: int = 1
    confidence: float = 1.0
    source_text: Optional[str] = None
    members: Optional[List[str]] = None  # v0.7.7: For GROUP entities, list of member entity_ids
    
    def matches(self, query: str) -> bool:
        """Check if this entity matches a query string."""
        query_lower = query.lower().strip()
        if self.name.lower() == query_lower:
            return True
        if query_lower in [a.lower() for a in self.aliases]:
            return True
        if query_lower in [p.lower() for p in self.pronouns]:
            return True
        return False
    
    def add_alias(self, alias: str) -> None:
        """Add an alias if not already present."""
        if alias.lower() not in [a.lower() for a in self.aliases]:
            self.aliases.append(alias)
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize for storage/debugging."""
        result = {
            "id": self.id,
            "name": self.name,
            "type": self.entity_type.value,
            "aliases": self.aliases,
            "pronouns": self.pronouns,
            "gender_hint": self.gender_hint.value,
            "description": self.description,
            "attributes": self.attributes,
            "first_mentioned": self.first_mentioned,
            "last_mentioned": self.last_mentioned,
            "mention_count": self.mention_count,
            "confidence": self.confidence,
        }
        # v0.7.7: Include members for GROUP entities
        if self.members:
            result["members"] = self.members
        return result


@dataclass
class ReferentCandidate:
    """
    v0.7.1: A candidate entity for pronoun resolution with scoring.
    """
    entity_id: str
    entity_name: str
    score: float                    # Higher = better match
    last_mentioned: int             # Turn number
    gender_match: bool              # Does gender hint match pronoun?
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "entity_name": self.entity_name,
            "score": self.score,
            "last_mentioned": self.last_mentioned,
            "gender_match": self.gender_match,
        }


@dataclass
class PronounGroup:
    """
    v0.7.1: Tracks candidates for a pronoun group (he/him/his, she/her/hers, etc.)
    """
    group_name: str                             # "masculine", "feminine", "neutral", "object"
    pronouns: Set[str]                          # {"he", "him", "his"}
    candidates: List[ReferentCandidate] = field(default_factory=list)
    
    def get_best_candidate(self) -> Optional[ReferentCandidate]:
        """Get the highest-scoring candidate."""
        if not self.candidates:
            return None
        # Sort by: gender_match (True first), then score (desc), then recency (desc)
        sorted_candidates = sorted(
            self.candidates,
            key=lambda c: (c.gender_match, c.score, c.last_mentioned),
            reverse=True
        )
        return sorted_candidates[0]
    
    def add_candidate(self, candidate: ReferentCandidate) -> None:
        """Add or update a candidate."""
        # Remove existing candidate for same entity
        self.candidates = [c for c in self.candidates if c.entity_id != candidate.entity_id]
        self.candidates.append(candidate)
    
    def to_dict(self) -> Dict[str, Any]:
        best = self.get_best_candidate()
        return {
            "group": self.group_name,
            "pronouns": list(self.pronouns),
            "best_match": best.entity_name if best else None,
            "candidates": [c.to_dict() for c in self.candidates],
        }


@dataclass
class WMTopic:
    """A conversation topic or thread."""
    id: str
    name: str
    description: Optional[str] = None
    status: TopicStatus = TopicStatus.ACTIVE
    related_entities: List[str] = field(default_factory=list)
    parent_topic: Optional[str] = None
    first_mentioned: int = 0
    last_mentioned: int = 0
    key_points: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "status": self.status.value,
            "related_entities": self.related_entities,
            "parent_topic": self.parent_topic,
            "first_mentioned": self.first_mentioned,
            "last_mentioned": self.last_mentioned,
            "key_points": self.key_points,
        }


@dataclass
class WMGoal:
    """A user goal or intention detected in the conversation."""
    id: str
    description: str
    status: GoalStatus = GoalStatus.ACTIVE
    related_entities: List[str] = field(default_factory=list)
    related_topics: List[str] = field(default_factory=list)
    created_at: int = 0
    resolved_at: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "status": self.status.value,
            "related_entities": self.related_entities,
            "related_topics": self.related_topics,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
        }


@dataclass
class WMQuestion:
    """An unresolved question in the conversation."""
    id: str
    question: str
    asker: str = "user"
    turn_asked: int = 0
    turn_answered: Optional[int] = None
    answer: Optional[str] = None
    related_entities: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "question": self.question,
            "asker": self.asker,
            "turn_asked": self.turn_asked,
            "turn_answered": self.turn_answered,
            "answer": self.answer,
        }


@dataclass 
class WMTurnSummary:
    """A compressed summary of a conversation turn."""
    turn_number: int
    user_summary: str
    nova_summary: str
    entities_mentioned: List[str] = field(default_factory=list)
    topics_discussed: List[str] = field(default_factory=list)
    emotional_tone: EmotionalTone = EmotionalTone.NEUTRAL
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "turn": self.turn_number,
            "user": self.user_summary,
            "nova": self.nova_summary,
            "entities": self.entities_mentioned,
            "topics": self.topics_discussed,
            "tone": self.emotional_tone.value,
        }


# Legacy compatibility - keep for API stability
@dataclass
class PronounReferent:
    """Legacy structure - kept for backward compatibility."""
    pronoun: str
    entity_id: str
    confidence: float = 1.0
    set_at_turn: int = 0


# =============================================================================
# EXTRACTION PATTERNS
# =============================================================================

PERSON_PATTERNS = [
    (r"\b(?:talked?|speak|spoke|met|call(?:ed)?|email(?:ed)?|messag(?:ed)?|text(?:ed)?|contact(?:ed)?)\s+(?:to|with)?\s*([A-Z][a-z]+)\b", "communicated with"),
    (r"\b([A-Z][a-z]+)\s+(?:said|told|mention(?:ed)?|suggest(?:ed)?|ask(?:ed)?|want(?:ed)?s?|think(?:s)?|helped?|found)\b", "took action"),
    (r"\b([A-Z][a-z]+)\s+(?:is|was|are|were|seem(?:s|ed)?|look(?:s|ed)?|appear(?:s|ed)?)\b", "being described"),
    (r"\bmy\s+(?:friend|colleague|coworker|boss|manager|brother|sister|mom|dad|wife|husband|partner)\s+([A-Z][a-z]+)\b", "relation"),
    (r"\b([A-Z][a-z]+)'s\b", "possessive reference"),
    (r"\bwith\s+([A-Z][a-z]+)\b", "involved with"),
]

RELATIONAL_PERSON_PATTERNS = [
    (r"\b(my\s+(?:friend|colleague|coworker|boss|manager|brother|sister|mom|dad|mother|father|wife|husband|partner|doctor|therapist|coach))\b", "relation"),
    (r"\b(the\s+(?:guy|girl|man|woman|person|dude|lady))\b", "informal reference"),
    (r"\b(this\s+(?:guy|girl|man|woman|person|dude|lady))\b", "informal reference"),
]

PROJECT_PATTERNS = [
    (r"\b(?:the\s+)?(\w+)\s+project\b", "named project"),
    (r"\bproject\s+(\w+)\b", "named project"),
    (r"\b(house\s*hack(?:ing)?)\b", "strategy"),
    (r"\b(NovaOS|Nova)\s+(?:kernel|system|module|project)?\b", "software"),
    (r"\b(?:the|my|our)\s+(side\s+(?:business|project|hustle))\b", "venture"),
    (r"\b(?:the|my|our)\s+(startup|company|business)\b", "venture"),
]

TIME_PATTERNS = [
    r"\b(yesterday|today|tomorrow|last\s+(?:week|month|year)|this\s+(?:week|month|year)|next\s+(?:week|month|year))\b",
    r"\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b",
    r"\b(\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM)?)\b",
    r"\b(in\s+\d+\s+(?:days?|weeks?|months?|years?))\b",
    r"\b(\d{4})\b",
]

GOAL_PATTERNS = [
    (r"\b(?:I\s+)?need\s+to\s+figure\s+out\s+(.+?)(?:\.|$)", "figure out"),
    (r"\b(?:I\s+)?(?:want|need)\s+to\s+decide\s+(.+?)(?:\.|$)", "decide"),
    (r"\btrying\s+to\s+(.+?)(?:\.|$)", "trying to"),
    (r"\bplanning\s+(?:to|on)\s+(.+?)(?:\.|$)", "planning"),
]

EMOTIONAL_PATTERNS = {
    EmotionalTone.STRESSED: [r"\b(stressed|anxious|worried|overwhelmed|freaking out)\b"],
    EmotionalTone.CONFUSED: [r"\b(confused|lost|unsure|don't understand|unclear)\b"],
    EmotionalTone.FRUSTRATED: [r"\b(frustrated|annoyed|irritated|pissed|angry)\b"],
    EmotionalTone.EXCITED: [r"\b(excited|pumped|stoked|thrilled|can't wait)\b"],
    EmotionalTone.POSITIVE: [r"\b(happy|great|good|awesome|fantastic|wonderful)\b"],
    EmotionalTone.NEGATIVE: [r"\b(sad|bad|terrible|awful|horrible|sucks)\b"],
    EmotionalTone.UNCERTAIN: [r"\b(maybe|perhaps|not sure|might|possibly|idk|dunno)\b"],
}

NOT_NAMES = {
    "i", "you", "we", "they", "he", "she", "it", "me", "him", "her", "us", "them",
    "nova", "novaos", "claude", "gpt", "chatgpt",
    "the", "a", "an", "this", "that", "these", "those",
    "what", "when", "where", "why", "how", "who", "which",
    "yes", "no", "yeah", "yep", "nope", "okay", "ok", "sure", "right", "well",
    "should", "would", "could", "can", "will", "may", "might", "must",
    "anyway", "actually", "basically", "honestly", "really", "literally",
    "think", "know", "want", "need", "like", "feel", "see", "get", "got",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june", "july", 
    "august", "september", "october", "november", "december",
    "today", "tomorrow", "yesterday",
}

# v0.7.1: Gender inference patterns
# These patterns help infer gender from context
MASCULINE_HINT_PATTERNS = [
    r"\b([A-Z][a-z]+)\s*(?:\.\.\.|,|;)?\s*[Hh]e\b",        # "Steven...he" or "Steven, he"
    r"\b[Hh]e\s+(?:is|was|seems?|said|told|asked)\s+[A-Z][a-z]+\b",  # "he is Steven"
    r"\bmy\s+(?:brother|dad|father|husband|boyfriend|son)\s+([A-Z][a-z]+)\b",  # "my brother Steven"
    r"\b(?:guy|man|dude|gentleman)\s+(?:named\s+)?([A-Z][a-z]+)\b",  # "guy named Steven"
]

FEMININE_HINT_PATTERNS = [
    r"\b([A-Z][a-z]+)\s*(?:\.\.\.|,|;)?\s*[Ss]he\b",        # "Sarah...she" or "Sarah, she"
    r"\b[Ss]he\s+(?:is|was|seems?|said|told|asked)\s+[A-Z][a-z]+\b",  # "she is Sarah"
    r"\bmy\s+(?:sister|mom|mother|wife|girlfriend|daughter)\s+([A-Z][a-z]+)\b",  # "my sister Sarah"
    r"\b(?:girl|woman|lady|gal)\s+(?:named\s+)?([A-Z][a-z]+)\b",  # "woman named Sarah"
]

# =============================================================================
# v0.7.5 — GROUP DETECTION PATTERNS
# =============================================================================

# Pattern to detect "X and Y" group references
GROUP_DETECTION_PATTERN = re.compile(
    r"\b([A-Z][a-z]+)\s+and\s+([A-Z][a-z]+)\b"
)

# Pattern with "both" qualifier
GROUP_BOTH_PATTERN = re.compile(
    r"\b([A-Z][a-z]+)\s+and\s+([A-Z][a-z]+)\s+(?:both|together)\b"
)

# =============================================================================
# v0.7.5 — TOPIC TANGENT/RETURN PATTERNS  
# =============================================================================

# Patterns that indicate starting a tangent (push current topic)
TANGENT_START_PATTERNS = [
    (r"^side\s+note[,:\-—]?\s*", "side_note"),
    (r"^quick\s+tangent[,:\-—]?\s*", "quick_tangent"),
    (r"^small\s+tangent[,:\-—]?\s*", "small_tangent"),
    (r"^different\s+question[,:\-—]?\s*", "different_question"),
    (r"^new\s+topic[,:\-—]?\s*", "new_topic"),
    (r"^on\s+another\s+note[,:\-—]?\s*", "another_note"),
    (r"^totally\s+unrelated[,:\-—]?\s*", "unrelated"),
    (r"^off\s+topic[,:\-—]?\s*", "off_topic"),
    (r"^random\s+(?:question|thought)[,:\-—]?\s*", "random"),
    (r"^real\s+quick[,:\-—]?\s*", "real_quick"),
]

# Patterns that indicate returning to previous topic (pop from stack)
TOPIC_RETURN_PATTERNS = [
    (r"^anyway[,\-—]?\s+back\s+to\b", "anyway_back"),
    (r"^back\s+to\s+(?:the\s+)?(\w+)", "back_to"),
    (r"^where\s+were\s+we\s*(?:again)?\s*\??", "where_were_we"),
    (r"^let'?s\s+(?:go\s+)?back\s+to\b", "lets_back"),
    (r"^returning\s+to\b", "returning_to"),
    (r"^so\s+anyway[,\-—]?\s*", "so_anyway"),
    (r"^getting\s+back\s+to\b", "getting_back"),
    (r"^as\s+(?:i|we)\s+(?:was|were)\s+saying\b", "as_i_was_saying"),
]

# =============================================================================
# v0.7.5 — META-QUESTION PATTERNS
# =============================================================================

META_QUESTION_PATTERNS = [
    # Topic recall
    (r"what\s+(?:were\s+we|was\s+i)\s+(?:talking|discussing)\s+about", "topic_recall"),
    (r"what\s+(?:were\s+we|was\s+i)\s+saying", "topic_recall"),
    (r"where\s+did\s+we\s+leave\s+off", "topic_recall"),
    
    # Entity recall
    (r"what\s+do\s+you\s+remember\s+about\s+(\w+)", "entity_recall"),
    (r"what\s+did\s+i\s+tell\s+you\s+about\s+(\w+)", "entity_recall"),
    (r"what\s+do\s+(?:i|we)\s+know\s+about\s+(\w+)", "entity_recall"),
    
    # Person/group recall
    (r"who\s+(?:were\s+we|was\s+i)\s+discussing\s*(?:again)?", "person_recall"),
    (r"who\s+are\s+they\s*(?:again)?", "group_recall"),
    (r"who\s+is\s+(\w+)\s*(?:again)?", "person_recall"),
    
    # Context recall
    (r"what'?s\s+the\s+context\s*(?:again)?", "context_recall"),
    (r"catch\s+me\s+up", "context_recall"),
    (r"where\s+are\s+we\s*\??", "context_recall"),
    
    # v0.7.7: Event-specific recall (MUST be before generic reminder)
    (r"what\s+did\s+(\w+)\s+say", "event_recall_said"),
    (r"what\s+did\s+(\w+)\s+do", "event_recall_did"),
    (r"what\s+did\s+(\w+)\s+(?:suggest|recommend)", "event_recall_suggested"),
    (r"what\s+did\s+(\w+)\s+(?:ask|question)", "event_recall_asked"),
    (r"remind\s+me\s+what\s+(\w+)\s+said", "event_recall_said"),
    
    # Generic reminder (comes AFTER event recall patterns)
    (r"remind\s+me\s+(?:who|what)\s+(\w+)", "reminder"),
]


# =============================================================================
# WORKING MEMORY CLASS
# =============================================================================

class NovaWorkingMemory:
    """
    The main Working Memory engine for NovaOS.
    
    v0.7.1: Gender-aware pronoun resolution with multi-candidate tracking.
    """
    
    def __init__(self, session_id: str, max_history: int = 30):
        self.session_id = session_id
        self.max_history = max_history
        
        # Core state
        self.entities: Dict[str, WMEntity] = {}
        self.topics: Dict[str, WMTopic] = {}
        self.goals: Dict[str, WMGoal] = {}
        self.questions: Dict[str, WMQuestion] = {}
        
        # v0.7.1: Pronoun groups instead of flat referents
        self.pronoun_groups: Dict[str, PronounGroup] = {
            "masculine": PronounGroup("masculine", MASCULINE_PRONOUNS),
            "feminine": PronounGroup("feminine", FEMININE_PRONOUNS),
            "neutral": PronounGroup("neutral", NEUTRAL_PRONOUNS),
            "object": PronounGroup("object", OBJECT_PRONOUNS),
        }
        
        # Legacy referents for backward compatibility
        self.referents: Dict[str, PronounReferent] = {}
        
        # Conversation tracking
        self.turn_count: int = 0
        self.turn_history: List[WMTurnSummary] = []
        self.last_turn_summary: Optional[WMTurnSummary] = None
        
        # Active state
        self.active_topic_id: Optional[str] = None
        self.topic_stack: List[str] = []  # v0.7.3: For multi-topic navigation
        self.emotional_tone: EmotionalTone = EmotionalTone.NEUTRAL
        
        # v0.7.3: Group entities (e.g., "Steven and Sarah")
        self.groups: Dict[str, List[str]] = {}  # group_entity_id → member_entity_ids
        
        # v0.7.6: Snapshot/persistence tracking
        self.snapshots_saved: List[str] = []  # List of snapshot labels saved this session
        self.snapshots_loaded: List[int] = []  # Memory IDs loaded into this session
        self.rehydrated_from: Optional[int] = None  # Memory ID if rehydrated
        
        # v0.7.7: Event tracking for recall
        self.entity_events: Dict[str, List[Dict[str, Any]]] = {}  # entity_id → list of events
        
        # Timestamps
        self.created_at: datetime = datetime.now()
        self.last_updated: datetime = datetime.now()
        
        # ID counters
        self._entity_counter = 0
        self._topic_counter = 0
        self._goal_counter = 0
        self._question_counter = 0
        self._group_counter = 0  # v0.7.3
        self._snapshot_counter = 0  # v0.7.6
    
    # =========================================================================
    # ID GENERATION
    # =========================================================================
    
    def _gen_entity_id(self) -> str:
        self._entity_counter += 1
        return f"e{self._entity_counter}"
    
    def _gen_topic_id(self) -> str:
        self._topic_counter += 1
        return f"t{self._topic_counter}"
    
    def _gen_goal_id(self) -> str:
        self._goal_counter += 1
        return f"g{self._goal_counter}"
    
    def _gen_question_id(self) -> str:
        self._question_counter += 1
        return f"q{self._question_counter}"
    
    # =========================================================================
    # MAIN UPDATE API
    # =========================================================================
    
    def update(self, user_message: str, nova_response: Optional[str] = None) -> Dict[str, Any]:
        """
        Update working memory with a new conversation turn.
        """
        self.turn_count += 1
        self.last_updated = datetime.now()
        
        results = {
            "turn": self.turn_count,
            "entities_extracted": [],
            "topics_extracted": [],
            "goals_detected": [],
            "questions_detected": [],
            "pronouns_resolved": {},
            "emotional_tone": None,
            "gender_inferences": [],  # v0.7.1
            "groups_detected": [],    # v0.7.5
            "tangent_detected": None, # v0.7.5
            "return_detected": None,  # v0.7.5
        }
        
        # v0.7.5: Check for tangent/return patterns FIRST (before entity extraction)
        tangent_result = self._check_tangent_patterns(user_message)
        if tangent_result:
            results["tangent_detected"] = tangent_result
        
        return_result = self._check_return_patterns(user_message)
        if return_result:
            results["return_detected"] = return_result
        
        # 1. Extract entities from user message
        extracted_entities = self._extract_entities(user_message)
        for entity in extracted_entities:
            self._add_or_update_entity(entity)
            results["entities_extracted"].append(entity.name)
        
        # 2. v0.7.1: Infer gender from context AFTER entities are added
        gender_inferences = self._infer_gender_from_context(user_message)
        results["gender_inferences"] = gender_inferences
        
        # 3. v0.7.5: Detect groups from "X and Y" patterns
        groups_detected = self._detect_groups(user_message)
        for group_id in groups_detected:
            if group_id in self.entities:
                results["groups_detected"].append(self.entities[group_id].name)
        
        # 4. Extract topics
        extracted_topics = self._extract_topics(user_message)
        for topic in extracted_topics:
            self._add_or_update_topic(topic)
            results["topics_extracted"].append(topic.name)
        
        # 5. Detect goals/intentions
        detected_goals = self._extract_goals(user_message)
        for goal in detected_goals:
            self._add_goal(goal)
            results["goals_detected"].append(goal.description)
        
        # 6. Detect questions
        detected_questions = self._extract_questions(user_message)
        for question in detected_questions:
            self._add_question(question)
            results["questions_detected"].append(question.question)
        
        # 7. Resolve pronouns in the message (and update last_mentioned)
        pronouns_found = self._find_pronouns(user_message)
        for pronoun in pronouns_found:
            resolved = self.resolve_pronoun(pronoun)
            if resolved:
                results["pronouns_resolved"][pronoun] = resolved.name
                # Update the entity's last_mentioned
                if resolved.id in self.entities:
                    self.entities[resolved.id].last_mentioned = self.turn_count
        
        # 8. Detect emotional tone
        tone = self._detect_emotional_tone(user_message)
        self.emotional_tone = tone
        results["emotional_tone"] = tone.value
        
        # 9. Update active topic
        self._update_active_topic()
        
        # 10. Create turn summary
        user_summary = self._summarize_message(user_message)
        nova_summary = self._summarize_message(nova_response) if nova_response else ""
        
        entity_ids = [e.id for e in extracted_entities]
        topic_ids = [t.id for t in extracted_topics]
        
        turn_summary = WMTurnSummary(
            turn_number=self.turn_count,
            user_summary=user_summary,
            nova_summary=nova_summary,
            entities_mentioned=entity_ids,
            topics_discussed=topic_ids,
            emotional_tone=tone,
        )
        
        self.last_turn_summary = turn_summary
        self.turn_history.append(turn_summary)
        
        # Compress history if too long
        if len(self.turn_history) > self.max_history:
            self._compress_history()
        
        return results
    
    def record_nova_response(self, response: str) -> None:
        """Record Nova's response after it's generated."""
        if self.last_turn_summary:
            self.last_turn_summary.nova_summary = self._summarize_message(response)
    
    # =========================================================================
    # ENTITY MANAGEMENT
    # =========================================================================
    
    def _extract_entities(self, text: str) -> List[WMEntity]:
        """Extract entities from text."""
        entities = []
        seen_names = set()
        
        # Extract person names
        for pattern, context in PERSON_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                name = match.group(1)
                name_lower = name.lower()
                
                if name_lower in NOT_NAMES or name_lower in seen_names:
                    continue
                if len(name) < 2:
                    continue
                
                seen_names.add(name_lower)
                
                entity = WMEntity(
                    id=self._gen_entity_id(),
                    name=name,
                    entity_type=EntityType.PERSON,
                    description=context,
                    pronouns=[],  # Will be set based on gender inference
                    gender_hint=GenderHint.NEUTRAL,  # Default, will update
                    first_mentioned=self.turn_count,
                    last_mentioned=self.turn_count,
                    source_text=match.group(0),
                )
                entities.append(entity)
        
        # Extract relational references
        for pattern, context in RELATIONAL_PERSON_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                ref = match.group(1)
                ref_lower = ref.lower()
                
                if ref_lower in seen_names:
                    continue
                
                seen_names.add(ref_lower)
                
                # Infer gender from relational term
                gender = GenderHint.NEUTRAL
                if any(term in ref_lower for term in ["brother", "dad", "father", "husband", "boyfriend", "son", "guy", "man", "dude"]):
                    gender = GenderHint.MASCULINE
                elif any(term in ref_lower for term in ["sister", "mom", "mother", "wife", "girlfriend", "daughter", "girl", "woman", "lady", "gal"]):
                    gender = GenderHint.FEMININE
                
                entity = WMEntity(
                    id=self._gen_entity_id(),
                    name=ref,
                    entity_type=EntityType.PERSON,
                    description=context,
                    pronouns=[],
                    gender_hint=gender,
                    first_mentioned=self.turn_count,
                    last_mentioned=self.turn_count,
                    source_text=match.group(0),
                )
                entities.append(entity)
        
        # Extract projects
        seen_projects = set()
        for pattern, context in PROJECT_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                name = match.group(1).strip()
                name_lower = name.lower()
                
                if name_lower in NOT_NAMES or name_lower in seen_projects:
                    continue
                if len(name) < 2:
                    continue
                
                seen_projects.add(name_lower)
                
                entity = WMEntity(
                    id=self._gen_entity_id(),
                    name=name,
                    entity_type=EntityType.PROJECT,
                    description=context,
                    pronouns=["it", "its", "this", "that"],
                    gender_hint=GenderHint.OBJECT,
                    first_mentioned=self.turn_count,
                    last_mentioned=self.turn_count,
                    source_text=match.group(0),
                )
                entities.append(entity)
        
        # Extract time references
        for pattern in TIME_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                time_ref = match.group(1) if match.lastindex else match.group(0)
                
                entity = WMEntity(
                    id=self._gen_entity_id(),
                    name=time_ref,
                    entity_type=EntityType.TIME,
                    first_mentioned=self.turn_count,
                    last_mentioned=self.turn_count,
                )
                entities.append(entity)
        
        return entities
    
    def _infer_gender_from_context(self, text: str) -> List[Dict[str, str]]:
        """
        v0.7.1: Infer gender for entities from pronoun usage in text.
        
        Key insight: When user says "He seemed interested" right after mentioning
        Steven, we can infer Steven is masculine.
        
        Strategy:
        1. If message starts with a pronoun (He/She), apply to most recently
           mentioned person of unknown gender.
        2. If message contains "Name...he/she" in same sentence, apply to that name.
        3. Check relational patterns ("my brother Steven" → masculine).
        """
        inferences = []
        text_stripped = text.strip()
        
        # Strategy 1: Message starts with gendered pronoun
        # "He seemed interested" → apply to most recent person
        if re.match(r'^[Hh]e\b', text_stripped):
            # Find most recently mentioned person with neutral gender
            recent_person = self._get_most_recent_neutral_person()
            if recent_person:
                recent_person.gender_hint = GenderHint.MASCULINE
                self._update_pronoun_candidates(recent_person)
                inferences.append({
                    "entity": recent_person.name, 
                    "gender": "masculine",
                    "source": "sentence_start"
                })
        
        elif re.match(r'^[Ss]he\b', text_stripped):
            recent_person = self._get_most_recent_neutral_person()
            if recent_person:
                recent_person.gender_hint = GenderHint.FEMININE
                self._update_pronoun_candidates(recent_person)
                inferences.append({
                    "entity": recent_person.name,
                    "gender": "feminine", 
                    "source": "sentence_start"
                })
        
        # Strategy 2: Check for masculine hints in patterns
        for pattern in MASCULINE_HINT_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                name = match.group(1) if match.lastindex else None
                if name:
                    entity = self._find_entity_by_name(name)
                    if entity and entity.entity_type == EntityType.PERSON:
                        if entity.gender_hint == GenderHint.NEUTRAL:
                            entity.gender_hint = GenderHint.MASCULINE
                            self._update_pronoun_candidates(entity)
                            inferences.append({
                                "entity": name,
                                "gender": "masculine",
                                "source": "pattern"
                            })
        
        # Strategy 3: Check for feminine hints in patterns
        for pattern in FEMININE_HINT_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                name = match.group(1) if match.lastindex else None
                if name:
                    entity = self._find_entity_by_name(name)
                    if entity and entity.entity_type == EntityType.PERSON:
                        if entity.gender_hint == GenderHint.NEUTRAL:
                            entity.gender_hint = GenderHint.FEMININE
                            self._update_pronoun_candidates(entity)
                            inferences.append({
                                "entity": name,
                                "gender": "feminine",
                                "source": "pattern"
                            })
        
        # Strategy 4: Look for "Name ... he/she" in same message
        for entity in self.entities.values():
            if entity.entity_type != EntityType.PERSON:
                continue
            if entity.gender_hint != GenderHint.NEUTRAL:
                continue  # Already has gender
            
            name = entity.name
            # Look for "Name ... he" pattern (within ~50 chars)
            he_pattern = rf"\b{re.escape(name)}\b.{{0,50}}\bhe\b"
            she_pattern = rf"\b{re.escape(name)}\b.{{0,50}}\bshe\b"
            
            if re.search(he_pattern, text, re.IGNORECASE):
                entity.gender_hint = GenderHint.MASCULINE
                self._update_pronoun_candidates(entity)
                inferences.append({
                    "entity": name,
                    "gender": "masculine",
                    "source": "same_sentence"
                })
            elif re.search(she_pattern, text, re.IGNORECASE):
                entity.gender_hint = GenderHint.FEMININE
                self._update_pronoun_candidates(entity)
                inferences.append({
                    "entity": name,
                    "gender": "feminine",
                    "source": "same_sentence"
                })
        
        return inferences
    
    def _get_most_recent_neutral_person(self) -> Optional[WMEntity]:
        """Get the most recently mentioned person with neutral/unknown gender."""
        people = [
            e for e in self.entities.values()
            if e.entity_type == EntityType.PERSON and e.gender_hint == GenderHint.NEUTRAL
        ]
        if not people:
            return None
        return max(people, key=lambda p: p.last_mentioned)
    
    def _find_entity_by_name(self, name: str) -> Optional[WMEntity]:
        """Find an entity by name (case-insensitive)."""
        name_lower = name.lower()
        for entity in self.entities.values():
            if entity.name.lower() == name_lower:
                return entity
        return None
    
    def _add_or_update_entity(self, entity: WMEntity) -> WMEntity:
        """Add a new entity or update existing one."""
        # Check if entity already exists
        for existing_id, existing in self.entities.items():
            if existing.name.lower() == entity.name.lower():
                # Update existing entity
                existing.last_mentioned = self.turn_count
                existing.mention_count += 1
                if entity.description and not existing.description:
                    existing.description = entity.description
                
                # Update pronoun candidates
                self._update_pronoun_candidates(existing)
                
                return existing
        
        # Add new entity
        self.entities[entity.id] = entity
        
        # Add to appropriate pronoun group(s)
        self._update_pronoun_candidates(entity)
        
        return entity
    
    def _update_pronoun_candidates(self, entity: WMEntity) -> None:
        """
        v0.7.1: Update pronoun group candidates for an entity.
        
        This is the KEY FIX: Instead of overwriting all pronouns,
        we add the entity to the appropriate gender-specific group only.
        """
        if entity.entity_type == EntityType.PERSON:
            # Calculate base score (recency + mention count)
            base_score = entity.mention_count * 0.1 + (self.turn_count - entity.first_mentioned + 1) * 0.05
            
            if entity.gender_hint == GenderHint.MASCULINE:
                # Add to masculine group with high confidence
                candidate = ReferentCandidate(
                    entity_id=entity.id,
                    entity_name=entity.name,
                    score=base_score + 1.0,  # Bonus for gender match
                    last_mentioned=entity.last_mentioned,
                    gender_match=True,
                )
                self.pronoun_groups["masculine"].add_candidate(candidate)
                
                # Also add to neutral (they/them) with lower score
                neutral_candidate = ReferentCandidate(
                    entity_id=entity.id,
                    entity_name=entity.name,
                    score=base_score,
                    last_mentioned=entity.last_mentioned,
                    gender_match=False,
                )
                self.pronoun_groups["neutral"].add_candidate(neutral_candidate)
                
            elif entity.gender_hint == GenderHint.FEMININE:
                # Add to feminine group with high confidence
                candidate = ReferentCandidate(
                    entity_id=entity.id,
                    entity_name=entity.name,
                    score=base_score + 1.0,
                    last_mentioned=entity.last_mentioned,
                    gender_match=True,
                )
                self.pronoun_groups["feminine"].add_candidate(candidate)
                
                # Also add to neutral
                neutral_candidate = ReferentCandidate(
                    entity_id=entity.id,
                    entity_name=entity.name,
                    score=base_score,
                    last_mentioned=entity.last_mentioned,
                    gender_match=False,
                )
                self.pronoun_groups["neutral"].add_candidate(neutral_candidate)
                
            else:
                # Gender unknown - add to neutral only, don't touch he/she
                candidate = ReferentCandidate(
                    entity_id=entity.id,
                    entity_name=entity.name,
                    score=base_score,
                    last_mentioned=entity.last_mentioned,
                    gender_match=True,  # Neutral matches they/them
                )
                self.pronoun_groups["neutral"].add_candidate(candidate)
        
        elif entity.entity_type in [EntityType.PROJECT, EntityType.OBJECT, EntityType.CONCEPT]:
            # Add to object group
            base_score = entity.mention_count * 0.1
            candidate = ReferentCandidate(
                entity_id=entity.id,
                entity_name=entity.name,
                score=base_score + 1.0,
                last_mentioned=entity.last_mentioned,
                gender_match=True,
            )
            self.pronoun_groups["object"].add_candidate(candidate)
        
        elif entity.entity_type == EntityType.ORGANIZATION:
            # Organizations can be they/it
            base_score = entity.mention_count * 0.1
            for group_name in ["neutral", "object"]:
                candidate = ReferentCandidate(
                    entity_id=entity.id,
                    entity_name=entity.name,
                    score=base_score,
                    last_mentioned=entity.last_mentioned,
                    gender_match=True,
                )
                self.pronoun_groups[group_name].add_candidate(candidate)
        
        # Update legacy referents for backward compatibility
        self._update_legacy_referents()
    
    def _update_legacy_referents(self) -> None:
        """Update legacy referents dict from pronoun groups."""
        # Build legacy referents from best candidates
        for group_name, group in self.pronoun_groups.items():
            best = group.get_best_candidate()
            if best:
                for pronoun in group.pronouns:
                    self.referents[pronoun] = PronounReferent(
                        pronoun=pronoun,
                        entity_id=best.entity_id,
                        confidence=best.score,
                        set_at_turn=best.last_mentioned,
                    )
    
    def get_entity(self, name_or_id: str) -> Optional[WMEntity]:
        """Get an entity by name or ID."""
        if name_or_id in self.entities:
            return self.entities[name_or_id]
        
        name_lower = name_or_id.lower()
        for entity in self.entities.values():
            if entity.name.lower() == name_lower:
                return entity
            if name_lower in [a.lower() for a in entity.aliases]:
                return entity
        
        return None
    
    def get_active_entities(self, limit: int = 5) -> List[WMEntity]:
        """Get the most recently mentioned entities."""
        sorted_entities = sorted(
            self.entities.values(),
            key=lambda e: (e.last_mentioned, e.mention_count),
            reverse=True
        )
        return sorted_entities[:limit]
    
    def get_entities_by_type(self, entity_type: EntityType) -> List[WMEntity]:
        """Get all entities of a specific type."""
        return [e for e in self.entities.values() if e.entity_type == entity_type]
    
    # =========================================================================
    # PRONOUN RESOLUTION (v0.7.1 - Completely Rewritten)
    # =========================================================================
    
    def resolve_pronoun(self, pronoun: str) -> Optional[WMEntity]:
        """
        v0.7.1: Resolve a pronoun to its referent entity using gender-aware logic.
        
        Args:
            pronoun: The pronoun to resolve ("he", "she", "it", etc.)
        
        Returns:
            The resolved entity or None if can't resolve
        """
        pronoun_lower = pronoun.lower()
        
        # Determine which pronoun group to use
        gender = PRONOUN_TO_GENDER.get(pronoun_lower)
        if not gender:
            return None
        
        # Map gender to group name
        group_name_map = {
            GenderHint.MASCULINE: "masculine",
            GenderHint.FEMININE: "feminine",
            GenderHint.NEUTRAL: "neutral",
            GenderHint.OBJECT: "object",
        }
        
        group_name = group_name_map.get(gender)
        if not group_name or group_name not in self.pronoun_groups:
            return None
        
        group = self.pronoun_groups[group_name]
        best = group.get_best_candidate()
        
        if best and best.entity_id in self.entities:
            return self.entities[best.entity_id]
        
        # Fallback: try neutral group for person pronouns
        if gender in [GenderHint.MASCULINE, GenderHint.FEMININE]:
            neutral_group = self.pronoun_groups.get("neutral")
            if neutral_group:
                best = neutral_group.get_best_candidate()
                if best and best.entity_id in self.entities:
                    return self.entities[best.entity_id]
        
        return None
    
    def get_referent_map(self) -> Dict[str, str]:
        """Get current pronoun → entity name mapping."""
        result = {}
        for group in self.pronoun_groups.values():
            best = group.get_best_candidate()
            if best:
                for pronoun in group.pronouns:
                    result[pronoun] = best.entity_name
        return result
    
    def get_pronoun_resolution_summary(self) -> Dict[str, Any]:
        """
        v0.7.1: Get a clear summary of pronoun resolution for #wm-debug.
        """
        summary = {}
        
        for group_name, group in self.pronoun_groups.items():
            best = group.get_best_candidate()
            candidates = group.candidates
            
            if candidates:
                pronoun_key = "/".join(sorted(group.pronouns))
                if best:
                    summary[pronoun_key] = {
                        "best_match": best.entity_name,
                        "candidates": [c.entity_name for c in candidates],
                        "all_candidates_detail": [c.to_dict() for c in candidates],
                    }
        
        return summary
    
    # =========================================================================
    # TOPIC MANAGEMENT
    # =========================================================================
    
    def _extract_topics(self, text: str) -> List[WMTopic]:
        """Extract conversation topics from text."""
        topics = []
        
        topic_patterns = [
            r"\babout\s+(.+?)(?:\.|,|$|\?)",
            r"\bregarding\s+(.+?)(?:\.|,|$|\?)",
            r"\bdiscuss(?:ing)?\s+(.+?)(?:\.|,|$|\?)",
        ]
        
        for pattern in topic_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                topic_text = match.group(1).strip()
                if len(topic_text) > 2 and len(topic_text) < 50:
                    topic = WMTopic(
                        id=self._gen_topic_id(),
                        name=topic_text[:50],
                        first_mentioned=self.turn_count,
                        last_mentioned=self.turn_count,
                    )
                    topics.append(topic)
        
        return topics
    
    def _add_or_update_topic(self, topic: WMTopic) -> WMTopic:
        """Add a new topic or update existing one."""
        for existing_id, existing in self.topics.items():
            if existing.name.lower() == topic.name.lower():
                existing.last_mentioned = self.turn_count
                existing.status = TopicStatus.ACTIVE
                return existing
        
        self.topics[topic.id] = topic
        return topic
    
    def _update_active_topic(self) -> None:
        """Update which topic is currently active."""
        active_topics = [
            t for t in self.topics.values()
            if t.status == TopicStatus.ACTIVE
        ]
        
        if active_topics:
            most_recent = max(active_topics, key=lambda t: t.last_mentioned)
            self.active_topic_id = most_recent.id
        elif self.entities:
            # No explicit topic - create implicit one from entities
            recent_entities = self.get_active_entities(2)
            if recent_entities:
                people = [e for e in recent_entities if e.entity_type == EntityType.PERSON]
                projects = [e for e in recent_entities if e.entity_type == EntityType.PROJECT]
                
                if people and projects:
                    topic_name = f"{projects[0].name} with {people[0].name}"
                elif people:
                    topic_name = f"conversation about {people[0].name}"
                elif projects:
                    topic_name = projects[0].name
                else:
                    topic_name = recent_entities[0].name
                
                topic = WMTopic(
                    id=self._gen_topic_id(),
                    name=topic_name,
                    related_entities=[e.id for e in recent_entities],
                    first_mentioned=self.turn_count,
                    last_mentioned=self.turn_count,
                )
                self.topics[topic.id] = topic
                self.active_topic_id = topic.id
    
    def get_active_topic(self) -> Optional[WMTopic]:
        """Get the currently active topic."""
        if self.active_topic_id and self.active_topic_id in self.topics:
            return self.topics[self.active_topic_id]
        return None
    
    # =========================================================================
    # GOAL MANAGEMENT
    # =========================================================================
    
    def _extract_goals(self, text: str) -> List[WMGoal]:
        """Extract user goals/intentions from text."""
        goals = []
        seen_goals = set()
        
        for pattern, _ in GOAL_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                goal_text = match.group(1).strip()
                goal_text = re.sub(r'\s+', ' ', goal_text)
                
                if len(goal_text) > 5 and len(goal_text) < 80:
                    goal_lower = goal_text.lower()
                    if goal_lower not in seen_goals:
                        seen_goals.add(goal_lower)
                        goal = WMGoal(
                            id=self._gen_goal_id(),
                            description=goal_text,
                            created_at=self.turn_count,
                        )
                        goals.append(goal)
                        break
        
        return goals[:2]
    
    def _add_goal(self, goal: WMGoal) -> None:
        """Add a new goal."""
        self.goals[goal.id] = goal
    
    def get_active_goals(self) -> List[WMGoal]:
        """Get all active goals."""
        return [g for g in self.goals.values() if g.status == GoalStatus.ACTIVE]
    
    # =========================================================================
    # QUESTION MANAGEMENT
    # =========================================================================
    
    def _extract_questions(self, text: str) -> List[WMQuestion]:
        """Extract questions from text."""
        questions = []
        
        if text.strip().endswith("?"):
            question = WMQuestion(
                id=self._gen_question_id(),
                question=text.strip(),
                asker="user",
                turn_asked=self.turn_count,
            )
            questions.append(question)
        
        return questions
    
    def _add_question(self, question: WMQuestion) -> None:
        """Add a new question."""
        self.questions[question.id] = question
    
    def get_unresolved_questions(self) -> List[WMQuestion]:
        """Get all unresolved questions."""
        return [q for q in self.questions.values() if q.turn_answered is None]
    
    # =========================================================================
    # HELPER METHODS
    # =========================================================================
    
    def _find_pronouns(self, text: str) -> List[str]:
        """Find pronouns in text that need resolution."""
        pronouns = []
        all_pronouns = MASCULINE_PRONOUNS | FEMININE_PRONOUNS | NEUTRAL_PRONOUNS | OBJECT_PRONOUNS
        
        for pronoun in all_pronouns:
            pattern = rf"\b{pronoun}\b"
            if re.search(pattern, text, re.IGNORECASE):
                pronouns.append(pronoun.lower())
        
        return list(set(pronouns))
    
    def _detect_emotional_tone(self, text: str) -> EmotionalTone:
        """Detect the emotional tone of the message."""
        text_lower = text.lower()
        
        for tone, patterns in EMOTIONAL_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, text_lower):
                    return tone
        
        return EmotionalTone.NEUTRAL
    
    def _summarize_message(self, text: Optional[str], max_length: int = 100) -> str:
        """Create a compressed summary of a message."""
        if not text:
            return ""
        
        text = text.strip()
        if len(text) <= max_length:
            return text
        
        return text[:max_length-3] + "..."
    
    def _compress_history(self) -> None:
        """Compress turn history when it gets too long."""
        if len(self.turn_history) > self.max_history:
            self.turn_history = self.turn_history[-self.max_history:]
    
    # =========================================================================
    # CONTEXT BUNDLE (FOR PERSONA)
    # =========================================================================
    
    def get_context_bundle(self) -> Dict[str, Any]:
        """Get a complete context bundle for persona use."""
        active_entities = self.get_active_entities(5)
        active_topic = self.get_active_topic()
        active_goals = self.get_active_goals()
        unresolved = self.get_unresolved_questions()
        referent_map = self.get_referent_map()
        
        recent_messages = []
        for turn in self.turn_history[-5:]:
            recent_messages.append({
                "turn": turn.turn_number,
                "user": turn.user_summary,
                "nova": turn.nova_summary,
            })
        
        return {
            "turn_count": self.turn_count,
            "entities": {
                "all": [e.to_dict() for e in active_entities],
                "people": [e.to_dict() for e in self.get_entities_by_type(EntityType.PERSON)[:3]],
                "projects": [e.to_dict() for e in self.get_entities_by_type(EntityType.PROJECT)[:3]],
            },
            "active_topic": active_topic.to_dict() if active_topic else None,
            "goals": [g.to_dict() for g in active_goals],
            "unresolved_questions": [q.to_dict() for q in unresolved],
            "referents": referent_map,
            "pronoun_groups": self.get_pronoun_resolution_summary(),
            "emotional_tone": self.emotional_tone.value,
            "recent_turns": recent_messages,
            "last_turn": self.last_turn_summary.to_dict() if self.last_turn_summary else None,
        }
    
    def build_persona_context_string(self) -> str:
        """Build a formatted context string for injection into persona system prompt."""
        bundle = self.get_context_bundle()
        lines = []
        
        lines.append("[WORKING MEMORY - CONVERSATION CONTEXT]")
        lines.append("")
        lines.append(f"Turn {self.turn_count} in this conversation.")
        lines.append("")
        
        # Active topic
        if bundle["active_topic"]:
            topic = bundle["active_topic"]
            lines.append(f"CURRENT TOPIC: {topic['name']}")
            if topic.get("description"):
                lines.append(f"  → {topic['description']}")
            lines.append("")
        
        # People mentioned
        people = bundle["entities"]["people"]
        if people:
            lines.append("PEOPLE IN THIS CONVERSATION:")
            for p in people:
                desc = f" ({p['description']})" if p.get('description') else ""
                gender = f" [{p.get('gender_hint', 'neutral')}]"
                lines.append(f"  • {p['name']}{desc}{gender}")
            lines.append("")
        
        # Projects/things mentioned
        projects = bundle["entities"]["projects"]
        if projects:
            lines.append("PROJECTS/THINGS MENTIONED:")
            for p in projects:
                desc = f" ({p['description']})" if p.get('description') else ""
                lines.append(f"  • {p['name']}{desc}")
            lines.append("")
        
        # v0.7.1: Improved pronoun resolution display
        pronoun_summary = bundle.get("pronoun_groups", {})
        if pronoun_summary:
            lines.append("PRONOUN RESOLUTION:")
            for pronoun_key, data in pronoun_summary.items():
                best = data.get("best_match")
                if best:
                    lines.append(f"  • {pronoun_key} → {best}")
            lines.append("")
        
        # Active goals
        if bundle["goals"]:
            lines.append("USER'S CURRENT GOALS:")
            for g in bundle["goals"]:
                lines.append(f"  • {g['description']}")
            lines.append("")
        
        # Unresolved questions
        if bundle["unresolved_questions"]:
            lines.append("UNRESOLVED QUESTIONS:")
            for q in bundle["unresolved_questions"]:
                lines.append(f"  • {q['question'][:80]}")
            lines.append("")
        
        # Emotional tone
        if bundle["emotional_tone"] != "neutral":
            lines.append(f"USER'S EMOTIONAL TONE: {bundle['emotional_tone']}")
            lines.append("")
        
        # Recent conversation
        if bundle["recent_turns"]:
            lines.append("RECENT CONVERSATION:")
            for turn in bundle["recent_turns"][-3:]:
                user_text = turn['user']
                if len(user_text) > 60:
                    user_text = user_text[:60] + "..."
                lines.append(f"  User: \"{user_text}\"")
                if turn['nova']:
                    nova_text = turn['nova']
                    if len(nova_text) > 60:
                        nova_text = nova_text[:60] + "..."
                    lines.append(f"  Nova: \"{nova_text}\"")
            lines.append("")
        
        # Instructions
        lines.append("─" * 40)
        lines.append("INSTRUCTIONS:")
        lines.append("• You REMEMBER this conversation. Use the context above.")
        lines.append("• When user says 'he/him', resolve to the MASCULINE person listed.")
        lines.append("• When user says 'she/her', resolve to the FEMININE person listed.")
        lines.append("• Do NOT say 'I don't know who you mean' if person is listed above.")
        lines.append("• Reference earlier parts of conversation naturally.")
        lines.append("─" * 40)
        
        return "\n".join(lines)
    
    # =========================================================================
    # SPECIAL QUERIES (FOR REFERENCE QUESTIONS)
    # =========================================================================
    
    def answer_reference_question(self, question: str) -> Optional[str]:
        """
        Try to answer reference questions directly from working memory.
        
        v0.7.1: Uses gender-aware pronoun resolution.
        """
        question_lower = question.lower().strip()
        
        # "What's his name again?"
        if re.search(r"\bwhat('s| is| was)\s+his\s+name\b", question_lower):
            # Resolve "his" → masculine person
            entity = self.resolve_pronoun("his")
            if entity:
                context = f" — {entity.description}" if entity.description else ""
                return f"You mentioned {entity.name}{context}."
            return None
        
        # "What's her name again?"
        if re.search(r"\bwhat('s| is| was)\s+her\s+name\b", question_lower):
            # Resolve "her" → feminine person
            entity = self.resolve_pronoun("her")
            if entity:
                context = f" — {entity.description}" if entity.description else ""
                return f"You mentioned {entity.name}{context}."
            return None
        
        # "What's their name again?"
        if re.search(r"\bwhat('s| is| was)\s+their\s+name\b", question_lower):
            entity = self.resolve_pronoun("their")
            if entity:
                context = f" — {entity.description}" if entity.description else ""
                return f"You mentioned {entity.name}{context}."
            return None
        
        # "Who is he/she/that?"
        if re.search(r"\bwho\s+(is|was)\s+(he|him)\b", question_lower):
            entity = self.resolve_pronoun("he")
            if entity:
                context = f" ({entity.description})" if entity.description else ""
                return f"That's {entity.name}{context}."
            return None
        
        if re.search(r"\bwho\s+(is|was)\s+(she|her)\b", question_lower):
            entity = self.resolve_pronoun("she")
            if entity:
                context = f" ({entity.description})" if entity.description else ""
                return f"That's {entity.name}{context}."
            return None
        
        # "What were we talking about?"
        if re.search(r"\bwhat\s+(were|are)\s+we\s+talk", question_lower):
            topic = self.get_active_topic()
            if topic:
                return f"We were discussing {topic.name}."
            
            people = self.get_entities_by_type(EntityType.PERSON)
            projects = self.get_entities_by_type(EntityType.PROJECT)
            
            parts = []
            if people:
                names = [p.name for p in people[:2]]
                parts.append(f"talking about {', '.join(names)}")
            if projects:
                parts.append(f"the {projects[0].name}")
            
            if parts:
                return f"We were {' and '.join(parts)}."
            return None
        
        # "What did I say earlier?"
        if re.search(r"\bwhat\s+did\s+i\s+(say|mention)\b", question_lower):
            if self.turn_history:
                recent = [t.user_summary for t in self.turn_history[-3:] if t.user_summary]
                if recent:
                    return f"You mentioned: {'; '.join(recent)}"
            return None
        
        return None
    
    def _get_most_recent_person(self) -> Optional[WMEntity]:
        """Get the most recently mentioned person."""
        people = self.get_entities_by_type(EntityType.PERSON)
        if people:
            return max(people, key=lambda p: p.last_mentioned)
        return None
    
    # =========================================================================
    # RESET / CLEAR
    # =========================================================================
    
    def clear(self) -> None:
        """Clear all working memory."""
        self.entities.clear()
        self.topics.clear()
        self.goals.clear()
        self.questions.clear()
        
        # Reset pronoun groups
        self.pronoun_groups = {
            "masculine": PronounGroup("masculine", MASCULINE_PRONOUNS),
            "feminine": PronounGroup("feminine", FEMININE_PRONOUNS),
            "neutral": PronounGroup("neutral", NEUTRAL_PRONOUNS),
            "object": PronounGroup("object", OBJECT_PRONOUNS),
        }
        self.referents.clear()
        
        self.turn_history.clear()
        self.last_turn_summary = None
        self.active_topic_id = None
        self.topic_stack.clear()  # v0.7.3
        self.groups.clear()       # v0.7.3
        self.emotional_tone = EmotionalTone.NEUTRAL
        self.turn_count = 0
        self.last_updated = datetime.now()
    
    # =========================================================================
    # v0.7.3 — TOPIC MANAGEMENT EXTENSIONS
    # =========================================================================
    
    def clear_topic(self) -> str:
        """
        v0.7.3: Clear only the current topic, keep entities and pronouns.
        
        Returns:
            Confirmation message
        """
        old_topic_name = None
        if self.active_topic_id and self.active_topic_id in self.topics:
            old_topic_name = self.topics[self.active_topic_id].name
            del self.topics[self.active_topic_id]
        
        self.active_topic_id = None
        
        # Clear topic-specific questions but keep entity-related ones
        topic_questions = [
            qid for qid, q in self.questions.items()
            if not q.related_entities  # Only questions without entity relations
        ]
        for qid in topic_questions:
            del self.questions[qid]
        
        if old_topic_name:
            return f"Topic '{old_topic_name}' cleared. People and entities remain remembered."
        return "Current topic cleared. People and entities remain remembered."
    
    def push_topic(self, new_topic_name: str) -> str:
        """
        v0.7.3: Create or activate a topic, push current topic to stack.
        
        Args:
            new_topic_name: Name for the new topic
        
        Returns:
            The new topic ID
        """
        # Push current topic to stack if exists
        if self.active_topic_id:
            self.topic_stack.append(self.active_topic_id)
            # Keep stack bounded
            if len(self.topic_stack) > 5:
                self.topic_stack = self.topic_stack[-5:]
        
        # Check if topic already exists
        for tid, topic in self.topics.items():
            if topic.name.lower() == new_topic_name.lower():
                topic.status = TopicStatus.ACTIVE
                topic.last_mentioned = self.turn_count
                self.active_topic_id = tid
                return tid
        
        # Create new topic
        new_topic = WMTopic(
            id=self._gen_topic_id(),
            name=new_topic_name,
            status=TopicStatus.ACTIVE,
            first_mentioned=self.turn_count,
            last_mentioned=self.turn_count,
        )
        self.topics[new_topic.id] = new_topic
        self.active_topic_id = new_topic.id
        return new_topic.id
    
    def pop_topic(self) -> Optional[str]:
        """
        v0.7.3: Return to previous topic from stack.
        
        Returns:
            The previous topic ID, or None if stack is empty
        """
        if not self.topic_stack:
            return None
        
        # Mark current topic as paused
        if self.active_topic_id and self.active_topic_id in self.topics:
            self.topics[self.active_topic_id].status = TopicStatus.PAUSED
        
        # Pop and activate previous topic
        prev_topic_id = self.topic_stack.pop()
        if prev_topic_id in self.topics:
            self.topics[prev_topic_id].status = TopicStatus.ACTIVE
            self.topics[prev_topic_id].last_mentioned = self.turn_count
            self.active_topic_id = prev_topic_id
            return prev_topic_id
        
        self.active_topic_id = None
        return None
    
    def list_topics(self) -> List[Dict[str, Any]]:
        """
        v0.7.3: Return list of recent topics with metadata.
        
        Returns:
            List of topic dicts with id, name, status, is_active
        """
        result = []
        for tid, topic in self.topics.items():
            result.append({
                "id": tid,
                "name": topic.name,
                "status": topic.status.value,
                "is_active": tid == self.active_topic_id,
                "first_mentioned": topic.first_mentioned,
                "last_mentioned": topic.last_mentioned,
            })
        # Sort by last_mentioned descending
        result.sort(key=lambda x: x["last_mentioned"], reverse=True)
        return result
    
    def switch_topic(self, topic_identifier: str) -> Optional[str]:
        """
        v0.7.3: Switch to a topic by ID or name.
        
        Args:
            topic_identifier: Topic ID (e.g., "t1") or name
        
        Returns:
            Topic ID if found, None otherwise
        """
        # Try by ID first
        if topic_identifier in self.topics:
            if self.active_topic_id and self.active_topic_id != topic_identifier:
                self.topic_stack.append(self.active_topic_id)
            self.topics[topic_identifier].status = TopicStatus.ACTIVE
            self.topics[topic_identifier].last_mentioned = self.turn_count
            self.active_topic_id = topic_identifier
            return topic_identifier
        
        # Try by name (case-insensitive)
        identifier_lower = topic_identifier.lower()
        for tid, topic in self.topics.items():
            if topic.name.lower() == identifier_lower or identifier_lower in topic.name.lower():
                if self.active_topic_id and self.active_topic_id != tid:
                    self.topic_stack.append(self.active_topic_id)
                topic.status = TopicStatus.ACTIVE
                topic.last_mentioned = self.turn_count
                self.active_topic_id = tid
                return tid
        
        return None
    
    # =========================================================================
    # v0.7.3 — GROUP ENTITY SUPPORT
    # =========================================================================
    
    def register_group(self, name: str, member_names: List[str]) -> Optional[str]:
        """
        v0.7.3: Create a GROUP entity representing multiple people.
        
        Args:
            name: Group name (e.g., "Steven and Sarah")
            member_names: List of member entity names
        
        Returns:
            Group entity ID, or None if no valid members found
        
        v0.7.7: Added members field to entity for direct access.
        """
        # Find member entity IDs
        member_ids = []
        for member_name in member_names:
            entity = self._find_entity_by_name(member_name)
            if entity:
                member_ids.append(entity.id)
        
        if not member_ids:
            return None
        
        # Create group entity
        self._group_counter += 1
        group_id = f"grp{self._group_counter}"
        
        group_entity = WMEntity(
            id=group_id,
            name=name,
            entity_type=EntityType.GROUP,
            description=f"Group of {len(member_ids)} people",
            pronouns=["they", "them", "their"],
            gender_hint=GenderHint.NEUTRAL,
            first_mentioned=self.turn_count,
            last_mentioned=self.turn_count,
            members=member_ids,  # v0.7.7: Store member IDs directly on entity
        )
        
        self.entities[group_id] = group_entity
        self.groups[group_id] = member_ids
        
        # Add to neutral pronoun group with high priority
        candidate = ReferentCandidate(
            entity_id=group_id,
            entity_name=name,
            score=2.0,  # Higher than individual entities
            last_mentioned=self.turn_count,
            gender_match=True,
        )
        self.pronoun_groups["neutral"].add_candidate(candidate)
        
        return group_id
    
    def get_group_members(self, group_id: str) -> List[WMEntity]:
        """Get member entities for a group."""
        member_ids = self.groups.get(group_id, [])
        return [self.entities[mid] for mid in member_ids if mid in self.entities]
    
    # =========================================================================
    # v0.7.5 — AUTOMATIC GROUP DETECTION
    # =========================================================================
    
    def _detect_groups(self, message: str) -> List[str]:
        """
        v0.7.5: Detect "X and Y" patterns and create group entities.
        
        Returns:
            List of created group entity IDs
        """
        created_groups = []
        
        # First try with "both" qualifier (higher confidence)
        for match in GROUP_BOTH_PATTERN.finditer(message):
            name1, name2 = match.group(1), match.group(2)
            group_id = self._create_group_if_valid(name1, name2)
            if group_id:
                created_groups.append(group_id)
        
        # Then try basic "X and Y" pattern
        for match in GROUP_DETECTION_PATTERN.finditer(message):
            name1, name2 = match.group(1), match.group(2)
            
            # Skip if this pair was already created with "both" qualifier
            group_name = f"{name1} and {name2}"
            if any(self.entities.get(gid, {}) and 
                   getattr(self.entities.get(gid), 'name', '') == group_name 
                   for gid in created_groups):
                continue
            
            group_id = self._create_group_if_valid(name1, name2)
            if group_id:
                created_groups.append(group_id)
        
        return created_groups
    
    def _create_group_if_valid(self, name1: str, name2: str) -> Optional[str]:
        """
        Create a group entity if both names are valid people.
        
        Returns:
            Group entity ID if created, None otherwise
        """
        # Filter out non-names
        if name1.lower() in NOT_NAMES or name2.lower() in NOT_NAMES:
            return None
        
        # Check if entities exist (or create them)
        entity1 = self._find_entity_by_name(name1)
        entity2 = self._find_entity_by_name(name2)
        
        # Both must be known people or we create them
        if not entity1:
            entity1 = WMEntity(
                id=self._gen_entity_id(),
                name=name1,
                entity_type=EntityType.PERSON,
                first_mentioned=self.turn_count,
                last_mentioned=self.turn_count,
            )
            self.entities[entity1.id] = entity1
        
        if not entity2:
            entity2 = WMEntity(
                id=self._gen_entity_id(),
                name=name2,
                entity_type=EntityType.PERSON,
                first_mentioned=self.turn_count,
                last_mentioned=self.turn_count,
            )
            self.entities[entity2.id] = entity2
        
        # Check if this group already exists
        group_name = f"{name1} and {name2}"
        alt_group_name = f"{name2} and {name1}"
        
        for gid, members in self.groups.items():
            if gid in self.entities:
                existing_name = self.entities[gid].name
                if existing_name == group_name or existing_name == alt_group_name:
                    # Update last_mentioned
                    self.entities[gid].last_mentioned = self.turn_count
                    return None  # Already exists
        
        # Create the group
        return self.register_group(group_name, [name1, name2])
    
    # =========================================================================
    # v0.7.5 — TANGENT/RETURN DETECTION
    # =========================================================================
    
    def _check_tangent_patterns(self, message: str) -> Optional[Dict[str, Any]]:
        """
        v0.7.5: Check if user is starting a tangent.
        
        Returns:
            Dict with tangent info if detected, None otherwise
        """
        message_lower = message.lower().strip()
        
        for pattern, trigger_name in TANGENT_START_PATTERNS:
            if re.match(pattern, message_lower, re.IGNORECASE):
                # Push current topic to stack
                old_topic_id = self.active_topic_id
                old_topic_name = None
                if old_topic_id and old_topic_id in self.topics:
                    old_topic_name = self.topics[old_topic_id].name
                    self.topic_stack.append(old_topic_id)
                    # Keep stack bounded
                    if len(self.topic_stack) > 5:
                        self.topic_stack = self.topic_stack[-5:]
                    # Mark as paused
                    self.topics[old_topic_id].status = TopicStatus.PAUSED
                
                # Extract tangent topic from rest of message
                cleaned = re.sub(pattern, "", message_lower, count=1, flags=re.IGNORECASE).strip()
                tangent_topic = cleaned[:50] if cleaned else "tangent"
                
                return {
                    "type": "tangent_start",
                    "trigger": trigger_name,
                    "old_topic": old_topic_name,
                    "tangent_topic": tangent_topic,
                }
        
        return None
    
    def _check_return_patterns(self, message: str) -> Optional[Dict[str, Any]]:
        """
        v0.7.5: Check if user is returning to previous topic.
        
        Returns:
            Dict with return info if detected, None otherwise
        """
        message_lower = message.lower().strip()
        
        for pattern, trigger_name in TOPIC_RETURN_PATTERNS:
            match = re.match(pattern, message_lower, re.IGNORECASE)
            if match:
                # Check if they mentioned a specific topic
                target_topic = None
                if match.lastindex and match.lastindex >= 1:
                    target_topic = match.group(1)
                
                result = {
                    "type": "topic_return",
                    "trigger": trigger_name,
                    "target_topic": target_topic,
                }
                
                # If specific topic mentioned, try to switch to it
                if target_topic:
                    switched = self.switch_topic(target_topic)
                    if switched:
                        result["switched_to"] = switched
                        if switched in self.topics:
                            result["topic_name"] = self.topics[switched].name
                        return result
                
                # Otherwise, pop from stack
                if self.topic_stack:
                    prev_topic_id = self.pop_topic()
                    if prev_topic_id:
                        result["switched_to"] = prev_topic_id
                        if prev_topic_id in self.topics:
                            result["topic_name"] = self.topics[prev_topic_id].name
                
                return result
        
        return None
    
    # =========================================================================
    # v0.7.5 — META-QUESTION HANDLING
    # =========================================================================
    
    def check_meta_question(self, message: str) -> Optional[Dict[str, Any]]:
        """
        v0.7.5: Check if the message is a meta-question about the conversation.
        
        Returns:
            Dict with meta-question type and extracted info, or None
        """
        message_lower = message.lower().strip()
        
        for pattern, question_type in META_QUESTION_PATTERNS:
            match = re.search(pattern, message_lower, re.IGNORECASE)
            if match:
                result = {
                    "type": question_type,
                    "pattern": pattern,
                }
                
                # Extract entity name if captured
                if match.lastindex and match.lastindex >= 1:
                    result["entity_mentioned"] = match.group(1)
                
                return result
        
        return None
    
    def answer_meta_question(self, meta_info: Dict[str, Any]) -> Optional[str]:
        """
        v0.7.5: Generate an answer for a meta-question using WM state.
        v0.7.7: Added event recall support.
        
        Args:
            meta_info: Result from check_meta_question()
        
        Returns:
            Answer string, or None if cannot answer
        """
        question_type = meta_info.get("type")
        
        if question_type == "topic_recall":
            return self._answer_topic_recall()
        
        elif question_type == "entity_recall":
            entity_name = meta_info.get("entity_mentioned")
            if entity_name:
                return self._answer_entity_recall(entity_name)
        
        elif question_type == "person_recall":
            return self._answer_person_recall()
        
        elif question_type == "group_recall":
            return self._answer_group_recall()
        
        elif question_type == "context_recall":
            return self._answer_context_recall()
        
        elif question_type == "reminder":
            entity_name = meta_info.get("entity_mentioned")
            if entity_name:
                return self._answer_entity_recall(entity_name)
        
        # v0.7.7: Event recall types
        elif question_type.startswith("event_recall_"):
            entity_name = meta_info.get("entity_mentioned")
            if entity_name:
                # Extract event type from question_type (e.g., "event_recall_said" → "said")
                event_type = question_type.replace("event_recall_", "")
                return self.answer_event_recall(entity_name, event_type)
        
        return None
    
    def _answer_topic_recall(self) -> Optional[str]:
        """Answer 'what were we talking about?'"""
        if self.active_topic_id and self.active_topic_id in self.topics:
            topic = self.topics[self.active_topic_id]
            
            # Get related entities
            people = self.get_entities_by_type(EntityType.PERSON)
            people_str = ""
            if people:
                names = [p.name for p in people[:3]]
                people_str = f" (involving {', '.join(names)})"
            
            return f"We were discussing {topic.name}{people_str}."
        
        # Check topic stack
        if self.topic_stack:
            recent_id = self.topic_stack[-1]
            if recent_id in self.topics:
                return f"We were on a tangent. Before that, we were discussing {self.topics[recent_id].name}."
        
        return "We haven't established a specific topic yet."
    
    def _answer_person_recall(self) -> Optional[str]:
        """Answer 'who were we discussing?'"""
        people = self.get_entities_by_type(EntityType.PERSON)
        if not people:
            return "We haven't discussed any specific people yet."
        
        # Sort by last_mentioned
        people_sorted = sorted(people, key=lambda p: p.last_mentioned, reverse=True)
        
        parts = []
        for person in people_sorted[:5]:
            part = person.name
            if person.gender_hint and person.gender_hint != GenderHint.NEUTRAL:
                part += f" ({person.gender_hint.value})"
            parts.append(part)
        
        return f"We've been discussing: {', '.join(parts)}."
    
    def _answer_group_recall(self) -> Optional[str]:
        """Answer 'who are they again?'"""
        # Find recent group
        groups = [e for e in self.entities.values() if e.entity_type == EntityType.GROUP]
        
        if not groups:
            # Try neutral pronoun resolution
            resolved = self.resolve_pronoun("they")
            if resolved:
                return f"'They' refers to {resolved.name}."
            return "I'm not sure who 'they' refers to in this context."
        
        # Get most recent group
        recent_group = max(groups, key=lambda g: g.last_mentioned)
        
        # Get member details
        members = self.get_group_members(recent_group.id)
        if members:
            member_details = []
            for m in members:
                detail = m.name
                if m.gender_hint and m.gender_hint != GenderHint.NEUTRAL:
                    detail += f" ({m.gender_hint.value})"
                member_details.append(detail)
            
            return f"'They' refers to {recent_group.name} — {', '.join(member_details)}."
        
        return f"'They' refers to {recent_group.name}."
    
    def _answer_entity_recall(self, entity_name: str) -> Optional[str]:
        """Answer 'what do you remember about X?'"""
        entity = self._find_entity_by_name(entity_name)
        if not entity:
            return f"I don't have any information about {entity_name}."
        
        parts = [f"{entity.name} is a {entity.entity_type.value}"]
        
        if entity.description:
            parts.append(f"— {entity.description}")
        
        if entity.gender_hint and entity.gender_hint != GenderHint.NEUTRAL:
            parts.append(f"(pronouns: {entity.gender_hint.value})")
        
        # Check if part of a group
        for gid, members in self.groups.items():
            if entity.id in members and gid in self.entities:
                group = self.entities[gid]
                parts.append(f"Part of group: {group.name}")
        
        return " ".join(parts) + "."
    
    def _answer_context_recall(self) -> Optional[str]:
        """Answer 'what's the context?'"""
        parts = []
        
        # Topic
        if self.active_topic_id and self.active_topic_id in self.topics:
            parts.append(f"Topic: {self.topics[self.active_topic_id].name}")
        
        # People
        people = self.get_entities_by_type(EntityType.PERSON)
        if people:
            names = [p.name for p in people[:4]]
            parts.append(f"People: {', '.join(names)}")
        
        # Groups
        groups = [e for e in self.entities.values() if e.entity_type == EntityType.GROUP]
        if groups:
            group_names = [g.name for g in groups]
            parts.append(f"Groups: {', '.join(group_names)}")
        
        # Tone
        if self.emotional_tone != EmotionalTone.NEUTRAL:
            parts.append(f"Tone: {self.emotional_tone.value}")
        
        # Turn count
        parts.append(f"Turns: {self.turn_count}")
        
        if not parts:
            return "We're just getting started — no context established yet."
        
        return "\n".join(parts)
    
    # =========================================================================
    # v0.7.3 — SNAPSHOT SUPPORT
    # =========================================================================
    
    def get_snapshot_summary(self, label: Optional[str] = None) -> str:
        """
        v0.7.3: Generate a text summary suitable for episodic memory storage.
        
        Args:
            label: Optional label for the snapshot
        
        Returns:
            Formatted summary string
        """
        lines = ["[WM SNAPSHOT]"]
        
        # Topic
        topic_name = label
        if not topic_name and self.active_topic_id and self.active_topic_id in self.topics:
            topic_name = self.topics[self.active_topic_id].name
        if not topic_name:
            topic_name = "conversation snapshot"
        
        # Get participants
        people = self.get_entities_by_type(EntityType.PERSON)
        participant_strs = []
        for p in people[:5]:
            gender = f" ({p.gender_hint.value})" if p.gender_hint != GenderHint.NEUTRAL else ""
            participant_strs.append(f"{p.name}{gender}")
        
        if participant_strs:
            lines.append(f"Topic: {topic_name} with {' and '.join(participant_strs)}")
            lines.append(f"Participants: {', '.join(participant_strs)}")
        else:
            lines.append(f"Topic: {topic_name}")
        
        # Goals
        active_goals = self.get_active_goals()
        if active_goals:
            lines.append(f"Goal: {active_goals[0].description}")
        
        # Unresolved questions
        unresolved = self.get_unresolved_questions()
        if unresolved:
            lines.append("Unresolved questions:")
            for q in unresolved[:3]:
                lines.append(f"  - {q.question[:80]}")
        
        # Turn info
        lines.append(f"Turns: {self.turn_count}")
        lines.append(f"Snapshot time: {datetime.now().isoformat()}")
        
        return "\n".join(lines)
    
    # =========================================================================
    # v0.7.6 — PERSISTENCE LAYER (Option B)
    # =========================================================================
    
    def create_snapshot_payload(self, label: Optional[str] = None, module: Optional[str] = None) -> Dict[str, Any]:
        """
        v0.7.6: Create a structured payload for episodic memory storage.
        
        Args:
            label: Optional label for the snapshot
            module: Optional module tag (cyber, business, etc.)
        
        Returns:
            Dict suitable for MemoryManager.store()
        """
        # Topic
        topic_name = label
        if not topic_name and self.active_topic_id and self.active_topic_id in self.topics:
            topic_name = self.topics[self.active_topic_id].name
        if not topic_name:
            topic_name = "conversation snapshot"
        
        # Participants (people entities)
        participants = []
        for entity in self.entities.values():
            if entity.entity_type == EntityType.PERSON:
                participants.append({
                    "name": entity.name,
                    "gender": entity.gender_hint.value if entity.gender_hint else "neutral",
                })
        
        # Groups
        groups = []
        for gid, members in self.groups.items():
            if gid in self.entities:
                group_entity = self.entities[gid]
                member_names = []
                for mid in members:
                    if mid in self.entities:
                        member_names.append(self.entities[mid].name)
                groups.append({
                    "name": group_entity.name,
                    "members": member_names,
                })
        
        # Goals
        goals = []
        for goal in self.goals.values():
            if goal.status.value == "active":
                goals.append(goal.description)
        
        # Unresolved questions
        unresolved = []
        for q in self.questions.values():
            if q.turn_answered is None:
                unresolved.append(q.question[:100])
        
        # Thread summary (last few turns)
        summary_parts = []
        for turn in self.turn_history[-3:]:
            if turn.user_summary:
                summary_parts.append(f"User: {turn.user_summary[:50]}")
            if turn.nova_summary:
                summary_parts.append(f"Nova: {turn.nova_summary[:50]}")
        summary = " | ".join(summary_parts) if summary_parts else ""
        
        # Build payload
        payload = {
            "topic": topic_name,
            "participants": participants,
            "groups": groups,
            "goals": goals,
            "unresolved": unresolved,
            "summary": summary,
            "turn_count": self.turn_count,
            "emotional_tone": self.emotional_tone.value,
            "timestamp": datetime.now().isoformat(),
        }
        
        # Tags for querying
        tags = ["wm", "snapshot"]
        if label:
            tags.append(f"label:{label.replace(' ', '-')[:30]}")
        if module:
            tags.append(f"module:{module}")
        for p in participants[:3]:
            tags.append(f"person:{p['name'].lower()}")
        
        return {
            "type": "episodic",
            "tags": tags,
            "payload": payload,
        }
    
    def rehydrate_from_snapshot(self, snapshot_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        v0.7.6: Rehydrate WM entities from a snapshot payload.
        
        This is a PARTIAL rehydration — only entities are loaded,
        not full WM state. This prevents conflicts.
        
        Args:
            snapshot_data: The payload from a stored snapshot
        
        Returns:
            Dict with rehydration results
        """
        results = {
            "entities_added": [],
            "groups_added": [],
            "conflicts": [],
        }
        
        # Rehydrate participants as entities
        for participant in snapshot_data.get("participants", []):
            name = participant.get("name")
            if not name:
                continue
            
            # Check if entity already exists
            existing = self._find_entity_by_name(name)
            if existing:
                results["conflicts"].append(f"{name} already exists")
                continue
            
            # Create entity
            gender = participant.get("gender", "neutral")
            try:
                gender_hint = GenderHint(gender)
            except ValueError:
                gender_hint = GenderHint.NEUTRAL
            
            entity = WMEntity(
                id=self._gen_entity_id(),
                name=name,
                entity_type=EntityType.PERSON,
                gender_hint=gender_hint,
                first_mentioned=self.turn_count,
                last_mentioned=self.turn_count,
                description="(rehydrated from snapshot)",
            )
            self.entities[entity.id] = entity
            results["entities_added"].append(name)
            
            # Add to pronoun groups
            candidate = ReferentCandidate(
                entity_id=entity.id,
                entity_name=entity.name,
                score=0.8,  # Lower score for rehydrated
                last_mentioned=self.turn_count,
                gender_match=True,
            )
            
            if gender_hint == GenderHint.MASCULINE:
                self.pronoun_groups["masculine"].add_candidate(candidate)
            elif gender_hint == GenderHint.FEMININE:
                self.pronoun_groups["feminine"].add_candidate(candidate)
            self.pronoun_groups["neutral"].add_candidate(candidate)
        
        # Rehydrate groups
        for group_data in snapshot_data.get("groups", []):
            group_name = group_data.get("name")
            member_names = group_data.get("members", [])
            
            if not group_name or not member_names:
                continue
            
            # Check if group exists
            existing = self._find_entity_by_name(group_name)
            if existing:
                results["conflicts"].append(f"Group {group_name} already exists")
                continue
            
            # Create group
            group_id = self.register_group(group_name, member_names)
            if group_id:
                results["groups_added"].append(group_name)
        
        return results
    
    # =========================================================================
    # v0.7.7 — EVENT TRACKING FOR RECALL
    # =========================================================================
    
    def record_entity_event(self, entity_id: str, event_type: str, content: str) -> None:
        """
        v0.7.7: Record an event associated with an entity.
        
        Used for "what did Sarah say?" type queries.
        
        Args:
            entity_id: The entity involved
            event_type: Type of event (said, did, asked, suggested)
            content: The event content
        """
        if entity_id not in self.entity_events:
            self.entity_events[entity_id] = []
        
        self.entity_events[entity_id].append({
            "type": event_type,
            "content": content[:200],
            "turn": self.turn_count,
            "timestamp": datetime.now().isoformat(),
        })
        
        # Keep bounded
        if len(self.entity_events[entity_id]) > 10:
            self.entity_events[entity_id] = self.entity_events[entity_id][-10:]
    
    def get_entity_events(self, entity_name: str) -> List[Dict[str, Any]]:
        """
        v0.7.7: Get events for an entity by name.
        
        Args:
            entity_name: Name of the entity
        
        Returns:
            List of events, most recent first
        """
        entity = self._find_entity_by_name(entity_name)
        if not entity:
            return []
        
        events = self.entity_events.get(entity.id, [])
        return list(reversed(events))
    
    def answer_event_recall(self, entity_name: str, event_type: Optional[str] = None) -> Optional[str]:
        """
        v0.7.7: Answer "what did X say/do?" questions.
        
        Args:
            entity_name: Name of the entity
            event_type: Optional filter (said, did, asked, suggested)
        
        Returns:
            Answer string, or None if no events
        """
        events = self.get_entity_events(entity_name)
        if not events:
            return None
        
        # Filter by type if specified
        if event_type:
            events = [e for e in events if e.get("type") == event_type]
        
        if not events:
            return None
        
        # Return most recent
        event = events[0]
        return f"{entity_name} {event['type']}: \"{event['content']}\""
    
    # =========================================================================
    # v0.7.7 — ENHANCED GROUP SUPPORT
    # =========================================================================
    
    def get_all_groups(self) -> List[Dict[str, Any]]:
        """
        v0.7.7: Get all group entities with member details.
        
        Returns:
            List of group dicts
        """
        result = []
        for gid, member_ids in self.groups.items():
            if gid not in self.entities:
                continue
            
            group = self.entities[gid]
            member_names = []
            for mid in member_ids:
                if mid in self.entities:
                    member_names.append(self.entities[mid].name)
            
            result.append({
                "id": gid,
                "name": group.name,
                "members": member_names,
                "last_mentioned": group.last_mentioned,
            })
        
        return result
    
    def get_group_context_string(self) -> str:
        """
        v0.7.7: Get context string for groups (for behavior layer).
        
        Returns:
            Formatted string listing groups
        """
        groups = self.get_all_groups()
        if not groups:
            return ""
        
        parts = ["GROUPS:"]
        for g in groups:
            parts.append(f"  • {g['name']} = {', '.join(g['members'])}")
        
        return "\n".join(parts)
    
    # =========================================================================
    # v0.7.7 — TOPIC MERGE
    # =========================================================================
    
    def merge_topic(self, topic_name: str) -> str:
        """
        v0.7.7: Merge into existing topic with same name, or create new.
        
        Unlike push_topic which always pushes to stack, this finds
        an existing topic by name and activates it.
        
        Args:
            topic_name: Topic name to merge into
        
        Returns:
            Topic ID (existing or new)
        """
        topic_lower = topic_name.lower()
        
        # Find existing topic with same name
        for tid, topic in self.topics.items():
            if topic.name.lower() == topic_lower:
                # Activate existing
                if self.active_topic_id and self.active_topic_id != tid:
                    self.topics[self.active_topic_id].status = TopicStatus.PAUSED
                
                topic.status = TopicStatus.ACTIVE
                topic.last_mentioned = self.turn_count
                self.active_topic_id = tid
                return tid
        
        # No existing topic, create new
        return self.push_topic(topic_name)
    
    # =========================================================================
    # SERIALIZATION
    # =========================================================================
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize full state for debugging."""
        return {
            "session_id": self.session_id,
            "turn_count": self.turn_count,
            "entities": {k: v.to_dict() for k, v in self.entities.items()},
            "topics": {k: v.to_dict() for k, v in self.topics.items()},
            "goals": {k: v.to_dict() for k, v in self.goals.items()},
            "questions": {k: v.to_dict() for k, v in self.questions.items()},
            "pronoun_groups": {k: v.to_dict() for k, v in self.pronoun_groups.items()},
            "referents": {k: {"entity": v.entity_id, "confidence": v.confidence} for k, v in self.referents.items()},
            "active_topic_id": self.active_topic_id,
            "topic_stack": self.topic_stack,  # v0.7.3
            "groups": self.groups,            # v0.7.3
            "emotional_tone": self.emotional_tone.value,
            "turn_history_count": len(self.turn_history),
            # v0.7.6
            "snapshots_saved": self.snapshots_saved,
            "snapshots_loaded": self.snapshots_loaded,
            "rehydrated_from": self.rehydrated_from,
            # v0.7.7
            "entity_events_count": {k: len(v) for k, v in self.entity_events.items()},
        }


# =============================================================================
# GLOBAL MANAGER
# =============================================================================

class NovaWMManager:
    """Global manager for Working Memory instances across sessions."""
    
    def __init__(self):
        self._instances: Dict[str, NovaWorkingMemory] = {}
    
    def get(self, session_id: str) -> NovaWorkingMemory:
        """Get or create Working Memory for a session."""
        if session_id not in self._instances:
            self._instances[session_id] = NovaWorkingMemory(session_id)
        return self._instances[session_id]
    
    def clear(self, session_id: str) -> None:
        """Clear Working Memory for a session."""
        if session_id in self._instances:
            self._instances[session_id].clear()
    
    def delete(self, session_id: str) -> None:
        """Delete Working Memory for a session."""
        self._instances.pop(session_id, None)


# Global instance
_wm_manager = NovaWMManager()


# =============================================================================
# PUBLIC API (for kernel use)
# =============================================================================

def get_wm(session_id: str) -> NovaWorkingMemory:
    """Get Working Memory instance for a session."""
    return _wm_manager.get(session_id)


def wm_update(session_id: str, user_message: str, nova_response: Optional[str] = None) -> Dict[str, Any]:
    """Update Working Memory with a new turn."""
    wm = _wm_manager.get(session_id)
    return wm.update(user_message, nova_response)


def wm_record_response(session_id: str, response: str) -> None:
    """Record Nova's response in Working Memory."""
    wm = _wm_manager.get(session_id)
    wm.record_nova_response(response)


def wm_get_context(session_id: str) -> Dict[str, Any]:
    """Get context bundle for persona."""
    wm = _wm_manager.get(session_id)
    return wm.get_context_bundle()


def wm_get_context_string(session_id: str) -> str:
    """Get formatted context string for persona system prompt."""
    wm = _wm_manager.get(session_id)
    return wm.build_persona_context_string()


def wm_resolve_pronoun(session_id: str, pronoun: str) -> Optional[str]:
    """Resolve a pronoun to entity name."""
    wm = _wm_manager.get(session_id)
    entity = wm.resolve_pronoun(pronoun)
    return entity.name if entity else None


def wm_answer_reference(session_id: str, question: str) -> Optional[str]:
    """Try to answer a reference question from Working Memory."""
    wm = _wm_manager.get(session_id)
    return wm.answer_reference_question(question)


def wm_clear(session_id: str) -> None:
    """Clear Working Memory for a session."""
    _wm_manager.clear(session_id)


def wm_delete(session_id: str) -> None:
    """Delete Working Memory for a session."""
    _wm_manager.delete(session_id)


# =============================================================================
# v0.7.3 PUBLIC API ADDITIONS
# =============================================================================

def wm_clear_topic(session_id: str) -> str:
    """
    v0.7.3: Clear only the current topic, keep entities and pronouns.
    
    Returns:
        Confirmation message
    """
    wm = _wm_manager.get(session_id)
    return wm.clear_topic()


def wm_push_topic(session_id: str, new_topic_name: str) -> str:
    """
    v0.7.3: Create or activate a topic, push current topic to stack.
    
    Returns:
        The new topic ID
    """
    wm = _wm_manager.get(session_id)
    return wm.push_topic(new_topic_name)


def wm_pop_topic(session_id: str) -> Optional[str]:
    """
    v0.7.3: Return to previous topic from stack.
    
    Returns:
        The previous topic ID, or None if stack is empty
    """
    wm = _wm_manager.get(session_id)
    return wm.pop_topic()


def wm_list_topics(session_id: str) -> List[Dict[str, Any]]:
    """
    v0.7.3: Return list of recent topics.
    
    Returns:
        List of topic dicts
    """
    wm = _wm_manager.get(session_id)
    return wm.list_topics()


def wm_switch_topic(session_id: str, topic_identifier: str) -> Optional[str]:
    """
    v0.7.3: Switch to a topic by ID or name.
    
    Returns:
        Topic ID if found, None otherwise
    """
    wm = _wm_manager.get(session_id)
    return wm.switch_topic(topic_identifier)


def wm_register_group(session_id: str, name: str, members: List[str]) -> Optional[str]:
    """
    v0.7.3: Create a GROUP entity representing multiple people.
    
    Returns:
        Group entity ID, or None if no valid members found
    """
    wm = _wm_manager.get(session_id)
    return wm.register_group(name, members)


def wm_get_snapshot(session_id: str, label: Optional[str] = None) -> str:
    """
    v0.7.3: Get a snapshot summary for episodic storage.
    
    Args:
        session_id: Session identifier
        label: Optional label/topic for the snapshot
    
    Returns:
        Formatted snapshot string
    """
    wm = _wm_manager.get(session_id)
    return wm.get_snapshot_summary(label)


# =============================================================================
# v0.7.5 — META-QUESTION API
# =============================================================================

def wm_check_meta_question(session_id: str, message: str) -> Optional[Dict[str, Any]]:
    """
    v0.7.5: Check if a message is a meta-question about the conversation.
    
    Args:
        session_id: Session identifier
        message: User message to check
    
    Returns:
        Dict with meta-question info, or None
    """
    wm = _wm_manager.get(session_id)
    return wm.check_meta_question(message)


def wm_answer_meta_question(session_id: str, meta_info: Dict[str, Any]) -> Optional[str]:
    """
    v0.7.5: Generate an answer for a meta-question using WM state.
    
    Args:
        session_id: Session identifier
        meta_info: Result from wm_check_meta_question()
    
    Returns:
        Answer string, or None
    """
    wm = _wm_manager.get(session_id)
    return wm.answer_meta_question(meta_info)


def wm_get_group_info(session_id: str, group_id: str) -> Optional[Dict[str, Any]]:
    """
    v0.7.5: Get information about a group entity.
    
    Args:
        session_id: Session identifier
        group_id: Group entity ID
    
    Returns:
        Dict with group name and member details, or None
    """
    wm = _wm_manager.get(session_id)
    
    if group_id not in wm.entities:
        return None
    
    group = wm.entities[group_id]
    if group.entity_type != EntityType.GROUP:
        return None
    
    members = wm.get_group_members(group_id)
    member_info = []
    for m in members:
        member_info.append({
            "id": m.id,
            "name": m.name,
            "gender": m.gender_hint.value if m.gender_hint else "neutral",
        })
    
    return {
        "id": group_id,
        "name": group.name,
        "members": member_info,
        "last_mentioned": group.last_mentioned,
    }


# =============================================================================
# v0.7.6 PUBLIC API — PERSISTENCE LAYER
# =============================================================================

def wm_create_snapshot(
    session_id: str, 
    label: Optional[str] = None, 
    module: Optional[str] = None
) -> Dict[str, Any]:
    """
    v0.7.6: Create a snapshot payload for episodic memory storage.
    
    Args:
        session_id: Session identifier
        label: Optional label for the snapshot
        module: Optional module tag
    
    Returns:
        Dict with type, tags, and payload for MemoryManager.store()
    """
    wm = _wm_manager.get(session_id)
    snapshot = wm.create_snapshot_payload(label, module)
    
    # Track that we saved a snapshot
    snapshot_label = label or snapshot["payload"].get("topic", "unnamed")
    wm.snapshots_saved.append(snapshot_label)
    
    return snapshot


def wm_rehydrate_from_snapshot(session_id: str, snapshot_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    v0.7.6: Rehydrate WM entities from a snapshot payload.
    
    Args:
        session_id: Session identifier
        snapshot_data: The payload from a stored snapshot
    
    Returns:
        Dict with rehydration results
    """
    wm = _wm_manager.get(session_id)
    return wm.rehydrate_from_snapshot(snapshot_data)


def wm_get_snapshots_info(session_id: str) -> Dict[str, Any]:
    """
    v0.7.6: Get info about snapshots for this session.
    
    Returns:
        Dict with saved/loaded snapshot info
    """
    wm = _wm_manager.get(session_id)
    return {
        "saved": wm.snapshots_saved,
        "loaded": wm.snapshots_loaded,
        "rehydrated_from": wm.rehydrated_from,
    }


# =============================================================================
# v0.7.7 PUBLIC API — ENHANCED GROUPS & EVENT RECALL
# =============================================================================

def wm_get_all_groups(session_id: str) -> List[Dict[str, Any]]:
    """
    v0.7.7: Get all group entities with member details.
    
    Returns:
        List of group dicts
    """
    wm = _wm_manager.get(session_id)
    return wm.get_all_groups()


def wm_get_group_context(session_id: str) -> str:
    """
    v0.7.7: Get context string for groups.
    
    Returns:
        Formatted string for behavior layer
    """
    wm = _wm_manager.get(session_id)
    return wm.get_group_context_string()


def wm_record_entity_event(session_id: str, entity_name: str, event_type: str, content: str) -> bool:
    """
    v0.7.7: Record an event for an entity.
    
    Args:
        session_id: Session identifier
        entity_name: Name of the entity
        event_type: Type of event (said, did, asked, suggested)
        content: The event content
    
    Returns:
        True if recorded, False if entity not found
    """
    wm = _wm_manager.get(session_id)
    entity = wm._find_entity_by_name(entity_name)
    if not entity:
        return False
    
    wm.record_entity_event(entity.id, event_type, content)
    return True


def wm_answer_event_recall(session_id: str, entity_name: str, event_type: Optional[str] = None) -> Optional[str]:
    """
    v0.7.7: Answer "what did X say/do?" questions.
    
    Args:
        session_id: Session identifier
        entity_name: Name of the entity
        event_type: Optional filter (said, did, asked, suggested)
    
    Returns:
        Answer string, or None
    """
    wm = _wm_manager.get(session_id)
    return wm.answer_event_recall(entity_name, event_type)


def wm_merge_topic(session_id: str, topic_name: str) -> str:
    """
    v0.7.7: Merge into existing topic or create new.
    
    Args:
        session_id: Session identifier
        topic_name: Topic name
    
    Returns:
        Topic ID
    """
    wm = _wm_manager.get(session_id)
    return wm.merge_topic(topic_name)


# Bridge function for loading relevant snapshots from memory
def wm_bridge_load_relevant(
    session_id: str,
    memory_manager,
    module: Optional[str] = None,
    max_snapshots: int = 3,
) -> List[Dict[str, Any]]:
    """
    v0.7.6: Load relevant WM snapshots from episodic memory.
    
    Args:
        session_id: Session identifier
        memory_manager: MemoryManager instance
        module: Optional module filter
        max_snapshots: Maximum snapshots to load
    
    Returns:
        List of rehydration results
    """
    if memory_manager is None:
        return []
    
    wm = _wm_manager.get(session_id)
    results = []
    
    try:
        # Query for WM snapshots
        tags = ["wm", "snapshot"]
        if module:
            tags.append(f"module:{module}")
        
        memories = memory_manager.recall(type="episodic", tags=tags)
        
        for memory in memories[:max_snapshots]:
            payload = memory.get("payload", {})
            if isinstance(payload, str):
                # Try to parse if JSON string
                try:
                    payload = json.loads(payload)
                except:
                    continue
            
            # Rehydrate
            result = wm.rehydrate_from_snapshot(payload)
            result["memory_id"] = memory.get("id")
            result["topic"] = payload.get("topic", "unknown")
            results.append(result)
            
            # Track that we loaded this
            wm.snapshots_loaded.append(memory.get("id"))
    
    except Exception as e:
        results.append({"error": str(e)})
    
    return results

