# kernel/nl_router.py
"""
v0.8.0 — Natural Language Router (Quest Engine Update)

Routes natural language input to syscommands via intent detection.

IMPORTANT: Quest commands are NEVER auto-executed.
The router will SUGGEST quest commands but not route to them directly.
Users must explicitly use #quest, #next, #pause, etc.

Design:
- Pattern-based intent detection (no LLM calls)
- Maps intents to CommandRequest objects
- Returns None if ambiguous (falls back to persona)
- Quest-related phrases return suggestions, not auto-execution
"""

from typing import Dict, Any, Optional, List, Tuple
import re
from dataclasses import dataclass

from .command_types import CommandRequest


@dataclass
class IntentMatch:
    """Result of intent detection."""
    command: str
    confidence: float  # 0.0 - 1.0
    args: Dict[str, Any]
    matched_pattern: str


# -----------------------------------------------------------------------------
# Intent Patterns
# -----------------------------------------------------------------------------

class IntentPatterns:
    """
    Natural language intent patterns.
    
    Each pattern is a tuple of:
    - regex pattern
    - command name
    - arg extractor function (or None)
    - confidence score
    """
    
    # ===== STATUS / SYSTEM =====
    STATUS_PATTERNS = [
        (r"\bhow('s| is| are) (nova|novaos|the system|everything)\b", "status", None, 0.9),
        (r"\bsystem (status|check)\b", "status", None, 0.9),
        (r"\b(what('s| is) (my|the) status)\b", "status", None, 0.85),
    ]
    
    # ===== HELP =====
    HELP_PATTERNS = [
        (r"\bwhat can you do\b", "help", None, 0.9),
        (r"\bshow( me)? commands\b", "help", None, 0.9),
        (r"\bavailable commands\b", "help", None, 0.9),
        (r"\b(how do i|how to)\b.*\?", "help", None, 0.6),
    ]
    
    # ===== IDENTITY =====
    IDENTITY_PATTERNS = [
        (r"\b(who are you|what is nova(os)?|your (purpose|identity))\b", "why", None, 0.9),
        (r"\b(show|display|view)( my)? identity\b", "identity-show", None, 0.9),
        (r"\b(my identity|identity profile)\b", "identity-show", None, 0.8),
    ]
    
    # ===== MODE =====
    MODE_PATTERNS = [
        (r"\b(switch to|enter|go into|set mode( to)?)\s*(deep[_\s]?work|reflection|debug|normal)\b", "mode", "_extract_mode", 0.95),
        (r"\b(deep[_\s]?work|focus) mode\b", "mode", lambda m: {"mode": "deep_work"}, 0.85),
        (r"\btime to (reflect|think)\b", "mode", lambda m: {"mode": "reflection"}, 0.8),
    ]
    
    # ===== MEMORY =====
    MEMORY_PATTERNS = [
        (r"\b(remember|store|save)( that)?\s+(.+)\b", "store", "_extract_remember", 0.85),
        (r"\b(recall|show|what do (i|you) (know|remember) about)\s+(.+)\b", "recall", "_extract_recall", 0.85),
        (r"\b(forget|delete) memory\s*#?(\d+)\b", "forget", "_extract_forget_id", 0.9),
        (r"\bmemory stats\b", "memory-stats", None, 0.95),
        (r"\b(show|list) (my )?memories\b", "recall", None, 0.8),
    ]
    
    # ===== WORKFLOW / QUEST =====
    # v0.8.0: REMOVED - Quest commands are NEVER auto-executed
    # The router does not route to quest commands.
    # Quest-related phrases are handled by check_quest_suggestion() instead.
    # Users must explicitly use: #quest, #next, #pause, #quest-log, etc.
    WORKFLOW_PATTERNS = [
        # INTENTIONALLY EMPTY - No auto-routing for quest commands
    ]
    
    # ===== REMINDERS =====
    REMINDER_PATTERNS = [
        (r"\bremind me (to\s+)?(.+?)(\s+(at|in|on)\s+.+)?\s*$", "remind-add", "_extract_reminder", 0.9),
        (r"\b(show|list)( my)? reminders\b", "remind-list", None, 0.9),
        (r"\bdelete reminder\s*#?(\d+)\b", "remind-delete", "_extract_remind_id", 0.9),
    ]
    
    # ===== TIME RHYTHM =====
    TIME_PATTERNS = [
        (r"\b(where am i|what time|time presence|temporal)\b.*\b(in time|context|phase)\b", "presence", None, 0.85),
        (r"\b(check|show)( the)? pulse\b", "pulse", None, 0.85),
        (r"\bwhat should i (do|focus on)\b", "align", None, 0.8),
        (r"\b(suggest|recommend|prioritize)( next)?\b", "align", None, 0.75),
    ]
    
    # ===== MODULES =====
    MODULE_PATTERNS = [
        (r"\b(show|list)( my)? modules\b", "map", None, 0.9),
        (r"\bcreate( a)? module\b", "forge", None, 0.8),
        (r"\binspect module\s+(\w+)\b", "inspect", "_extract_module_key", 0.9),
    ]
    
    # ===== INTERPRETATION =====
    INTERPRETATION_PATTERNS = [
        (r"\b(analyze|interpret)\s+(.+)\b", "interpret", "_extract_payload", 0.8),
        (r"\bfirst principles\b.*\b(.+)\b", "derive", "_extract_payload", 0.85),
        (r"\breframe\s+(.+)\b", "frame", "_extract_payload", 0.85),
        (r"\bpredict\s+(.+)\b", "forecast", "_extract_payload", 0.8),
        (r"\bforecast\s+(.+)\b", "forecast", "_extract_payload", 0.85),
    ]
    
    # ===== HUMAN STATE =====
    STATE_PATTERNS = [
        (r"\b(evolution|my) status\b", "evolution-status", None, 0.85),
        (r"\bhow am i doing\b", "evolution-status", None, 0.8),
        (r"\bcheck(-in| in|in)\b", "log-state", None, 0.75),
        (r"\b(log|update) (my )?(state|energy|stress)\b", "log-state", None, 0.8),
        (r"\b(my|check|show) capacity\b", "capacity", None, 0.8),
    ]
    
    # ===== CONTINUITY =====
    CONTINUITY_PATTERNS = [
        (r"\b(show|my) preferences\b", "preferences", None, 0.9),
        (r"\b(show|my|active) projects\b", "projects", None, 0.9),
    ]
    
    # ===== SNAPSHOT =====
    SNAPSHOT_PATTERNS = [
        (r"\b(create|make|take)( a)? snapshot\b", "snapshot", None, 0.9),
        (r"\b(save|backup) (state|system)\b", "snapshot", None, 0.85),
    ]
    
    @classmethod
    def get_all_patterns(cls) -> List[Tuple]:
        """Get all pattern lists combined."""
        all_patterns = []
        for attr in dir(cls):
            if attr.endswith("_PATTERNS"):
                all_patterns.extend(getattr(cls, attr))
        return all_patterns


