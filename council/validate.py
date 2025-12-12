# council/validate.py
"""
Nova Council — JSON Schema Validation

Light validation for Gemini response schemas.

v1.0.0: Initial implementation
"""

import sys
from typing import Any, Dict, List, Optional, Tuple


# -----------------------------------------------------------------------------
# Quest Ideation Schema Validation
# -----------------------------------------------------------------------------

QUEST_REQUIRED_FIELDS = {"quest_theme", "goal", "difficulty", "estimated_duration", "steps", "risks", "notes"}
QUEST_STEP_REQUIRED = {"step_title", "action", "completion_criteria"}
VALID_DIFFICULTIES = {"low", "medium", "high"}


def validate_quest_ideation(data: Optional[Dict[str, Any]]) -> Tuple[bool, str]:
    """
    Validate quest ideation response schema.
    
    Args:
        data: Parsed JSON response
        
    Returns:
        (is_valid, error_message) - True with empty string if valid
    """
    if data is None:
        return False, "Response is None"
    
    if not isinstance(data, dict):
        return False, f"Expected dict, got {type(data).__name__}"
    
    # Check required top-level fields
    missing = QUEST_REQUIRED_FIELDS - set(data.keys())
    if missing:
        return False, f"Missing required fields: {missing}"
    
    # Validate difficulty
    difficulty = data.get("difficulty", "").lower()
    if difficulty not in VALID_DIFFICULTIES:
        return False, f"Invalid difficulty '{difficulty}', must be one of {VALID_DIFFICULTIES}"
    
    # Validate steps
    steps = data.get("steps", [])
    if not isinstance(steps, list):
        return False, f"'steps' must be a list, got {type(steps).__name__}"
    
    if len(steps) > 5:
        return False, f"Too many steps ({len(steps)}), maximum is 5"
    
    if len(steps) == 0:
        return False, "At least one step is required"
    
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            return False, f"Step {i} must be a dict"
        
        step_missing = QUEST_STEP_REQUIRED - set(step.keys())
        if step_missing:
            return False, f"Step {i} missing fields: {step_missing}"
    
    # Validate risks
    risks = data.get("risks", [])
    if not isinstance(risks, list):
        return False, f"'risks' must be a list, got {type(risks).__name__}"
    
    print(f"[CouncilValidate] quest_ideation: VALID ({len(steps)} steps)", flush=True)
    return True, ""


# -----------------------------------------------------------------------------
# Live Research Schema Validation
# -----------------------------------------------------------------------------

LIVE_REQUIRED_FIELDS = {"meta", "facts", "options", "edge_cases", "open_questions", "sources"}
LIVE_META_REQUIRED = {"provider", "model", "mode", "timestamp"}
LIVE_OPTION_REQUIRED = {"title", "summary", "tradeoffs", "risks"}
LIVE_SOURCE_REQUIRED = {"title", "url", "note"}


def validate_live_research(data: Optional[Dict[str, Any]]) -> Tuple[bool, str]:
    """
    Validate live research response schema.
    
    Args:
        data: Parsed JSON response
        
    Returns:
        (is_valid, error_message) - True with empty string if valid
    """
    if data is None:
        return False, "Response is None"
    
    if not isinstance(data, dict):
        return False, f"Expected dict, got {type(data).__name__}"
    
    # Check required top-level fields
    missing = LIVE_REQUIRED_FIELDS - set(data.keys())
    if missing:
        return False, f"Missing required fields: {missing}"
    
    # Validate meta
    meta = data.get("meta", {})
    if not isinstance(meta, dict):
        return False, f"'meta' must be a dict, got {type(meta).__name__}"
    
    meta_missing = LIVE_META_REQUIRED - set(meta.keys())
    if meta_missing:
        return False, f"'meta' missing fields: {meta_missing}"
    
    # Validate facts (list of strings)
    facts = data.get("facts", [])
    if not isinstance(facts, list):
        return False, f"'facts' must be a list, got {type(facts).__name__}"
    
    # Validate options
    options = data.get("options", [])
    if not isinstance(options, list):
        return False, f"'options' must be a list, got {type(options).__name__}"
    
    for i, opt in enumerate(options):
        if not isinstance(opt, dict):
            return False, f"Option {i} must be a dict"
        
        opt_missing = LIVE_OPTION_REQUIRED - set(opt.keys())
        if opt_missing:
            return False, f"Option {i} missing fields: {opt_missing}"
    
    # Validate edge_cases and open_questions (lists)
    for field in ["edge_cases", "open_questions"]:
        val = data.get(field, [])
        if not isinstance(val, list):
            return False, f"'{field}' must be a list, got {type(val).__name__}"
    
    # Validate sources (can be empty)
    sources = data.get("sources", [])
    if not isinstance(sources, list):
        return False, f"'sources' must be a list, got {type(sources).__name__}"
    
    for i, src in enumerate(sources):
        if not isinstance(src, dict):
            return False, f"Source {i} must be a dict"
        
        src_missing = LIVE_SOURCE_REQUIRED - set(src.keys())
        if src_missing:
            return False, f"Source {i} missing fields: {src_missing}"
    
    print(f"[CouncilValidate] live_research: VALID ({len(facts)} facts, {len(options)} options)", flush=True)
    return True, ""


# -----------------------------------------------------------------------------
# Generic Validation
# -----------------------------------------------------------------------------

def validate_json_response(
    data: Optional[Dict[str, Any]],
    required_fields: Optional[List[str]] = None,
) -> Tuple[bool, str]:
    """
    Generic JSON response validation.
    
    Args:
        data: Parsed JSON response
        required_fields: Optional list of required top-level fields
        
    Returns:
        (is_valid, error_message)
    """
    if data is None:
        return False, "Response is None"
    
    if not isinstance(data, dict):
        return False, f"Expected dict, got {type(data).__name__}"
    
    if required_fields:
        missing = set(required_fields) - set(data.keys())
        if missing:
            return False, f"Missing required fields: {missing}"
    
    return True, ""


# -----------------------------------------------------------------------------
# Module Exports
# -----------------------------------------------------------------------------

__all__ = [
    "validate_quest_ideation",
    "validate_live_research",
    "validate_json_response",
]
