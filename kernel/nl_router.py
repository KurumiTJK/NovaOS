# kernel/nl_router.py
"""
v0.6 — Natural Language Router (Wizard-Aware)

Routes natural language input to syscommands via intent detection.
Integrates with the wizard system for guided command execution.

Design:
- Pattern-based intent detection (no LLM calls)
- Maps intents to CommandRequest objects
- Supports use_wizard=True for wizard-enabled commands
- Strips preambles ("ok nova", "hey nova", etc.)
- Returns None if ambiguous (falls back to persona)

ROUTING INVARIANTS:
- At top level, a command is only a command if it starts with #
- This router only handles natural language (non-# input)
- Section menus & wizards are handled elsewhere
"""

from typing import Dict, Any, Optional, List, Tuple
import re
from dataclasses import dataclass, field

from .command_types import CommandRequest


@dataclass
class IntentMatch:
    """Result of intent detection."""
    command: str
    confidence: float  # 0.0 - 1.0
    args: Dict[str, Any]
    matched_pattern: str
    use_wizard: bool = False


# -----------------------------------------------------------------------------
# Preamble Stripping
# -----------------------------------------------------------------------------

# Common preambles users might say before their intent
PREAMBLE_PATTERNS = [
    r"^(okay|ok|alright|yo|hey|hi|um+|uh+|so+|well|like|basically|actually)\s*,?\s*",
    r"^(nova|novaos)\s*,?\s*",
    r"^(can you|could you|would you|will you|please)\s+",
    r"^(i want to|i('d| would) like to|let('s| us)|i need to)\s+",
    r"^(lowkey|tbh|ngl|honestly|mmm+)\s*,?\s*",
]

_compiled_preambles = [re.compile(p, re.IGNORECASE) for p in PREAMBLE_PATTERNS]


def strip_preambles(text: str) -> str:
    """
    Strip common preambles from user input.
    
    Examples:
        "okay nova remind me to..." -> "remind me to..."
        "hey can you store this" -> "store this"
        "lowkey I need to log how I'm feeling" -> "log how I'm feeling"
    """
    result = text.strip()
    changed = True
    max_iterations = 5  # Prevent infinite loops
    iterations = 0
    
    while changed and iterations < max_iterations:
        changed = False
        iterations += 1
        for pattern in _compiled_preambles:
            new_result = pattern.sub("", result).strip()
            if new_result != result:
                result = new_result
                changed = True
    
    return result


# -----------------------------------------------------------------------------
# Wizard-Aware Intent Patterns
# -----------------------------------------------------------------------------

@dataclass
class NLPattern:
    """
    A natural language pattern definition.
    
    Attributes:
        name: Human-readable pattern name
        cmd_name: Target syscommand
        use_wizard: Whether to trigger wizard mode
        confidence: Base confidence score (0.0-1.0)
        patterns: List of regex patterns
        extractor: Optional arg extractor function name or callable
    """
    name: str
    cmd_name: str
    use_wizard: bool
    confidence: float
    patterns: List[str]
    extractor: Optional[str] = None


# =============================================================================
# GROUP A: Strong Wizard Candidates (15 commands)
# These trigger wizards for guided input
# =============================================================================

