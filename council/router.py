# council/router.py
"""
Nova Council — Mode Router

Detects the appropriate council mode based on:
1. Explicit flags (@solo, @explore, @live, @max)
2. Heuristics based on message content

v1.0.0: Initial implementation
"""

import re
import sys
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple

from council.state import CouncilMode


# -----------------------------------------------------------------------------
# Explicit Flags
# -----------------------------------------------------------------------------

class ExplicitFlag(Enum):
    """User-specified mode flags."""
    SOLO = "@solo"
    EXPLORE = "@explore"
    LIVE = "@live"
    MAX = "@max"


# Flag patterns (case-insensitive)
# Note: @ is not a word character, so we use (?:^|\s) for start boundary
FLAG_PATTERNS = {
    ExplicitFlag.SOLO: re.compile(r'(?:^|\s)@solo(?:\s|$)', re.IGNORECASE),
    ExplicitFlag.EXPLORE: re.compile(r'(?:^|\s)@explore(?:\s|$)', re.IGNORECASE),
    ExplicitFlag.LIVE: re.compile(r'(?:^|\s)@live(?:\s|$)', re.IGNORECASE),
    ExplicitFlag.MAX: re.compile(r'(?:^|\s)@max(?:\s|$)', re.IGNORECASE),
}


# -----------------------------------------------------------------------------
# Heuristic Patterns
# -----------------------------------------------------------------------------

# Command-intent patterns (triggers LIVE-MAX)
COMMAND_INTENT_PATTERNS = [
    re.compile(r'\bcreate\s+a?\s*command\b', re.IGNORECASE),
    re.compile(r'\bdesign\s+a?\s*command\b', re.IGNORECASE),
    re.compile(r'\badd\s+a?\s*command\b', re.IGNORECASE),
    re.compile(r'\bmodify\s+command\b', re.IGNORECASE),
    re.compile(r'\brefactor\s+command\b', re.IGNORECASE),
    re.compile(r'\bimplement\s+command\b', re.IGNORECASE),
    re.compile(r'\bSYS_HANDLERS\b', re.IGNORECASE),
    re.compile(r'\bhandler\b', re.IGNORECASE),
    re.compile(r'\brouter\b', re.IGNORECASE),
    re.compile(r'\bregistry\b', re.IGNORECASE),
    re.compile(r'\bnew\s+#\w+\s+command\b', re.IGNORECASE),
    re.compile(r'\badd\s+#\w+\b', re.IGNORECASE),
]

# Quest-intent patterns (triggers QUEST)
QUEST_INTENT_PATTERNS = [
    re.compile(r'\bcreate\s+a?\s*quest\b', re.IGNORECASE),
    re.compile(r'\bquest[- ]?compose\b', re.IGNORECASE),
    re.compile(r'\bquest\s+for\b', re.IGNORECASE),
    re.compile(r'\blesson\s+plan\b', re.IGNORECASE),
    re.compile(r'\bsteps\s+for\s+learning\b', re.IGNORECASE),
    re.compile(r'\blearning\s+path\b', re.IGNORECASE),
    re.compile(r'\bstudy\s+guide\b', re.IGNORECASE),
    re.compile(r'#quest[- ]?compose\b', re.IGNORECASE),
]

# Live-intent patterns (triggers LIVE)
LIVE_INTENT_PATTERNS = [
    re.compile(r'\blatest\b', re.IGNORECASE),
    re.compile(r'\bcurrent\b', re.IGNORECASE),
    re.compile(r'\btoday\b', re.IGNORECASE),
    re.compile(r'\bdocs\b', re.IGNORECASE),
    re.compile(r'\bpricing\b', re.IGNORECASE),
    re.compile(r'\bstatus\s+of\b', re.IGNORECASE),
    re.compile(r'\bverify\b', re.IGNORECASE),
    re.compile(r'\bresearch\b', re.IGNORECASE),
    re.compile(r'\blook\s+up\b', re.IGNORECASE),
    re.compile(r'\bfind\s+out\b', re.IGNORECASE),
]


# -----------------------------------------------------------------------------
# Routing Context
# -----------------------------------------------------------------------------

@dataclass
class CouncilRoutingContext:
    """Context for council mode routing."""
    raw_text: str
    clean_text: str  # Text with flags stripped
    detected_flag: Optional[ExplicitFlag] = None
    in_quest_flow: bool = False
    in_command_composer: bool = False


# -----------------------------------------------------------------------------
# Flag Extraction
# -----------------------------------------------------------------------------

def extract_flags(text: str) -> Tuple[str, Optional[ExplicitFlag]]:
    """
    Extract and strip explicit flags from text.
    
    Args:
        text: User input text
        
    Returns:
        (clean_text, detected_flag) - text with flag removed and the flag if found
    """
    for flag, pattern in FLAG_PATTERNS.items():
        if pattern.search(text):
            clean = pattern.sub('', text).strip()
            # Clean up any double spaces
            clean = re.sub(r'\s+', ' ', clean).strip()
            return clean, flag
    
    return text, None