# -----------------------------------------------------------------------------
# Argument Extractors
# -----------------------------------------------------------------------------

def _extract_mode(match: re.Match) -> Dict[str, Any]:
    """Extract mode from regex match."""
    text = match.group(0).lower()
    if "deep" in text or "work" in text:
        return {"mode": "deep_work"}
    elif "reflection" in text or "reflect" in text:
        return {"mode": "reflection"}
    elif "debug" in text:
        return {"mode": "debug"}
    return {"mode": "normal"}


def _extract_remember(match: re.Match) -> Dict[str, Any]:
    """Extract payload from 'remember ...' pattern."""
    payload = match.group(2) if match.lastindex >= 2 else match.group(0)
    return {"payload": payload.strip(), "type": "semantic"}


def _extract_recall(match: re.Match) -> Dict[str, Any]:
    """Extract query from recall pattern."""
    query = match.group(4) if match.lastindex >= 4 else ""
    args = {}
    if query:
        for mem_type in ["semantic", "procedural", "episodic"]:
            if mem_type in query.lower():
                args["type"] = mem_type
                query = query.lower().replace(mem_type, "").strip()
        if query:
            args["tags"] = query
    return args


def _extract_forget_id(match: re.Match) -> Dict[str, Any]:
    """Extract memory ID from forget pattern."""
    return {"ids": match.group(2)}