WIZARD_PATTERNS: List[NLPattern] = [
    # -------------------------------------------------------------------------
    # REMINDERS
    # -------------------------------------------------------------------------
    NLPattern(
        name="reminder_add",
        cmd_name="remind-add",
        use_wizard=True,
        confidence=0.88,
        patterns=[
            r"\bremind me\b",
            r"\bset a reminder\b",
            r"\bcreate a reminder\b",
            r"\breminder for\b",
            r"\bdon't let me forget\b",
        ],
    ),
    NLPattern(
        name="reminder_update",
        cmd_name="remind-update",
        use_wizard=True,
        confidence=0.85,
        patterns=[
            r"\b(edit|update|change|modify) (the |that |my )?reminder\b",
            r"\breminder.*(edit|update|change)\b",
        ],
    ),
    NLPattern(
        name="reminder_delete",
        cmd_name="remind-delete",
        use_wizard=True,
        confidence=0.85,
        patterns=[
            r"\b(delete|remove|cancel) (the |that |my )?reminder\b",
            r"\breminder.*(delete|remove|cancel)\b",
        ],
    ),
    
    # -------------------------------------------------------------------------
    # MEMORY
    # -------------------------------------------------------------------------
    NLPattern(
        name="memory_store",
        cmd_name="store",
        use_wizard=True,
        confidence=0.85,
        patterns=[
            r"\bremember (this|that)\b",
            r"\bremember:?\s+.{10,}",  # "remember X" with substantial content
            r"\bstore (this|that)( as)?\b",
            r"\bsave (this|that)( as| for)?\b",
            r"\bkeep (this|that) in memory\b",
            r"\bmake a (note|memory)\b",
            r"\bnote (this|that) down\b",
        ],
    ),
    NLPattern(
        name="memory_forget",
        cmd_name="forget",
        use_wizard=True,
        confidence=0.85,
        patterns=[
            r"\bforget (this|that|the) memory\b",
            r"\bdelete (this|that|the) memory\b",
            r"\bremove (this|that|the) memory\b",
            r"\bforget memory\s*#?\d*\b",
            r"\bdelete memory\s*#?\d*\b",
        ],
    ),
    NLPattern(
        name="memory_bind",
        cmd_name="bind",
        use_wizard=True,
        confidence=0.82,
        patterns=[
            r"\bbind (these |the |those )?memories\b",
            r"\blink (these |the |those )?memories\b",
            r"\bcluster (these |the |those )?memories\b",
            r"\bgroup (these |the |those )?memories\b",
        ],
    ),
    
    # -------------------------------------------------------------------------
    # HUMAN STATE
    # -------------------------------------------------------------------------
    NLPattern(
        name="log_state",
        cmd_name="log-state",
        use_wizard=True,
        confidence=0.85,
        patterns=[
            r"\blog (how i('m| am)|my)\s*(feeling|doing|state|energy|stress)\b",
            r"\bcheck(-|\s)?in\b",
            r"\brecord (my |how i('m| am) )?(state|feeling|energy)\b",
            r"\bupdate my (state|energy|stress)\b",
            r"\bhow('m| am) i (doing|feeling)\??\s*log\b",
            r"\blog (my )?(current )?(state|mood|energy)\b",
        ],
    ),
    
    # -------------------------------------------------------------------------
    # IDENTITY
    # -------------------------------------------------------------------------
    NLPattern(
        name="identity_set",
        cmd_name="identity-set",
        use_wizard=True,
        confidence=0.85,
        patterns=[
            r"\b(set|update|change) my (goals?|values?|roles?|name|strengths?)\b",
            r"\bmy (goals?|values?|roles?) (are|is|should be)\b",
            r"\badd.*(goal|value|role)\b",
            r"\bupdate (my )?identity\b",
        ],
    ),
    
    # -------------------------------------------------------------------------
    # WORKFLOWS
    # -------------------------------------------------------------------------
    NLPattern(
        name="workflow_start",
        cmd_name="flow",
        use_wizard=True,
        confidence=0.85,
        patterns=[
            r"\b(start|begin|run|launch) (the |a |that |my )?workflow\b",
            r"\bworkflow.*(start|begin|run|launch)\b",
            r"\bkick off (the |a )?workflow\b",
        ],
    ),
    NLPattern(
        name="workflow_compose",
        cmd_name="compose",
        use_wizard=True,
        confidence=0.85,
        patterns=[
            r"\b(create|make|build|design) (a |new )?workflow\b",
            r"\bworkflow for\b",
            r"\bset up a workflow\b",
            r"\bcompose (a )?workflow\b",
        ],
    ),
    NLPattern(
        name="workflow_delete",
        cmd_name="workflow-delete",
        use_wizard=True,
        confidence=0.85,
        patterns=[
            r"\b(delete|remove) (the |that |my )?workflow\b",
            r"\bworkflow.*(delete|remove)\b",
        ],
    ),
    
    # -------------------------------------------------------------------------
    # MODULES
    # -------------------------------------------------------------------------
    NLPattern(
        name="module_forge",
        cmd_name="forge",
        use_wizard=True,
        confidence=0.85,
        patterns=[
            r"\b(create|make|build|forge) (a |new )?module\b",
            r"\bmodule for\b",
            r"\bset up (a )?module\b",
            r"\bnew module (for|called|named)\b",
        ],
    ),
    
    # -------------------------------------------------------------------------
    # SNAPSHOTS
    # -------------------------------------------------------------------------
    NLPattern(
        name="snapshot_create",
        cmd_name="snapshot",
        use_wizard=True,
        confidence=0.88,
        patterns=[
            r"\b(take|create|make|save) (a )?snapshot\b",
            r"\bsnapshot (nova|novaos|the system|state)\b",
            r"\bsave (nova('s)?|the system('s)?|current) state\b",
            r"\bbackup (nova|novaos|state)\b",
        ],
    ),
    NLPattern(
        name="snapshot_restore",
        cmd_name="restore",
        use_wizard=True,
        confidence=0.85,
        patterns=[
            r"\brestore (from )?(a )?snapshot\b",
            r"\broll\s*back\b",
            r"\brevert (to |from )?(a )?snapshot\b",
            r"\bload (a )?snapshot\b",
        ],
    ),
    
    # -------------------------------------------------------------------------
    # CUSTOM COMMANDS
    # -------------------------------------------------------------------------
    NLPattern(
        name="command_add",
        cmd_name="command-add",
        use_wizard=True,
        confidence=0.85,
        patterns=[
            r"\b(create|make|add) (a )?(new )?(custom )?command\b",
            r"\bnew command (for|that|called|named)\b",
            r"\bset up (a )?command\b",
        ],
    ),
]


