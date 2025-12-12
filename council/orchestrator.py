# council/orchestrator.py
"""
Nova Council — Pipeline Orchestrator

Runs the appropriate pipeline based on council mode:
- SOLO: GPT-5 only
- QUEST: Gemini Flash → GPT-5 synthesis
- LIVE: Gemini Pro → GPT-5 final
- LIVE-MAX: Gemini Pro → GPT-5 design → GPT-5 verify (for command design)

v1.0.0: Initial implementation
"""

import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from council.state import CouncilMode, CouncilState, get_council_state
from council.router import detect_council_mode
from council.validate import validate_quest_ideation, validate_live_research
from providers.gemini_client import (
    gemini_quest_ideate,
    gemini_live_research,
    is_gemini_available,
)


# -----------------------------------------------------------------------------
# Cache Configuration
# -----------------------------------------------------------------------------

CACHE_DIR = Path(os.getenv("COUNCIL_CACHE_DIR", "/tmp/nova-council-cache"))
CACHE_TTL_HOURS = 24


# -----------------------------------------------------------------------------
# Request Hash Cache (QUEST mode only)
# -----------------------------------------------------------------------------

def _get_cache_path(request_hash: str) -> Path:
    """Get cache file path for a request hash."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"quest_{request_hash}.json"


def _compute_request_hash(request: str) -> str:
    """Compute deterministic hash for request caching."""
    return hashlib.sha256(request.encode()).hexdigest()[:16]


def _get_cached_quest(request: str) -> Optional[Dict[str, Any]]:
    """Get cached quest ideation if available and not expired."""
    request_hash = _compute_request_hash(request)
    cache_path = _get_cache_path(request_hash)
    
    if not cache_path.exists():
        return None
    
    try:
        with open(cache_path, 'r') as f:
            cached = json.load(f)
        
        # Check expiry
        cached_at = datetime.fromisoformat(cached.get("cached_at", "1970-01-01"))
        age_hours = (datetime.now(timezone.utc) - cached_at.replace(tzinfo=timezone.utc)).total_seconds() / 3600
        
        if age_hours > CACHE_TTL_HOURS:
            print(f"[CouncilCache] EXPIRED hash={request_hash} age={age_hours:.1f}h", flush=True)
            cache_path.unlink(missing_ok=True)
            return None
        
        print(f"[CouncilCache] HIT hash={request_hash} age={age_hours:.1f}h", flush=True)
        return cached.get("data")
        
    except Exception as e:
        print(f"[CouncilCache] ERROR reading cache: {e}", file=sys.stderr, flush=True)
        return None


def _cache_quest(request: str, data: Dict[str, Any]) -> None:
    """Cache quest ideation result."""
    request_hash = _compute_request_hash(request)
    cache_path = _get_cache_path(request_hash)
    
    try:
        cache_obj = {
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "request_hash": request_hash,
            "data": data,
        }
        with open(cache_path, 'w') as f:
            json.dump(cache_obj, f, indent=2)
        print(f"[CouncilCache] STORED hash={request_hash}", flush=True)
    except Exception as e:
        print(f"[CouncilCache] ERROR storing cache: {e}", file=sys.stderr, flush=True)


# -----------------------------------------------------------------------------
# Pipeline Result
# -----------------------------------------------------------------------------

@dataclass
class PipelineResult:
    """Result from running a council pipeline."""
    mode: CouncilMode
    success: bool
    gemini_used: bool
    gemini_result: Optional[Dict[str, Any]] = None
    extra_context: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    cache_hit: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode.value,
            "success": self.success,
            "gemini_used": self.gemini_used,
            "cache_hit": self.cache_hit,
            "error": self.error,
        }


# -----------------------------------------------------------------------------
# SOLO Pipeline
# -----------------------------------------------------------------------------

def run_solo_pipeline(
    user_text: str,
    session_id: str,
) -> PipelineResult:
    """
    Run SOLO pipeline (GPT-5 only, no Gemini).
    
    This is the existing behavior - returns empty result to let
    the caller proceed with normal GPT-5 processing.
    """
    print(f"[CouncilPipeline] SOLO - no Gemini processing", flush=True)
    return PipelineResult(
        mode=CouncilMode.OFF,
        success=True,
        gemini_used=False,
    )


# -----------------------------------------------------------------------------
# QUEST Pipeline (Cheap Ideation)
# -----------------------------------------------------------------------------

def run_quest_pipeline(
    user_text: str,
    session_id: str,
) -> PipelineResult:
    """
    Run QUEST pipeline:
    1. Check cache (24h TTL)
    2. If miss, call gemini_quest_ideate() (Flash)
    3. Validate JSON schema
    4. Return result for GPT-5 synthesis
    """
    print(f"[CouncilPipeline] QUEST - checking cache", flush=True)
    state = get_council_state(session_id)
    
    # Check cache first
    cached = _get_cached_quest(user_text)
    if cached:
        state.mark_cache_hit(CouncilMode.QUEST)
        return PipelineResult(
            mode=CouncilMode.QUEST,
            success=True,
            gemini_used=True,
            gemini_result=cached,
            extra_context={"gemini_quest_notes": cached},
            cache_hit=True,
        )
    
    # Check if Gemini is available
    if not is_gemini_available():
        print(f"[CouncilPipeline] QUEST - Gemini not available, falling back to SOLO", flush=True)
        return PipelineResult(
            mode=CouncilMode.OFF,
            success=True,
            gemini_used=False,
            error="Gemini not available",
        )
    
    # Call Gemini Flash
    print(f"[CouncilPipeline] QUEST - calling gemini_quest_ideate", flush=True)
    result = gemini_quest_ideate(user_text)
    
    if result is None:
        state.mark_error()
        print(f"[CouncilPipeline] QUEST - Gemini returned None, falling back to SOLO", flush=True)
        return PipelineResult(
            mode=CouncilMode.OFF,
            success=True,
            gemini_used=False,
            error="Gemini returned empty response",
        )
    
    # Validate schema
    is_valid, error = validate_quest_ideation(result)
    if not is_valid:
        state.mark_error()
        print(f"[CouncilPipeline] QUEST - validation failed: {error}", file=sys.stderr, flush=True)
        return PipelineResult(
            mode=CouncilMode.OFF,
            success=True,
            gemini_used=False,
            error=f"Schema validation failed: {error}",
        )
    
    # Cache the result
    _cache_quest(user_text, result)
    
    # Mark state as used
    state.mark_used(CouncilMode.QUEST)
    state.last_gemini_result = result
    
    print(f"[CouncilPipeline] QUEST - SUCCESS", flush=True)
    return PipelineResult(
        mode=CouncilMode.QUEST,
        success=True,
        gemini_used=True,
        gemini_result=result,
        extra_context={"gemini_quest_notes": result},
    )


# -----------------------------------------------------------------------------
# LIVE Pipeline (General Research)
# -----------------------------------------------------------------------------

def run_live_pipeline(
    user_text: str,
    session_id: str,
) -> PipelineResult:
    """
    Run LIVE pipeline:
    1. Call gemini_live_research() (Pro)
    2. Validate JSON schema
    3. Return result for GPT-5 final answer
    
    No caching for LIVE mode (research may change).
    """
    print(f"[CouncilPipeline] LIVE - calling gemini_live_research", flush=True)
    state = get_council_state(session_id)
    
    # Check if Gemini is available
    if not is_gemini_available():
        print(f"[CouncilPipeline] LIVE - Gemini not available, falling back to SOLO", flush=True)
        return PipelineResult(
            mode=CouncilMode.OFF,
            success=True,
            gemini_used=False,
            error="Gemini not available",
        )
    
    # Call Gemini Pro
    result = gemini_live_research(user_text)
    
    if result is None:
        state.mark_error()
        print(f"[CouncilPipeline] LIVE - Gemini returned None, falling back to SOLO", flush=True)
        return PipelineResult(
            mode=CouncilMode.OFF,
            success=True,
            gemini_used=False,
            error="Gemini returned empty response",
        )
    
    # Validate schema
    is_valid, error = validate_live_research(result)
    if not is_valid:
        state.mark_error()
        print(f"[CouncilPipeline] LIVE - validation failed: {error}", file=sys.stderr, flush=True)
        return PipelineResult(
            mode=CouncilMode.OFF,
            success=True,
            gemini_used=False,
            error=f"Schema validation failed: {error}",
        )
    
    # Mark state as used
    state.mark_used(CouncilMode.LIVE)
    state.last_gemini_result = result
    
    print(f"[CouncilPipeline] LIVE - SUCCESS", flush=True)
    return PipelineResult(
        mode=CouncilMode.LIVE,
        success=True,
        gemini_used=True,
        gemini_result=result,
        extra_context={"gemini_live_packet": result},
    )


# -----------------------------------------------------------------------------
# LIVE-MAX Pipeline (Command Design)
# -----------------------------------------------------------------------------

def run_live_max_pipeline(
    user_text: str,
    session_id: str,
    get_context_callback: Optional[Callable[[], Dict[str, str]]] = None,
) -> PipelineResult:
    """
    Run LIVE-MAX pipeline (most powerful, for command design):
    
    Pipeline steps:
    1. Gemini Pro Live Research
    2. Context retrieval (SYS_HANDLERS, registry, etc.)
    3. GPT-5 Design pass (done by caller)
    4. GPT-5 Verify pass (done by caller)
    
    This function handles step 1 and 2, returning context for GPT-5 passes.
    """
    print(f"[CouncilPipeline] LIVE-MAX - starting full pipeline", flush=True)
    state = get_council_state(session_id)
    
    # Always mark as LIVE-MAX even if Gemini fails (pipeline still runs)
    state.mark_used(CouncilMode.LIVE_MAX)
    
    extra_context: Dict[str, Any] = {
        "pipeline": "LIVE-MAX",
        "steps": ["gemini_research", "context_retrieval", "gpt5_design", "gpt5_verify"],
    }
    
    # Step 1: Gemini Pro research
    gemini_result = None
    if is_gemini_available():
        print(f"[CouncilPipeline] LIVE-MAX step 1 - gemini_live_research", flush=True)
        gemini_result = gemini_live_research(user_text)
        
        if gemini_result:
            is_valid, error = validate_live_research(gemini_result)
            if is_valid:
                extra_context["gemini_live_packet"] = gemini_result
                state.last_gemini_result = gemini_result
                print(f"[CouncilPipeline] LIVE-MAX step 1 - SUCCESS", flush=True)
            else:
                print(f"[CouncilPipeline] LIVE-MAX step 1 - validation failed: {error}", file=sys.stderr, flush=True)
                gemini_result = None
        else:
            print(f"[CouncilPipeline] LIVE-MAX step 1 - Gemini returned None", file=sys.stderr, flush=True)
    else:
        print(f"[CouncilPipeline] LIVE-MAX step 1 - Gemini not available (continuing without)", flush=True)
    
    # Step 2: Context retrieval
    if get_context_callback:
        print(f"[CouncilPipeline] LIVE-MAX step 2 - context retrieval", flush=True)
        try:
            code_context = get_context_callback()
            extra_context["code_context"] = code_context
            print(f"[CouncilPipeline] LIVE-MAX step 2 - retrieved {len(code_context)} context items", flush=True)
        except Exception as e:
            print(f"[CouncilPipeline] LIVE-MAX step 2 - context retrieval failed: {e}", file=sys.stderr, flush=True)
    
    # Steps 3 & 4 (GPT-5 passes) handled by caller
    extra_context["gpt5_passes_required"] = True
    
    print(f"[CouncilPipeline] LIVE-MAX - pre-processing complete, gemini_used={gemini_result is not None}", flush=True)
    return PipelineResult(
        mode=CouncilMode.LIVE_MAX,
        success=True,
        gemini_used=gemini_result is not None,
        gemini_result=gemini_result,
        extra_context=extra_context,
    )


# -----------------------------------------------------------------------------
# Main Orchestrator
# -----------------------------------------------------------------------------

def run_council_pipeline(
    user_text: str,
    session_id: str,
    in_quest_flow: bool = False,
    in_command_composer: bool = False,
    get_context_callback: Optional[Callable[[], Dict[str, str]]] = None,
) -> Tuple[PipelineResult, str]:
    """
    Main orchestrator entry point.
    
    Detects mode and runs appropriate pipeline.
    
    Args:
        user_text: Raw user input (may contain flags)
        session_id: Current session ID
        in_quest_flow: True if in quest composition wizard
        in_command_composer: True if in command composer wizard
        get_context_callback: Optional callback to retrieve code context for LIVE-MAX
        
    Returns:
        (pipeline_result, clean_text) - Result and text with flags stripped
    """
    # Detect mode and strip flags
    mode, clean_text, reason = detect_council_mode(
        user_text,
        in_quest_flow=in_quest_flow,
        in_command_composer=in_command_composer,
    )
    
    print(f"[CouncilOrchestrator] mode={mode.value} reason={reason}", flush=True)
    
    # Run appropriate pipeline
    if mode == CouncilMode.OFF:
        result = run_solo_pipeline(clean_text, session_id)
    elif mode == CouncilMode.QUEST:
        result = run_quest_pipeline(clean_text, session_id)
    elif mode == CouncilMode.LIVE:
        result = run_live_pipeline(clean_text, session_id)
    elif mode == CouncilMode.LIVE_MAX:
        result = run_live_max_pipeline(clean_text, session_id, get_context_callback)
    else:
        # Fallback to SOLO
        result = run_solo_pipeline(clean_text, session_id)
    
    return result, clean_text


# -----------------------------------------------------------------------------
# Module Exports
# -----------------------------------------------------------------------------

__all__ = [
    "PipelineResult",
    "run_council_pipeline",
    "run_solo_pipeline",
    "run_quest_pipeline",
    "run_live_pipeline",
    "run_live_max_pipeline",
]