# -----------------------------------------------------------------------------
# Heuristic Detection
# -----------------------------------------------------------------------------

def _has_command_intent(text: str) -> bool:
    """Check if text indicates command design intent."""
    for pattern in COMMAND_INTENT_PATTERNS:
        if pattern.search(text):
            return True
    return False


def _has_quest_intent(text: str) -> bool:
    """Check if text indicates quest creation intent."""
    for pattern in QUEST_INTENT_PATTERNS:
        if pattern.search(text):
            return True
    return False


def _has_live_intent(text: str) -> bool:
    """Check if text indicates live research intent."""
    for pattern in LIVE_INTENT_PATTERNS:
        if pattern.search(text):
            return True
    return False


# -----------------------------------------------------------------------------
# Main Router
# -----------------------------------------------------------------------------

def detect_council_mode(
    text: str,
    in_quest_flow: bool = False,
    in_command_composer: bool = False,
) -> Tuple[CouncilMode, str, str]:
    """
    Detect the appropriate council mode for the given input.
    
    Args:
        text: User input text
        in_quest_flow: True if user is inside quest composition
        in_command_composer: True if user is inside command composer
        
    Returns:
        (mode, clean_text, reason) - selected mode, text with flags stripped, reason
        
    Priority:
        1. Explicit flags (@solo, @explore, @live, @max)
        2. Command-intent heuristics → LIVE-MAX (mandatory)
        3. Quest-intent heuristics → QUEST
        4. Live-intent heuristics → LIVE
        5. Default → SOLO
    """
    # Extract any explicit flags
    clean_text, flag = extract_flags(text)
    
    # 1. Handle explicit flags
    if flag == ExplicitFlag.SOLO:
        reason = "explicit_@solo"
        print(f"[CouncilRouter] mode=SOLO reason={reason}", flush=True)
        return CouncilMode.OFF, clean_text, reason
    
    if flag == ExplicitFlag.EXPLORE:
        # @explore in quest flow → QUEST, otherwise → LIVE
        if in_quest_flow or _has_quest_intent(clean_text):
            reason = "explicit_@explore_quest_context"
            print(f"[CouncilRouter] mode=QUEST reason={reason}", flush=True)
            return CouncilMode.QUEST, clean_text, reason
        else:
            reason = "explicit_@explore_general"
            print(f"[CouncilRouter] mode=LIVE reason={reason}", flush=True)
            return CouncilMode.LIVE, clean_text, reason
    
    if flag == ExplicitFlag.LIVE:
        reason = "explicit_@live"
        print(f"[CouncilRouter] mode=LIVE reason={reason}", flush=True)
        return CouncilMode.LIVE, clean_text, reason
    
    if flag == ExplicitFlag.MAX:
        # @max only applies to command-intent; otherwise treat as LIVE
        if _has_command_intent(clean_text) or in_command_composer:
            reason = "explicit_@max_command_intent"
            print(f"[CouncilRouter] mode=LIVE-MAX reason={reason}", flush=True)
            return CouncilMode.LIVE_MAX, clean_text, reason
        else:
            reason = "explicit_@max_no_command_intent_fallback_live"
            print(f"[CouncilRouter] mode=LIVE reason={reason}", flush=True)
            return CouncilMode.LIVE, clean_text, reason
    
    # 2. Command-intent → LIVE-MAX (mandatory)
    if _has_command_intent(clean_text) or in_command_composer:
        reason = "heuristic_command_intent"
        print(f"[CouncilRouter] mode=LIVE-MAX reason={reason}", flush=True)
        return CouncilMode.LIVE_MAX, clean_text, reason
    
    # 3. Quest-intent → QUEST
    if _has_quest_intent(clean_text) or in_quest_flow:
        reason = "heuristic_quest_intent"
        print(f"[CouncilRouter] mode=QUEST reason={reason}", flush=True)
        return CouncilMode.QUEST, clean_text, reason
    
    # 4. Live-intent → LIVE
    if _has_live_intent(clean_text):
        reason = "heuristic_live_intent"
        print(f"[CouncilRouter] mode=LIVE reason={reason}", flush=True)
        return CouncilMode.LIVE, clean_text, reason
    
    # 5. Default → SOLO
    reason = "default_no_triggers"
    print(f"[CouncilRouter] mode=SOLO reason={reason}", flush=True)
    return CouncilMode.OFF, clean_text, reason


def is_command_intent(text: str) -> bool:
    """Public helper to check for command design intent."""
    return _has_command_intent(text)


def is_quest_intent(text: str) -> bool:
    """Public helper to check for quest intent."""
    return _has_quest_intent(text)


def is_live_intent(text: str) -> bool:
    """Public helper to check for live research intent."""
    return _has_live_intent(text)


# -----------------------------------------------------------------------------
# Module Exports
# -----------------------------------------------------------------------------

__all__ = [
    "CouncilMode",
    "ExplicitFlag",
    "CouncilRoutingContext",
    "detect_council_mode",
    "extract_flags",
    "is_command_intent",
    "is_quest_intent",
    "is_live_intent",
]