# =============================================================================
# GROUP B: Optional Wizard Commands (add if user says "wizard" or no args)
# These have lower confidence and are less common
# =============================================================================

OPTIONAL_WIZARD_PATTERNS: List[NLPattern] = [
    NLPattern(
        name="mode_set",
        cmd_name="mode",
        use_wizard=True,
        confidence=0.82,
        patterns=[
            r"\b(switch|change|set) (to )?(deep[_\s]?work|reflection|debug|normal) mode\b",
            r"\b(enter|go into) (deep[_\s]?work|reflection|debug|normal) mode\b",
            r"\bchange mode\b",
        ],
    ),
    NLPattern(
        name="dismantle_module",
        cmd_name="dismantle",
        use_wizard=True,
        confidence=0.82,
        patterns=[
            r"\b(delete|remove|dismantle) (the |that |my )?module\b",
            r"\bmodule.*(delete|remove|dismantle)\b",
        ],
    ),
    NLPattern(
        name="identity_restore",
        cmd_name="identity-restore",
        use_wizard=True,
        confidence=0.82,
        patterns=[
            r"\brestore (my )?identity\b",
            r"\brevert (my )?identity\b",
            r"\bidentity.*(restore|revert)\b",
        ],
    ),
    NLPattern(
        name="workflow_advance",
        cmd_name="advance",
        use_wizard=True,
        confidence=0.80,
        patterns=[
            r"\bnext step\b",
            r"\badvance (the )?workflow\b",
            r"\bcontinue (the )?workflow\b",
            r"\bmove (to )?(the )?next step\b",
        ],
    ),
    NLPattern(
        name="workflow_halt",
        cmd_name="halt",
        use_wizard=True,
        confidence=0.80,
        patterns=[
            r"\b(stop|pause|halt) (the )?workflow\b",
            r"\bworkflow.*(stop|pause|halt)\b",
        ],
    ),
    NLPattern(
        name="memory_trace",
        cmd_name="trace",
        use_wizard=True,
        confidence=0.80,
        patterns=[
            r"\btrace (the |that |this )?memory\b",
            r"\bmemory (trace|history|lineage)\b",
        ],
    ),
    NLPattern(
        name="module_inspect",
        cmd_name="inspect",
        use_wizard=True,
        confidence=0.80,
        patterns=[
            r"\binspect (the |that |this )?module\b",
            r"\bmodule (details|info|inspect)\b",
        ],
    ),
    NLPattern(
        name="memory_recall",
        cmd_name="recall",
        use_wizard=True,
        confidence=0.78,
        patterns=[
            r"\bwhat do (i|you) (know|remember) about\b",
            r"\brecall (my )?memories\b",
            r"\bshow (my )?memories\b",
            r"\blist (my )?memories\b",
            r"\bsearch (my )?memories\b",
        ],
    ),
]


# =============================================================================
# NON-WIZARD PATTERNS (instant commands, no wizard needed)
# =============================================================================

