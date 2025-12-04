# kernel/nl_router.py
"""
v0.6.1 — Natural Language Router (Wizard-Aware, Expanded Coverage)

Routes natural language input to syscommands via intent detection.
Integrates with the wizard system for guided command execution.

v0.6.1 UPGRADES:
- Expanded pattern coverage (~100 patterns)
- Continuity commands (preferences, projects, etc.)
- Identity history commands
- System info commands (env, model-info, help)
- Time-rhythm commands (presence, pulse, align)
- Interpretation commands (interpret, derive, forecast, etc.)
- Natural psychology patterns (emotional intents)
- Enhanced preamble stripping
- Conflict detection for mixed/ambiguous intents

Design:
- Pattern-based intent detection (no LLM calls)
- Maps intents to CommandRequest objects
- Supports use_wizard=True for wizard-enabled commands
- Strips preambles ("ok nova", "hey nova", etc.)
- Returns None if ambiguous (falls back to persona)

SAFETY RULES:
- Destructive commands MUST use wizard: dismantle, restore, workflow-delete,
  remind-delete, command-remove, forget, identity-clear-history
- Mixed intent → no match
- Ambiguous → persona fallback
- MIN_CONFIDENCE = 0.75

ROUTING INVARIANTS:
- At top level, a command is only a command if it starts with #
- This router only handles natural language (non-# input)
- Section menus & wizards are handled elsewhere
"""

from typing import Dict, Any, Optional, List, Tuple, Set
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
# Preamble Stripping (v0.6.1 expanded)
# -----------------------------------------------------------------------------

PREAMBLE_PATTERNS = [
    # Basic greetings / fillers
    r"^(okay|ok|alright|yo|hey|hi|hello|um+|uh+|so+|well|like|basically|actually)\s*,?\s*",
    # Nova address
    r"^(nova|novaos)\s*,?\s*",
    # Polite requests
    r"^(can you|could you|would you|will you|please|pls)\s+",
    # Intent preambles
    r"^(i want to|i('d| would) like to|let('s| us)|i need to|i wanna|i gotta)\s+",
    # Slang / casual
    r"^(lowkey|tbh|ngl|honestly|mmm+|hmm+|bruh|dude|bro)\s*,?\s*",
    # Thinking out loud
    r"^(i think|i guess|i suppose|maybe|perhaps)\s+",
    # Question starters (keep the question)
    r"^(just|quickly|real quick)\s+",
]

_compiled_preambles = [re.compile(p, re.IGNORECASE) for p in PREAMBLE_PATTERNS]


