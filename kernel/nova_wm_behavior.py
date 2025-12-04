# kernel/nova_wm_behavior.py
"""
NovaOS v0.7.2 — Working Memory Behavior Layer

This layer sits above the entity/topic/pronoun memory from v0.7.0–v0.7.1
and provides human-like conversational continuity.

Key Capabilities:
- Open question tracking (when Nova asks something)
- Implicit reply understanding ("yes", "idk", "sure", etc.)
- Conversational goal management with lifecycle states
- Topic drift detection ("Anyway...", "Different question...")
- User state inference (confusion, urgency, decisiveness)
- Conversation thread memory with summaries

Integration:
    from nova_wm_behavior import (
        behavior_update,
        behavior_after_response,
        behavior_get_context,
    )
    
    # In persona fallback flow:
    wm_update(session_id, user_message)
    behavior_update(session_id, user_message)
    # ... generate response ...
    behavior_after_response(session_id, nova_response)

This layer is ADDITIVE — it does not modify v0.7.1 entity/pronoun logic.
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Set, Tuple
from enum import Enum
from datetime import datetime
import re


# =============================================================================
# ENUMS
# =============================================================================

class ConversationGoalType(Enum):
    """Types of conversational goals Nova can assist with."""
    DECISION_ASSIST = "decision_assist"     # Help user decide something
    GUIDANCE = "guidance"                    # User needs direction
    REFLECTION = "reflection"                # Help user think through something
    PLANNING = "planning"                    # Help user plan
    DRAFTING = "drafting"                    # Help draft a message/document
    DEBRIEFING = "debriefing"               # Debrief a situation/conversation
    INFORMATION = "information"              # Provide information
    EMOTIONAL_SUPPORT = "emotional_support"  # User needs emotional support
    BRAINSTORMING = "brainstorming"         # Generate ideas
    UNKNOWN = "unknown"


class GoalStatus(Enum):
    """Lifecycle states for conversation goals."""
    CREATED = "created"
    ACTIVE = "active"
    RESOLVED = "resolved"
    DROPPED = "dropped"


class UserStateSignal(Enum):
    """Inferred user state signals."""
    UNCERTAIN = "uncertain"
    CONFUSED = "confused"
    STRESSED = "stressed"
    DISENGAGED = "disengaged"
    ENGAGED = "engaged"
    DECISIVE = "decisive"
    INDECISIVE = "indecisive"
    URGENT = "urgent"
    RELAXED = "relaxed"
    FRUSTRATED = "frustrated"


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class OpenQuestion:
    """
    An open question that Nova has asked and is awaiting response.
    """
    id: str
    text: str                          # The question text
    turn_asked: int                    # Which turn Nova asked this
    topic_id: Optional[str] = None     # Related topic
    goal_id: Optional[str] = None      # Related goal
    answered: bool = False
    answer_turn: Optional[int] = None
    answer_text: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "turn_asked": self.turn_asked,
            "topic_id": self.topic_id,
            "goal_id": self.goal_id,
            "answered": self.answered,
            "answer_turn": self.answer_turn,
        }


@dataclass
class ConversationGoal:
    """
    A conversational goal the user is pursuing.
    """
    id: str
    goal_type: ConversationGoalType
    description: str                    # "decide whether to follow up with Steven"
    status: GoalStatus = GoalStatus.CREATED
    related_entities: List[str] = field(default_factory=list)
    related_topics: List[str] = field(default_factory=list)
    created_at: int = 0                # Turn number
    activated_at: Optional[int] = None
    resolved_at: Optional[int] = None
    resolution: Optional[str] = None   # How it was resolved
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.goal_type.value,
            "description": self.description,
            "status": self.status.value,
            "related_entities": self.related_entities,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
        }


@dataclass
class UserState:
    """
    Inferred state of the user based on conversation signals.
    """
    clarity_level: float = 0.5         # 0=confused, 1=clear
    decisiveness: float = 0.5          # 0=indecisive, 1=decisive
    stress_level: float = 0.0          # 0=relaxed, 1=stressed
    engagement: float = 0.5            # 0=disengaged, 1=highly engaged
    urgency: float = 0.0               # 0=no rush, 1=urgent
    signals: List[UserStateSignal] = field(default_factory=list)
    last_updated: int = 0              # Turn number
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "clarity_level": round(self.clarity_level, 2),
            "decisiveness": round(self.decisiveness, 2),
            "stress_level": round(self.stress_level, 2),
            "engagement": round(self.engagement, 2),
            "urgency": round(self.urgency, 2),
            "signals": [s.value for s in self.signals],
        }
    
    def get_primary_signal(self) -> Optional[str]:
        """Get the strongest signal."""
        if self.signals:
            return self.signals[0].value
        if self.stress_level > 0.6:
            return "stressed"
        if self.clarity_level < 0.3:
            return "confused"
        if self.engagement < 0.3:
            return "disengaged"
        if self.urgency > 0.6:
            return "urgent"
        return None


@dataclass
class TopicTransition:
    """
    Record of a topic transition.
    """
    from_topic: Optional[str]
    to_topic: str
    turn: int
    trigger_phrase: Optional[str] = None  # "Anyway...", "Different question..."
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "from": self.from_topic,
            "to": self.to_topic,
            "turn": self.turn,
            "trigger": self.trigger_phrase,
        }


@dataclass
class ThreadSummary:
    """
    Summary of the current conversation thread.
    """
    topic: Optional[str] = None
    goal: Optional[str] = None
    participants: List[str] = field(default_factory=list)
    unresolved_questions: List[str] = field(default_factory=list)
    key_points: List[str] = field(default_factory=list)
    turn_range: Tuple[int, int] = (0, 0)  # (start_turn, end_turn)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "topic": self.topic,
            "goal": self.goal,
            "participants": self.participants,
            "unresolved_questions": self.unresolved_questions,
            "key_points": self.key_points,
            "turn_range": self.turn_range,
        }


# =============================================================================
# PATTERN DEFINITIONS
# =============================================================================

# Implicit reply patterns (maps to most recent open question)
IMPLICIT_AFFIRMATIVE = {
    r"^yes\.?$", r"^yep\.?$", r"^yeah\.?$", r"^yea\.?$", r"^y$",
    r"^sure\.?$", r"^ok(ay)?\.?$", r"^alright\.?$", r"^sounds good\.?$",
    r"^go ahead\.?$", r"^proceed\.?$", r"^do it\.?$", r"^please\.?$",
    r"^definitely\.?$", r"^absolutely\.?$", r"^of course\.?$",
    r"^let'?s do it\.?$", r"^let'?s go\.?$", r"^i think so\.?$",
}

IMPLICIT_NEGATIVE = {
    r"^no\.?$", r"^nope\.?$", r"^nah\.?$", r"^n$",
    r"^not really\.?$", r"^i don'?t think so\.?$",
    r"^skip\.?$", r"^pass\.?$", r"^never mind\.?$", r"^nevermind\.?$",
}

IMPLICIT_UNCERTAIN = {
    r"^idk\.?$", r"^i don'?t know\.?$", r"^not sure\.?$",
    r"^maybe\.?$", r"^perhaps\.?$", r"^possibly\.?$",
    r"^i'?m not sure\.?$", r"^hard to say\.?$",
    r"^either\.?$", r"^whichever\.?$", r"^both\.?$", r"^neither\.?$",
}

IMPLICIT_CONTINUE = {
    r"^continue\.?$", r"^go on\.?$", r"^keep going\.?$",
    r"^explain more\.?$", r"^tell me more\.?$", r"^more\.?$",
    r"^and\??$", r"^then\??$", r"^what else\.?$",
}

IMPLICIT_DEFER = {
    r"^what do you think\??$", r"^you decide\.?$",
    r"^your call\.?$", r"^up to you\.?$",
    r"^i'?ll leave it to you\.?$", r"^you choose\.?$",
}

# Topic switch patterns
TOPIC_SWITCH_PATTERNS = [
    (r"^anyway[,\.\-—]?\s+", "anyway"),  # Must have space after
    (r"^different (?:question|topic|thing)[,\.\-—:\s]+", "different"),
    (r"^switching (?:gears|topics?)[,\.\-—:\s]+", "switching"),
    (r"^also[,\.\-—]\s+", "also"),  # Must have punctuation then space
    (r"^oh[,\.\-—]\s*(?:also|and|btw)\b", "oh_also"),
    (r"^btw[,\.\-—]?\s+", "btw"),
    (r"^by the way[,\.\-—]?\s+", "btw"),
    (r"^on (?:a|another) (?:different|separate) (?:note|topic)[,\.\-—:\s]+", "different_note"),
    (r"^new topic[,\.\-—:\s]+", "new_topic"),
    (r"^unrelated[,\.\-—:\s]+", "unrelated"),
    (r"^quick question[,\.\-—:\s]+", "quick_question"),
    (r"^random[,\.\-—:\s]+", "random"),
]

# Goal inference patterns
GOAL_PATTERNS = {
    ConversationGoalType.DECISION_ASSIST: [
        r"\bshould i\b",
        r"\bwhat should i\b",
        r"\bi need to decide\b",
        r"\bhelp me decide\b",
        r"\bwhich (?:one|should)\b",
    ],
    ConversationGoalType.GUIDANCE: [
        r"\bi don'?t know what to do\b",
        r"\bwhat do i do\b",
        r"\bhelp me (?:figure|understand)\b",
        r"\bi'?m lost\b",
        r"\bi'?m stuck\b",
    ],
    ConversationGoalType.REFLECTION: [
        r"\bhelp me think\b",
        r"\blet me think\b",
        r"\bthinking about\b",
        r"\bprocessing\b",
        r"\breflecting on\b",
    ],
    ConversationGoalType.PLANNING: [
        r"\bplan(?:ning)?\b",
        r"\bnext steps?\b",
        r"\bwhat'?s next\b",
        r"\bhow do i\b",
        r"\bwhat should i do next\b",
    ],
    ConversationGoalType.DRAFTING: [
        r"\bdraft\b",
        r"\bwrite (?:a|an|the)\b",
        r"\bhelp me (?:write|compose|craft)\b",
        r"\bmessage (?:to|for)\b",
        r"\bemail (?:to|for)\b",
    ],
    ConversationGoalType.DEBRIEFING: [
        r"\bdebrief\b",
        r"\bwhat happened\b",
        r"\btell me about\b",
        r"\bso (?:basically|essentially)\b",
        r"\blet me tell you\b",
    ],
    ConversationGoalType.EMOTIONAL_SUPPORT: [
        r"\bi'?m (?:stressed|anxious|worried|scared|upset|sad|frustrated)\b",
        r"\bfeeling (?:stressed|anxious|worried|scared|upset|sad|frustrated)\b",
        r"\bneed (?:to vent|support)\b",
        r"\blistening?\b",
    ],
    ConversationGoalType.BRAINSTORMING: [
        r"\bbrainstorm\b",
        r"\bideas?\b",
        r"\bwhat if\b",
        r"\bpossibilities\b",
        r"\boptions?\b",
    ],
}

# User state inference patterns
USER_STATE_PATTERNS = {
    UserStateSignal.UNCERTAIN: [
        r"\bidk\b", r"\bi don'?t know\b", r"\bnot sure\b",
        r"\bmaybe\b", r"\bperhaps\b", r"\bi guess\b",
    ],
    UserStateSignal.CONFUSED: [
        r"\bconfused\b", r"\bwait what\b", r"\bhuh\??$",
        r"\bi don'?t understand\b", r"\bwhat do you mean\b",
        r"\bi'?m lost\b", r"\bokay wait\b",
    ],
    UserStateSignal.STRESSED: [
        r"\bstressed\b", r"\banxious\b", r"\bworried\b",
        r"\boverwhelmed\b", r"\bfreaking out\b", r"\bpanicking\b",
    ],
    UserStateSignal.FRUSTRATED: [
        r"\bfrustrated\b", r"\bannoyed\b", r"\birritated\b",
        r"\bugh\b", r"\bthis is (?:annoying|frustrating)\b",
    ],
    UserStateSignal.URGENT: [
        r"\burgent\b", r"\basap\b", r"\bright now\b",
        r"\bimmediately\b", r"\bquickly\b", r"\btime sensitive\b",
    ],
    UserStateSignal.DISENGAGED: [
        r"^nah\.?$", r"^meh\.?$", r"\bwhatever\b",
        r"\bi don'?t care\b", r"\bdoesn'?t matter\b",
    ],
    UserStateSignal.DECISIVE: [
        r"\bi'?ve decided\b", r"\bi'?m going to\b", r"\bi will\b",
        r"\bdefinitely\b", r"\bfor sure\b", r"\blet'?s do\b",
    ],
}

# Nova question patterns (to detect when Nova is asking something)
NOVA_QUESTION_PATTERNS = [
    r"\?$",                                    # Ends with question mark
    r"\bwhat do you think\b",
    r"\bshould i\b.*\?",
    r"\bdo you want\b.*\?",
    r"\bwhich (?:one|option)\b.*\?",
    r"\bwhat'?s next\b.*\?",
    r"\bwould you (?:like|prefer)\b.*\?",
    r"\bhow (?:about|would)\b.*\?",
    r"\bany (?:thoughts|preferences)\b.*\?",
]


# =============================================================================
# BEHAVIOR ENGINE
# =============================================================================

class WMBehaviorEngine:
    """
    The Behavior Layer for NovaOS Working Memory.
    
    Provides human-like conversational continuity by tracking:
    - Open questions Nova has asked
    - Implicit replies from user
    - Conversation goals
    - Topic transitions
    - User state inference
    """
    
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.turn_count: int = 0
        
        # Open questions tracking
        self.open_questions: List[OpenQuestion] = []
        self._question_counter: int = 0
        
        # Goal tracking
        self.goals: Dict[str, ConversationGoal] = {}
        self.active_goal_id: Optional[str] = None
        self.goal_stack: List[str] = []  # For nested goals
        self._goal_counter: int = 0
        
        # User state
        self.user_state: UserState = UserState()
        
        # Topic transitions
        self.topic_transitions: List[TopicTransition] = []
        self.current_topic_id: Optional[str] = None
        
        # Thread memory
        self.thread_summary: ThreadSummary = ThreadSummary()
        
        # Last Nova response (for question extraction)
        self.last_nova_response: Optional[str] = None
        
        # Implicit reply mapping
        self.last_implicit_mapping: Optional[Dict[str, Any]] = None
    
    # =========================================================================
    # ID GENERATION
    # =========================================================================
    
    def _gen_question_id(self) -> str:
        self._question_counter += 1
        return f"oq{self._question_counter}"
    
    def _gen_goal_id(self) -> str:
        self._goal_counter += 1
        return f"bg{self._goal_counter}"
    
    # =========================================================================
    # UPDATE FROM USER MESSAGE
    # =========================================================================
    
    def update(self, user_message: str, wm_context: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Update behavior state based on user message.
        
        Called AFTER wm_update() in the kernel flow.
        
        Args:
            user_message: The user's message
            wm_context: Context from NovaWM (entities, pronouns, etc.)
        
        Returns:
            Dict with behavior analysis results
        """
        self.turn_count += 1
        wm_context = wm_context or {}
        
        result = {
            "turn": self.turn_count,
            "implicit_reply": None,
            "answered_question": None,
            "goal_detected": None,
            "topic_switch": None,
            "user_state_signals": [],
        }
        
        message_lower = user_message.lower().strip()
        
        # 1. Check for implicit reply to open question
        implicit_result = self._check_implicit_reply(message_lower)
        if implicit_result:
            result["implicit_reply"] = implicit_result
            result["answered_question"] = implicit_result.get("question_id")
        
        # 2. Check for topic switch
        topic_switch = self._check_topic_switch(user_message, wm_context)
        if topic_switch:
            result["topic_switch"] = topic_switch
        
        # 3. Detect conversation goal
        goal = self._detect_goal(user_message, wm_context)
        if goal:
            self._add_goal(goal)
            result["goal_detected"] = goal.to_dict()
        
        # 4. Update user state
        signals = self._infer_user_state(message_lower)
        result["user_state_signals"] = [s.value for s in signals]
        
        # 5. Update thread summary
        self._update_thread_summary(wm_context)
        
        return result
    
    def after_response(self, nova_response: str) -> Dict[str, Any]:
        """
        Process Nova's response to extract questions and update state.
        
        Called AFTER generating the response.
        
        Args:
            nova_response: Nova's generated response
        
        Returns:
            Dict with questions found
        """
        self.last_nova_response = nova_response
        
        result = {
            "questions_found": [],
        }
        
        # Extract questions from Nova's response
        questions = self._extract_nova_questions(nova_response)
        for q in questions:
            self.open_questions.append(q)
            result["questions_found"].append(q.to_dict())
        
        # Keep only last 5 open questions
        if len(self.open_questions) > 5:
            self.open_questions = self.open_questions[-5:]
        
        return result
    
    # =========================================================================
    # IMPLICIT REPLY HANDLING
    # =========================================================================
    
    def _check_implicit_reply(self, message: str) -> Optional[Dict[str, Any]]:
        """
        Check if message is an implicit reply to an open question.
        """
        if not self.open_questions:
            return None
        
        # Find unanswered questions
        unanswered = [q for q in self.open_questions if not q.answered]
        if not unanswered:
            return None
        
        # Most recent unanswered question
        target_question = unanswered[-1]
        
        # Check affirmative patterns
        for pattern in IMPLICIT_AFFIRMATIVE:
            if re.match(pattern, message, re.IGNORECASE):
                self._mark_question_answered(target_question, message, "affirmative")
                return {
                    "type": "affirmative",
                    "question_id": target_question.id,
                    "question_text": target_question.text,
                    "interpretation": "yes",
                }
        
        # Check negative patterns
        for pattern in IMPLICIT_NEGATIVE:
            if re.match(pattern, message, re.IGNORECASE):
                self._mark_question_answered(target_question, message, "negative")
                return {
                    "type": "negative",
                    "question_id": target_question.id,
                    "question_text": target_question.text,
                    "interpretation": "no",
                }
        
        # Check uncertain patterns
        for pattern in IMPLICIT_UNCERTAIN:
            if re.match(pattern, message, re.IGNORECASE):
                self._mark_question_answered(target_question, message, "uncertain")
                return {
                    "type": "uncertain",
                    "question_id": target_question.id,
                    "question_text": target_question.text,
                    "interpretation": "unsure",
                }
        
        # Check continue patterns
        for pattern in IMPLICIT_CONTINUE:
            if re.match(pattern, message, re.IGNORECASE):
                return {
                    "type": "continue",
                    "question_id": target_question.id,
                    "question_text": target_question.text,
                    "interpretation": "continue",
                }
        
        # Check defer patterns
        for pattern in IMPLICIT_DEFER:
            if re.match(pattern, message, re.IGNORECASE):
                return {
                    "type": "defer",
                    "question_id": target_question.id,
                    "question_text": target_question.text,
                    "interpretation": "defer_to_nova",
                }
        
        return None
    
    def _mark_question_answered(
        self, 
        question: OpenQuestion, 
        answer: str, 
        answer_type: str
    ) -> None:
        """Mark a question as answered."""
        question.answered = True
        question.answer_turn = self.turn_count
        question.answer_text = answer
    
    # =========================================================================
    # TOPIC SWITCHING
    # =========================================================================
    
    def _check_topic_switch(
        self, 
        message: str, 
        wm_context: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Check if user is switching topics.
        """
        message_lower = message.lower().strip()
        
        for pattern, trigger_name in TOPIC_SWITCH_PATTERNS:
            match = re.match(pattern, message_lower, re.IGNORECASE)
            if match:
                # Record the transition
                old_topic = self.current_topic_id
                
                # Get new topic from WM context if available
                new_topic = wm_context.get("active_topic", {}).get("name", "new topic")
                
                transition = TopicTransition(
                    from_topic=old_topic,
                    to_topic=new_topic,
                    turn=self.turn_count,
                    trigger_phrase=trigger_name,
                )
                self.topic_transitions.append(transition)
                self.current_topic_id = new_topic
                
                # Close previous topic's goal if any
                if self.active_goal_id and old_topic:
                    self._pause_goal(self.active_goal_id)
                
                return {
                    "from_topic": old_topic,
                    "to_topic": new_topic,
                    "trigger": trigger_name,
                }
        
        return None
    
    # =========================================================================
    # GOAL DETECTION & MANAGEMENT
    # =========================================================================
    
    def _detect_goal(
        self, 
        message: str, 
        wm_context: Dict[str, Any]
    ) -> Optional[ConversationGoal]:
        """
        Detect conversation goal from user message.
        """
        message_lower = message.lower()
        
        for goal_type, patterns in GOAL_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, message_lower, re.IGNORECASE):
                    # Don't create duplicate goals
                    for existing in self.goals.values():
                        if existing.goal_type == goal_type and existing.status == GoalStatus.ACTIVE:
                            return None
                    
                    # Extract related entities from WM context
                    entities = []
                    if wm_context.get("entities"):
                        people = wm_context["entities"].get("people", [])
                        entities = [p.get("name") for p in people[:3] if p.get("name")]
                    
                    goal = ConversationGoal(
                        id=self._gen_goal_id(),
                        goal_type=goal_type,
                        description=self._extract_goal_description(message, goal_type),
                        status=GoalStatus.ACTIVE,
                        related_entities=entities,
                        created_at=self.turn_count,
                        activated_at=self.turn_count,
                    )
                    return goal
        
        return None
    
    def _extract_goal_description(self, message: str, goal_type: ConversationGoalType) -> str:
        """Extract a description for the goal from the message."""
        # Truncate and clean
        desc = message.strip()
        if len(desc) > 80:
            desc = desc[:80] + "..."
        
        # Add goal type prefix for clarity
        prefixes = {
            ConversationGoalType.DECISION_ASSIST: "Help decide:",
            ConversationGoalType.GUIDANCE: "Provide guidance:",
            ConversationGoalType.REFLECTION: "Help reflect on:",
            ConversationGoalType.PLANNING: "Help plan:",
            ConversationGoalType.DRAFTING: "Help draft:",
            ConversationGoalType.DEBRIEFING: "Debrief:",
            ConversationGoalType.EMOTIONAL_SUPPORT: "Provide support:",
            ConversationGoalType.BRAINSTORMING: "Brainstorm:",
        }
        
        prefix = prefixes.get(goal_type, "")
        if prefix:
            return f"{prefix} {desc}"
        return desc
    
    def _add_goal(self, goal: ConversationGoal) -> None:
        """Add a goal and make it active."""
        self.goals[goal.id] = goal
        
        # Push current goal to stack if exists
        if self.active_goal_id:
            self.goal_stack.append(self.active_goal_id)
        
        self.active_goal_id = goal.id
    
    def _pause_goal(self, goal_id: str) -> None:
        """Pause a goal (when switching topics)."""
        if goal_id in self.goals:
            # Don't change status, just remove from active
            if self.active_goal_id == goal_id:
                self.active_goal_id = None
    
    def resolve_goal(self, goal_id: str = None, resolution: str = None) -> bool:
        """
        Mark a goal as resolved.
        
        Args:
            goal_id: The goal to resolve (defaults to active goal)
            resolution: How it was resolved
        
        Returns:
            True if goal was found and resolved
        """
        target_id = goal_id or self.active_goal_id
        if not target_id or target_id not in self.goals:
            return False
        
        goal = self.goals[target_id]
        goal.status = GoalStatus.RESOLVED
        goal.resolved_at = self.turn_count
        goal.resolution = resolution
        
        # Pop from stack if needed
        if self.active_goal_id == target_id:
            if self.goal_stack:
                self.active_goal_id = self.goal_stack.pop()
            else:
                self.active_goal_id = None
        
        return True
    
    def get_active_goal(self) -> Optional[ConversationGoal]:
        """Get the currently active goal."""
        if self.active_goal_id and self.active_goal_id in self.goals:
            return self.goals[self.active_goal_id]
        return None
    
    # =========================================================================
    # USER STATE INFERENCE
    # =========================================================================
    
    def _infer_user_state(self, message: str) -> List[UserStateSignal]:
        """
        Infer user state signals from message.
        """
        signals = []
        
        for signal, patterns in USER_STATE_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, message, re.IGNORECASE):
                    signals.append(signal)
                    break  # One match per signal type
        
        # Update user state based on signals
        self._update_user_state(signals)
        
        return signals
    
    def _update_user_state(self, signals: List[UserStateSignal]) -> None:
        """
        Update user state based on detected signals.
        """
        # Decay existing signals slightly
        self.user_state.clarity_level = min(1.0, self.user_state.clarity_level + 0.05)
        self.user_state.stress_level = max(0.0, self.user_state.stress_level - 0.05)
        self.user_state.urgency = max(0.0, self.user_state.urgency - 0.05)
        
        # Apply new signals
        for signal in signals:
            if signal == UserStateSignal.UNCERTAIN:
                self.user_state.clarity_level -= 0.2
                self.user_state.decisiveness -= 0.1
            
            elif signal == UserStateSignal.CONFUSED:
                self.user_state.clarity_level -= 0.3
            
            elif signal == UserStateSignal.STRESSED:
                self.user_state.stress_level += 0.3
            
            elif signal == UserStateSignal.FRUSTRATED:
                self.user_state.stress_level += 0.2
                self.user_state.engagement += 0.1  # Frustration often means engaged
            
            elif signal == UserStateSignal.URGENT:
                self.user_state.urgency += 0.3
            
            elif signal == UserStateSignal.DISENGAGED:
                self.user_state.engagement -= 0.3
            
            elif signal == UserStateSignal.DECISIVE:
                self.user_state.decisiveness += 0.3
                self.user_state.clarity_level += 0.1
        
        # Clamp values
        self.user_state.clarity_level = max(0.0, min(1.0, self.user_state.clarity_level))
        self.user_state.decisiveness = max(0.0, min(1.0, self.user_state.decisiveness))
        self.user_state.stress_level = max(0.0, min(1.0, self.user_state.stress_level))
        self.user_state.engagement = max(0.0, min(1.0, self.user_state.engagement))
        self.user_state.urgency = max(0.0, min(1.0, self.user_state.urgency))
        
        # Store signals
        self.user_state.signals = signals[:3]  # Keep top 3
        self.user_state.last_updated = self.turn_count
    
    # =========================================================================
    # NOVA QUESTION EXTRACTION
    # =========================================================================
    
    def _extract_nova_questions(self, response: str) -> List[OpenQuestion]:
        """
        Extract questions from Nova's response.
        """
        questions = []
        
        # Split into sentences
        sentences = re.split(r'[.!]\s+', response)
        
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            
            # Check if it's a question
            is_question = False
            for pattern in NOVA_QUESTION_PATTERNS:
                if re.search(pattern, sentence, re.IGNORECASE):
                    is_question = True
                    break
            
            if is_question:
                question = OpenQuestion(
                    id=self._gen_question_id(),
                    text=sentence,
                    turn_asked=self.turn_count,
                    topic_id=self.current_topic_id,
                    goal_id=self.active_goal_id,
                )
                questions.append(question)
        
        return questions
    
    # =========================================================================
    # THREAD SUMMARY
    # =========================================================================
    
    def _update_thread_summary(self, wm_context: Dict[str, Any]) -> None:
        """
        Update the thread summary with current state.
        """
        # Topic
        if wm_context.get("active_topic"):
            self.thread_summary.topic = wm_context["active_topic"].get("name")
        
        # Goal
        if self.active_goal_id and self.active_goal_id in self.goals:
            self.thread_summary.goal = self.goals[self.active_goal_id].description
        
        # Participants (people from WM)
        if wm_context.get("entities"):
            people = wm_context["entities"].get("people", [])
            self.thread_summary.participants = [
                p.get("name") for p in people if p.get("name")
            ][:5]
        
        # Unresolved questions
        self.thread_summary.unresolved_questions = [
            q.text for q in self.open_questions if not q.answered
        ][:3]
        
        # Update turn range
        start = self.thread_summary.turn_range[0] or self.turn_count
        self.thread_summary.turn_range = (start, self.turn_count)
    
    # =========================================================================
    # CONTEXT GENERATION
    # =========================================================================
    
    def get_context(self) -> Dict[str, Any]:
        """
        Get behavior context bundle for persona injection.
        """
        active_goal = self.get_active_goal()
        
        return {
            "active_topic": self.current_topic_id,
            "active_goal": active_goal.to_dict() if active_goal else None,
            "goal_type": active_goal.goal_type.value if active_goal else None,
            "open_questions": [q.to_dict() for q in self.open_questions if not q.answered],
            "user_state": self.user_state.to_dict(),
            "user_state_signal": self.user_state.get_primary_signal(),
            "thread_summary": self.thread_summary.to_dict(),
            "topic_transitions": [t.to_dict() for t in self.topic_transitions[-3:]],
            "last_implicit_reply": self.last_implicit_mapping,
        }
    
    def build_context_string(self) -> str:
        """
        Build a formatted context string for persona system prompt.
        """
        ctx = self.get_context()
        lines = []
        
        lines.append("[BEHAVIOR LAYER - CONVERSATIONAL CONTINUITY]")
        lines.append("")
        
        # Active goal
        if ctx["active_goal"]:
            lines.append(f"ACTIVE GOAL: {ctx['active_goal']['description']}")
            lines.append(f"  Type: {ctx['goal_type']}")
            lines.append("")
        
        # Open questions (questions Nova asked)
        if ctx["open_questions"]:
            lines.append("AWAITING USER RESPONSE TO:")
            for q in ctx["open_questions"][:2]:
                lines.append(f"  • \"{q['text'][:60]}...\"" if len(q['text']) > 60 else f"  • \"{q['text']}\"")
            lines.append("")
        
        # User state
        if ctx["user_state_signal"]:
            lines.append(f"USER STATE: {ctx['user_state_signal']}")
            state = ctx["user_state"]
            if state["stress_level"] > 0.5:
                lines.append(f"  ⚠️ User appears stressed")
            if state["clarity_level"] < 0.4:
                lines.append(f"  ⚠️ User may be confused")
            if state["urgency"] > 0.5:
                lines.append(f"  ⚠️ User indicates urgency")
            lines.append("")
        
        # Thread summary
        summary = ctx["thread_summary"]
        if summary.get("participants"):
            lines.append(f"PARTICIPANTS: {', '.join(summary['participants'])}")
        if summary.get("unresolved_questions"):
            lines.append(f"UNRESOLVED: {len(summary['unresolved_questions'])} questions pending")
        
        # Topic transitions
        if ctx["topic_transitions"]:
            last_transition = ctx["topic_transitions"][-1]
            lines.append(f"TOPIC SHIFT: '{last_transition.get('from')}' → '{last_transition.get('to')}'")
        
        if len(lines) <= 2:  # Only header
            return ""  # No behavior context needed
        
        lines.append("")
        lines.append("─" * 40)
        lines.append("BEHAVIOR INSTRUCTIONS:")
        lines.append("• If user gives short reply (yes/no/idk), map to AWAITING RESPONSE question.")
        lines.append("• Acknowledge user state naturally if stressed/confused/urgent.")
        lines.append("• Keep goal in mind when responding.")
        lines.append("─" * 40)
        
        return "\n".join(lines)
    
    # =========================================================================
    # ANSWER REFERENCE QUESTIONS
    # =========================================================================
    
    def answer_reference_question(self, question: str) -> Optional[str]:
        """
        Try to answer "what were we talking about?" type questions.
        """
        question_lower = question.lower().strip()
        
        # "What were we talking about?"
        if re.search(r"\bwhat\s+(were|are)\s+we\s+talk", question_lower):
            summary = self.thread_summary
            parts = []
            
            if summary.topic:
                parts.append(f"We were discussing {summary.topic}")
            
            if summary.participants:
                parts.append(f"involving {', '.join(summary.participants[:2])}")
            
            goal = self.get_active_goal()
            if goal:
                parts.append(f"Your goal was to {goal.description.lower()}")
            
            if parts:
                return ". ".join(parts) + "."
            return None
        
        # "What was the question?" / "What did you ask?"
        if re.search(r"\bwhat\s+(was|is)\s+the\s+question\b|\bwhat\s+did\s+you\s+ask\b", question_lower):
            unanswered = [q for q in self.open_questions if not q.answered]
            if unanswered:
                return f"I asked: \"{unanswered[-1].text}\""
            return None
        
        return None
    
    # =========================================================================
    # RESET / CLEAR
    # =========================================================================
    
    def clear(self) -> None:
        """Clear all behavior state."""
        self.turn_count = 0
        self.open_questions.clear()
        self.goals.clear()
        self.active_goal_id = None
        self.goal_stack.clear()
        self.user_state = UserState()
        self.topic_transitions.clear()
        self.current_topic_id = None
        self.thread_summary = ThreadSummary()
        self.last_nova_response = None
        self.last_implicit_mapping = None
    
    # =========================================================================
    # SERIALIZATION
    # =========================================================================
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize for debugging."""
        return {
            "session_id": self.session_id,
            "turn_count": self.turn_count,
            "open_questions": [q.to_dict() for q in self.open_questions],
            "active_goal_id": self.active_goal_id,
            "goals": {k: v.to_dict() for k, v in self.goals.items()},
            "goal_stack": self.goal_stack,
            "user_state": self.user_state.to_dict(),
            "current_topic_id": self.current_topic_id,
            "topic_transitions": [t.to_dict() for t in self.topic_transitions],
            "thread_summary": self.thread_summary.to_dict(),
        }


# =============================================================================
# GLOBAL MANAGER
# =============================================================================

class BehaviorEngineManager:
    """Global manager for Behavior Engine instances across sessions."""
    
    def __init__(self):
        self._instances: Dict[str, WMBehaviorEngine] = {}
    
    def get(self, session_id: str) -> WMBehaviorEngine:
        """Get or create Behavior Engine for a session."""
        if session_id not in self._instances:
            self._instances[session_id] = WMBehaviorEngine(session_id)
        return self._instances[session_id]
    
    def clear(self, session_id: str) -> None:
        """Clear Behavior Engine for a session."""
        if session_id in self._instances:
            self._instances[session_id].clear()
    
    def delete(self, session_id: str) -> None:
        """Delete Behavior Engine for a session."""
        self._instances.pop(session_id, None)


# Global instance
_behavior_manager = BehaviorEngineManager()


# =============================================================================
# PUBLIC API
# =============================================================================

def get_behavior_engine(session_id: str) -> WMBehaviorEngine:
    """Get Behavior Engine instance for a session."""
    return _behavior_manager.get(session_id)


def behavior_update(
    session_id: str, 
    user_message: str, 
    wm_context: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    Update Behavior Layer with user message.
    
    Call AFTER wm_update() in the kernel flow.
    """
    engine = _behavior_manager.get(session_id)
    return engine.update(user_message, wm_context)


def behavior_after_response(session_id: str, nova_response: str) -> Dict[str, Any]:
    """
    Process Nova's response in Behavior Layer.
    
    Call AFTER generating the response.
    """
    engine = _behavior_manager.get(session_id)
    return engine.after_response(nova_response)


def behavior_get_context(session_id: str) -> Dict[str, Any]:
    """Get behavior context bundle."""
    engine = _behavior_manager.get(session_id)
    return engine.get_context()


def behavior_get_context_string(session_id: str) -> str:
    """Get formatted behavior context string for persona system prompt."""
    engine = _behavior_manager.get(session_id)
    return engine.build_context_string()


def behavior_answer_reference(session_id: str, question: str) -> Optional[str]:
    """Try to answer reference questions from Behavior Layer."""
    engine = _behavior_manager.get(session_id)
    return engine.answer_reference_question(question)


def behavior_resolve_goal(session_id: str, goal_id: str = None, resolution: str = None) -> bool:
    """Mark a goal as resolved."""
    engine = _behavior_manager.get(session_id)
    return engine.resolve_goal(goal_id, resolution)


def behavior_clear(session_id: str) -> None:
    """Clear Behavior Engine for a session."""
    _behavior_manager.clear(session_id)


def behavior_delete(session_id: str) -> None:
    """Delete Behavior Engine for a session."""
    _behavior_manager.delete(session_id)
