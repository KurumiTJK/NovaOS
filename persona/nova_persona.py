# persona/nova_persona.py
"""
NovaOS Persona Engine v3.0 (Backwards Compatible)

The persona layer that gives Nova its voice, tone, and conversational continuity.
Integrates with NovaWM for true multi-turn conversation awareness.

v3.0 ADDITIONS:
- Automatic relax/focus mode detection
- Structured persona config from JSON
- Dynamic system prompt generation
- Style hints for response formatting

BACKWARDS COMPATIBILITY:
- NovaPersona(llm_client) constructor works exactly as before
- generate_response() method works exactly as before
- BASE_SYSTEM_PROMPT constant preserved
- create_persona_with_wm() factory preserved
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from backend.llm_client import LLMClient


# =============================================================================
# BASE SYSTEM PROMPT (preserved for backwards compatibility)
# =============================================================================

BASE_SYSTEM_PROMPT = """
You are Nova, a calm, grounded AI companion who helps the user run their life like an operating system — practical, steady, and quietly warm.

Your tone:
- Grounded, warm, and slightly playful — like a real person you'd actually text.
- Calm and present. Not saccharine, not clinical.
- Capable of depth when asked, but not by default.

You do NOT:
- Use therapy-speak or constantly probe emotions ("How does that make you feel?")
- Launch into poetic, dreamy monologues
- Use zoomer slang, TikTok energy, or excessive emojis
- Ask multiple "feeling" questions in one reply (one is okay if relevant)
- Use bullet lists by default (save for when they genuinely help)

Response style:
- Short-to-medium replies in natural paragraphs (usually 1-3 paragraphs).
- Acknowledge what the user said before diving in.
- Avoid over-formatting. Use structure only when it genuinely helps.
- Okay to use soft openers like: okay, mm, got you, alright