INSTANT_PATTERNS: List[NLPattern] = [
    # STATUS / SYSTEM
    NLPattern(
        name="system_status",
        cmd_name="status",
        use_wizard=False,
        confidence=0.85,
        patterns=[
            r"\bhow('s| is| are) (nova|novaos|the system|everything)\b",
            r"\bsystem (status|check)\b",
            r"\bwhat('s| is) (my |the )?(current )?status\b",
        ],
    ),
    
    # HELP
    NLPattern(
        name="help",
        cmd_name="help",
        use_wizard=False,
        confidence=0.85,
        patterns=[
            r"\bwhat can you do\b",
            r"\bshow( me)? (the )?commands\b",
            r"\bavailable commands\b",
            r"\blist (the )?commands\b",
        ],
    ),
    
    # IDENTITY (getters)
    NLPattern(
        name="identity_why",
        cmd_name="why",
        use_wizard=False,
        confidence=0.88,
        patterns=[
            r"\bwho are you\b",
            r"\bwhat is nova(os)?\b",
            r"\byour (purpose|identity|mission)\b",
            r"\bwhy (do you |are you |nova)\b",
        ],
    ),
    NLPattern(
        name="identity_show",
        cmd_name="identity-show",
        use_wizard=False,
        confidence=0.85,
        patterns=[
            r"\b(show|display|view)( my)? identity\b",
            r"\bmy identity( profile)?\b",
        ],
    ),
    
    # MEMORY (getters)
    NLPattern(
        name="memory_stats",
        cmd_name="memory-stats",
        use_wizard=False,
        confidence=0.90,
        patterns=[
            r"\bmemory stats\b",
            r"\bmemory statistics\b",
            r"\bhow (much|many) memories\b",
        ],
    ),
    
    # WORKFLOWS (getters)
    NLPattern(
        name="workflow_list",
        cmd_name="workflow-list",
        use_wizard=False,
        confidence=0.88,
        patterns=[
            r"\b(show|list)( my| the| all)? workflows\b",
            r"\bwhat workflows\b",
        ],
    ),
    
    # REMINDERS (getters)
    NLPattern(
        name="reminder_list",
        cmd_name="remind-list",
        use_wizard=False,
        confidence=0.88,
        patterns=[
            r"\b(show|list)( my| the| all)? reminders\b",
            r"\bwhat reminders\b",
        ],
    ),
    
    # MODULES (getters)
    NLPattern(
        name="module_list",
        cmd_name="map",
        use_wizard=False,
        confidence=0.88,
        patterns=[
            r"\b(show|list)( my| the| all)? modules\b",
            r"\bwhat modules\b",
        ],
    ),
    
    # TIME RHYTHM
    NLPattern(
        name="time_presence",
        cmd_name="presence",
        use_wizard=False,
        confidence=0.82,
        patterns=[
            r"\b(where am i|what time|time presence|temporal)\b.*\b(in time|context|phase)\b",
            r"\btime (rhythm |presence |context )\b",
        ],
    ),
    NLPattern(
        name="time_align",
        cmd_name="align",
        use_wizard=False,
        confidence=0.78,
        patterns=[
            r"\bwhat should i (do|focus on|work on)\b",
            r"\b(suggest|recommend|prioritize)( what| next)?\b",
            r"\balign me\b",
        ],
    ),
    
    # HUMAN STATE (getters)
    NLPattern(
        name="state_evolution",
        cmd_name="evolution-status",
        use_wizard=False,
        confidence=0.82,
        patterns=[
            r"\b(evolution|my) status\b",
            r"\bhow am i doing\b",
            r"\bmy (current )?state\b",
        ],
    ),
    NLPattern(
        name="state_capacity",
        cmd_name="capacity",
        use_wizard=False,
        confidence=0.80,
        patterns=[
            r"\b(my|check|show|what('s| is)) (my )?capacity\b",
            r"\bhow much capacity\b",
            r"\bam i (over)?loaded\b",
        ],
    ),
    
    # CONTINUITY
    NLPattern(
        name="continuity_preferences",
        cmd_name="preferences",
        use_wizard=False,
        confidence=0.88,
        patterns=[
            r"\b(show|my|what are my) preferences\b",
        ],
    ),
    NLPattern(
        name="continuity_projects",
        cmd_name="projects",
        use_wizard=False,
        confidence=0.88,
        patterns=[
            r"\b(show|my|what are my|active) projects\b",
        ],
    ),
]