def _extract_reminder(match: re.Match) -> Dict[str, Any]:
    """Extract reminder details."""
    msg = match.group(2) if match.lastindex >= 2 else ""
    time_part = match.group(3) if match.lastindex >= 3 else ""
    args = {"msg": msg.strip()}
    if time_part:
        time_match = re.search(r"(at|in|on)\s+(.+)", time_part, re.IGNORECASE)
        if time_match:
            args["at"] = time_match.group(2).strip()
    return args


def _extract_remind_id(match: re.Match) -> Dict[str, Any]:
    """Extract reminder ID."""
    return {"id": match.group(1)}


def _extract_module_key(match: re.Match) -> Dict[str, Any]:
    """Extract module key."""
    return {"key": match.group(1)}


def _extract_payload(match: re.Match) -> Dict[str, Any]:
    """Extract payload/query text."""
    payload = match.group(match.lastindex) if match.lastindex else match.group(0)
    return {"_": [payload.strip()]}


# Map extractor names to functions
EXTRACTORS = {
    "_extract_mode": _extract_mode,
    "_extract_remember": _extract_remember,
    "_extract_recall": _extract_recall,
    "_extract_forget_id": _extract_forget_id,
    "_extract_reminder": _extract_reminder,
    "_extract_remind_id": _extract_remind_id,
    "_extract_module_key": _extract_module_key,
    "_extract_payload": _extract_payload,
}


# -----------------------------------------------------------------------------
# Quest Suggestion Patterns (v0.8.0)
# -----------------------------------------------------------------------------
# These patterns detect quest-related intent but DO NOT auto-execute.
# Instead, they return a suggestion for the user to run the command explicitly.

QUEST_SUGGESTION_PATTERNS = [
    (r"\b(start|begin|run|resume)( the| my| a)? (quest|workflow|learning)\b", "quest", "To start or resume a quest, run: `#quest`"),
    (r"\b(show|list|view)( my)? quests?\b", "quest", "To see available quests, run: `#quest`"),
    (r"\bnext step\b", "next", "To advance to the next step, run: `#next`"),
    (r"\b(advance|continue)( the| my)? (quest|learning)\b", "next", "To advance your quest, run: `#next`"),
    (r"\b(stop|pause|halt)( the| my)? (quest|workflow|learning)\b", "pause", "To pause your quest, run: `#pause`"),
    (r"\b(my|show|check) (progress|xp|skills?|streak)\b", "quest-log", "To see your progress, run: `#quest-log`"),
    (r"\b(create|make|compose)( a)? (quest|workflow)\b", "quest-compose", "To create a new quest, run: `#quest-compose`"),
    (r"\bquest (status|log|progress)\b", "quest-log", "To see your quest log, run: `#quest-log`"),
    (r"\breset( my)? (quest|progress)\b", "quest-reset", "To reset quest progress, run: `#quest-reset`"),
    # Legacy workflow phrases - redirect to quest commands
    (r"\b(start|begin|run)( the)? workflow\b", "quest", "Workflows are now Quests! Run: `#quest`"),
    (r"\b(show|list)( my)? workflows\b", "quest-list", "Workflows are now Quests! Run: `#quest-list`"),
    (r"\b(advance|continue)( the)? workflow\b", "next", "Workflows are now Quests! Run: `#next`"),
    (r"\b(stop|pause|halt)( the)? workflow\b", "pause", "Workflows are now Quests! Run: `#pause`"),
]


