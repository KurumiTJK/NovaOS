# council/__init__.py
"""
Nova Council — Core Package

Multi-model orchestration system for NovaOS.

Modes:
- OFF (SOLO): GPT-5 only
- QUEST: Gemini Flash ideation → GPT-5 synthesis  
- LIVE: Gemini Pro research → GPT-5 final
- LIVE-MAX: Full pipeline for command design
"""

from council.state import (
    CouncilMode,
    CouncilState,
    get_council_state,
    reset_council_state,
    clear_all_states,
    MODE_DISPLAY,
)

from council.router import (
    detect_council_mode,
    extract_flags,
    is_command_intent,
    is_quest_intent,
    is_live_intent,
    ExplicitFlag,
)

from council.orchestrator import (
    PipelineResult,
    run_council_pipeline,
    run_solo_pipeline,
    run_quest_pipeline,
    run_live_pipeline,
    run_live_max_pipeline,
)

from council.validate import (
    validate_quest_ideation,
    validate_live_research,
    validate_json_response,
)

__all__ = [
    # State
    "CouncilMode",
    "CouncilState", 
    "get_council_state",
    "reset_council_state",
    "clear_all_states",
    "MODE_DISPLAY",
    # Router
    "detect_council_mode",
    "extract_flags",
    "is_command_intent",
    "is_quest_intent",
    "is_live_intent",
    "ExplicitFlag",
    # Orchestrator
    "PipelineResult",
    "run_council_pipeline",
    "run_solo_pipeline",
    "run_quest_pipeline",
    "run_live_pipeline",
    "run_live_max_pipeline",
    # Validation
    "validate_quest_ideation",
    "validate_live_research",
    "validate_json_response",
]