# =============================================================================
# Combine all patterns
# =============================================================================

ALL_PATTERNS: List[NLPattern] = WIZARD_PATTERNS + OPTIONAL_WIZARD_PATTERNS + INSTANT_PATTERNS


# -----------------------------------------------------------------------------
# Natural Language Router
# -----------------------------------------------------------------------------

class NaturalLanguageRouter:
    """
    v0.6 Natural Language Router (Wizard-Aware)
    
    Routes natural language input to syscommands via pattern matching.
    Supports wizard triggering for commands that benefit from guided input.
    """
    
    # Minimum confidence to accept a match
    MIN_CONFIDENCE = 0.75
    
    def __init__(self):
        self._compiled_patterns: List[Tuple[NLPattern, List[re.Pattern]]] = []
        
        # Compile all patterns
        for nl_pattern in ALL_PATTERNS:
            compiled_regexes = []
            for regex_str in nl_pattern.patterns:
                try:
                    compiled_regexes.append(re.compile(regex_str, re.IGNORECASE))
                except re.error:
                    pass  # Skip invalid patterns
            if compiled_regexes:
                self._compiled_patterns.append((nl_pattern, compiled_regexes))
    
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
        
        # Strip preambles for better matching
        cleaned_text = strip_preambles(text)
        
        # Find best match
        best_match: Optional[IntentMatch] = None
        
        for nl_pattern, compiled_regexes in self._compiled_patterns:
            for compiled in compiled_regexes:
                match = compiled.search(cleaned_text)
                if match:
                    # Calculate confidence with length factor
                    match_len = len(match.group(0))
                    text_len = len(cleaned_text)
                    length_factor = min(1.0, match_len / max(text_len * 0.4, 1))
                    adjusted_confidence = nl_pattern.confidence * (0.85 + 0.15 * length_factor)
                    
                    if best_match is None or adjusted_confidence > best_match.confidence:
                        best_match = IntentMatch(
                            command=nl_pattern.cmd_name,
                            confidence=adjusted_confidence,
                            args={},  # Wizard will collect args
                            matched_pattern=match.group(0),
                            use_wizard=nl_pattern.use_wizard,
                        )
                    break  # Only need first match per pattern group
        
        if best_match and best_match.confidence >= self.MIN_CONFIDENCE:
            return CommandRequest(
                cmd_name=best_match.command,
                args=best_match.args,
                session_id="",  # Will be set by caller
                raw_text=text,
                meta={
                    "source": "nl_router",
                    "confidence": best_match.confidence,
                    "matched_pattern": best_match.matched_pattern,
                    "use_wizard": best_match.use_wizard,
                    "cleaned_text": cleaned_text,
                },
            )
        
        return None
    
    def get_intent_debug(self, text: str) -> Dict[str, Any]:
        """
        Debug helper: show all matching intents with confidence scores.
        """
        cleaned_text = strip_preambles(text)
        matches = []
        
        for nl_pattern, compiled_regexes in self._compiled_patterns:
            for compiled in compiled_regexes:
                match = compiled.search(cleaned_text)
                if match:
                    match_len = len(match.group(0))
                    text_len = len(cleaned_text)
                    length_factor = min(1.0, match_len / max(text_len * 0.4, 1))
                    adjusted_confidence = nl_pattern.confidence * (0.85 + 0.15 * length_factor)
                    
                    matches.append({
                        "name": nl_pattern.name,
                        "command": nl_pattern.cmd_name,
                        "confidence": round(adjusted_confidence, 3),
                        "use_wizard": nl_pattern.use_wizard,
                        "pattern": compiled.pattern,
                        "matched": match.group(0),
                    })
                    break
        
        # Sort by confidence
        matches.sort(key=lambda m: -m["confidence"])
        
        return {
            "input": text,
            "cleaned": cleaned_text,
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
    The returned CommandRequest.meta will include:
    - use_wizard: bool - whether to trigger wizard mode
    - confidence: float - match confidence
    - matched_pattern: str - the regex that matched
    """
    return _nl_router.route(text)


def debug_nl_intent(text: str) -> Dict[str, Any]:
    """Debug helper for NL intent detection."""
    return _nl_router.get_intent_debug(text)