def check_quest_suggestion(text: str) -> Optional[str]:
    """
    Check if text matches a quest-related pattern.
    
    Returns a suggestion string if matched, None otherwise.
    
    IMPORTANT: This does NOT execute any command. It only suggests
    the explicit command the user should run.
    """
    text_lower = text.lower()
    
    for pattern, command, suggestion in QUEST_SUGGESTION_PATTERNS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return suggestion
    
    return None


# -----------------------------------------------------------------------------
# Natural Language Router
# -----------------------------------------------------------------------------

class NaturalLanguageRouter:
    """
    v0.8.0 Natural Language Router
    
    Routes natural language input to syscommands via pattern matching.
    Quest commands are NEVER auto-routed - only suggested.
    """
    
    MIN_CONFIDENCE = 0.7
    
    def __init__(self):
        self.patterns = IntentPatterns.get_all_patterns()
        self._compiled = []
        for pattern, command, extractor, confidence in self.patterns:
            try:
                compiled = re.compile(pattern, re.IGNORECASE)
                self._compiled.append((compiled, command, extractor, confidence))
            except re.error:
                pass
    
    def route(self, text: str) -> Optional[CommandRequest]:
        """
        Route natural language text to a CommandRequest.
        
        Returns None if no confident match found.
        """
        text = text.strip()
        if not text:
            return None
        
        # Skip if looks like a command
        if text.startswith("#") or text.startswith("/"):
            return None
        
        # Find best match
        best_match: Optional[IntentMatch] = None
        
        for compiled, command, extractor, confidence in self._compiled:
            match = compiled.search(text)
            if match:
                match_len = len(match.group(0))
                text_len = len(text)
                length_factor = min(1.0, match_len / max(text_len * 0.5, 1))
                adjusted_confidence = confidence * (0.8 + 0.2 * length_factor)
                
                if best_match is None or adjusted_confidence > best_match.confidence:
                    args = {}
                    if extractor:
                        if callable(extractor):
                            args = extractor(match)
                        elif isinstance(extractor, str) and extractor in EXTRACTORS:
                            args = EXTRACTORS[extractor](match)
                    
                    best_match = IntentMatch(
                        command=command,
                        confidence=adjusted_confidence,
                        args=args,
                        matched_pattern=match.group(0),
                    )
        
        if best_match and best_match.confidence >= self.MIN_CONFIDENCE:
            return CommandRequest(
                cmd_name=best_match.command,
                args=best_match.args,
                session_id="",
                raw_text=text,
                meta={
                    "source": "nl_router",
                    "confidence": best_match.confidence,
                    "matched_pattern": best_match.matched_pattern,
                },
            )
        
        return None
    
    def get_intent_debug(self, text: str) -> Dict[str, Any]:
        """Debug helper: show all matching intents with confidence scores."""
        matches = []
        
        for compiled, command, extractor, confidence in self._compiled:
            match = compiled.search(text)
            if match:
                match_len = len(match.group(0))
                text_len = len(text)
                length_factor = min(1.0, match_len / max(text_len * 0.5, 1))
                adjusted_confidence = confidence * (0.8 + 0.2 * length_factor)
                
                matches.append({
                    "command": command,
                    "confidence": adjusted_confidence,
                    "pattern": compiled.pattern,
                    "matched": match.group(0),
                })
        
        matches.sort(key=lambda m: -m["confidence"])
        
        return {
            "input": text,
            "matches": matches[:10],
            "best_match": matches[0] if matches else None,
            "would_route": matches[0]["confidence"] >= self.MIN_CONFIDENCE if matches else False,
        }


# Global router instance
_nl_router = NaturalLanguageRouter()


def route_natural_language(text: str) -> Optional[CommandRequest]:
    """
    Main entry point for NL routing.
    
    Returns CommandRequest if confident match found, None otherwise.
    """
    return _nl_router.route(text)


def debug_nl_intent(text: str) -> Dict[str, Any]:
    """Debug helper for NL intent detection."""
    return _nl_router.get_intent_debug(text)