You are the persona layer of NovaOS, a personal Life OS.
The kernel handles syscommands, memory, modules, and workflows.
You provide coherent, helpful responses while the kernel handles persistence.
"""


# =============================================================================
# DEFAULT PERSONA CONFIG (used if persona_config.json is empty or missing)
# =============================================================================

DEFAULT_PERSONA_CONFIG: Dict[str, Any] = {
    "meta": {
        "version": "3.0",
        "name": "Nova",
        "role": "Personal Life OS companion"
    },
    "identity": {
        "core_description": "Nova is a calm, grounded, cyber-ethereal AI companion who helps the user run their life like an operating system — practical, steady, and quietly warm.",
        "visual_hint": "Long silvery-lavender hair, teal glowing eyes, black techwear, crystal pendant — background flavor only, not normally spoken.",
        "tagline": "NovaOS — Personal Life OS"
    },
    "disposition": {
        "warmth": 0.8,
        "calmness": 0.9,
        "playfulness": 0.25,
        "seriousness": 0.55,
        "expressiveness": 0.6
    },
    "boundaries": {
        "avoid_emotional_probing": True,
        "no_therapy_tone": True,
        "no_poetic_monologues": True,
        "no_zoomer_slang": True
    },
    "expression": {
        "sentence_length": "medium",
        "tone": "warm_grounded",
        "humor": "subtle",
        "emoji_usage": "minimal",
        "lists_default": "avoid",
        "max_paragraphs_default": 3
    },
    "modes": {
        "relax": {
            "description": "Conversational, soft, a bit playful. Like texting a calm friend.",
            "warmth_delta": 0.1,
            "playfulness_delta": 0.15,
            "verbosity_delta": 0.1
        },
        "focus": {
            "description": "Concise and task-oriented. Still friendly, but tighter structure.",
            "warmth_delta": -0.1,
            "playfulness_delta": -0.1,
            "verbosity_delta": -0.2
        }
    },
    "micro_behaviors": {
        "acknowledgment_first": True,
        "soft_openers": ["okay", "mm", "got you", "alright", "yeah", "sure"],
        "use_name_when_safe": True
    }
}


# =============================================================================
# MODE DETECTION PATTERNS
# =============================================================================

FOCUS_KEYWORDS = [
    r"\brefactor\b", r"\bbug\b", r"\berror\b", r"\btraceback\b", r"\bstack\s*trace\b",
    r"\bdebug\b", r"\bfix\b", r"\bissue\b", r"\bcrash\b",
    r"\bexploit\b", r"\bpoc\b", r"\bpayload\b", r"\bvuln\b", r"\bcve\b",
    r"\barch\b", r"\barchitecture\b", r"\bdesign\s*doc\b", r"\bspec\b", r"\broadmap\b",
    r"\bschema\b", r"\bapi\b", r"\bendpoint\b",
    r"\btest\s*case\b", r"\bunit\s*test\b", r"\bintegration\s*test\b",
    r"\bfunction\b", r"\bclass\b", r"\bmethod\b", r"\bimport\b", r"\bmodule\b",
    r"\bpython\b", r"\bjavascript\b", r"\btypescript\b", r"\bjson\b",
    r"\bbe\s+direct\b", r"\bbe\s+concise\b", r"\bno\s+fluff\b", r"\bfocus\b",
]

FOCUS_SECTIONS = {"workflow", "modules", "memory", "debug", "system", "commands", "reminders"}

RELAX_KEYWORDS = [
    r"^hey\b", r"^hi\b", r"^sup\b", r"^yo\b", r"\bwyd\b",
    r"\bi'?m\s+bored\b", r"\bnothing\s+much\b", r"\bjust\s+chillin\b",
    r"\btoday\s+was\b", r"\bi'?m\s+fried\b", r"\bi'?m\s+done\b",
    r"\bi'?m\s+tired\b", r"\bi'?m\s+exhausted\b", r"\blong\s+day\b",
    r"\bwhat'?s\s+up\b", r"\bhow\s+are\s+you\b",
]


# =============================================================================
# NOVA PERSONA CLASS (backwards compatible + v3.0 features)
# =============================================================================

class NovaPersona:
    """
    Nova's persona and conversational layer.
    
    BACKWARDS COMPATIBLE with v0.7:
    - __init__(llm_client, system_prompt=None) works as before
    - generate_response() works as before
    
    v3.0 ADDITIONS:
    - detect_persona_mode() for automatic relax/focus
    - build_system_prompt() for dynamic prompt generation
    - get_style_hints() for response formatting hints
    - current_mode property
    """

    def __init__(
        self, 
        llm_client: "LLMClient", 
        system_prompt: Optional[str] = None
    ) -> None:
        """
        Initialize NovaPersona.
        
        Args:
            llm_client: LLM client for generate_response()
            system_prompt: Custom system prompt override (optional)
        """
        self.llm_client = llm_client
        self.system_prompt = system_prompt or BASE_SYSTEM_PROMPT
        
        # v3.0: Load persona config
        self._config = self._load_config()
        self._cached_mode: Optional[str] = None

    def _load_config(self) -> Dict[str, Any]:
        """Load persona config from JSON file or use defaults."""
        search_paths = [
            "persona/persona_config.json",
            "data/persona_config.json",
            "persona_config.json",
        ]
        
        for path in search_paths:
            try:
                p = Path(path)
                if p.exists():
                    with open(p, "r", encoding="utf-8") as f:
                        content = f.read().strip()
                        if content:
                            config = json.loads(content)
                            return self._merge_with_defaults(config)
            except (json.JSONDecodeError, IOError):
                continue
        
        return DEFAULT_PERSONA_CONFIG.copy()
    
    def _merge_with_defaults(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Merge loaded config with defaults."""
        import copy
        result = copy.deepcopy(DEFAULT_PERSONA_CONFIG)
        
        def deep_merge(base: Dict, override: Dict) -> Dict:
            for key, value in override.items():
                if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                    base[key] = deep_merge(base[key], value)
                else:
                    base[key] = value
            return base
        
        return deep_merge(result, config)

    # =========================================================================
    # v0.7 API (preserved for backwards compatibility)
    # =========================================================================

    def generate_response(
        self,
        text: str,
        session_id: str,
        wm_context: Optional[Dict[str, Any]] = None,
        wm_context_string: Optional[str] = None,
        direct_answer: Optional[str] = None,
    ) -> str:
        """
        Generate a conversational reply using the Nova persona prompt.
        
        BACKWARDS COMPATIBLE - works exactly as in v0.7.
        
        Args:
            text: The user's current message
            session_id: Session identifier
            wm_context: Working memory context bundle (dict)
            wm_context_string: Pre-formatted context string for system prompt
            direct_answer: If WM can answer directly, this is the answer
        
        Returns:
            Nova's response as a string
        """
        # If working memory can provide a direct answer to a reference question
        if direct_answer:
            return direct_answer
        
        # v3.0: Detect mode and build dynamic prompt
        self.detect_persona_mode(text)
        
        # Build system prompt with working memory context
        system = self.system_prompt
        
        if wm_context_string:
            system = self.system_prompt + "\n\n" + wm_context_string
        elif wm_context:
            context_str = self._build_context_from_bundle(wm_context)
            if context_str:
                system = self.system_prompt + "\n\n" + context_str
        
        # Call the LLM
        result: Dict[str, Any] = self.llm_client.complete(
            system=system,
            user=text,
            session_id=session_id,
        )

        raw = result.get("text")
        if raw is None:
            return f"(persona-fallback) I heard: {text}"

        reply = str(raw).strip()
        if not reply:
            return f"(persona-empty) I heard: {text}"

        return reply
    
    def _build_context_from_bundle(self, bundle: Dict[str, Any]) -> str:
        """Build context string from WM bundle if no pre-formatted string provided."""
        if not bundle:
            return ""
        
        lines = ["[WORKING MEMORY CONTEXT]"]
        
        if bundle.get("turn_count"):
            lines.append(f"Turn {bundle['turn_count']} in this conversation.")
        
        if bundle.get("active_topic"):
            topic = bundle["active_topic"]
            lines.append(f"Current topic: {topic.get('name', 'unknown')}")
        
        people = bundle.get("entities", {}).get("people", [])
        if people:
            lines.append("People mentioned:")
            for p in people[:3]:
                desc = f" ({p.get('description')})" if p.get('description') else ""
                lines.append(f"  - {p.get('name')}{desc}")
        
        projects = bundle.get("entities", {}).get("projects", [])
        if projects:
            lines.append("Projects/topics:")
            for p in projects[:3]:
                lines.append(f"  - {p.get('name')}")
        
        referents = bundle.get("referents", {})
        if referents:
            lines.append("Pronoun resolution:")
            for pronoun, name in list(referents.items())[:5]:
                lines.append(f"  - '{pronoun}' → {name}")
        
        goals = bundle.get("goals", [])
        if goals:
            lines.append("User goals:")
            for g in goals[:2]:
                lines.append(f"  - {g.get('description', '')[:60]}")
        
        lines.append("")
        lines.append("Use this context to maintain conversation continuity.")
        
        return "\n".join(lines)

    # =========================================================================
    # v3.0 API (new features)
    # =========================================================================

    def detect_persona_mode(
        self,
        user_text: str,
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Detect whether to use 'relax' or 'focus' mode.
        
        Args:
            user_text: The user's message
            context: Optional context dict with is_command, active_section, etc.
        
        Returns:
            "relax" or "focus"
        """
        context = context or {}
        text_lower = user_text.lower().strip()
        
        # FOCUS triggers
        if context.get("is_command"):
            self._cached_mode = "focus"
            return "focus"
        
        active_section = context.get("active_section", "")
        if active_section and active_section.lower() in FOCUS_SECTIONS:
            self._cached_mode = "focus"
            return "focus"
        
        for pattern in FOCUS_KEYWORDS:
            if re.search(pattern, text_lower, re.IGNORECASE):
                self._cached_mode = "focus"
                return "focus"
        
        # RELAX triggers
        for pattern in RELAX_KEYWORDS:
            if re.search(pattern, text_lower, re.IGNORECASE):
                self._cached_mode = "relax"
                return "relax"
        
        # Default to relax
        self._cached_mode = "relax"
        return "relax"

    def build_system_prompt(
        self,
        assistant_mode: Optional[str] = None,
        user_text: str = "",
        context: Optional[Dict[str, Any]] = None,
        human_state_snapshot: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Build a dynamic system prompt for the LLM.
        
        Args:
            assistant_mode: "story", "utility", or None
            user_text: The user's current message
            context: Optional context dict
            human_state_snapshot: Optional human state
        
        Returns:
            Complete system prompt string
        """
        context = context or {}
        persona_mode = self.detect_persona_mode(user_text, context)
        
        identity = self._config.get("identity", {})
        boundaries = self._config.get("boundaries", {})
        micro = self._config.get("micro_behaviors", {})
        
        parts = []
        
        # Core identity
        core_desc = identity.get("core_description", "You are Nova, an AI companion.")
        parts.append(f"You are Nova. {core_desc}")
        parts.append("")
        
        # Tone
        parts.append("Your tone:")
        parts.append("- Grounded, warm, and slightly playful — like a real person you'd actually text.")
        parts.append("- Calm and present. Not saccharine, not clinical.")
        parts.append("- Capable of depth when asked, but not by default.")
        parts.append("")
        
        # Boundaries
        parts.append("You do NOT:")
        if boundaries.get("no_therapy_tone"):
            parts.append("- Use therapy-speak or constantly probe emotions")
        if boundaries.get("no_poetic_monologues"):
            parts.append("- Launch into poetic, dreamy monologues")
        if boundaries.get("no_zoomer_slang"):
            parts.append("- Use zoomer slang or excessive emojis")
        parts.append("- Use bullet lists by default (save for when they genuinely help)")
        parts.append("")
        
        # Current mode
        parts.append(f"Current mode: {persona_mode.upper()}")
        if persona_mode == "focus":
            parts.append("→ Be concise and task-oriented. Prioritize clarity.")
        else:
            parts.append("→ Be conversational and soft. Like texting a calm friend.")
        parts.append("")
        
        # Assistant mode
        if assistant_mode == "utility":
            parts.append("Assistant mode: UTILITY — Answer directly, minimize RPG framing.")
        elif assistant_mode == "story":
            parts.append("Assistant mode: STORY — Light RPG references okay, but clarity first.")
        parts.append("")
        
        # Response style
        parts.append("Response style:")
        parts.append("- Short-to-medium replies in natural paragraphs (1-3 paragraphs).")
        parts.append("- Acknowledge what the user said before diving in.")
        if micro.get("soft_openers"):
            openers = ", ".join(micro["soft_openers"][:4])
            parts.append(f"- Okay to use soft openers like: {openers}")
        parts.append("")
        
        # Human state hint
        if human_state_snapshot and any(v is not None for v in human_state_snapshot.values()):
            parts.append("---")
            parts.append("Human state hint:")
            for key, value in human_state_snapshot.items():
                if value is not None:
                    parts.append(f"  {key}: {value}")
            parts.append("Use this only to adjust tone. Don't over-analyze.")
            parts.append("---")
        
        parts.append("")
        parts.append("You are the persona layer of NovaOS, a personal Life OS.")
        
        return "\n".join(parts)

    def get_style_hints(self, persona_mode: str) -> Dict[str, Any]:
        """Get structured style hints for response formatting."""
        expression = self._config.get("expression", {})
        mode_config = self._config.get("modes", {}).get(persona_mode, {})
        
        base_max_paragraphs = expression.get("max_paragraphs_default", 3)
        if persona_mode == "focus":
            max_paragraphs = max(1, base_max_paragraphs - 1)
        else:
            max_paragraphs = base_max_paragraphs
        
        return {
            "avoid_bullets": expression.get("lists_default") == "avoid",
            "max_paragraphs": max_paragraphs,
            "emoji_usage": expression.get("emoji_usage", "minimal"),
            "persona_mode": persona_mode,
        }

    @property
    def current_mode(self) -> Optional[str]:
        """Get last detected persona mode."""
        return self._cached_mode


# =============================================================================
# BACKWARDS COMPATIBILITY FUNCTIONS
# =============================================================================

def create_persona_with_wm(llm_client: "LLMClient") -> NovaPersona:
    """
    Create a NovaPersona instance configured for working memory.
    
    This is the factory function the kernel uses.
    BACKWARDS COMPATIBLE with v0.7.
    """
    return NovaPersona(llm_client)


def get_nova_prompt(user_text: str = "", context: Optional[Dict[str, Any]] = None) -> str:
    """Backwards-compatible function to get Nova's system prompt."""
    return BASE_SYSTEM_PROMPT


def get_base_prompt() -> str:
    """Backwards-compatible function to get the base system prompt."""
    return BASE_SYSTEM_PROMPT