def strip_preambles(text: str) -> str:
    """
    Strip common preambles from user input.
    
    Examples:
        "okay nova remind me to..." -> "remind me to..."
        "hey can you store this" -> "store this"
        "lowkey I need to log how I'm feeling" -> "log how I'm feeling"
        "bruh i gotta check in" -> "check in"
    """
    result = text.strip()
    changed = True
    max_iterations = 5
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
# Pattern Definition
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
        destructive: If True, MUST use wizard (safety)
    """
    name: str
    cmd_name: str
    use_wizard: bool
    confidence: float
    patterns: List[str]
    destructive: bool = False


# =============================================================================
# DESTRUCTIVE COMMANDS (always require wizard)
# =============================================================================

DESTRUCTIVE_PATTERNS: List[NLPattern] = [
    # MEMORY FORGET
    NLPattern(
        name="memory_forget",
        cmd_name="forget",
        use_wizard=True,
        confidence=0.85,
        destructive=True,
        patterns=[
            r"\bforget (this|that|the) memory\b",
            r"\bdelete (this|that|the) memory\b",
            r"\bremove (this|that|the) memory\b",
            r"\bforget memory\s*#?\d*\b",
            r"\bdelete memory\s*#?\d*\b",
            r"\berase (this|that|the) memory\b",
        ],
    ),
    
    # REMINDER DELETE
    NLPattern(
        name="reminder_delete",
        cmd_name="remind-delete",
        use_wizard=True,
        confidence=0.85,
        destructive=True,
        patterns=[
            r"\b(delete|remove|cancel) (the |that |my )?reminder\b",
            r"\breminder.*(delete|remove|cancel)\b",
            r"\bget rid of (the |that |my )?reminder\b",
        ],
    ),
    
    # WORKFLOW DELETE
    NLPattern(
        name="workflow_delete",
        cmd_name="workflow-delete",
        use_wizard=True,
        confidence=0.85,
        destructive=True,
        patterns=[
            r"\b(delete|remove) (the |that |my )?(\w+\s+)?workflow\b",
            r"\bworkflow.*(delete|remove)\b",
            r"\bget rid of (the |that )?(\w+\s+)?workflow\b",
        ],
    ),
    
    # MODULE DISMANTLE
    NLPattern(
        name="dismantle_module",
        cmd_name="dismantle",
        use_wizard=True,
        confidence=0.85,
        destructive=True,
        patterns=[
            r"\b(delete|remove|dismantle) (the |that |my )?module\b",
            r"\bmodule.*(delete|remove|dismantle)\b",
            r"\bget rid of (the |that )?module\b",
        ],
    ),
    
    # SNAPSHOT RESTORE
    NLPattern(
        name="snapshot_restore",
        cmd_name="restore",
        use_wizard=True,
        confidence=0.85,
        destructive=True,
        patterns=[
            r"\brestore (from )?(a )?snapshot\b",
            r"\broll\s*back\b",
            r"\brevert (to |from )?(a )?snapshot\b",
            r"\bload (a )?snapshot\b",
            r"\bundo to (a )?snapshot\b",
        ],
    ),
    
    # COMMAND REMOVE
    NLPattern(
        name="command_remove",
        cmd_name="command-remove",
        use_wizard=True,
        confidence=0.85,
        destructive=True,
        patterns=[
            r"\b(delete|remove) (the |that |my )?(custom )?command\b",
            r"\bcommand.*(delete|remove)\b",
        ],
    ),
    
    # IDENTITY CLEAR HISTORY
    NLPattern(
        name="identity_clear_history",
        cmd_name="identity-clear-history",
        use_wizard=True,
        confidence=0.85,
        destructive=True,
        patterns=[
            r"\b(clear|reset|wipe) (my )?identity history\b",
            r"\bidentity.*(clear|reset|wipe)\b",
            r"\bdelete (my )?identity (history|snapshots)\b",
        ],
    ),
]


# =============================================================================
# GROUP A: WIZARD COMMANDS (guided input)
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
            r"\breminder (for|to|about)\b",
            r"\bdon't let me forget\b",
            r"\bmake sure i (remember|don't forget)\b",
            r"\bping me (about|when|to)\b",
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
            r"\breschedule (the |that |my )?reminder\b",
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
            r"\bremember:?\s+.{10,}",
            r"\bstore (this|that)( as)?\b",
            r"\bsave (this|that)( as| for)?\b",
            r"\bkeep (this|that) in memory\b",
            r"\bmake a (note|memory)( of| about)?\b",
            r"\bnote (this|that) down\b",
            r"\bdon't forget (this|that)\b",
            r"\bhold onto (this|that)\b",
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
            r"\bconnect (these |the |those )?memories\b",
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
            r"\bupdate my (state|energy|stress|mood)\b",
            r"\blog (my )?(current )?(state|mood|energy|vibe)\b",
            r"\btrack (my )?(energy|stress|mood|state)\b",
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
            r"\badd (a )?(goal|value|role)\b",
            r"\bupdate (my )?identity\b",
            r"\bchange my (identity|profile)\b",
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
            r"\bgo back to (an )?old(er)? identity\b",
        ],
    ),
    NLPattern(
        name="identity_snapshot",
        cmd_name="identity-snapshot",
        use_wizard=True,
        confidence=0.82,
        patterns=[
            r"\bsnapshot (my )?identity\b",
            r"\bsave (my )?identity\b",
            r"\bcapture (my )?identity\b",
            r"\bidentity snapshot\b",
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
            r"\b(start|begin|run|launch) (the |a |that |my )?(\w+\s+)?workflow\b",
            r"\b(start|begin|run|launch) (the |a |that |my )?\w+ workflow\b",
            r"\bworkflow.*(start|begin|run|launch)\b",
            r"\bkick off (the |a )?(\w+\s+)?workflow\b",
            r"\bactivate (the |a )?(\w+\s+)?workflow\b",
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
            r"\bnew workflow (for|to|that)\b",
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
            r"\bproceed\b",
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
            r"\bput (the )?workflow on hold\b",
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
            r"\bspin up (a )?module\b",
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
            r"\bexamine (the |that )?module\b",
            r"\blook at (the |that )?module\b",
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
            r"\bcapture (the )?current state\b",
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
            r"\bdefine (a )?(new )?command\b",
        ],
    ),
    
    # -------------------------------------------------------------------------
    # MODE
    # -------------------------------------------------------------------------
    NLPattern(
        name="mode_set",
        cmd_name="mode",
        use_wizard=True,
        confidence=0.82,
        patterns=[
            r"\b(switch|change|set) (to )?(deep[_\s]?work|reflection|debug|normal) mode\b",
            r"\b(enter|go into) (deep[_\s]?work|reflection|debug|normal) mode\b",
            r"\bchange mode\b",
            r"\bactivate (deep[_\s]?work|reflection|debug) mode\b",
        ],
    ),
    
    # -------------------------------------------------------------------------
    # MEMORY MANAGEMENT (optional wizard)
    # -------------------------------------------------------------------------
    NLPattern(
        name="memory_trace",
        cmd_name="trace",
        use_wizard=True,
        confidence=0.80,
        patterns=[
            r"\btrace (the |that |this )?memory\b",
            r"\bmemory (trace|history|lineage)\b",
            r"\bwhere did (this |that )?memory come from\b",
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
            r"\bsearch (my )?memories\b",
            r"\bfind (that |the )?memory\b",
        ],
    ),
]


# =============================================================================
# GROUP B: INSTANT COMMANDS (no wizard needed)
# =============================================================================

INSTANT_PATTERNS: List[NLPattern] = [
    # -------------------------------------------------------------------------
    # CONTINUITY (v0.6.1 NEW)
    # -------------------------------------------------------------------------
    NLPattern(
        name="continuity_preferences",
        cmd_name="preferences",
        use_wizard=False,
        confidence=0.85,
        patterns=[
            r"\b(show|my|what are my) preferences\b",
            r"\bwhat (do i|are my) priorit(y|ies)\b",
            r"\bmy priorities\b",
            r"\bwhat matters to me\b",
        ],
    ),
    NLPattern(
        name="continuity_projects",
        cmd_name="projects",
        use_wizard=False,
        confidence=0.85,
        patterns=[
            r"\b(show|my|what are my|active|list) projects\b",
            r"\bwhat('s| is) on my plate\b",
            r"\bwhat am i working on\b",
            r"\bmy active projects\b",
            r"\bcurrent projects\b",
        ],
    ),
    NLPattern(
        name="continuity_context",
        cmd_name="continuity-context",
        use_wizard=False,
        confidence=0.82,
        patterns=[
            r"\b(give me|show) (my )?continuity (view|context)\b",
            r"\bfull context\b",
            r"\bwhat do you know about me\b",
            r"\bmy (full )?context\b",
        ],
    ),
    NLPattern(
        name="reconfirm_prompts",
        cmd_name="reconfirm-prompts",
        use_wizard=False,
        confidence=0.80,
        patterns=[
            r"\bwhat should i (focus on|do) (today|now|next)\b",
            r"\breconfirm (my )?priorities\b",
            r"\bhelp me (get back on|stay on) track\b",
            r"\bwhat('s| is) important (right )?now\b",
            r"\bremind me what matters\b",
        ],
    ),
    NLPattern(
        name="suggest_workflow",
        cmd_name="suggest-workflow",
        use_wizard=False,
        confidence=0.80,
        patterns=[
            r"\bsuggest (a )?workflow (for|to)\b",
            r"\bworkflow suggestion\b",
            r"\brecommend (a )?workflow\b",
            r"\bwhat workflow (should i|for)\b",
        ],
    ),
    
    # -------------------------------------------------------------------------
    # IDENTITY GETTERS (v0.6.1 NEW)
    # -------------------------------------------------------------------------
    NLPattern(
        name="identity_history",
        cmd_name="identity-history",
        use_wizard=False,
        confidence=0.92,  # Much higher than identity-show (0.85) to win margin check
        patterns=[
            r"\b(show|my) identity (history|timeline)\b",
            r"\bidentity (snapshots|versions|history)\b",
            r"\bhow has my identity changed\b",
            r"\bidentity evolution\b",
            r"\bmy identity (history|timeline)\b",
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
            r"\bwho am i( to you)?\b",
            r"\bwhat do you know about me\b",
        ],
    ),
    
    # -------------------------------------------------------------------------
    # SYSTEM INFO (v0.6.1 NEW)
    # -------------------------------------------------------------------------
    NLPattern(
        name="system_env",
        cmd_name="env",
        use_wizard=False,
        confidence=0.85,
        patterns=[
            r"\bwhat mode am i in\b",
            r"\bcurrent mode\b",
            r"\b(show|my) environment\b",
            r"\benv(ironment)? (settings|state)\b",
            r"\bwhat('s| is) (the )?debug (mode|state)\b",
        ],
    ),
    NLPattern(
        name="system_model_info",
        cmd_name="model-info",
        use_wizard=False,
        confidence=0.85,
        patterns=[
            r"\bwhat model (are you|is this)\b",
            r"\bmodel info\b",
            r"\bwhat (llm|ai) (are you|is this)\b",
            r"\bwhich model\b",
            r"\bmodel (version|routing)\b",
        ],
    ),
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
            r"\bwhat (are your|commands do you have)\b",
            r"\bhelp me (understand|with) commands\b",
        ],
    ),
    NLPattern(
        name="system_status",
        cmd_name="status",
        use_wizard=False,
        confidence=0.85,
        patterns=[
            r"\bhow('s| is| are) (nova|novaos|the system|everything)\b",
            r"\bsystem (status|check|health)\b",
            r"\bwhat('s| is) (my |the )?(current )?status\b",
            r"\bare you (okay|working|running)\b",
        ],
    ),
    
    # -------------------------------------------------------------------------
    # MODULE LISTING
    # -------------------------------------------------------------------------
    NLPattern(
        name="module_list",
        cmd_name="map",
        use_wizard=False,
        confidence=0.88,
        patterns=[
            r"\b(show|list)( my| the| all)? modules\b",
            r"\bwhat modules\b",
            r"\bmodule (list|map)\b",
            r"\bwhich modules\b",
        ],
    ),
    
    # -------------------------------------------------------------------------
    # TIME RHYTHM (v0.6.1 NEW)
    # -------------------------------------------------------------------------
    NLPattern(
        name="time_presence",
        cmd_name="presence",
        use_wizard=False,
        confidence=0.82,
        patterns=[
            r"\b(give me|show) (my )?presence (snapshot|check)\b",
            r"\btime (rhythm )?presence\b",
            r"\bwhere am i (in time|temporally)\b",
            r"\btemporal (context|snapshot)\b",
            r"\bpresence check\b",
        ],
    ),
    NLPattern(
        name="time_pulse",
        cmd_name="pulse",
        use_wizard=False,
        confidence=0.82,
        patterns=[
            r"\b(run|do|give me) (a )?pulse (check|diagnostic)\b",
            r"\bpulse (check|status)\b",
            r"\bcheck (my |the )?pulse\b",
            r"\bworkflow pulse\b",
        ],
    ),
    NLPattern(
        name="time_align",
        cmd_name="align",
        use_wizard=False,
        confidence=0.80,
        patterns=[
            r"\bhow aligned am i\b",
            r"\balignment (check|status)\b",
            r"\balign me\b",
            r"\bam i aligned\b",
            r"\bcheck (my )?alignment\b",
        ],
    ),
    
    # -------------------------------------------------------------------------
    # INTERPRETATION (v0.6.1 NEW)
    # -------------------------------------------------------------------------
    NLPattern(
        name="interpret",
        cmd_name="interpret",
        use_wizard=False,
        confidence=0.80,
        patterns=[
            r"\b(help me )?understand (this|that)\b",
            r"\bwhat does (this|that) mean\b",
            r"\binterpret (this|that)\b",
            r"\bexplain (this|that) to me\b",
            # Note: "break down" moved to derive for first-principles usage
        ],
    ),
    NLPattern(
        name="derive",
        cmd_name="derive",
        use_wizard=False,
        confidence=0.85,  # Higher than interpret (0.80) to win in specificity
        patterns=[
            r"\b(first principles|from basics)\b",
            r"\bderive (this|that)\b",
            r"\bbreak (this|that|it) down (to|into) (basics|fundamentals|first principles)\b",
            r"\bfundamental(s|ly)\b.*\b(this|that|it)\b",
            r"\bdown to basics\b",
        ],
    ),
    NLPattern(
        name="synthesize",
        cmd_name="synthesize",
        use_wizard=False,
        confidence=0.80,
        patterns=[
            r"\bsynthesize (this|that|these)\b",
            r"\bcombine (these |the )?ideas\b",
            r"\bput (this|these) together\b",
            r"\bintegrate (this|these|that)\b",
        ],
    ),
    NLPattern(
        name="frame",
        cmd_name="frame",
        use_wizard=False,
        confidence=0.82,
        patterns=[
            r"\breframe (this|that|it)\b",
            r"\bframe (this|that) differently\b",
            r"\blook at (this|that|it) (another|different) way\b",
            r"\bnew perspective on (this|that)\b",
        ],
    ),
    NLPattern(
        name="forecast",
        cmd_name="forecast",
        use_wizard=False,
        confidence=0.82,
        patterns=[
            r"\bpredict (what|if|how)\b",
            r"\bforecast\b",
            r"\bwhat (happens|would happen) if\b",
            r"\bwhat('s| is) (the )?likely outcome\b",
            r"\bproject (this|that) forward\b",
        ],
    ),
    
    # -------------------------------------------------------------------------
    # MEMORY GETTERS
    # -------------------------------------------------------------------------
    NLPattern(
        name="memory_stats",
        cmd_name="memory-stats",
        use_wizard=False,
        confidence=0.90,
        patterns=[
            r"\bmemory stats\b",
            r"\bmemory statistics\b",
            r"\bhow (much|many) memories\b",
            r"\bmemory (count|health)\b",
        ],
    ),
    NLPattern(
        name="memory_list",
        cmd_name="recall",
        use_wizard=False,
        confidence=0.82,
        patterns=[
            r"\bshow (my |all )?memories\b",
            r"\blist (my |all )?memories\b",
            r"\bwhat (do i|have you) remember(ed)?\b",
        ],
    ),
    
    # -------------------------------------------------------------------------
    # WORKFLOW GETTERS
    # -------------------------------------------------------------------------
    NLPattern(
        name="workflow_list",
        cmd_name="workflow-list",
        use_wizard=False,
        confidence=0.88,
        patterns=[
            r"\b(show|list)( my| the| all)? workflows\b",
            r"\bwhat workflows\b",
            r"\bwhich workflows\b",
            r"\bactive workflows\b",
        ],
    ),
    
    # -------------------------------------------------------------------------
    # REMINDER GETTERS
    # -------------------------------------------------------------------------
    NLPattern(
        name="reminder_list",
        cmd_name="remind-list",
        use_wizard=False,
        confidence=0.88,
        patterns=[
            r"\b(show|list)( my| the| all)? reminders\b",
            r"\bwhat reminders\b",
            r"\bupcoming reminders\b",
            r"\bwhat (do i|am i) reminded (of|about)\b",
        ],
    ),
    
    # -------------------------------------------------------------------------
    # HUMAN STATE GETTERS
    # -------------------------------------------------------------------------
    NLPattern(
        name="state_evolution",
        cmd_name="evolution-status",
        use_wizard=False,
        confidence=0.82,
        patterns=[
            r"\b(evolution|my) status\b",
            r"\bhow am i (doing|progressing)\b",
            r"\bmy (current )?state\b",
            r"\bhow('s| is) my (energy|stress)\b",
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
            r"\bdo i have (band)?width\b",
            r"\bcan i take on more\b",
        ],
    ),
    
    # -------------------------------------------------------------------------
    # IDENTITY INFO
    # -------------------------------------------------------------------------
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
            r"\btell me about (yourself|nova)\b",
        ],
    ),
]


# =============================================================================
# PSYCHOLOGICAL / EMOTIONAL PATTERNS (v0.6.1 NEW)
# High confidence required (0.80+) since these are implicit
# =============================================================================

PSYCHOLOGICAL_PATTERNS: List[NLPattern] = [
    NLPattern(
        name="psych_lost_direction",
        cmd_name="reconfirm-prompts",
        use_wizard=False,
        confidence=0.82,
        patterns=[
            r"\bi feel (lost|stuck|confused|overwhelmed)\b",
            r"\bi (need|want) direction\b",
            r"\bwhat should i (be doing|focus on)\b",
            r"\bi('m| am) (not sure|unsure) what to do\b",
            r"\bhelp me (figure out|decide) what to do\b",
        ],
    ),
    NLPattern(
        name="psych_check_in",
        cmd_name="log-state",
        use_wizard=True,
        confidence=0.82,
        patterns=[
            r"\bi('m| am) (feeling|doing) (really )?(bad|terrible|awful|great|amazing|good)\b",
            r"\bi('m| am) (exhausted|burnt out|burned out|energized|pumped)\b",
            r"\bi('m| am) (stressed|anxious|calm|relaxed)\b",
            r"\bfeeling (off|weird|strange|good|bad) (today|rn|right now)\b",
        ],
    ),
    NLPattern(
        name="psych_capacity_check",
        cmd_name="capacity",
        use_wizard=False,
        confidence=0.80,
        patterns=[
            r"\bi can't (think|focus|handle) (rn|right now|anymore)\b",
            r"\bi('m| am) (too|so) tired\b",
            r"\bi('m| am) running on (empty|fumes)\b",
            r"\bdo i have (any )?(space|room|capacity)\b",
        ],
    ),
    NLPattern(
        name="psych_get_back_on_track",
        cmd_name="reconfirm-prompts",
        use_wizard=False,
        confidence=0.82,
        patterns=[
            r"\bhelp me get back on track\b",
            r"\bi need to (refocus|get organized|prioritize)\b",
            r"\bwhere (was i|did i leave off)\b",
            r"\blet('s| me) (refocus|regroup)\b",
        ],
    ),
]


# =============================================================================
# Combine all patterns
# =============================================================================

ALL_PATTERNS: List[NLPattern] = (
    DESTRUCTIVE_PATTERNS + 
    WIZARD_PATTERNS + 
    INSTANT_PATTERNS + 
    PSYCHOLOGICAL_PATTERNS
)


# =============================================================================
# Conflict Detection
# =============================================================================

# Commands that conflict with each other (if both match, return no match)
CONFLICTING_COMMANDS: List[Set[str]] = [
    {"store", "forget"},  # Can't remember and forget same thing
    {"remind-add", "remind-delete"},  # Can't add and delete reminder
    {"workflow-delete", "flow"},  # Can't start and delete workflow
    {"forge", "dismantle"},  # Can't create and delete module
    {"snapshot", "restore"},  # Can't snapshot and restore at once
]


def has_conflict(matches: List[IntentMatch]) -> bool:
    """Check if matches contain conflicting commands."""
    if len(matches) < 2:
        return False
    
    matched_commands = {m.command for m in matches}
    
    for conflict_set in CONFLICTING_COMMANDS:
        if len(matched_commands & conflict_set) > 1:
            return True
    
    return False


# -----------------------------------------------------------------------------
# Natural Language Router
# -----------------------------------------------------------------------------

class NaturalLanguageRouter:
    """
    v0.6.1 Natural Language Router (Wizard-Aware, Expanded Coverage)
    
    Routes natural language input to syscommands via pattern matching.
    Supports wizard triggering for commands that benefit from guided input.
    Enforces safety rules for destructive commands.
    """
    
    MIN_CONFIDENCE = 0.75
    CONFLICT_MARGIN = 0.05  # If top two matches within this margin, treat as ambiguous
    
    def __init__(self):
        self._compiled_patterns: List[Tuple[NLPattern, List[re.Pattern]]] = []
        
        for nl_pattern in ALL_PATTERNS:
            compiled_regexes = []
            for regex_str in nl_pattern.patterns:
                try:
                    compiled_regexes.append(re.compile(regex_str, re.IGNORECASE))
                except re.error:
                    pass
            if compiled_regexes:
                self._compiled_patterns.append((nl_pattern, compiled_regexes))
    
    def route(self, text: str) -> Optional[CommandRequest]:
        """
        Route natural language text to a CommandRequest.
        
        Returns None if:
        - No confident match found
        - Mixed/conflicting intent detected
        - Ambiguous (two matches with similar confidence)
        """
        text = text.strip()
        if not text:
            return None
        
        # Skip if looks like a command
        if text.startswith("#") or text.startswith("/"):
            return None
        
        # Strip preambles
        cleaned_text = strip_preambles(text)
        
        # Find all matches
        all_matches: List[IntentMatch] = []
        
        for nl_pattern, compiled_regexes in self._compiled_patterns:
            for compiled in compiled_regexes:
                match = compiled.search(cleaned_text)
                if match:
                    # Calculate confidence with length factor
                    match_len = len(match.group(0))
                    text_len = len(cleaned_text)
                    length_factor = min(1.0, match_len / max(text_len * 0.4, 1))
                    adjusted_confidence = nl_pattern.confidence * (0.85 + 0.15 * length_factor)
                    
                    # Destructive commands always use wizard
                    use_wizard = nl_pattern.use_wizard or nl_pattern.destructive
                    
                    all_matches.append(IntentMatch(
                        command=nl_pattern.cmd_name,
                        confidence=adjusted_confidence,
                        args={},
                        matched_pattern=match.group(0),
                        use_wizard=use_wizard,
                    ))
                    break  # Only first match per pattern group
        
        if not all_matches:
            return None
        
        # Sort by confidence
        all_matches.sort(key=lambda m: -m.confidence)
        
        # Check for conflicts
        if has_conflict(all_matches[:3]):  # Check top 3 matches
            return None  # Mixed intent
        
        # Check for ambiguity (two high matches too close)
        if len(all_matches) >= 2:
            top = all_matches[0]
            second = all_matches[1]
            if (top.confidence >= self.MIN_CONFIDENCE and 
                second.confidence >= self.MIN_CONFIDENCE and
                top.confidence - second.confidence < self.CONFLICT_MARGIN and
                top.command != second.command):
                return None  # Ambiguous
        
        best_match = all_matches[0]
        
        if best_match.confidence >= self.MIN_CONFIDENCE:
            return CommandRequest(
                cmd_name=best_match.command,
                args=best_match.args,
                session_id="",
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
        """Debug helper: show all matching intents with confidence scores."""
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
                        "use_wizard": nl_pattern.use_wizard or nl_pattern.destructive,
                        "destructive": nl_pattern.destructive,
                        "pattern": compiled.pattern,
                        "matched": match.group(0),
                    })
                    break
        
        matches.sort(key=lambda m: -m["confidence"])
        
        has_conflicts = has_conflict([
            IntentMatch(m["command"], m["confidence"], {}, m["matched"], m["use_wizard"])
            for m in matches[:3]
        ])
        
        would_route = (
            len(matches) > 0 and 
            matches[0]["confidence"] >= self.MIN_CONFIDENCE and
            not has_conflicts
        )
        
        return {
            "input": text,
            "cleaned": cleaned_text,
            "matches": matches[:10],
            "best_match": matches[0] if matches else None,
            "has_conflict": has_conflicts,
            "would_route": would_route,
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
