# kernel/lesson_engine/__init__.py
"""
v1.0.0 — Lesson Engine

Retrieval-backed, step-sized lesson generation for NovaOS Quest Compose.

3-Phase Pipeline:
  Phase A (Retrieval): Gemini 2.5 Pro with web grounding
  Phase B (Step Builder): Gemini 2.5 Pro
  Phase C (Plan Refiner): GPT-5.1

This module provides:
  - generate_lesson_plan(): Main entry point for Quest Compose
  - generate_lesson_plan_streaming(): Streaming version with progress events
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

from .schemas import (
    EvidencePack,
    EvidenceResource,
    LessonPlan,
    LessonStep,
    validate_lesson_plan,
)
from .retrieval import (
    retrieve_all_evidence,
    save_evidence_packs,
    load_evidence_packs,
)
from .step_builder import (
    build_steps_from_evidence,
    save_raw_steps,
    load_raw_steps,
)
from .plan_refiner import (
    refine_lesson_plan,
    save_final_plan,
    load_final_plan,
)


# =============================================================================
# PUBLIC API
# =============================================================================

def generate_lesson_plan_streaming(
    domains: List[Dict[str, Any]],
    quest_id: str,
    quest_title: str,
    kernel: Any,
    user_constraints: Optional[Dict] = None,
    skip_retrieval: bool = False,
) -> Generator[Dict[str, Any], None, List[Dict[str, Any]]]:
    """
    Generate a lesson plan using the 3-phase engine.
    Streaming version that yields progress events.
    
    This is the main integration point for Quest Compose.
    
    Args:
        domains: List of confirmed domains with subtopics
        quest_id: Quest identifier
        quest_title: Quest title
        kernel: NovaKernel instance
        user_constraints: Optional dict with time_per_session, free_only, etc.
        skip_retrieval: If True, reuse existing evidence (idempotent refinement)
    
    Yields:
        Progress events:
        - {"type": "log", "message": "..."}
        - {"type": "progress", "message": "...", "percent": N}
        - {"type": "steps", "steps": [...]}  # Final steps
        - {"type": "error", "message": "..."}
    
    Returns:
        List of step dicts in Quest Engine format
    """
    def _log(msg: str):
        return {"type": "log", "message": f"[LessonEngine] {msg}"}
    
    def _progress(msg: str, pct: int):
        return {"type": "progress", "message": msg, "percent": pct}
    
    def _steps(steps_list: List[Dict[str, Any]]):
        return {"type": "steps", "steps": steps_list}
    
    def _error(msg: str):
        return {"type": "error", "message": msg}
    
    try:
        yield _log("Starting 3-phase lesson generation")
        yield _progress("Initializing Lesson Engine...", 5)
        
        # Get data directory
        data_dir = Path(getattr(kernel.config, 'data_dir', 'data'))
        
        evidence_packs = []
        raw_steps = []
        
        # ═══════════════════════════════════════════════════════════════════════
        # PHASE A: RETRIEVAL (Gemini with web grounding)
        # ═══════════════════════════════════════════════════════════════════════
        yield _progress("Phase A: Resource Retrieval...", 10)
        
        if skip_retrieval:
            yield _log("Skipping retrieval, loading existing evidence...")
            evidence_packs = load_evidence_packs(data_dir)
        
        if not evidence_packs:
            yield _log("Retrieving resources with Gemini web grounding...")
            
            # Run retrieval
            for event in retrieve_all_evidence(domains, kernel, user_constraints):
                if isinstance(event, list):  # Final result
                    evidence_packs = event
                else:
                    # Adjust progress for Phase A (10-35%)
                    if event.get("type") == "progress":
                        event["percent"] = 10 + int(event["percent"] * 0.25)
                    yield event
            
            # Save evidence
            if evidence_packs:
                save_evidence_packs(evidence_packs, data_dir)
                yield _log(f"Saved {len(evidence_packs)} evidence packs")
        
        if not evidence_packs:
            yield _error("No evidence packs generated - cannot proceed")
            return []
        
        yield _progress("Phase A complete", 35)
        
        # ═══════════════════════════════════════════════════════════════════════
        # PHASE B: STEP BUILDER (Gemini)
        # ═══════════════════════════════════════════════════════════════════════
        yield _progress("Phase B: Building Steps...", 40)
        yield _log("Converting evidence to atomic learning steps...")
        
        # Run step builder
        for event in build_steps_from_evidence(evidence_packs, quest_title, kernel):
            if isinstance(event, list):  # Final result
                raw_steps = event
            else:
                # Adjust progress for Phase B (40-70%)
                if event.get("type") == "progress":
                    event["percent"] = 40 + int(event["percent"] * 0.30)
                yield event
        
        if not raw_steps:
            yield _error("No steps generated from evidence")
            return []
        
        # Save raw steps
        save_raw_steps(raw_steps, data_dir)
        yield _log(f"Built {len(raw_steps)} raw steps")
        yield _progress("Phase B complete", 70)
        
        # ═══════════════════════════════════════════════════════════════════════
        # PHASE C: PLAN REFINEMENT (GPT-5.1)
        # ═══════════════════════════════════════════════════════════════════════
        yield _progress("Phase C: Refining Plan...", 75)
        yield _log("Refining with GPT-5.1 (sequencing, pacing)...")
        
        # Get user pacing from constraints
        user_pacing = None
        if user_constraints:
            user_pacing = {"steps_per_day": user_constraints.get("steps_per_day", 1)}
        
        # Run plan refiner
        final_plan = None
        for event in refine_lesson_plan(raw_steps, evidence_packs, quest_id, quest_title, kernel, user_pacing):
            if isinstance(event, LessonPlan):
                final_plan = event
            else:
                # Adjust progress for Phase C (75-95%)
                if event.get("type") == "progress":
                    event["percent"] = 75 + int(event["percent"] * 0.20)
                yield event
        
        if not final_plan:
            yield _log("Warning: Using raw steps without refinement")
            # Create plan from raw steps
            total_hours = sum(s.estimated_time_minutes for s in raw_steps) / 60
            final_plan = LessonPlan(
                quest_id=quest_id,
                quest_title=quest_title,
                total_steps=len(raw_steps),
                total_hours=round(total_hours, 1),
                steps=raw_steps,
                evidence_packs=evidence_packs,
            )
        
        # Save final plan
        save_final_plan(final_plan, data_dir)
        
        # ═══════════════════════════════════════════════════════════════════════
        # FINALIZE
        # ═══════════════════════════════════════════════════════════════════════
        yield _progress("Complete!", 100)
        yield _log(f"Generated {final_plan.total_steps} steps ({final_plan.total_hours}h total)")
        
        # Convert to Quest Engine format
        quest_steps = final_plan.to_quest_steps()
        yield _steps(quest_steps)
        
        return quest_steps
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        yield _error(f"Lesson generation failed: {str(e)}")
        return []


def generate_lesson_plan(
    domains: List[Dict[str, Any]],
    quest_id: str,
    quest_title: str,
    kernel: Any,
    user_constraints: Optional[Dict] = None,
) -> List[Dict[str, Any]]:
    """
    Non-streaming version of lesson plan generation.
    
    Args:
        domains: List of confirmed domains with subtopics
        quest_id: Quest identifier
        quest_title: Quest title
        kernel: NovaKernel instance
        user_constraints: Optional constraints
    
    Returns:
        List of step dicts in Quest Engine format
    """
    result = []
    
    for event in generate_lesson_plan_streaming(domains, quest_id, quest_title, kernel, user_constraints):
        if event.get("type") == "steps":
            result = event.get("steps", [])
        elif event.get("type") == "log":
            print(event.get("message", ""), flush=True)
    
    return result


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Main API
    "generate_lesson_plan",
    "generate_lesson_plan_streaming",
    
    # Schemas
    "EvidencePack",
    "EvidenceResource",
    "LessonPlan",
    "LessonStep",
    "validate_lesson_plan",
    
    # Individual phases (for testing/debugging)
    "retrieve_all_evidence",
    "build_steps_from_evidence",
    "refine_lesson_plan",
    
    # Storage
    "save_evidence_packs",
    "load_evidence_packs",
    "save_raw_steps",
    "load_raw_steps",
    "save_final_plan",
    "load_final_plan",
]
